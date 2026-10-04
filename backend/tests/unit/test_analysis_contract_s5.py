"""Phase S.5 focused tests — Integration & Contract Consistency Audit.

Covers:
  A. semantically equivalent requests produce equivalent effective inputs
  B. API and service produce consistent results
  C. cached and uncached response contracts are equivalent
  D. evidence/provenance survive the complete response pipeline
  E. partial metric failure follows the documented contract
  F. no-data result follows the documented contract
  G. failed synthesis is not represented as a successful complete analysis
  H. failed analysis is not cached
  I. validation still occurs correctly on cache-hit requests
  J. no cross-request result contamination exists through the complete API/service path

All tests mock Earth Engine and the metric executor.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.cache_service import cache_service


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the global cache before and after each test."""
    cache_service.clear()
    yield
    cache_service.clear()


def _make_mock_outcome(key: str, value: Any, status: str = "ok") -> MagicMock:
    """Create a mock ExecutionOutcome with full provenance."""
    from app.services.agriculture.catalog import get_metric
    from app.services.agriculture.types import (
        MetricResult,
        Provenance,
        QualityLevel,
        TemporalKind,
    )

    metric = get_metric(key)
    prov = Provenance(
        source_dataset_id=metric.dataset_ids[0] if metric.dataset_ids else "unknown",
        source_dataset_name=metric.display_name,
        bands=["B4", "B8"],
        formula="(NIR - Red) / (NIR + Red)",
        unit=metric.unit,
        spatial_resolution="10 m",
        temporal_resolution="16-day",
        measurement_basis=metric.measurement_basis,
        quality_level=QualityLevel.GOOD,
        temporal_kind=TemporalKind.OBSERVATION,
        requested_start="2024-07-01",
        requested_end="2024-07-31",
        image_count=12,
        limitations=["10 m Sentinel-2"],
        citation="ESA Copernicus",
    )
    result = MetricResult(
        metric_key=key,
        display_name=metric.display_name,
        display_name_fa=metric.display_name_fa,
        status=status,
        value=value,
        unit=metric.unit,
        provenance=prov if status == "ok" else None,
        warnings=[],
    )
    outcome = MagicMock()
    outcome.result = result
    outcome.metric_key = key
    return outcome


def _make_unavailable_outcome(key: str) -> MagicMock:
    """Create a mock ExecutionOutcome for an unavailable metric."""
    from app.services.agriculture.catalog import get_metric
    from app.services.agriculture.types import MetricResult

    metric = get_metric(key)
    result = MetricResult.unavailable(
        metric_key=key,
        display_name=metric.display_name,
        display_name_fa=metric.display_name_fa,
        reason="outside_temporal_coverage",
        message="No data available for this period",
    )
    outcome = MagicMock()
    outcome.result = result
    outcome.metric_key = key
    return outcome


def _make_error_outcome(key: str) -> MagicMock:
    """Create a mock ExecutionOutcome for a failed metric."""
    from app.services.agriculture.catalog import get_metric
    from app.services.agriculture.types import MetricResult

    metric = get_metric(key)
    result = MetricResult.error(
        metric_key=key,
        display_name=metric.display_name,
        display_name_fa=metric.display_name_fa,
        message="Computation failed",
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


from app.api.v1 import agriculture
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agriculture.router, prefix="/api/v1/agriculture")

    from app.core.exceptions import AppException

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Any, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def exception_handler(request: Any, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return app


_test_app = _create_test_app()
client = TestClient(_test_app)


# ---------------------------------------------------------------------------
# A. Semantically equivalent requests produce equivalent effective inputs
# ---------------------------------------------------------------------------


class TestEquivalentRequests:
    def test_same_inputs_produce_same_result(self) -> None:
        """Two identical requests produce equivalent results."""
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
        assert resp1.json()["overall_sufficiency"] == resp2.json()["overall_sufficiency"]
        assert resp1.json()["evidence_bundles"] == resp2.json()["evidence_bundles"]

    def test_domain_order_does_not_affect_result(self) -> None:
        """Different ordering of same domains produces same result."""
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
                    "domains": ["vegetation", "water"],
                },
            )
            resp2 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                    "domains": ["water", "vegetation"],
                },
            )

        assert resp1.json()["domain_summaries"] == resp2.json()["domain_summaries"]


# ---------------------------------------------------------------------------
# B. API and service produce consistent results
# ---------------------------------------------------------------------------


class TestAPIAndServiceConsistency:
    def test_analysis_service_returns_valid_dict(self) -> None:
        """AnalysisService.create_analysis returns a valid result dict."""
        from app.services.analysis_service import AnalysisService

        service = AnalysisService()
        geometry = {"type": "Point", "coordinates": [51.3, 35.7]}
        db = MagicMock()

        mock_geometry = MagicMock()
        result_data = {
            "status": "completed",
            "analysis_type": "climate",
            "climate": {"temperature": {"mean": 25.0}},
        }

        with patch(
            "app.services.analysis_service.create_ee_geometry",
            return_value=mock_geometry,
        ), patch.object(
            service, "_run_domain_analysis", return_value=result_data
        ):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    service.create_analysis(
                        db, geometry, "2025-01-01", "2025-09-01", "climate"
                    )
                )
            finally:
                loop.close()

        assert result["status"] == "completed"
        assert result["analysis_type"] == "climate"
        assert "id" in result
        assert "completed_at" in result

    def test_agriculture_endpoint_returns_valid_response(self) -> None:
        """Agriculture endpoint returns valid AgriculturalAnalysisResponse."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
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
        data = resp.json()
        # Verify required top-level keys
        required = {
            "domain_summaries", "evidence_bundles", "overall_sufficiency",
            "available_domains", "limitations", "metadata",
        }
        assert required.issubset(data.keys())


# ---------------------------------------------------------------------------
# C. Cached and uncached response contracts are equivalent
# ---------------------------------------------------------------------------


class TestCacheContractEquivalence:
    def test_cache_hit_preserves_all_response_fields(self) -> None:
        """Cached response has identical structure to fresh response."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            resp_fresh = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            resp_cached = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        fresh = resp_fresh.json()
        cached = resp_cached.json()
        # Same keys
        assert set(fresh.keys()) == set(cached.keys())
        # Same data (except request_id and generated_at which differ)
        assert fresh["domain_summaries"] == cached["domain_summaries"]
        assert fresh["evidence_bundles"] == cached["evidence_bundles"]
        assert fresh["overall_sufficiency"] == cached["overall_sufficiency"]
        assert fresh["available_domains"] == cached["available_domains"]
        assert fresh["limitations"] == cached["limitations"]

    def test_cache_hit_response_deserializes_to_pydantic_model(self) -> None:
        """Cached data can be reconstructed as AgriculturalAnalysisResponse."""
        from app.schemas.agriculture import AgriculturalAnalysisResponse

        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            # Prime cache
            resp1 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            # Cache hit
            resp2 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        # Both should be valid Pydantic models
        model1 = AgriculturalAnalysisResponse(**resp1.json())
        model2 = AgriculturalAnalysisResponse(**resp2.json())
        assert model1.domain_summaries == model2.domain_summaries


# ---------------------------------------------------------------------------
# D. Evidence/provenance survive the complete response pipeline
# ---------------------------------------------------------------------------


class TestEvidenceProvenanceSurvival:
    def test_provenance_survives_serialization(self) -> None:
        """Provenance data in metric results survives through to API response."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            resp = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        data = resp.json()
        bundles = data.get("evidence_bundles", {})
        for domain, bundle in bundles.items():
            for item in bundle.get("items", []):
                prov = item.get("provenance")
                if prov is not None:
                    assert "source_dataset_id" in prov
                    assert "source_dataset_name" in prov
                    assert "bands" in prov
                    assert "unit" in prov
                    assert "spatial_resolution" in prov
                    assert "temporal_resolution" in prov

    def test_evidence_item_fields_complete(self) -> None:
        """Evidence items have all required fields."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            resp = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        data = resp.json()
        for domain, bundle in data.get("evidence_bundles", {}).items():
            for item in bundle.get("items", []):
                assert "metric_key" in item
                assert "status" in item
                assert "quality" in item
                assert "is_usable" in item
                assert "is_proxy" in item


# ---------------------------------------------------------------------------
# E. Partial metric failure follows the documented contract
# ---------------------------------------------------------------------------


class TestPartialMetricFailure:
    def test_partial_failure_includes_successful_metrics(self) -> None:
        """When some metrics fail, successful metrics still appear in response."""
        mock_geometry = MagicMock()
        outcomes = {
            "ndvi": _make_mock_outcome("ndvi", 0.65),
            "evi": _make_error_outcome("evi"),
        }

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            resp = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                    "domains": ["vegetation"],
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        # At least one evidence bundle should exist with the successful metric
        bundles = data.get("evidence_bundles", {})
        found_ndvi = False
        for domain, bundle in bundles.items():
            for item in bundle.get("items", []):
                if item["metric_key"] == "ndvi":
                    found_ndvi = True
                    assert item["is_usable"] is True
        assert found_ndvi

    def test_partial_failure_error_metric_not_usable(self) -> None:
        """Error metric is marked as not usable in evidence."""
        mock_geometry = MagicMock()
        outcomes = {
            "ndvi": _make_mock_outcome("ndvi", 0.65),
            "evi": _make_error_outcome("evi"),
        }

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            resp = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                    "domains": ["vegetation"],
                },
            )

        data = resp.json()
        bundles = data.get("evidence_bundles", {})
        for domain, bundle in bundles.items():
            for item in bundle.get("items", []):
                if item["metric_key"] == "evi":
                    assert item["is_usable"] is False


# ---------------------------------------------------------------------------
# F. No-data result follows the documented contract
# ---------------------------------------------------------------------------


class TestNoDataResult:
    def test_all_unavailable_produces_insufficient_sufficiency(self) -> None:
        """All metrics unavailable -> overall_sufficiency = insufficient."""
        mock_geometry = MagicMock()
        outcomes = {
            "ndvi": _make_unavailable_outcome("ndvi"),
            "evi": _make_unavailable_outcome("evi"),
        }

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            resp = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                    "domains": ["vegetation"],
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_sufficiency"] == "insufficient"

    def test_no_metrics_produces_empty_response(self) -> None:
        """No metrics executed -> empty domain summaries."""
        mock_geometry = MagicMock()
        outcomes: dict = {}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            resp = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                    "domains": ["vegetation"],
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["domain_summaries"] == {}
        assert data["overall_sufficiency"] == "insufficient"


# ---------------------------------------------------------------------------
# G. Failed synthesis is not represented as a successful complete analysis
# ---------------------------------------------------------------------------


class TestFailedSynthesis:
    def test_synthesis_exception_returns_error(self) -> None:
        """If synthesis engine fails, the endpoint returns an error."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ), patch(
            "app.services.agriculture.synthesis.SynthesisEngine.synthesise",
            side_effect=RuntimeError("synthesis engine crashed"),
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
        data = resp.json()
        assert "error" in data

    def test_synthesis_exception_not_cached(self) -> None:
        """Synthesis failure should not produce a cache entry."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ), patch(
            "app.services.agriculture.synthesis.SynthesisEngine.synthesise",
            side_effect=RuntimeError("synthesis engine crashed"),
        ):
            client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        assert cache_service.size == 0


# ---------------------------------------------------------------------------
# H. Failed analysis is not cached
# ---------------------------------------------------------------------------


class TestFailedAnalysisNotCached:
    def test_geometry_failure_not_cached(self) -> None:
        """EE geometry creation failure should not produce a cache entry."""
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

    def test_executor_failure_not_cached(self) -> None:
        """Metric executor failure should not produce a cache entry."""
        mock_geometry = MagicMock()

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            side_effect=RuntimeError("executor crashed"),
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


# ---------------------------------------------------------------------------
# I. Validation still occurs correctly on cache-hit requests
# ---------------------------------------------------------------------------


class TestValidationOnCacheHit:
    def test_invalid_dates_rejected_even_with_cache_hit(self) -> None:
        """Invalid date range is rejected even if a valid result is cached."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            # Prime cache with valid request
            resp1 = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )
            assert resp1.status_code == 200

        # Now send invalid dates — should fail validation
        resp2 = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                "start_date": "2024-07-31",
                "end_date": "2024-07-01",
            },
        )
        assert resp2.status_code == 400

    def test_invalid_geometry_rejected_even_with_cache_hit(self) -> None:
        """Invalid geometry is rejected even if a valid result is cached."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            # Prime cache
            client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": "2024-07-01",
                    "end_date": "2024-07-31",
                },
            )

        # Invalid geometry type
        resp = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": {"type": "LineString", "coordinates": [[51.3, 35.7], [52.0, 36.0]]},
                "start_date": "2024-07-01",
                "end_date": "2024-07-31",
            },
        )
        assert resp.status_code == 422

    def test_invalid_domain_rejected_even_with_cache_hit(self) -> None:
        """Invalid domain is rejected even if a valid result is cached."""
        mock_geometry = MagicMock()
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=mock_geometry
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ):
            # Prime cache
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
                "domains": ["nonexistent_domain"],
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# J. No cross-request result contamination through the complete API/service path
# ---------------------------------------------------------------------------


class TestNoCrossRequestContamination:
    def test_different_requests_isolated_through_full_pipeline(self) -> None:
        """Two different requests produce isolated results end-to-end."""
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

        # Results should differ because inputs differ
        data_a = resp_a.json()
        data_b = resp_b.json()
        assert data_a["evidence_bundles"] != data_b["evidence_bundles"]

    def test_cache_hit_does_not_leak_request_id(self) -> None:
        """Each request gets its own request_id, even on cache hit."""
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

        id1 = resp1.json().get("request_id")
        id2 = resp2.json().get("request_id")
        assert id1 is not None
        assert id2 is not None
        assert id1 != id2
