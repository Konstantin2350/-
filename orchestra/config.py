from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ИИ-Оркестр"
    environment: str = "development"
    api_key: str | None = None
    api_keys: str = ""
    jwt_secret: str | None = None
    jwt_issuer: str = "ai-orchestra"
    webhook_secret: str | None = None
    database_url: str = "sqlite+aiosqlite:///./orchestra.db"
    redis_url: str | None = None
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    bitrix_webhook_url: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-5-mini"
    embedding_model: str = "text-embedding-3-large"
    stt_base_url: str | None = None
    stt_api_key: str | None = None
    stt_model: str = "whisper-1"
    memory_ttl_seconds: int = 86_400
    knowledge_chunk_size: int = Field(default=900, ge=200, le=4_000)
    knowledge_chunk_overlap: int = Field(default=120, ge=0, le=1_000)
    max_upload_bytes: int = 20 * 1024 * 1024
    max_document_text_chars: int = 5_000_000
    max_audio_bytes: int = 100 * 1024 * 1024
    max_agent_steps: int = Field(default=8, ge=1, le=20)
    rate_limit_per_minute: int = Field(default=300, ge=10, le=100_000)
    cors_origins: str = ""

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def api_key_roles(self) -> dict[str, str]:
        result: dict[str, str] = {}
        if self.api_key:
            result[self.api_key] = "admin"
        for item in self.api_keys.split(","):
            key, separator, role = item.strip().partition(":")
            if separator and key and role in {"viewer", "operator", "manager", "admin"}:
                result[key] = role
        return result

    @property
    def production_issues(self) -> list[str]:
        issues = []
        if self.environment == "production":
            if not self.api_key_roles and not self.jwt_secret:
                issues.append("API_KEYS or JWT_SECRET is required")
            if not self.webhook_secret:
                issues.append("WEBHOOK_SECRET is required")
            if not self.database_url.startswith("postgresql+asyncpg://"):
                issues.append("PostgreSQL DATABASE_URL is required")
            if not self.redis_url:
                issues.append("REDIS_URL is required")
        return issues


@lru_cache
def get_settings() -> Settings:
    return Settings()
