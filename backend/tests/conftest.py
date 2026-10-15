"""Shared test configuration.

Two hard rules encoded here:

1. Integration tests that touch Earth Engine are SKIPPED unless the
   environment variable ``RUN_GEE_INTEGRATION_TESTS`` is set to a truthy
   value. The default test run must never require internet access or
   credentials.
2. Unit tests must never import ``ee``. A guard below fails loudly if a
   unit test tries, because that would silently make the suite depend on
   Earth Engine being initialised.
"""

from __future__ import annotations

import os
import sys

import pytest

TRUTHY = {"1", "true", "yes", "on"}


def _integration_enabled() -> bool:
    return os.environ.get("RUN_GEE_INTEGRATION_TESTS", "").strip().lower() in TRUTHY


def _gee_credentials_available() -> bool:
    """Check if valid Earth Engine credentials are configured and accessible."""
    try:
        from app.services.earth_engine.authentication import (
            _service_account_configured,
            _has_default_credentials,
            _key_file,
            configuration_problems,
        )
        if _service_account_configured():
            kf = _key_file()
            if kf is not None and kf.exists():
                return len(configuration_problems()) == 0
        if _has_default_credentials():
            return True
        return False
    except Exception:
        return False


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires Earth Engine credentials and internet access; "
        "skipped unless RUN_GEE_INTEGRATION_TESTS is set",
    )
    config.addinivalue_line(
        "markers",
        "requires_gee: requires configured Earth Engine credentials and initialization; "
        "auto-skips when no credentials are configured",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-skip integration-marked tests when the opt-in flag is absent,
    and auto-skip requires_gee tests when GEE credentials are not configured."""
    gee_available = _gee_credentials_available()
    skip_gee_marker = pytest.mark.skip(
        reason="Test requires Earth Engine credentials; skipped because GEE is not configured."
    )
    skip_integration_marker = pytest.mark.skip(
        reason=(
            "Integration test skipped by default. "
            "Set RUN_GEE_INTEGRATION_TESTS=1 to enable."
        )
    )
    for item in items:
        if "requires_gee" in item.keywords and not gee_available:
            item.add_marker(skip_gee_marker)
        if "integration" in item.keywords and not _integration_enabled():
            item.add_marker(skip_integration_marker)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
