import unittest

from app.classifier import classifier


class QuestionClassifierTests(unittest.TestCase):
    def test_blocks_engine_oil_used_in_cvt(self) -> None:
        answer = classifier.safety_q("น้ำมันเครื่องใช้แทนน้ำมันเกียร์ CVT ได้ไหม")
        self.assertIsNotNone(answer)
        self.assertIn("ไม่ได้เด็ดขาด", answer)

    def test_blocks_cvt_oil_for_diesel_pickup(self) -> None:
        answer = classifier.safety_q("Toyota Revo เติม CVT ได้ไหม")
        self.assertIsNotNone(answer)
        self.assertIn("ไม่ได้ใช้เกียร์ CVT", answer)

    def test_allows_unrelated_question(self) -> None:
        self.assertIsNone(classifier.safety_q("ตัวแทนจำหน่ายอยู่ที่ไหน"))

    def test_detects_greeting_after_whitespace(self) -> None:
        self.assertTrue(classifier.is_greeting("  สวัสดีครับ"))
