"""Admin API: login, knowledge reload and cache stats (JWT protected)."""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..logging_setup import cache_stats
from ..security import create_admin_token, verify_jwt
from ..services.rag import rag
from ..services.redis_service import RedisService, get_redis_svc

router = APIRouter(prefix="/admin", tags=["admin"])


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def admin_login(req: LoginRequest):
    if not secrets.compare_digest(req.password, settings.ADMIN_PASSWORD.get_secret_value()):
        raise HTTPException(status_code=401, detail="รหัสผ่านไม่ถูกต้อง")
    return {"access_token": create_admin_token(), "token_type": "bearer", "expires_in": "24h"}


@router.post("/reload", dependencies=[Depends(verify_jwt)])
async def admin_reload(rs: RedisService = Depends(get_redis_svc)):
    old_hash = rag.knowledge_hash
    success, _ = await rag.reload()
    if not success:
        raise HTTPException(500, "Rebuild failed")

    deleted = await rs.purge_cache_by_prefix(f"cache:{old_hash[:8]}") if old_hash else 0
    return {
        "status": "reloaded",
        "new_hash": rag.knowledge_hash[:8],
        "cache_purged": deleted,
        "message": f"Purged {deleted} stale cache entries.",
    }


@router.get("/cache-stats", dependencies=[Depends(verify_jwt)])
async def admin_cache_stats():
    return {
        "hit_rate": cache_stats.hit_rate,
        "hits": cache_stats.hits,
        "misses": cache_stats.misses,
        "direct_hits": cache_stats.direct_hits,
        "knowledge_hash": rag.knowledge_hash[:8],
    }
