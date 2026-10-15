from pathlib import Path
from typing import List, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"

#: Credential combinations that are acceptable for local development only.
_DEV_DATABASE_MARKERS = ("postgres:postgres@", "postgres:postgres123@")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(str(_ENV_FILE), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Database (async driver — matches asyncpg in requirements and
    # create_async_engine in app/db/session.py)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres123@localhost:5434/agri_intelligence"

    # Database connection pool
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_TIMEOUT: int = 30

    # Google Earth Engine
    EE_PROJECT_ID: Optional[str] = "proverbial-will-507706-e1"
    EE_SERVICE_ACCOUNT: Optional[str] = "agricultural-ai@proverbial-will-507706-e1.iam.gserviceaccount.com"
    EE_PRIVATE_KEY_FILE: Optional[str] = "backend/credentials/gee-key.json"

    # Redis
    REDIS_URL: Optional[str] = None

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Cache
    CACHE_TTL: int = 3600

    # Tile Proxy Security
    TILE_SIGNING_SECRET: str = "agri_tile_secret_default_key_change_in_production"
    TRUSTED_PROXIES: List[str] = ["127.0.0.1", "::1"]

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @model_validator(mode="after")
    def _validate_production_safety(self) -> "Settings":
        """Reject unsafe configuration when APP_ENV=production.

        Development defaults (debug mode, well-known database credentials,
        wildcard CORS) must never reach a production deployment. Fail fast at
        startup instead of silently running with them.
        """
        if not self.is_production:
            return self

        problems: List[str] = []
        if self.APP_DEBUG:
            problems.append("APP_DEBUG must be false when APP_ENV=production")
        for marker in _DEV_DATABASE_MARKERS:
            if marker in self.DATABASE_URL:
                problems.append(
                    "DATABASE_URL uses development default credentials; "
                    "supply production credentials via the environment"
                )
                break
        if any(origin.strip() == "*" for origin in self.CORS_ORIGINS):
            problems.append("CORS_ORIGINS must not contain '*' in production")
        if not self.DATABASE_URL:
            problems.append("DATABASE_URL must be set in production")
        if problems:
            raise ValueError(
                "Unsafe production configuration: " + "; ".join(problems)
            )
        return self


settings = Settings()
