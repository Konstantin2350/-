from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "ИИ-Оркестр"
    environment: str = "development"
    api_key: str | None = None
    webhook_secret: str | None = None
    database_url: str = "sqlite+aiosqlite:///./orchestra.db"
    redis_url: str | None = None
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    internal_api_url: str = "http://api:8787"
    bitrix_webhook_url: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-5-mini"
    embedding_model: str = "text-embedding-3-large"
    memory_ttl_seconds: int = 86_400
    knowledge_chunk_size: int = Field(default=900, ge=200, le=4_000)
    knowledge_chunk_overlap: int = Field(default=120, ge=0, le=1_000)
    max_upload_bytes: int = 20 * 1024 * 1024
    max_agent_steps: int = Field(default=8, ge=1, le=20)
    cors_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
