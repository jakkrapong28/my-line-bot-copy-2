"""Redis-backed distributed rate limiting, response cache and chat history.

All Redis access goes through ``_safe`` which implements a simple circuit
breaker so that a Redis outage degrades gracefully instead of taking the
whole bot down.
"""
import json
import time
from typing import Awaitable, Dict, List, Optional

import redis.asyncio as redis
from fastapi import HTTPException
from redis.exceptions import RedisError

from ..config import settings
from ..logging_setup import cache_stats, logger
from ..state import resources


class RedisService:
    def __init__(self, client: redis.Redis):
        self.client = client

    async def _safe(self, coro: Awaitable):
        now = time.time()
        if (
            resources.redis_failure_count >= 3
            and now - resources.redis_last_failure < resources.CIRCUIT_OPEN_TIMEOUT
        ):
            return None
        try:
            result = await coro
            resources.redis_failure_count = 0
            return result
        except RedisError as e:
            resources.redis_failure_count += 1
            resources.redis_last_failure = time.time()
            logger.error("redis_error", err=str(e))
            return None

    async def check_rate_limit(self, identifier: str) -> bool:
        key = f"rate_limit:{identifier}"

        async def _op():
            async with self.client.pipeline() as p:
                p.incr(key)
                p.expire(key, 60)
                r = await p.execute()
                return r[0] <= settings.RATE_LIMIT_PER_MINUTE

        # Fail open: if Redis is unavailable we allow the request.
        result = await self._safe(_op())
        return True if result is None else result

    async def get_cache(self, key: str) -> Optional[str]:
        val = await self._safe(self.client.get(key))
        if val:
            cache_stats.hits += 1
        else:
            cache_stats.misses += 1
        return val

    async def set_cache(self, key: str, value: str) -> None:
        await self._safe(self.client.setex(key, settings.CACHE_TTL_SECONDS, value))

    async def purge_cache_by_prefix(self, prefix: str) -> int:
        cursor, deleted = 0, 0
        pattern = f"{prefix}:*"
        try:
            while True:
                cursor, keys = await self.client.scan(cursor, match=pattern, count=500)
                if keys:
                    await self.client.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
        except RedisError as e:
            logger.warning("cache_purge_failed", err=str(e))
        return deleted

    async def get_history(self, user_id: str) -> List[Dict]:
        key = f"hist:{user_id}"
        data = await self._safe(self.client.get(key))
        return json.loads(data) if data else []

    async def append_history(self, user_id: str, new_msgs: List[Dict]) -> None:
        key = f"hist:{user_id}"
        hist = await self.get_history(user_id)
        hist.extend(new_msgs)
        hist = hist[-settings.MAX_HISTORY_MESSAGES:]
        await self._safe(
            self.client.setex(key, settings.HISTORY_TTL_SECONDS, json.dumps(hist, ensure_ascii=False))
        )


async def get_redis_svc() -> RedisService:
    if not resources.redis_pool:
        raise HTTPException(503, "Redis is down")
    return RedisService(resources.redis_pool)
