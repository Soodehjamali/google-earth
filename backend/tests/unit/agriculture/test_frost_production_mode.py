import os
import pytest
from app.main import validate_production_frost_safety
from app.core.config import settings

def test_production_mode_rejects_fake_forecast(monkeypatch):
    """Verify that in production environment, setting FROST_USE_LIVE_GEE=0 raises RuntimeError at startup (X5)."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FROST_USE_LIVE_GEE", "0")

    with pytest.raises(RuntimeError, match="CRITICAL_PRODUCTION_SAFETY_VIOLATION"):
        validate_production_frost_safety()


def test_production_mode_allows_live_forecast(monkeypatch):
    """Verify that in production environment with live GEE enabled, startup check succeeds."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FROST_USE_LIVE_GEE", "1")

    # Should not raise
    validate_production_frost_safety()


def test_development_mode_allows_fake_forecast(monkeypatch):
    """Verify that in development environment, fake forecast is permitted without startup crash."""
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("FROST_USE_LIVE_GEE", "0")

    # Should not raise
    validate_production_frost_safety()
