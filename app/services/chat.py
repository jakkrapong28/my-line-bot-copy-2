"""Conversation orchestration shared by every chat transport."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, TypedDict

from ..classifier import classifier


class ChatMessage(TypedDict):
    role: str
    content: str


class RagBackend(Protocol):
    knowledge_hash: str

    async def ask(self, question: str, history: list[ChatMessage]) -> str: ...


class ConversationStore(Protocol):
    async def get_cache(self, key: str) -> str | None: ...

    async def set_cache(self, key: str, value: str) -> None: ...

    async def get_history(self, user_id: str) -> list[ChatMessage]: ...

    async def append_history(self, user_id: str, new_msgs: list[ChatMessage]) -> None: ...


@dataclass(frozen=True, slots=True)
class AnswerResult:
    text: str
    cached: bool


def build_cache_key(
    question: str,
    knowledge_hash: str,
    history: Sequence[ChatMessage] = (),
) -> str:
    """Build a cache key that cannot leak context-dependent answers.

    The previous implementation keyed only on the question, so a short
    follow-up such as "แล้วรุ่นนี้ล่ะ" could receive an answer generated for
    another conversation. Including the normalized recent history preserves
    safe cross-user caching for identical contexts.
    """

    normalized_question = classifier.compress(question.casefold())
    normalized_history = [
        {
            "role": message.get("role", ""),
            "content": classifier.compress(message.get("content", "")),
        }
        for message in history
    ]
    payload = json.dumps(
        [normalized_question, normalized_history],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    knowledge_version = knowledge_hash[:8] if knowledge_hash else "nohash"
    return f"cache:{knowledge_version}:{digest}"


class ChatService:
    """Coordinates history, cache and RAG without transport-specific logic."""

    def __init__(self, rag_backend: RagBackend) -> None:
        self._rag = rag_backend

    async def answer(
        self,
        question: str,
        user_id: str,
        store: ConversationStore,
    ) -> AnswerResult:
        question = question.strip()
        if not question:
            raise ValueError("question must not be blank")

        history = await store.get_history(user_id)
        key = build_cache_key(question, self._rag.knowledge_hash, history)
        answer = await store.get_cache(key)
        cached = answer is not None

        if answer is None:
            answer = await self._rag.ask(question, history)
            if not classifier.is_handover(answer):
                await store.set_cache(key, answer)

        # Keep memory consistent even when the answer came from cache or from
        # a deterministic RAG fast path (greeting, safety, direct answer).
        await store.append_history(
            user_id,
            [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
        )
        return AnswerResult(text=answer, cached=cached)
