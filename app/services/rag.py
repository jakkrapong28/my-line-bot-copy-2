"""Hybrid (BM25 + vector) retrieval, reranking and the Groq-backed RAG chain."""

import asyncio
import gc
import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from flashrank import Ranker, RerankRequest
from joblib import dump, load
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.retrievers import BaseRetriever
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from tenacity import retry, stop_after_attempt, wait_exponential

from ..classifier import DIRECT_ANSWERS, classifier
from ..config import settings
from ..logging_setup import cache_stats, logger
from .chat import ChatMessage

SYSTEM_PROMPT = (
    'คุณคือ "พี่เอเนออส" ผู้เชี่ยวชาญผลิตภัณฑ์ ENEOS Thailand\n\n'
    "【กฎเหล็ก — ต้องจำและใช้ตอบเสมอ】\n"
    "1. ราคา/สั่งซื้อ → ให้ตรวจสอบกับตัวแทน https://www.eneosthailand.com/agent เสมอ ห้ามบอกราคา\n"
    "2. น้ำยาหล่อเย็น → ชมพู=TOYOTA/LEXUS | ฟ้า=HONDA/NISSAN/MITSUBISHI | เขียว=MAZDA/FORD/SUZUKI | ไม่มีสีเหลือง\n"
    "3. สมัครตัวแทน → ต้องการ: ชื่อร้าน / ที่อยู่ / เบอร์โทร / ประเภทร้าน\n"
    "4. มอเตอร์ไซค์เกียร์ออโต้ → ต้องใช้ JASO MB เท่านั้น\n"
    "5. ไมล์ > 200,000 กม. → แนะนำเบอร์ 40\n"
    "6. รถกระบะดีเซล → ไม่มี CVT\n"
    "7. น้ำมันเครื่อง ≠ ATF ≠ CVT\n\n"
    "【วิธีตอบ】\n"
    "- ตอบตรงประเด็น กระชับ ไม่เกิน 4 ประโยค\n"
    "- ใช้เฉพาะข้อมูลใน [Context] เท่านั้น ห้ามเดา\n"
    "- ถ้าไม่มีข้อมูลจริงๆ ให้ตอบ INSUFFICIENT_CONTEXT\n"
    "- ลงท้ายด้วย 'ครับ' เสมอ\n\n"
    "[Context]:\n{context}"
)

# system rules/context + real conversation turns + the new question.
PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ]
)

KNOWLEDGE_EXTS = (".pdf", ".xlsx", ".txt", ".md")


RRF_K = 60  # Reciprocal Rank Fusion damping constant


class HybridRetriever(BaseRetriever):
    """Fuses BM25 (keyword) and vector (semantic) results with Reciprocal Rank
    Fusion: a document ranked high by *both* retrievers floats to the top, which
    is more robust than a plain concatenate-and-dedup merge."""

    bm25: BM25Retriever
    vector: BaseRetriever

    def _get_relevant_documents(self, query: str) -> list[Document]:
        scores: dict[str, float] = {}
        docs_by_key: dict[str, Document] = {}
        for ranked in (self.bm25.invoke(query), self.vector.invoke(query)):
            for rank, doc in enumerate(ranked):
                key = doc.page_content
                scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
                docs_by_key.setdefault(key, doc)
        top_keys = sorted(scores, key=scores.get, reverse=True)[: settings.RETRIEVER_K]
        return [docs_by_key[key] for key in top_keys]


class RAGService:
    def __init__(self) -> None:
        self.llm_chain = None
        self.retriever = None
        self.reranker: Ranker | None = None
        self.ready = False
        self.sem = asyncio.Semaphore(settings.MAX_CONCURRENT_RAG)
        self.knowledge_hash = ""

    async def initialize(self) -> None:
        try:
            await asyncio.to_thread(self._build)
            self.ready = True
            logger.info("rag_ready", hash=self.knowledge_hash[:8])
        except Exception as e:
            logger.critical("rag_init_failed", err=str(e), exc_info=True)

    async def reload(self) -> tuple[bool, str]:
        was_ready = self.ready
        self.ready = False
        old_hash = self.knowledge_hash
        try:
            await asyncio.to_thread(self._build)
            self.ready = True
            return True, old_hash
        except Exception as e:
            self.ready = was_ready
            self.knowledge_hash = old_hash
            logger.critical("rag_reload_failed", err=str(e))
            return False, old_hash

    # ------------------------------------------------------------------ build
    def _knowledge_files(self) -> list[Path]:
        return [
            p
            for p in sorted(settings.knowledge_dir.glob("*.*"))
            if p.suffix.lower() in KNOWLEDGE_EXTS
        ]

    def _load_docs(self) -> list[Document]:
        docs: list[Document] = []
        for p in self._knowledge_files():
            if p.stat().st_size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
                continue
            try:
                suffix = p.suffix.lower()
                if suffix == ".pdf":
                    docs.extend(PyPDFLoader(str(p)).load())
                elif suffix in (".txt", ".md"):
                    text = re.sub(
                        r"\[cite_start\]|\[cite:\s*\d+\]", "", p.read_text(encoding="utf-8")
                    )
                    docs.append(Document(page_content=text, metadata={"source": p.name}))
                elif suffix == ".xlsx":
                    df = pd.read_excel(p)
                    for _, row in df.iterrows():
                        parts = [
                            f"{col}: {val}"
                            for col, val in row.items()
                            if pd.notna(val) and str(val).strip() not in ("", "nan")
                        ]
                        if parts:
                            docs.append(
                                Document(
                                    page_content=" | ".join(parts), metadata={"source": p.name}
                                )
                            )
            except Exception as e:
                logger.warning("file_load_error", file=p.name, err=str(e))
        return docs

    def _compute_hash(self) -> str:
        digest = hashlib.sha256()
        files = self._knowledge_files()
        for path in files:
            digest.update(path.name.encode("utf-8"))
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
        return digest.hexdigest() if files else "empty"

    def _build(self) -> None:
        cur_hash = self._compute_hash()
        self.knowledge_hash = cur_hash

        hash_file = settings.chroma_path / "hash.txt"
        stored = hash_file.read_text().strip() if hash_file.exists() else ""
        need_build = (
            settings.FORCE_REBUILD_DB
            or cur_hash != stored
            or not settings.chroma_path.exists()
            or not settings.bm25_cache_path.is_file()
        )

        raw_docs = self._load_docs()
        if not raw_docs:
            raise RuntimeError("No knowledge files found!")

        embed = HuggingFaceEmbeddings(
            model_name="intfloat/multilingual-e5-base",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True, "batch_size": 32},
        )
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["--------------------", "\n\n", "\n", " "],
        )
        if self.reranker is None:
            self.reranker = Ranker(
                model_name="ms-marco-MiniLM-L-12-v2",
                cache_dir=str(settings.rerank_models_dir),
            )

        if need_build:
            if settings.chroma_path.exists():
                shutil.rmtree(settings.chroma_path)
            settings.chroma_path.mkdir(parents=True, exist_ok=True)
            chunks = splitter.split_documents(raw_docs)
            vectordb = Chroma.from_documents(
                chunks,
                embed,
                collection_name="eneos_v5",
                persist_directory=str(settings.chroma_path),
            )
            bm25 = BM25Retriever.from_documents(chunks)
            bm25.k = settings.RETRIEVER_K
            dump(bm25, settings.bm25_cache_path)
            hash_file.write_text(cur_hash, encoding="utf-8")
            del chunks
        else:
            vectordb = Chroma(
                collection_name="eneos_v5",
                embedding_function=embed,
                persist_directory=str(settings.chroma_path),
            )
            bm25 = load(settings.bm25_cache_path)

        self.retriever = HybridRetriever(
            bm25=bm25, vector=vectordb.as_retriever(search_kwargs={"k": settings.RETRIEVER_K})
        )

        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            groq_api_key=settings.GROQ_API_KEY.get_secret_value(),
            max_tokens=768,
        )
        self.llm_chain = PROMPT | llm | StrOutputParser()
        gc.collect()

    # ------------------------------------------------------------------- ask
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _llm(self, payload: dict[str, Any]) -> str:
        if self.llm_chain is None:
            raise RuntimeError("RAG service is not initialized")
        return await self.llm_chain.ainvoke(payload)

    async def ask(self, question: str, history: list[ChatMessage]) -> str:
        if not self.ready:
            return "ระบบกำลังอัปเดตข้อมูล กรุณารอสักครู่นะครับ"

        if classifier.is_greeting(question):
            return "สวัสดีครับ 😊 ENEOS ยินดีให้คำปรึกษาครับ มีคำถามเรื่องน้ำมันเครื่องสอบถามได้เลยนะครับ"

        for pat, ans in DIRECT_ANSWERS:
            if pat.search(question):
                cache_stats.direct_hits += 1
                return ans

        if safe := classifier.safety_q(question):
            return safe

        docs = await asyncio.to_thread(self.retriever.invoke, question)
        if not docs:
            return "คำถามนี้เฉพาะเจาะจงมากครับ พี่เอเนออสขอส่งต่อให้เจ้าหน้าที่ผู้เชี่ยวชาญดูแลต่อนะครับ"

        if self.reranker is None:
            raise RuntimeError("RAG service is not initialized")
        results = await asyncio.to_thread(
            self.reranker.rerank,
            RerankRequest(
                query=question,
                passages=[
                    {"id": str(i), "text": d.page_content, "meta": d.metadata}
                    for i, d in enumerate(docs)
                ],
            ),
        )

        final_docs = [
            r["text"]
            for r in results[: settings.RERANK_TOP_K]
            if r["score"] >= settings.RERANK_HARD_CUTOFF
        ]
        if not final_docs:
            return "คำถามนี้มีความเฉพาะเจาะจงสูงครับ พี่เอเนออสขอส่งต่อให้เจ้าหน้าที่ดูแลต่อนะครับ"

        async with self.sem:
            context = classifier.compress("\n\n---\n\n".join(final_docs))
            msgs = [
                HumanMessage(content=m["content"])
                if m.get("role") == "user"
                else AIMessage(content=m["content"])
                for m in history
            ]

            try:
                raw = await self._llm({"input": question, "chat_history": msgs, "context": context})
            except Exception:
                return "ขออภัยครับ ระบบขัดข้องชั่วคราว ติดต่อเจ้าหน้าที่ได้ที่ https://www.eneosthailand.com/agent ครับ"

            if "INSUFFICIENT_CONTEXT" in raw:
                return "คำถามนี้มีความเฉพาะเจาะจงสูงครับ พี่เอเนออสขอส่งต่อให้เจ้าหน้าที่ดูแลต่อนะครับ"

            answer = raw.strip()
            if classifier.pat_danger.search(answer):
                return "ขออภัยครับ คำถามนี้เกี่ยวข้องกับการใช้น้ำมันข้ามประเภท เพื่อความปลอดภัยขอส่งต่อให้เจ้าหน้าที่โดยตรงครับ"

            if not answer.endswith("ครับ"):
                answer += " ครับ"

            return answer


rag = RAGService()
