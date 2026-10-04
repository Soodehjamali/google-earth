"""Production configuration safety tests.

Verifies the fail-fast validation that prevents development defaults from
reaching a production deployment, and that the hardened routes/middleware
are wired correctly. These tests never touch the network, a database, or
Earth Engine.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


def _make_settings(**overrides) -> Settings:
    """Build Settings without reading any .env file or process env leakage."""
    base = {
        "_env_file": None,
        "APP_ENV": "production",
        "APP_DEBUG": False,
        "DATABASE_URL": "postgresql+asyncpg://appuser:strong-pass@db.internal:5432/agri",
        "CORS_ORIGINS": ["https://agri.example.com"],
    }
    base.update(overrides)
    return Settings(**base)


class TestDevelopmentDefaults:
    def test_development_defaults_are_accepted(self):
        settings = Settings(_env_file=None)
        assert settings.is_development
        assert settings.APP_DEBUG is True

    def test_development_allows_localhost_database(self):
        settings = Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/agri_intelligence",
        )
        assert settings.is_development


class TestProductionValidation:
    def test_clean_production_config_is_accepted(self):
        settings = _make_settings()
        assert settings.is_production
        assert settings.APP_DEBUG is False

    def test_production_rejects_debug_mode(self):
        with pytest.raises(ValueError, match="APP_DEBUG"):
            _make_settings(APP_DEBUG=True)

    def test_production_rejects_default_database_credentials(self):
        with pytest.raises(ValueError, match="development default credentials"):
            _make_settings(
                DATABASE_URL="postgresql+asyncpg://postgres:postgres@db:5432/agri"
            )

    def test_production_rejects_legacy_default_database_credentials(self):
        with pytest.raises(ValueError, match="development default credentials"):
            _make_settings(
                DATABASE_URL="postgresql+asyncpg://postgres:postgres123@db:5432/agri"
            )

    def test_production_rejects_wildcard_cors(self):
        with pytest.raises(ValueError, match="CORS_ORIGINS"):
            _make_settings(CORS_ORIGINS=["*"])


class TestHardenedAppWiring:
    """Static wiring checks — importing the app must not start it."""

    def test_readiness_route_is_registered(self):
        from app.main import app

        paths = {route.path for route in app.routes}
        assert "/api/v1/health" in paths
        assert "/api/v1/health/ready" in paths

    def test_docs_enabled_in_development(self):
        from app.main import app

        # Tests run with development defaults, so docs must be available.
        assert app.docs_url == "/docs"
        assert app.openapi_url == "/openapi.json"
