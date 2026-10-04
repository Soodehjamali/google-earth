"""Tests for agriculture analysis caching (Phase S.3).

Proves that the cache service is integrated into the agriculture
analysis flow: cache miss executes metrics and stores results,
cache hit returns cached results without re-execution, different
requests produce separate cache entries, and failed computations
are not cached.

All tests mock Earth Engine and the metric executor.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from app.services.cache_service import CacheService, cache_service


# ---------------------------------------------------------------------------
# 1. Cache service unit tests
# ---------------------------------------------------------------------------


class TestCacheServiceUnit:
    """Verify the CacheService basics."""

    def setup_method(self) -> None:
        self.cache = CacheService(ttl=60)

    def test_set_and_get(self) -> None:
        self.cache.set("key1", {"data": "value"})
        assert self.cache.get("key1") == {"data": "value"}

    def test_get_missing_key(self) -> None:
        assert self.cache.get("nonexistent") is None

    def test_invalidate(self) -> None:
        self.cache.set("key1", "value")
        self.cache.invalidate("key1")
        assert self.cache.get("key1") is None

    def test_size(self) -> None:
        assert self.cache.size == 0
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        assert self.cache.size == 2

    def test_clear(self) -> None:
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        self.cache.clear()
        assert self.cache.size == 0


# ---------------------------------------------------------------------------
# 2. Cache key determinism tests
# ---------------------------------------------------------------------------


class TestCacheKeyDeterminism:
    """Verify _build_analysis_cache_key produces deterministic, distinct keys."""

    def test_same_request_same_key(self) -> None:
        from app.api.v1.agriculture import _build_analysis_cache_key
        from app.schemas.agriculture import AgricultureAnalysisRequest

        req = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
        )
        k1 = _build_analysis_cache_key(req)
        k2 = _build_analysis_cache_key(req)
        assert k1 == k2
        assert len(k1) == 64  # SHA-256 hex digest

    def test_different_geometry_different_key(self) -> None:
        from app.api.v1.agriculture import _build_analysis_cache_key
        from app.schemas.agriculture import AgricultureAnalysisRequest

        req1 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
        )
        req2 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [52.0, 36.0]},
            start_date="2024-07-01",
            end_date="2024-07-31",
        )
        assert _build_analysis_cache_key(req1) != _build_analysis_cache_key(req2)

    def test_different_dates_different_key(self) -> None:
        from app.api.v1.agriculture import _build_analysis_cache_key
        from app.schemas.agriculture import AgricultureAnalysisRequest

        req1 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
        )
        req2 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-08-01",
            end_date="2024-08-31",
        )
        assert _build_analysis_cache_key(req1) != _build_analysis_cache_key(req2)

    def test_different_domains_different_key(self) -> None:
        from app.api.v1.agriculture import _build_analysis_cache_key
        from app.schemas.agriculture import AgricultureAnalysisRequest

        req1 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=["vegetation"],
        )
        req2 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=["water"],
        )
        assert _build_analysis_cache_key(req1) != _build_analysis_cache_key(req2)


# ---------------------------------------------------------------------------
# 3. Agriculture endpoint cache integration tests
# ---------------------------------------------------------------------------


def _make_mock_outcome(key: str, value: Any) -> MagicMock:
    """Create a mock ExecutionOutcome."""
    from app.services.agriculture.catalog import get_metric
    from app.services.agriculture.types import MetricResult, Provenance, QualityLevel, TemporalKind

    metric = get_metric(key)
    result = MetricResult(
        metric_key=key,
        display_name=metric.display_name,
        display_name_fa=metric.display_name_fa,
        status="ok",
        value=value,
        unit=metric.unit,
        provenance=Provenance(
            source_dataset_id=metric.dataset_ids[0] if metric.dataset_ids else "unknown",
            source_dataset_name=metric.display_name,
            bands=[],
            formula="",
            unit=metric.unit,
            spatial_resolution="1 km",
            temporal_resolution="16-day",
            measurement_basis=QualityLevel.GOOD,
            quality_level=QualityLevel.GOOD,
            temporal_kind=TemporalKind.OBSERVATION,
            requested_start="2024-07-01",
            requested_end="2024-07-31",
        ),
        warnings=[],
    )
    outcome = MagicMock()
    outcome.result = result
    outcome.metric_key = key
    return outcome


class TestAgricultureEndpointCache:
    """Prove cache is used in POST /api/v1/agriculture/analysis."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        """Clear the global cache before each test."""
        cache_service.clear()
        yield
        cache_service.clear()

    def test_cache_miss_executes_metrics_and_stores(self) -> None:
        """First call: cache miss → metrics executed → result stored."""
        from app.services.agriculture.catalog import get_metric

        mock_geometry = MagicMock()
        outcomes = {
            "ndvi": _make_mock_outcome("ndvi", 0.65),
            "evi": _make_mock_outcome("evi", 0.55),
        }

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ) as mock_execute:
            response = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        assert response.status_code == 200
        # Metrics were executed
        mock_execute.assert_called_once()
        # Cache now has one entry
        assert cache_service.size == 1

    def test_cache_hit_returns_cached_without_reexecution(self) -> None:
        """Second identical call: cache hit → no metric execution."""
        mock_geometry = MagicMock()
        outcomes = {
            "ndvi": _make_mock_outcome("ndvi", 0.65),
            "evi": _make_mock_outcome("evi", 0.55),
        }

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ) as mock_execute:
            # First call → cache miss
            resp1 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            assert resp1.status_code == 200
            call_count_after_first = mock_execute.call_count

            # Second call → cache hit
            resp2 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            assert resp2.status_code == 200
            # Metrics were NOT called again
            assert mock_execute.call_count == call_count_after_first

        # Both responses have identical domain summaries
        assert resp1.json()["domain_summaries"] == resp2.json()["domain_summaries"]

    def test_different_requests_produce_separate_entries(self) -> None:
        """Different geometry → different cache key → separate entries."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [52.0, 36.0]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        assert cache_service.size == 2


# ---------------------------------------------------------------------------
# 4. analysis_service cache integration tests
# ---------------------------------------------------------------------------


class TestAnalysisServiceCache:
    """Prove cache is used in AnalysisService.create_analysis."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        cache_service.clear()
        yield
        cache_service.clear()

    @pytest.mark.parametrize("analysis_type", ["climate", "water", "soil"])
    def test_domain_analysis_cache_hit(self, analysis_type: str) -> None:
        """Second call for same domain analysis → cache hit, no EE call."""
        from app.services.analysis_service import AnalysisService

        service = AnalysisService()
        geometry = {"type": "Point", "coordinates": [51.3, 35.7]}
        db = MagicMock()

        mock_geometry = MagicMock()
        result_data = {"status": "completed", "analysis_type": analysis_type}

        with patch(
            "app.services.analysis_service.create_ee_geometry",
            return_value=mock_geometry,
        ), patch.object(
            service, "_run_domain_analysis", return_value=result_data
        ) as mock_run:
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                # First call → cache miss
                r1 = loop.run_until_complete(
                    service.create_analysis(db, geometry, "2025-01-01", "2025-09-01", analysis_type)
                )
                assert mock_run.call_count == 1

                # Second call → cache hit
                r2 = loop.run_until_complete(
                    service.create_analysis(db, geometry, "2025-01-01", "2025-09-01", analysis_type)
                )
                # _run_domain_analysis was NOT called again
                assert mock_run.call_count == 1
                assert r2["status"] == "completed"
            finally:
                loop.close()

    def test_failed_result_not_cached(self) -> None:
        """A failed analysis result is not stored in cache."""
        from app.services.analysis_service import AnalysisService

        service = AnalysisService()
        geometry = {"type": "Point", "coordinates": [51.3, 35.7]}
        db = MagicMock()

        mock_geometry = MagicMock()
        result_data = {"status": "failed", "message": "error"}

        with patch(
            "app.services.analysis_service.create_ee_geometry",
            return_value=mock_geometry,
        ), patch.object(
            service, "_run_domain_analysis", return_value=result_data
        ):
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    service.create_analysis(db, geometry, "2025-01-01", "2025-09-01", "climate")
                )
            finally:
                loop.close()

        # Cache should be empty because result was "failed"
        assert cache_service.size == 0


# ---------------------------------------------------------------------------
# 5. Import test client from existing test setup
# ---------------------------------------------------------------------------

# Reuse the test app and client from the existing agriculture tests
from app.api.v1 import agriculture
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agriculture.router, prefix="/api/v1/agriculture")

    @app.exception_handler(Exception)
    async def exception_handler(request: Any, exc: Exception) -> Any:
        from starlette.responses import JSONResponse
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return app


_test_app = _create_test_app()
client = TestClient(_test_app)


@pytest.fixture(autouse=True)
def _register_metrics():
    """Ensure the metric registry is populated for every test."""
    from app.services.agriculture import register_all_metrics
    from app.services.agriculture.catalog import metric_keys

    if not metric_keys():
        register_all_metrics()
    yield
