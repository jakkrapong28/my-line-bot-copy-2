"""Structured logging and in-process cache statistics."""
import structlog

from .config import settings

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.dev.ConsoleRenderer() if settings.DEBUG else structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.WriteLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


class CacheStats:
    __slots__ = ("hits", "misses", "direct_hits")

    def __init__(self) -> None:
        self.hits = self.misses = self.direct_hits = 0

    @property
    def hit_rate(self) -> str:
        total = self.hits + self.misses
        return "N/A" if not total else f"{self.hits / total * 100:.1f}% ({self.hits}/{total})"


cache_stats = CacheStats()
