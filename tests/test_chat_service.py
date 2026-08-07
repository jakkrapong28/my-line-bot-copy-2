from __future__ import annotations

import unittest

from app.services.chat import ChatMessage, ChatService, build_cache_key


class FakeRag:
    knowledge_hash = "abcdef1234567890"

    def __init__(self, answer: str = "คำตอบครับ") -> None:
        self.answer_text = answer
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    async def ask(self, question: str, history: list[ChatMessage]) -> str:
        self.calls.append((question, history.copy()))
        return self.answer_text


class MemoryStore:
    def __init__(self) -> None:
        self.cache: dict[str, str] = {}
        self.history: dict[str, list[ChatMessage]] = {}

    async def get_cache(self, key: str) -> str | None:
        return self.cache.get(key)

    async def set_cache(self, key: str, value: str) -> None:
        self.cache[key] = value

    async def get_history(self, user_id: str) -> list[ChatMessage]:
        return self.history.get(user_id, []).copy()

    async def append_history(self, user_id: str, messages: list[ChatMessage]) -> None:
        self.history.setdefault(user_id, []).extend(messages)


class CacheKeyTests(unittest.TestCase):
    def test_normalizes_question_whitespace_and_case(self) -> None:
        first = build_cache_key("  HELLO   World ", "abcdef123")
        second = build_cache_key("hello world", "abcdef123")
        self.assertEqual(first, second)

    def test_changes_when_conversation_context_changes(self) -> None:
        first = build_cache_key(
            "แล้วรุ่นนี้ล่ะ",
            "abcdef123",
            [{"role": "user", "content": "รถ Honda City"}],
        )
        second = build_cache_key(
            "แล้วรุ่นนี้ล่ะ",
            "abcdef123",
            [{"role": "user", "content": "รถ Toyota Revo"}],
        )
        self.assertNotEqual(first, second)

    def test_changes_when_knowledge_changes(self) -> None:
        self.assertNotEqual(
            build_cache_key("คำถาม", "11111111aaaaaaaa"),
            build_cache_key("คำถาม", "22222222bbbbbbbb"),
        )


class ChatServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_hit_skips_rag_and_still_updates_history(self) -> None:
        rag = FakeRag()
        store = MemoryStore()
        key = build_cache_key("คำถาม", rag.knowledge_hash)
        store.cache[key] = "จาก cache ครับ"

        result = await ChatService(rag).answer("คำถาม", "user-1", store)

        self.assertTrue(result.cached)
        self.assertEqual(result.text, "จาก cache ครับ")
        self.assertEqual(rag.calls, [])
        self.assertEqual(len(store.history["user-1"]), 2)

    async def test_cache_miss_calls_rag_and_caches_answer(self) -> None:
        rag = FakeRag()
        store = MemoryStore()

        result = await ChatService(rag).answer("คำถาม", "user-1", store)

        self.assertFalse(result.cached)
        self.assertEqual(len(rag.calls), 1)
        self.assertEqual(list(store.cache.values()), ["คำตอบครับ"])

    async def test_handover_answer_is_not_cached(self) -> None:
        rag = FakeRag("ขอส่งต่อให้เจ้าหน้าที่ดูแลครับ")
        store = MemoryStore()

        await ChatService(rag).answer("คำถาม", "user-1", store)

        self.assertEqual(store.cache, {})

    async def test_rejects_blank_question(self) -> None:
        with self.assertRaises(ValueError):
            await ChatService(FakeRag()).answer("   ", "user-1", MemoryStore())
