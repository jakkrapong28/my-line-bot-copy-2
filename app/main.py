"""FastAPI application factory, lifecycle and router wiring.

ENEOS AI v5.3 — Groq Llama-3.3-70b · Redis · Hybrid RAG · JWT admin.
"""

from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.exceptions import RedisError

from .config import settings
from .logging_setup import logger
from .routers import admin, health, webhook
from .services.rag import rag
from .state import resources


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", version=settings.VERSION)
    resources.http_client = httpx.AsyncClient(
        http2=True,
        timeout=10.0,
        limits=httpx.Limits(max_keepalive_connections=50, max_connections=200),
    )
    resources.redis_pool = redis.from_url(
        settings.REDIS_URL, decode_responses=True, socket_timeout=2, max_connections=200
    )
    try:
        await resources.redis_pool.ping()
        resources.redis_connected = True
        logger.info("redis_connected")
    except RedisError as exc:
        # Cache, history and rate limiting are designed to fail open. Keeping
        # the API alive also makes it possible to recover when Redis returns.
        resources.redis_connected = False
        logger.warning("redis_unavailable_at_startup", err=str(exc))

    try:
        await rag.initialize()
        yield
    finally:
        logger.info("shutdown")
        if resources.http_client:
            await resources.http_client.aclose()
        if resources.redis_pool:
            await resources.redis_pool.aclose()
        resources.http_client = None
        resources.redis_pool = None
        resources.redis_connected = False


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, version=settings.VERSION, lifespan=lifespan)

    # When origins are wildcarded, credentials must be disabled (CORS spec).
    allow_credentials = settings.CORS_ORIGINS != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(webhook.router)
    app.include_router(admin.router)
    app.include_router(health.router)
    return app


app = create_app()
