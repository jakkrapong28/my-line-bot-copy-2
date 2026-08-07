"""Shared mutable runtime state (connection pools + Redis circuit breaker)."""

import httpx
import redis.asyncio as redis


class Resources:
    redis_pool: redis.Redis | None = None
    http_client: httpx.AsyncClient | None = None
    redis_connected: bool = False
    # Redis circuit breaker
    redis_last_failure: float = 0.0
    redis_failure_count: int = 0
    CIRCUIT_OPEN_TIMEOUT: float = 60.0


resources = Resources()
