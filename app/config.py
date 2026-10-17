from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    api_key: str | None = None
    allowed_origins: str = ""
    c2e_model: str = "megalaa/coptic-english-translator"
    e2c_model: str = "megalaa/english-coptic-translator"
    c2e_revision: str = "main"
    e2c_revision: str = "main"
    max_input_chars: int = Field(default=1200, ge=1, le=10_000)
    rate_limit: str = "30/minute"
    cache_entries: int = Field(default=1000, ge=1, le=100_000)
    cache_ttl_seconds: int = Field(default=3600, ge=1, le=86_400)
    generation_max_new_tokens: int = Field(default=64, ge=1, le=512)

    model_config = SettingsConfigDict(
        env_prefix="COPTIC_",
        env_file=".env",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
