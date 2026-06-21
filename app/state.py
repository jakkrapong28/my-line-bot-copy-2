"""Shared mutable runtime state (connection pools + Redis circuit breaker)."""
from typing import Optional

import httpx
import redis.asyncio as redis


class Resources:
    redis_pool: Optional[redis.Redis] = None
    http_client: Optional[httpx.AsyncClient] = None
    # Redis circuit breaker
    redis_last_failure: float = 0.0
    redis_failure_count: int = 0
    CIRCUIT_OPEN_TIMEOUT: float = 60.0


resources = Resources()
