"""Application configuration loaded from environment / .env."""
from pathlib import Path
from typing import List

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "ENEOS AI v5.3 Ultimate"
    VERSION: str = "2026.05.3"
    DEBUG: bool = False

    FORCE_REBUILD_DB: bool = False

    # --- Secrets (must be provided via environment / .env) ---
    LINE_CHANNEL_ACCESS_TOKEN: SecretStr = Field(...)
    LINE_CHANNEL_SECRET: SecretStr = Field(...)
    GROQ_API_KEY: SecretStr = Field(...)
    ADMIN_PASSWORD: SecretStr = Field(...)
    ADMIN_JWT_SECRET: SecretStr = Field(...)

    REDIS_URL: str = "redis://localhost:6379/0"

    # --- CORS ---
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])

    # --- Runtime limits ---
    MAX_CONCURRENT_RAG: int = 5
    CACHE_TTL_SECONDS: int = 31_536_000
    RATE_LIMIT_PER_MINUTE: int = 100
    HISTORY_TTL_SECONDS: int = 31_536_000
    MAX_HISTORY_MESSAGES: int = 6  # ~3 user/assistant turns of context

    # --- RAG tuning ---
    CHUNK_SIZE: int = 1200
    CHUNK_OVERLAP: int = 120
    RETRIEVER_K: int = 15
    RERANK_TOP_K: int = 6
    RERANK_HARD_CUTOFF: float = 0.15
    MAX_UPLOAD_SIZE_MB: int = 50

    @computed_field
    @property
    def base_dir(self) -> Path:
        return BASE_DIR

    @computed_field
    @property
    def knowledge_dir(self) -> Path:
        return BASE_DIR / "knowledge"

    @computed_field
    @property
    def chroma_path(self) -> Path:
        return BASE_DIR / "chroma_db_v5"

    @computed_field
    @property
    def bm25_cache_path(self) -> Path:
        return BASE_DIR / "bm25_cache_v5.joblib"

    @computed_field
    @property
    def rerank_models_dir(self) -> Path:
        return BASE_DIR / "rerank_models"


settings = Settings()
settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
