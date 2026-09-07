"""Application configuration using pydantic-settings."""

from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Database (async driver — matches asyncpg in requirements and
    # create_async_engine in app/db/session.py)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agri_intelligence"

    # Google Earth Engine
    EE_PROJECT_ID: Optional[str] = None
    EE_SERVICE_ACCOUNT: Optional[str] = None
    EE_PRIVATE_KEY_FILE: Optional[str] = None

    # Redis
    REDIS_URL: Optional[str] = None

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Cache
    CACHE_TTL: int = 3600

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


settings = Settings()
