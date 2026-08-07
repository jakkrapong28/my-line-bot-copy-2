"""Shared FastAPI dependencies."""

from fastapi import Depends, HTTPException, Request

from .services.redis_service import RedisService, get_redis_svc


async def check_rate_limit(request: Request, rs: RedisService = Depends(get_redis_svc)) -> None:
    ip = request.client.host if request.client else "unknown"
    if not await rs.check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="รับข้อความถี่เกินไปครับ กรุณารอสักครู่")
