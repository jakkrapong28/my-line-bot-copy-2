# ENEOS AI v5.3 — LINE RAG Chatbot

ผู้ช่วย AI สำหรับ **LINE Official Account ของ ENEOS Thailand** ตอบคำถามเรื่องน้ำมันหล่อลื่น
เกียร์ น้ำยาหล่อเย็น และผลิตภัณฑ์ ENEOS เป็นภาษาไทย ด้วยความแม่นยำสูงและมี Safety Guardrail
ป้องกันการแนะนำน้ำมันผิดประเภท

> **Tech stack:** FastAPI · Groq Llama-3.3-70B · Hybrid RAG (BM25 + Chroma + FlashRank) ·
> Redis · JWT · Docker

---

## ✨ จุดเด่นเชิงเทคนิค

- **Hybrid Retrieval + RRF** — รวมผลการค้นแบบ keyword (BM25) และ semantic (vector) ด้วย
  *Reciprocal Rank Fusion* เอกสารที่ทั้งสองวิธีเห็นตรงกันจะถูกดันขึ้นบน แล้วกรองอีกชั้นด้วย
  FlashRank reranker
- **Safety Guardrail** — กฎเชิง regex + กฎใน system prompt กันการแนะนำน้ำมันข้ามประเภท
  (น้ำมันเครื่อง / เกียร์ / CVT) ที่อาจทำให้รถเสียหาย
- **Multi-turn memory** — จำบริบทบทสนทนาผ่าน Redis (ส่งเข้าโมเดลเป็น conversation turns จริง
  ด้วย `MessagesPlaceholder`)
- **Distributed cache & rate limit** — อยู่บน Redis ทำงานถูกต้องแม้สเกลหลาย instance พร้อม
  circuit breaker ให้ degrade อย่างนุ่มนวลเมื่อ Redis ล่ม
- **Secure admin** — Login → JWT → Access, เทียบรหัสผ่านแบบ timing-safe, secret บังคับมาจาก env
- **Production-ready** — structured JSON logs, health check, Docker Compose, dependency pinning

---

## 🏗️ สถาปัตยกรรม

```
LINE User
    │
    ▼
[/line/webhook] ──► [FastAPI]
                        │  (signature verify · rate limit · cache lookup)
                        ▼
                  [RAGService.ask]
        ┌───────────────┼────────────────┐
        ▼               ▼                 ▼
  Greeting / Direct  Safety check   Hybrid Retrieval
   answers (regex)   (regex)        ├─ BM25 (keyword)
                                    ├─ Chroma (semantic)
                                    └─ RRF fusion → FlashRank rerank
                                          │
                                          ▼
                                 [Groq · Llama-3.3-70B]
                                          │
                                          ▼
                                   Answer → LINE reply
```

### โครงสร้างโปรเจกต์

```
app/
├── config.py              # Settings (pydantic-settings) อ่านจาก .env
├── logging_setup.py       # structured logging + cache stats
├── state.py               # connection pools + Redis circuit breaker
├── classifier.py          # QuestionClassifier + canned/direct answers
├── security.py            # JWT login / verify
├── deps.py                # FastAPI dependencies (rate limit)
├── services/
│   ├── chat.py            # conversation orchestration · context-safe cache
│   ├── redis_service.py   # cache · rate limit · chat history
│   └── rag.py             # Hybrid retriever (RRF) · rerank · LLM chain
├── routers/
│   ├── webhook.py         # /line/webhook · /api/ask
│   ├── admin.py           # /admin/login · /admin/reload · /admin/cache-stats
│   └── health.py          # /health
└── main.py                # app factory + lifespan

main.py                    # entrypoint (uvicorn main:app)
Dockerfile · docker-compose.yml · requirements.txt
```

---

## 🚀 เริ่มต้นใช้งาน

### ความต้องการ
- Python 3.13 · Redis · RAM แนะนำ 8GB+ (โหลด embedding model)

### วิธีที่ 1 — Docker Compose (แนะนำ)

```bash
cp .env.example .env        # แล้วกรอกค่าให้ครบ
docker compose up --build   # รัน redis + bot พร้อมกัน
```

การรันครั้งแรกจะดาวน์โหลด embedding/reranker models และสร้างดัชนีใน Docker named volume
จึงอาจใช้เวลาหลายนาที; รอบถัดไปจะใช้ข้อมูลที่ persist ไว้

### วิธีที่ 2 — รันตรง

```bash
cp .env.example .env        # กรอกค่าให้ครบ
pip install -r requirements.txt
# วาง knowledge files (.pdf/.xlsx/.txt/.md) ใน knowledge/
python main.py              # http://localhost:8000
```

### ตรวจสอบคุณภาพโค้ด

ชุด unit tests ไม่เรียก Redis, Groq หรือดาวน์โหลดโมเดล จึงรันได้เร็วและ deterministic:

```bash
python -m unittest discover -v
pip install -r requirements-dev.txt
ruff check app tests main.py
ruff format --check app tests main.py
```

GitHub Actions จะรันทั้ง lint, format check และ unit tests อัตโนมัติทุก push/PR

### ตัวแปร .env

```env
# จำเป็น (ไม่มี default — ระบบจะไม่สตาร์ทถ้าขาด)
LINE_CHANNEL_ACCESS_TOKEN=
LINE_CHANNEL_SECRET=
GROQ_API_KEY=
ADMIN_PASSWORD=          # ใช้สตริงสุ่มยาว ๆ
ADMIN_JWT_SECRET=        # ใช้สตริงสุ่มยาว ๆ

# ออปชัน
REDIS_URL=redis://localhost:6379/0
DATA_DIR=.                  # ที่เก็บ generated indexes/models
DEBUG=false
FORCE_REBUILD_DB=false
# CORS_ORIGINS=["https://your-frontend.com"]   # อย่าใช้ "*" บน production
```

---

## 📡 API Endpoints

| Method | Path | หน้าที่ | Auth |
|---|---|---|---|
| POST | `/line/webhook` | รับข้อความจาก LINE | LINE Signature |
| POST | `/api/ask` | ถามตรงผ่าน API | — |
| POST | `/admin/login` | รับ JWT token | Password |
| POST | `/admin/reload` | rebuild knowledge base + purge cache | JWT |
| GET | `/admin/cache-stats` | สถิติ cache | JWT |
| GET | `/health` | สถานะระบบ | — |

### อัปเดตความรู้ (Knowledge update)

```bash
# 1) วางไฟล์ใหม่ใน knowledge/  →  2) ขอ token  →  3) reload
TOKEN=$(curl -s -X POST localhost:8000/admin/login \
  -H "Content-Type: application/json" \
  -d '{"password":"<ADMIN_PASSWORD>"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -X POST localhost:8000/admin/reload -H "Authorization: Bearer $TOKEN"
```
ระบบจะคำนวณ hash ของไฟล์ใหม่ rebuild เฉพาะเมื่อมีการเปลี่ยนแปลง และล้าง cache เก่าเฉพาะส่วนที่เกี่ยวข้อง

---

## 🧠 การจูนความแม่นยำ (RAG tuning)

ทุกค่าปรับได้ผ่าน `.env` (override `app/config.py`)

| ค่า | Default | ผล | ปรับเมื่อ |
|---|---|---|---|
| `CHUNK_SIZE` | 1200 | ขนาดชิ้นข้อมูลที่ตัด | AI ตอบขาด ๆ → เพิ่ม |
| `CHUNK_OVERLAP` | 120 | การซ้อนทับระหว่างชิ้น | ข้อมูลคาบเกี่ยวขาดตอน → เพิ่ม |
| `RETRIEVER_K` | 15 | จำนวนชิ้นดึงมาก่อน fusion | อยากครอบคลุมมากขึ้น → เพิ่ม |
| `RERANK_TOP_K` | 6 | จำนวนชิ้นที่ส่งให้ LLM | AI ข้อมูลไม่พอ → เพิ่ม |
| `RERANK_HARD_CUTOFF` | 0.15 | เกณฑ์ตัดข้อมูลไม่เกี่ยว | AI ตอบนอกเรื่อง → เพิ่ม |
| `MAX_HISTORY_MESSAGES` | 6 | จำนวน turn ที่จำได้ | อยากให้คุยต่อเนื่องนานขึ้น → เพิ่ม |

### เปลี่ยน LLM / Embedding

แก้ที่ `app/services/rag.py` (เมธอด `RAGService._build`):

```python
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.1, ...)
```
- เปลี่ยนค่าย: import `ChatOpenAI` / `ChatAnthropic` แล้วใส่ key ใน `.env`
- เปลี่ยน embedding (`intfloat/multilingual-e5-base`): ต้อง `FORCE_REBUILD_DB=true` แล้วรีสตาร์ท

System prompt (ชื่อบอท + กฎเหล็ก) อยู่ที่ค่าคงที่ `SYSTEM_PROMPT` ในไฟล์เดียวกัน

---

## 🛠️ Troubleshooting

| ปัญหา | สาเหตุ | วิธีแก้ |
|---|---|---|
| `/health` ขึ้น `degraded` | RAG ยังโหลดไม่เสร็จ | รอสักครู่ / เช็ค log |
| Redis error | Redis ไม่ได้รัน | สตาร์ท `redis-server` |
| ตอบผิด / ไม่ตรง | ข้อมูลใน knowledge ไม่พอ | เพิ่มไฟล์แล้ว `/admin/reload` |
| ช้ามาก | RAM/CPU ไม่พอ | ลด `RETRIEVER_K` / เพิ่ม RAM |
| สตาร์ทไม่ขึ้น | `.env` ขาด secret ที่จำเป็น | กรอกให้ครบตาม `.env.example` |

---

## 🗺️ Roadmap

**ระยะสั้น** — Web UI upload · dashboard คำถามยอดนิยม · LINE Flex Message · แจ้งเตือน admin ตอน handover
**ระยะกลาง** — embedding บน GPU · เพิ่มช่องทาง Messenger/WhatsApp · evaluation pipeline วัด accuracy
**ระยะยาว** — fine-tune ด้วยบทสนทนาจริง · multi-modal (ถ่ายรูปน้ำมันแล้วถาม) · analytics เต็มรูปแบบ
