from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CLOUDEO_",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 18800
    database_url: str = "sqlite+aiosqlite:///./cloudeo.db"

    jev_backend: str = "mock"
    jev_model: str = "typesafe/jev-1.13"
    jev_url: str = "https://openrouter.ai/api/alpha/decisions"
    openrouter_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OPENROUTER_API_KEY",
            "CLOUDEO_OPENROUTER_API_KEY",
        ),
    )

    treg_backend: str = "mock"
    treg_repo: str | None = None
    treg_timeout_seconds: int = 60

    # Search a wider band, then retain only compatible concrete providers.
    treg_discovery_limit: int = 12
    treg_candidate_limit: int = 5

    route_confidence: float = 0.65
    verify_probability: float = 0.85
    max_attempts: int = 2


settings = Settings()
