"""Liveness / readiness endpoint."""

from fastapi import APIRouter

from ..config import settings
from ..services.rag import rag
from ..state import resources

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {
        "status": "healthy" if rag.ready else "degraded",
        "version": settings.VERSION,
        "redis": resources.redis_connected,
        "knowledge_hash": rag.knowledge_hash[:8] if rag.knowledge_hash else "unknown",
    }
