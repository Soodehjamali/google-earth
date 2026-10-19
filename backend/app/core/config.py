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
    DATABASE_URL: str = "postgresql+asyncpg://postgres@localhost:5434/agri_intelligence"

    # Database connection pool
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_TIMEOUT: int = 30

    # Google Earth Engine (credentials supplied via environment or .env)
    EE_PROJECT_ID: Optional[str] = None
    EE_SERVICE_ACCOUNT: Optional[str] = None
    EE_PRIVATE_KEY_FILE: Optional[str] = None

    # Redis
    REDIS_URL: Optional[str] = None

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Cache
    CACHE_TTL: int = 3600

    # Tile Proxy Security
    TILE_SIGNING_SECRET: str = "agri_tile_secret_default_key_change_in_production"
    TRUSTED_PROXIES: List[str] = ["127.0.0.1", "::1"]

    # Frost Risk Authentication & Administration
    ADMIN_API_KEY: Optional[str] = None
    ALERT_ADMIN_OVERRIDE: bool = False
    FROST_USE_LIVE_GEE: bool = False
    USE_LIVE_GEE: Optional[bool] = None
    GEE_TILE_TIMEOUT_SECONDS: float = 60.0

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @model_validator(mode="after")
    def _validate_and_resolve_settings(self) -> "Settings":
        """Resolve USE_LIVE_GEE default and validate production safety."""
        if self.USE_LIVE_GEE is None:
            if self.FROST_USE_LIVE_GEE:
                self.USE_LIVE_GEE = True
            elif self.EE_PROJECT_ID and self.EE_PRIVATE_KEY_FILE:
                key_path = Path(self.EE_PRIVATE_KEY_FILE)
                if not key_path.is_absolute():
                    key_path = _BACKEND_DIR / self.EE_PRIVATE_KEY_FILE
                self.USE_LIVE_GEE = key_path.exists()
            else:
                self.USE_LIVE_GEE = False

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
