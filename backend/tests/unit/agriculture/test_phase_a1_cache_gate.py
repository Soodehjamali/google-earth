"""Phase A1 regression tests — TASK 3 (cache-safety gate).

D3: ``cache_service.set(...)`` used to run for any non-raising
response. An Earth Engine outage therefore produced HTTP 200 with all
metrics unavailable, ``overall_sufficiency = "insufficient"`` — and
that outage shape was cached for ``CACHE_TTL = 3600``.

The fix gates the cache write behind ``_response_has_usable_measurement``:
a response is only cached when at least one evidence item, temporal
point, or spatial observation carries a real provider measurement.

  A. healthy real result is cacheable; partial result is cacheable
  B. infrastructure outage (all-unavailable) result is not cached
  C. repeated request after outage does not receive stale outage cache
  D. existing legitimate cache behavior remains intact
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api.v1 import agriculture
from app.core.exceptions import AppException
from app.services.agriculture.quality import QualityLevel
from app.services.agriculture.types import MetricResult
from app.services.cache_service import cache_service


ANALYSIS_BODY: Dict[str, Any] = {
    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
    "start_date": "2024-07-01",
    "end_date": "2024-07-31",
}


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache_service.clear()
    yield
    cache_service.clear()


@pytest.fixture(autouse=True)
def _register_metrics():
    from app.services.agriculture import register_all_metrics
    from app.services.agriculture.catalog import metric_keys

    if not metric_keys():
        register_all_metrics()
    yield


def _result(
    key: str,
    value: Optional[float],
    *,
    quality: QualityLevel = QualityLevel.GOOD,
) -> MetricResult:
    """Build a real MetricResult for the given metric.

    ``value=None`` models a metric that ran but produced no usable
    measurement (the "honestly unavailable" case).
    """
    from app.services.agriculture.catalog import get_metric
    from app.services.agriculture.types import (
        Provenance,
        TemporalKind,
    )

    metric = get_metric(key)
    return MetricResult(
        metric_key=key,
        display_name=metric.display_name,
        display_name_fa=metric.display_name_fa,
        status="ok" if value is not None else "error",
        value=value,
        unit=metric.unit,
        reason=None if value is not None else "metric_value_unavailable",
        message=None if value is not None else "no usable observation",
        provenance=Provenance(
            source_dataset_id=(
                metric.dataset_ids[0] if metric.dataset_ids else "unknown"
            ),
            source_dataset_name=metric.display_name,
            bands=[],
            formula="",
            unit=metric.unit,
            spatial_resolution="1 km",
            temporal_resolution="16-day",
            measurement_basis=quality,
            quality_level=quality,
            temporal_kind=TemporalKind.OBSERVATION,
            requested_start="2024-07-01",
            requested_end="2024-07-31",
        ),
        warnings=[],
    )


def _make_outcome(key: str, value: Optional[float], **kw) -> MagicMock:
    outcome = MagicMock()
    outcome.result = _result(key, value, **kw)
    outcome.metric_key = key
    return outcome


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agriculture.router, prefix="/api/v1/agriculture")

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


def _post(client: TestClient) -> Any:
    return client.post("/api/v1/agriculture/analysis", json=ANALYSIS_BODY)


def _item_value(body: Dict[str, Any], metric_key: str) -> Optional[float]:
    """Value of one metric's evidence item, wherever its bundle sits.

    Bundles are keyed by synthesis domain, not by metric key, so a
    direct ``body["evidence_bundles"][metric_key]`` lookup is wrong.
    """
    for bundle in body["evidence_bundles"].values():
        for item in bundle["items"]:
            if item["metric_key"] == metric_key:
                return item["value"]
    raise AssertionError(f"{metric_key} not found in evidence bundles")


# ---------------------------------------------------------------------------
# A. healthy / partial results remain cacheable
# ---------------------------------------------------------------------------


class TestHealthyResultIsCacheable:
    def test_real_result_is_cached_and_served_on_second_request(self) -> None:
        outcomes = {"ndvi": _make_outcome("ndvi", 0.65)}
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            side_effect=[(outcomes, []), RuntimeError("must not re-execute")],
        ), patch(
            "app.services.agriculture.temporal_section.build_temporal_section", return_value=None
        ), patch(
            "app.services.agriculture.spatial_section.build_spatial_section", return_value=None
        ):
            client = TestClient(_create_test_app())

            resp1 = _post(client)
            assert resp1.status_code == 200
            assert cache_service.size == 1

            resp2 = _post(client)
            assert resp2.status_code == 200
            assert _item_value(resp2.json(), "ndvi") == 0.65


class TestPartialResultIsCacheable:
    def test_partial_real_result_is_cached(self) -> None:
        """Provider answered, one metric honestly unavailable — still cacheable.

        A sibling metric produced a real measurement, so the evidence
        layer is not an outage footprint.
        """
        outcomes = {
            "ndvi": _make_outcome("ndvi", None, quality=QualityLevel.POOR),
            "evi": _make_outcome("evi", 0.41),
        }
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            side_effect=[(outcomes, []), RuntimeError("must not re-execute")],
        ), patch(
            "app.services.agriculture.temporal_section.build_temporal_section", return_value=None
        ), patch(
            "app.services.agriculture.spatial_section.build_spatial_section", return_value=None
        ):
            client = TestClient(_create_test_app())

            resp1 = _post(client)
            assert resp1.status_code == 200
            assert cache_service.size == 1

            resp2 = _post(client)
            assert resp2.status_code == 200
            assert _item_value(resp2.json(), "evi") == 0.41


# ---------------------------------------------------------------------------
# B. infrastructure outage (all-unavailable) is not cached
# ---------------------------------------------------------------------------


class TestOutageResultIsNotCached:
    def test_all_unavailable_result_is_not_cached(self) -> None:
        """The D3 outage signature: HTTP 200, every metric unavailable."""
        outage = {
            "ndvi": _make_outcome("ndvi", None),
            "evi": _make_outcome("evi", None),
        }
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outage, []),
        ), patch(
            "app.services.agriculture.temporal_section.build_temporal_section", return_value=None
        ), patch(
            "app.services.agriculture.spatial_section.build_spatial_section", return_value=None
        ):
            client = TestClient(_create_test_app())

            resp = _post(client)
            assert resp.status_code == 200
            assert cache_service.size == 0

    def test_empty_outcome_map_is_not_cached(self) -> None:
        """No outcome at all (provider produced nothing) is not cached either."""
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=({}, []),
        ), patch(
            "app.services.agriculture.temporal_section.build_temporal_section", return_value=None
        ), patch(
            "app.services.agriculture.spatial_section.build_spatial_section", return_value=None
        ):
            client = TestClient(_create_test_app())

            resp = _post(client)
            assert resp.status_code == 200
            assert cache_service.size == 0

    def test_gate_reports_reason_in_metadata(self) -> None:
        """A refused write names the gate so operators can see why."""
        outage = {"ndvi": _make_outcome("ndvi", None)}
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outage, []),
        ), patch(
            "app.services.agriculture.temporal_section.build_temporal_section", return_value=None
        ), patch(
            "app.services.agriculture.spatial_section.build_spatial_section", return_value=None
        ):
            client = TestClient(_create_test_app())

            resp = _post(client)
            assert resp.status_code == 200
            assert resp.json()["metadata"]["cache_gate"] == "no_usable_measurement"


# ---------------------------------------------------------------------------
# C. no stale outage cache after recovery
# ---------------------------------------------------------------------------


class TestNoStaleOutageCacheAfterRecovery:
    def test_outage_then_healthy_serves_fresh_result(self) -> None:
        """Outage response must not poison the next, healthy request.

        First request hits an outage (all metrics unavailable) and must
        leave no cache entry; the second identical request executes
        again and receives the real, fresh measurement.
        """
        outage = {"ndvi": _make_outcome("ndvi", None)}
        healthy = {"ndvi": _make_outcome("ndvi", 0.65)}

        calls: List[int] = []

        def _execute(keys, context):  # noqa: ANN001
            calls.append(1)
            return (outage, []) if len(calls) == 1 else (healthy, [])

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            side_effect=_execute,
        ), patch(
            "app.services.agriculture.temporal_section.build_temporal_section", return_value=None
        ), patch(
            "app.services.agriculture.spatial_section.build_spatial_section", return_value=None
        ):
            client = TestClient(_create_test_app())

            resp1 = _post(client)
            assert resp1.status_code == 200
            assert _item_value(resp1.json(), "ndvi") is None
            assert cache_service.size == 0

            resp2 = _post(client)
            assert resp2.status_code == 200
            # Second request re-executed and got the recovered result —
            # never the stale outage shape.
            assert len(calls) == 2
            assert _item_value(resp2.json(), "ndvi") == 0.65
            assert cache_service.size == 1


# ---------------------------------------------------------------------------
# D. existing legitimate cache behavior remains intact
# ---------------------------------------------------------------------------


class TestLegitimateCacheBehaviorIntact:
    def test_identical_request_still_hits_cache(self) -> None:
        """S4 behavior: same request twice → single execution."""
        outcomes = {"ndvi": _make_outcome("ndvi", 0.65)}
        execute = MagicMock(return_value=(outcomes, []))
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics", new=execute
        ), patch(
            "app.services.agriculture.temporal_section.build_temporal_section", return_value=None
        ), patch(
            "app.services.agriculture.spatial_section.build_spatial_section", return_value=None
        ):
            client = TestClient(_create_test_app())

            assert _post(client).status_code == 200
            assert _post(client).status_code == 200
            assert execute.call_count == 1
            assert cache_service.size == 1

    def test_cache_read_failure_still_returns_analysis(self) -> None:
        """S4 behavior: backend read failure must not break the analysis."""
        outcomes = {"ndvi": _make_outcome("ndvi", 0.65)}
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ), patch(
            "app.services.cache_service.cache_service.get",
            side_effect=RuntimeError("backend down"),
        ), patch(
            "app.services.agriculture.temporal_section.build_temporal_section", return_value=None
        ), patch(
            "app.services.agriculture.spatial_section.build_spatial_section", return_value=None
        ):
            client = TestClient(_create_test_app())

            resp = _post(client)
            assert resp.status_code == 200
            assert _item_value(resp.json(), "ndvi") == 0.65
