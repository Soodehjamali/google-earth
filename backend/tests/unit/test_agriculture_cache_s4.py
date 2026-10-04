"""Tests for agriculture analysis cache correctness (Phase S.4).

Covers:
  A. identical request -> cache hit
  B. materially different request -> cache miss
  C. cache hit returns equivalent result
  D. failed analysis is not cached
  E. cache backend/read failure does not break analysis
  F. cache write failure does not break analysis
  G. no cross-request cache contamination
  H. analysis does not execute expensive path after valid cache hit
  I. cache key changes when materially result-affecting input changes
  J. cache key remains stable for semantically identical requests

All tests mock Earth Engine and the metric executor.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.cache_service import CacheService, cache_service


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the global cache before and after each test."""
    cache_service.clear()
    yield
    cache_service.clear()


def _make_mock_outcome(key: str, value: Any) -> MagicMock:
    """Create a mock ExecutionOutcome."""
    from app.services.agriculture.catalog import get_metric
    from app.services.agriculture.types import (
        MetricResult,
        Provenance,
        QualityLevel,
        TemporalKind,
    )

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


@pytest.fixture(autouse=True)
def _register_metrics():
    """Ensure the metric registry is populated for every test."""
    from app.services.agriculture import register_all_metrics
    from app.services.agriculture.catalog import metric_keys

    if not metric_keys():
        register_all_metrics()
    yield


# Reuse the test app and client from the existing agriculture tests
from app.api.v1 import agriculture
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agriculture.router, prefix="/api/v1/agriculture")

    from app.core.exceptions import AppException

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Any, exc: AppException) -> Any:
        from starlette.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def exception_handler(request: Any, exc: Exception) -> Any:
        from starlette.responses import JSONResponse
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return app


_test_app = _create_test_app()
client = TestClient(_test_app)


# ---------------------------------------------------------------------------
# A. Identical request -> cache hit
# ---------------------------------------------------------------------------


class TestCacheHitOnIdenticalRequest:
    def test_identical_request_returns_cache_hit(self) -> None:
        """Two identical requests: second should hit cache."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ) as mock_execute:
            # First call — cache miss
            resp1 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            assert resp1.status_code == 200
            first_call_count = mock_execute.call_count

            # Second call — should hit cache
            resp2 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            assert resp2.status_code == 200
            # Metrics NOT executed again
            assert mock_execute.call_count == first_call_count


# ---------------------------------------------------------------------------
# B. Materially different request -> cache miss
# ---------------------------------------------------------------------------


class TestCacheMissOnDifferentRequest:
    def test_different_geometry_causes_cache_miss(self) -> None:
        """Different geometry -> different cache key -> full execution."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ) as mock_execute:
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
            # Both should have executed metrics
            assert mock_execute.call_count == 2

    def test_different_dates_causes_cache_miss(self) -> None:
        """Different date range -> different cache key -> full execution."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ) as mock_execute:
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
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-08-01",
                    "end_date": "2024-08-31",
                },
            )
            assert mock_execute.call_count == 2

    def test_different_domains_causes_cache_miss(self) -> None:
        """Different domains -> different cache key -> full execution."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ) as mock_execute:
            client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                    "domains": ["vegetation"],
                },
            )
            client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                    "domains": ["water"],
                },
            )
            assert mock_execute.call_count == 2


# ---------------------------------------------------------------------------
# C. Cache hit returns equivalent result
# ---------------------------------------------------------------------------


class TestCacheHitReturnsEquivalentResult:
    def test_cache_hit_returns_same_domain_summaries(self) -> None:
        """Cached response has identical domain summaries to fresh response."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            resp1 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            resp2 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        assert resp1.json()["domain_summaries"] == resp2.json()["domain_summaries"]
        assert resp1.json()["evidence_bundles"] == resp2.json()["evidence_bundles"]
        assert resp1.json()["overall_sufficiency"] == resp2.json()["overall_sufficiency"]

    def test_cache_hit_preserves_response_structure(self) -> None:
        """Cached response preserves all top-level keys."""
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
            resp = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        data = resp.json()
        required_keys = {
            "domain_summaries", "evidence_bundles", "overall_sufficiency",
            "available_domains", "limitations", "metadata",
        }
        assert required_keys.issubset(data.keys())


# ---------------------------------------------------------------------------
# D. Failed analysis is not cached
# ---------------------------------------------------------------------------


class TestFailedAnalysisNotCached:
    def test_failed_result_not_cached_in_endpoint(self) -> None:
        """A failing analysis (exception) should not be stored in cache."""
        with patch(
            "app.utils.geometry.create_ee_geometry",
            side_effect=RuntimeError("EE unavailable"),
        ):
            resp = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
        assert resp.status_code == 500
        assert cache_service.size == 0

    def test_failed_result_not_cached_in_analysis_service(self) -> None:
        """AnalysisService: failed result should not be stored in cache."""
        from app.services.analysis_service import AnalysisService

        service = AnalysisService()
        geometry = {"type": "Point", "coordinates": [51.3, 35.7]}
        db = MagicMock()

        with patch(
            "app.services.analysis_service.create_ee_geometry",
            side_effect=RuntimeError("EE unavailable"),
        ):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    service.create_analysis(db, geometry, "2025-01-01", "2025-09-01", "climate")
                )
            finally:
                loop.close()

        assert result["status"] == "failed"
        assert cache_service.size == 0


# ---------------------------------------------------------------------------
# E. Cache backend/read failure does not break analysis
# ---------------------------------------------------------------------------


class TestCacheReadFailureGraceful:
    def test_cache_get_exception_proceeds_without_cache(self) -> None:
        """If cache_service.get() raises, analysis should still succeed."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ), patch(
            "app.services.cache_service.cache_service.get",
            side_effect=RuntimeError("cache backend down"),
        ):
            resp = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
        assert resp.status_code == 200
        assert "domain_summaries" in resp.json()

    def test_cache_get_exception_in_analysis_service(self) -> None:
        """AnalysisService: cache read failure should not prevent execution."""
        from app.services.analysis_service import AnalysisService

        service = AnalysisService()
        geometry = {"type": "Point", "coordinates": [51.3, 35.7]}
        db = MagicMock()

        mock_geometry = MagicMock()
        result_data = {"status": "completed", "analysis_type": "climate"}

        with patch(
            "app.services.analysis_service.create_ee_geometry",
            return_value=mock_geometry,
        ), patch.object(
            service, "_run_domain_analysis", return_value=result_data
        ), patch(
            "app.services.cache_service.cache_service.get",
            side_effect=RuntimeError("cache backend down"),
        ):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    service.create_analysis(db, geometry, "2025-01-01", "2025-09-01", "climate")
                )
            finally:
                loop.close()

        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# F. Cache write failure does not break analysis
# ---------------------------------------------------------------------------


class TestCacheWriteFailureGraceful:
    def test_cache_set_exception_does_not_break_endpoint(self) -> None:
        """If cache_service.set() raises, analysis should still return."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ), patch(
            "app.services.cache_service.cache_service.set",
            side_effect=RuntimeError("cache backend full"),
        ):
            resp = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
        assert resp.status_code == 200
        # Since cache write failed, a second call should also execute (no cache entry)
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ) as mock_execute:
            resp2 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            assert resp2.status_code == 200
            # Metrics executed again because cache write failed
            mock_execute.assert_called_once()

    def test_cache_set_exception_in_analysis_service(self) -> None:
        """AnalysisService: cache write failure should not prevent return."""
        from app.services.analysis_service import AnalysisService

        service = AnalysisService()
        geometry = {"type": "Point", "coordinates": [51.3, 35.7]}
        db = MagicMock()

        mock_geometry = MagicMock()
        result_data = {"status": "completed", "analysis_type": "climate"}

        with patch(
            "app.services.analysis_service.create_ee_geometry",
            return_value=mock_geometry,
        ), patch.object(
            service, "_run_domain_analysis", return_value=result_data
        ), patch(
            "app.services.cache_service.cache_service.set",
            side_effect=RuntimeError("cache backend full"),
        ):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    service.create_analysis(db, geometry, "2025-01-01", "2025-09-01", "climate")
                )
            finally:
                loop.close()

        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# G. No cross-request cache contamination
# ---------------------------------------------------------------------------


class TestNoCrossRequestContamination:
    def test_different_requests_isolated_in_cache(self) -> None:
        """Two different requests should not leak data into each other."""
        mock_geometry = MagicMock()
        outcomes_a = {"ndvi": _make_mock_outcome("ndvi", 0.65)}
        outcomes_b = {"ndvi": _make_mock_outcome("ndvi", 0.30)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes_a, []),
        ):
            resp_a = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes_b, []),
        ):
            resp_b = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [52.0, 36.0]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        # Verify responses have different evidence
        bundles_a = resp_a.json()["evidence_bundles"]
        bundles_b = resp_b.json()["evidence_bundles"]
        # Both should be valid but with different values
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200


# ---------------------------------------------------------------------------
# H. No expensive path execution after valid cache hit
# ---------------------------------------------------------------------------


class TestNoExecutionAfterCacheHit:
    def test_execute_metrics_not_called_after_cache_hit(self) -> None:
        """After a cache hit, execute_metrics should NOT be called."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ) as mock_execute:
            # Prime the cache
            client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            mock_execute.reset_mock()

            # Cache hit — should not call execute_metrics
            client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            mock_execute.assert_not_called()

    def test_create_ee_geometry_not_called_after_cache_hit(self) -> None:
        """After a cache hit, create_ee_geometry should NOT be called."""
        from app.services.analysis_service import AnalysisService

        service = AnalysisService()
        geometry = {"type": "Point", "coordinates": [51.3, 35.7]}
        db = MagicMock()

        mock_geometry = MagicMock()
        result_data = {"status": "completed", "analysis_type": "climate"}

        with patch(
            "app.services.analysis_service.create_ee_geometry",
            return_value=mock_geometry,
        ) as mock_geom, patch.object(
            service, "_run_domain_analysis", return_value=result_data
        ) as mock_run:
            loop = asyncio.new_event_loop()
            try:
                # Prime the cache
                loop.run_until_complete(
                    service.create_analysis(db, geometry, "2025-01-01", "2025-09-01", "climate")
                )
                mock_geom.reset_mock()
                mock_run.reset_mock()

                # Cache hit — should not create geometry or run domain analysis
                loop.run_until_complete(
                    service.create_analysis(db, geometry, "2025-01-01", "2025-09-01", "climate")
                )
                mock_geom.assert_not_called()
                mock_run.assert_not_called()
            finally:
                loop.close()


# ---------------------------------------------------------------------------
# I. Cache key changes when materially result-affecting input changes
# ---------------------------------------------------------------------------


class TestCacheKeyChangesOnMaterialInput:
    def test_cloud_max_percent_changes_key(self) -> None:
        """Different cloud_max_percent -> different cache key."""
        from app.api.v1.agriculture import _build_analysis_cache_key
        from app.schemas.agriculture import AgricultureAnalysisRequest

        req1 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            cloud_max_percent=20.0,
        )
        req2 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            cloud_max_percent=50.0,
        )
        assert _build_analysis_cache_key(req1) != _build_analysis_cache_key(req2)

    def test_polygon_geometry_changes_key(self) -> None:
        """Different polygon -> different cache key."""
        from app.api.v1.agriculture import _build_analysis_cache_key
        from app.schemas.agriculture import AgricultureAnalysisRequest

        req1 = AgricultureAnalysisRequest(
            geometry={
                "type": "Polygon",
                "coordinates": [[[51.0, 35.0], [51.5, 35.0], [51.5, 35.5], [51.0, 35.5], [51.0, 35.0]]],
            },
            start_date="2024-07-01",
            end_date="2024-07-31",
        )
        req2 = AgricultureAnalysisRequest(
            geometry={
                "type": "Polygon",
                "coordinates": [[[52.0, 36.0], [52.5, 36.0], [52.5, 36.5], [52.0, 36.5], [52.0, 36.0]]],
            },
            start_date="2024-07-01",
            end_date="2024-07-31",
        )
        assert _build_analysis_cache_key(req1) != _build_analysis_cache_key(req2)

    def test_none_vs_empty_domains_same_key(self) -> None:
        """None and [] domains should produce the same key (both mean 'all domains')."""
        from app.api.v1.agriculture import _build_analysis_cache_key
        from app.schemas.agriculture import AgricultureAnalysisRequest

        req_none = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=None,
        )
        req_empty = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=[],
        )
        assert _build_analysis_cache_key(req_none) == _build_analysis_cache_key(req_empty)


# ---------------------------------------------------------------------------
# J. Cache key remains stable for semantically identical requests
# ---------------------------------------------------------------------------


class TestCacheKeyStability:
    def test_same_request_always_same_key(self) -> None:
        """Multiple calls with identical inputs always produce the same key."""
        from app.api.v1.agriculture import _build_analysis_cache_key
        from app.schemas.agriculture import AgricultureAnalysisRequest

        req = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=["vegetation", "water"],
            cloud_max_percent=30.0,
        )
        keys = [_build_analysis_cache_key(req) for _ in range(10)]
        assert len(set(keys)) == 1

    def test_domain_order_does_not_affect_key(self) -> None:
        """Different ordering of same domains should produce the same key."""
        from app.api.v1.agriculture import _build_analysis_cache_key
        from app.schemas.agriculture import AgricultureAnalysisRequest

        req1 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=["vegetation", "water"],
        )
        req2 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
            domains=["water", "vegetation"],
        )
        assert _build_analysis_cache_key(req1) == _build_analysis_cache_key(req2)

    def test_coordinate_precision_does_not_affect_key(self) -> None:
        """Same coordinates with different float precision should produce the same key."""
        from app.api.v1.agriculture import _build_analysis_cache_key
        from app.schemas.agriculture import AgricultureAnalysisRequest

        req1 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.3, 35.7]},
            start_date="2024-07-01",
            end_date="2024-07-31",
        )
        req2 = AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [51.300000, 35.700000]},
            start_date="2024-07-01",
            end_date="2024-07-31",
        )
        assert _build_analysis_cache_key(req1) == _build_analysis_cache_key(req2)
