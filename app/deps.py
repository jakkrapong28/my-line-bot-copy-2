"""Shared FastAPI dependencies and helpers."""
import hashlib

from fastapi import Depends, HTTPException, Request

from .classifier import classifier
from .services.rag import rag
from .services.redis_service import RedisService, get_redis_svc


def cache_key(q: str) -> str:
    kb = rag.knowledge_hash[:8] if rag.knowledge_hash else "nohash"
    qh = hashlib.sha256(classifier.compress(q.lower()).encode()).hexdigest()[:16]
    return f"cache:{kb}:{qh}"


async def check_rate_limit(request: Request, rs: RedisService = Depends(get_redis_svc)) -> None:
    ip = request.client.host if request.client else "unknown"
    if not await rs.check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="รับข้อความถี่เกินไปครับ กรุณารอสักครู่")
