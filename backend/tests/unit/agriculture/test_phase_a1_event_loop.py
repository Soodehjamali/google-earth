"""Phase A1 regression tests — TASK 1 (event-loop blocking).

D1: ``run_agriculture_analysis`` is async and used to call the
synchronous ``execute_metrics`` directly, blocking the event loop for
the whole Earth Engine round trip. When EE/network retries were slow,
every endpoint — including ``/health`` — piled up, and a server
restart was required.

The fix offloads the blocking call with ``asyncio.to_thread``. These
tests pin the three behaviors the fix must preserve:

  A. while the metric execution blocks, the running event loop stays
     responsive (a heartbeat coroutine keeps ticking) and execution
     happens on a worker thread, not the loop thread;
  B. an executor exception propagates unchanged as a 500 response;
  C. the response body is identical with and without the offload.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api.v1 import agriculture
from app.api.v1.agriculture import run_agriculture_analysis
from app.core.exceptions import AppException
from app.schemas.agriculture import AgricultureAnalysisRequest
from app.services.cache_service import cache_service


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

ANALYSIS_BODY: Dict[str, Any] = {
    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
    "start_date": "2024-07-01",
    "end_date": "2024-07-31",
}


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


def _make_mock_outcome(key: str, value: float) -> MagicMock:
    """A mock ExecutionOutcome carrying a usable MetricResult."""
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
            source_dataset_id=(
                metric.dataset_ids[0] if metric.dataset_ids else "unknown"
            ),
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


# ---------------------------------------------------------------------------
# A. async analysis does not block the event loop
# ---------------------------------------------------------------------------


class TestAnalysisDoesNotBlockEventLoop:
    @pytest.mark.asyncio
    async def test_slow_executor_keeps_event_loop_responsive(self) -> None:
        """A blocked execute_metrics must not freeze the running loop.

        The executor sleeps on a worker thread (as a slow Earth Engine
        round trip would). While it sleeps, a heartbeat coroutine on the
        same loop must keep ticking — and the execution must not be on
        the loop thread. If the endpoint ever blocks the loop again,
        the heartbeat stalls and the thread-id assertion fails.
        """
        loop = asyncio.get_running_loop()
        loop_thread_id = threading.get_ident()
        started = threading.Event()
        release = threading.Event()
        observed_thread_ids = []

        def _slow_execute(keys, context):
            observed_thread_ids.append(threading.get_ident())
            started.set()
            release.wait(timeout=30)
            return {"ndvi": _make_mock_outcome("ndvi", 0.65)}, []

        heartbeats = 0

        async def _heartbeat() -> None:
            nonlocal heartbeats
            while True:
                heartbeats += 1
                await asyncio.sleep(0.01)

        hb_task = loop.create_task(_heartbeat())
        response = None
        try:
            with patch(
                "app.utils.geometry.create_ee_geometry",
                return_value=MagicMock(),
            ), patch(
                "app.services.agriculture.executor.execute_metrics",
                side_effect=_slow_execute,
            ), patch(
                "app.services.agriculture.temporal_section.build_temporal_section",
                return_value=None,
            ), patch(
                "app.services.agriculture.spatial_section.build_spatial_section",
                return_value=None,
            ):
                task = loop.create_task(
                    run_agriculture_analysis(
                        AgricultureAnalysisRequest(**ANALYSIS_BODY)
                    )
                )
                # Wait for the executor to start without blocking the loop.
                await asyncio.to_thread(started.wait, 10)
                assert started.is_set(), "executor never started"

                # Give the loop time to prove it is still alive while the
                # executor is blocked.
                await asyncio.sleep(0.15)
                assert heartbeats >= 5, (
                    "event loop stopped responding while execute_metrics "
                    "was blocked — the call is no longer offloaded"
                )
                assert not task.done()

                # Execution must be off the loop thread (to_thread worker).
                assert observed_thread_ids and (
                    observed_thread_ids[0] != loop_thread_id
                ), "execute_metrics ran on the event loop thread"

                release.set()
                response = await asyncio.wait_for(task, timeout=30)
        finally:
            release.set()
            hb_task.cancel()

        assert response is not None
        assert response.request_id
        assert response.metadata["metrics_executed"] == "1"

    @pytest.mark.asyncio
    async def test_offload_uses_to_thread_not_per_request_pool(self) -> None:
        """The offload must land on the default shared executor.

        Two sequential analyses must not spawn two fresh thread pools:
        ``asyncio.to_thread`` uses the loop's default ThreadPoolExecutor,
        whose threads are reused.
        """
        observed = []

        def _execute(keys, context):
            observed.append(threading.get_ident())
            return {"ndvi": _make_mock_outcome("ndvi", 0.65)}, []

        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            side_effect=_execute,
        ), patch(
            "app.services.agriculture.temporal_section.build_temporal_section",
            return_value=None,
        ), patch(
            "app.services.agriculture.spatial_section.build_spatial_section",
            return_value=None,
        ):
            req = AgricultureAnalysisRequest(**ANALYSIS_BODY)
            response1 = await run_agriculture_analysis(req)
            cache_service.clear()  # second call must execute again
            response2 = await run_agriculture_analysis(req)

        assert len(observed) == 2
        assert response2.metadata["metrics_executed"] == "1"
        # The default executor reuses worker threads; a per-request pool
        # factory would very likely produce a different thread each time.
        assert observed[0] == observed[1]


# ---------------------------------------------------------------------------
# B. exception propagates correctly
# ---------------------------------------------------------------------------


class TestExecutorExceptionPropagation:
    def test_executor_exception_maps_to_500(self) -> None:
        """A raised exception must not be swallowed or mis-cached."""
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            side_effect=RuntimeError("EE exploded mid-flight"),
        ):
            client = TestClient(_create_test_app())
            resp = client.post(
                "/api/v1/agriculture/analysis", json=ANALYSIS_BODY
            )
            assert resp.status_code == 500
            assert resp.json()["error"] == "Analysis failed: RuntimeError"

    def test_raised_exception_result_is_not_cached(self) -> None:
        """A failing execution must leave no cache entry behind."""
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            side_effect=RuntimeError("EE exploded mid-flight"),
        ):
            client = TestClient(_create_test_app())
            client.post("/api/v1/agriculture/analysis", json=ANALYSIS_BODY)
            assert cache_service.size == 0


# ---------------------------------------------------------------------------
# C. response remains unchanged
# ---------------------------------------------------------------------------


class TestResponseUnchanged:
    def test_successful_response_shape_is_preserved(self) -> None:
        """With EE healthy, the response is identical to the direct path."""
        outcomes = {"ndvi": _make_mock_outcome("ndvi", 0.65)}
        with patch(
            "app.utils.geometry.create_ee_geometry", return_value=MagicMock()
        ), patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(outcomes, []),
        ), patch(
            "app.services.agriculture.temporal_section.build_temporal_section",
            return_value=None,
        ), patch(
            "app.services.agriculture.spatial_section.build_spatial_section",
            return_value=None,
        ):
            client = TestClient(_create_test_app())
            resp = client.post(
                "/api/v1/agriculture/analysis", json=ANALYSIS_BODY
            )
            assert resp.status_code == 200
            body = resp.json()

            # Established response contract fields remain present.
            for field in (
                "request_id",
                "domain_summaries",
                "overall_sufficiency",
                "evidence_bundles",
                "metadata",
            ):
                assert field in body
            assert body["metadata"]["metrics_executed"] == "1"
            # Bundles are keyed by synthesis domain, not metric key.
            veg_items = body["evidence_bundles"]["vegetation"]["items"]
            assert veg_items[0]["metric_key"] == "ndvi"
            assert veg_items[0]["value"] == 0.65
