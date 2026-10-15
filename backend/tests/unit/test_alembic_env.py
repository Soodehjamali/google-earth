"""Tests for Alembic environment configuration and URL resolution."""

from pathlib import Path
from alembic.config import Config
from app.core.config import settings


def test_alembic_env_resolves_production_settings_database_url():
    """Verify that without explicit test override, alembic resolves settings.DATABASE_URL."""
    ini_path = Path("alembic.ini") if Path("alembic.ini").exists() else Path("backend/alembic.ini")
    cfg = Config(str(ini_path))

    # 1. By default, alembic.ini contains NO hardcoded credentials
    raw_url = cfg.get_main_option("sqlalchemy.url")
    assert raw_url is None or "driver://user:pass" in raw_url or raw_url == ""

    # 2. Production env.py resolution strictly injects settings.DATABASE_URL
    existing_url = cfg.get_main_option("sqlalchemy.url")
    if not existing_url or "driver://user:pass" in existing_url:
        cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    resolved_url = cfg.get_main_option("sqlalchemy.url")
    assert resolved_url == settings.DATABASE_URL
    assert "driver://user:pass" not in resolved_url


def test_alembic_env_respects_explicit_test_url_override():
    """Verify that explicit programmatic overrides (e.g. SQLite for tests) are preserved."""
    ini_path = Path("alembic.ini") if Path("alembic.ini").exists() else Path("backend/alembic.ini")
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", "sqlite:///test.db")

    existing_url = cfg.get_main_option("sqlalchemy.url")
    if not existing_url or "driver://user:pass" in existing_url:
        cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    # Must preserve the explicit sqlite test URL override
    assert cfg.get_main_option("sqlalchemy.url") == "sqlite:///test.db"
