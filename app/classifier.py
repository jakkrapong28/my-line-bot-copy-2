"""Lightweight rule-based question classification, safety checks and canned replies."""
import re
from typing import List, Optional, Tuple


class QuestionClassifier:
    def __init__(self) -> None:
        self.pat_engine_oil = re.compile(r"น้ำมันเครื่อง|เบอร์|10w|5w|0w|20w|เบนซิน|ดีเซล", re.I)
        self.pat_gear = re.compile(r"เกียร์|cvt|atf", re.I)
        self.pat_mix = re.compile(r"ผสม|เติมแทน|ใช้แทน|แก้ขัด|ใส่แทน|ใส่ได้ไหม", re.I)
        self.pat_diesel_car = re.compile(r"revo|vigo|d-?max|fortuner|ranger|bt-?50|triton", re.I)
        self.pat_greeting = re.compile(r"^(สวัสดี|หวัดดี|ดีครับ|ดีค่ะ|hello|hi|hey)", re.I)
        self.pat_handover = re.compile(r"ขอส่งต่อให้เจ้าหน้าที่|ประสานงานให้เจ้าหน้าที่|ขออนุญาตประสานงาน")
        self.pat_danger = re.compile(r"(น้ำมันเครื่อง).{0,40}(cvt|เกียร์\s*cvt)|(cvt).{0,40}(น้ำมันเครื่อง)", re.I)
        self.pat_spaces = re.compile(r"\s+")

    def safety_q(self, q: str) -> Optional[str]:
        ql = q.lower()
        if self.pat_engine_oil.search(ql) and self.pat_gear.search(ql) and self.pat_mix.search(ql):
            return (
                "⚠️ ไม่ได้เด็ดขาดครับ!\n"
                "น้ำมันเครื่องและน้ำมันเกียร์เป็นคนละประเภทกัน ห้ามนำมาผสมหรือใช้แทนกันเด็ดขาดครับ เกียร์จะพังทันทีครับ"
            )
        if self.pat_diesel_car.search(ql) and "cvt" in ql:
            return "⚠️ ระวังครับ!\nรถกระบะดีเซล ไม่ได้ใช้เกียร์ CVT ห้ามเติมน้ำมัน CVT เด็ดขาดครับ"
        return None

    def is_handover(self, text: str) -> bool:
        return bool(self.pat_handover.search(text))

    def is_greeting(self, q: str) -> bool:
        return bool(self.pat_greeting.search(q.strip()))

    def compress(self, text: str) -> str:
        return self.pat_spaces.sub(" ", text).strip()


classifier = QuestionClassifier()


# Deterministic answers for high-intent queries (skip the LLM entirely).
DIRECT_ANSWERS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"หาตัวแทนจำหน่าย|ขอทราบตัวแทน|อยากทราบตัวแทน|ค้นหาตัวแทน|ซื้อ.{0,6}ที่ไหนดี|จำหน่าย.{0,6}ที่ไหนบ้าง", re.I),
     "ค้นหาตัวแทนจำหน่ายใกล้บ้านได้เลยครับ 😊\n🔍 https://www.eneosthailand.com/agent"),
    (re.compile(r"shopee|lazada|ซื้อ.{0,6}ออนไลน์|สั่ง.{0,6}ออนไลน์|ออนไลน์.{0,6}ซื้อ", re.I),
     "สั่งซื้อสินค้า ENEOS ออนไลน์ได้ที่นี่ครับ 🛒\nhttps://www.eneosthailand.com/agent_online"),
    (re.compile(r"สมัครงาน|ร่วมงาน.{0,6}eneos|eneos.{0,6}สมัครงาน", re.I),
     "สนใจสมัครงาน ENEOS ส่ง CV มาได้ที่ hr@eneos.co.th ครับ 📧"),
    (re.compile(r"จารบี|ไฮดรอลิก|สินค้าอุตสาหกรรม|compressor.{0,6}oil|gear.{0,6}oil.{0,6}อุตสาหกรรม", re.I),
     "สินค้าอุตสาหกรรม ENEOS ติดต่อได้ที่ครับ\n🏭 https://eneosindustrial.com/contact-us"),
    (re.compile(r"datasheet|tds|ข้อมูลทางเทคนิค|ดาวน์โหลด.{0,6}สินค้า|spec sheet", re.I),
     "ดาวน์โหลด Datasheet / TDS ได้ที่ครับ 📄\nhttps://www.eneosthailand.com/download"),
    (re.compile(r"ค้นหาน้ำมัน.{0,6}รถ|เช็คน้ำมัน.{0,6}รถ|น้ำมัน.{0,6}เหมาะ.{0,10}รถ|รถ.{0,6}ใช้น้ำมัน.{0,6}อะไร", re.I),
     "ค้นหาน้ำมันที่เหมาะกับรถของคุณได้ที่ครับ 🚗\nhttps://www.eneosthailand.com/index\n(เลือกยี่ห้อและรุ่นรถได้เลยครับ)"),
    (re.compile(r"ติดต่อฝ่ายขาย|เบอร์.{0,6}ฝ่ายขาย|เบอร์.{0,6}เซล|ต้องการให้เซล|เซลติดต่อ", re.I),
     "ติดต่อฝ่ายขาย ENEOS ได้เลยครับ 📞\n• สายหลัก: 02-168-8271, 065-730-7201\n"
     "หรือดูข้อมูลเพิ่มเติมที่ https://www.eneosthailand.com/contact_us ครับ"),
    (re.compile(r"สินค้า.{0,6}ทั้งหมด|รายการสินค้า|ดูสินค้า.{0,6}eneos", re.I),
     "ดูสินค้าทั้งหมดได้ที่ครับ 🛢️\nhttps://www.eneosthailand.com/products"),
    (re.compile(r"เว็บ.{0,6}eneos|eneos.{0,6}เว็บ|website.{0,6}eneos", re.I),
     "เว็บไซต์ ENEOS Thailand ครับ 🌐\nhttps://www.eneosthailand.com"),
]
