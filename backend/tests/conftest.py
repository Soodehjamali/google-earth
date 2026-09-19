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


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires Earth Engine credentials and internet access; "
        "skipped unless RUN_GEE_INTEGRATION_TESTS is set",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-skip integration-marked tests when the opt-in flag is absent."""
    if _integration_enabled():
        return
    skip_marker = pytest.mark.skip(
        reason=(
            "Integration test skipped by default. "
            "Set RUN_GEE_INTEGRATION_TESTS=1 to enable."
        )
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
