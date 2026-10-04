"""P6.3 integration tests: ground-truth validation inside /analysis.

Locks that POST /api/v1/agriculture/analysis accepts an optional
``ground_truth`` list, validates it through the P6.2 ingestion
boundary, adapts already-produced scalar/temporal/spatial outputs,
and returns an additive ``validation`` section — while requests
without references behave exactly as before and the analysis cache
never leaks validation across different reference sets.

Only Earth Engine-touching builders are mocked, with hand-built
REAL dataclass instances; evidence, synthesis, temporal, and
validation run for real. No network, no credentials.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.v1 import agriculture
from app.core.exceptions import AppException
from app.services.agriculture.base import MetricContext
from app.services.agriculture.temporal_profile import (
    TemporalProfile,
    TemporalProfilePoint,
)
from app.services.cache_service import cache_service
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    TemporalKind,
)

JAN = ("2024-01-01", "2024-01-31")
FEB = ("2024-02-01", "2024-02-29")
MAR = ("2024-03-01", "2024-03-31")
FULL = ("2024-01-01", "2024-04-30")

VALIDATION_STATUSES = {
    "MATCHED_REFERENCE",
    "MISMATCHED_REFERENCE",
    "INSUFFICIENT_REFERENCE",
    "INSUFFICIENT_ANALYSIS",
    "UNAVAILABLE",
    "NOT_VALIDATED",
}


def _create_test_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(AppException)
    async def _app_exception_handler(request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": exc.detail},
        )

    app.include_router(agriculture.router, prefix="/api/v1/agriculture")
    return app


@pytest.fixture
def client():
    return TestClient(_create_test_app())


@pytest.fixture(autouse=True)
def _registered_and_fresh_cache():
    from app.services.agriculture import register_all_metrics
    from app.services.agriculture.catalog import metric_keys

    if not metric_keys():
        register_all_metrics()
    cache_service.clear()
    yield
    cache_service.clear()


def _ref(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "observation_id": "obs-1",
        "variable": "observed_stress",
        "value": 2.0,
        "unit": "index",
        "state": "present",
        "latitude": 32.42,
        "longitude": 53.68,
        "observed_on": "2024-01-15",
        "window_start": JAN[0],
        "window_end": JAN[1],
        "source": "field_observation",
        "method": "visual inspection",
        "quality": "good",
        "status": "available",
        "metric_key": "ndvi",
        "domain": "vegetation",
        "cell_id": "r1c1",
        "provenance": {"plot": "A"},
        "limitations": ["single visit"],
    }
    base.update(overrides)
    return base


def _scalar_outcome(metric_key: str, value: Optional[float], unit: str,
                    start: str = FULL[0], end: str = FULL[1],
                    status: str = "ok") -> Any:
    from app.services.agriculture.catalog import get_metric

    metric = get_metric(metric_key)
    result = MetricResult(
        metric_key=metric_key,
        display_name=metric.display_name,
        display_name_fa=metric.display_name_fa,
        status=status,
        value=value,
        unit=unit,
        provenance=Provenance(
            source_dataset_id="COPERNICUS/S2_SR_HARMONIZED",
            source_dataset_name=metric.display_name,
            bands=[],
            formula="",
            unit=unit,
            spatial_resolution="10 m",
            temporal_resolution="5 days",
            measurement_basis=metric.measurement_basis,
            quality_level=QualityLevel.GOOD,
            temporal_kind=TemporalKind.OBSERVATION,
            requested_start=start,
            requested_end=end,
        ),
        warnings=[],
    )
    outcome = MagicMock()
    outcome.result = result
    outcome.metric_key = metric_key
    return outcome


def _ndvi_profile() -> TemporalProfile:
    values: List[Optional[float]] = [0.6, 0.62, 0.7, 0.65]
    windows = [JAN, ("2024-02-01", "2024-02-29"),
               ("2024-03-01", "2024-03-31"), ("2024-04-01", "2024-04-30")]
    return TemporalProfile(
        metric_key="ndvi",
        dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        unit="index",
        window_start=FULL[0],
        window_end=FULL[1],
        points=tuple(
            TemporalProfilePoint(
                window_start=w[0], window_end=w[1], value=v, unit="index",
                quality="good" if v is not None else "insufficient",
                coverage_percent=100.0 if v is not None else 0.0,
                image_count=4,
            )
            for w, v in zip(windows, values)
        ),
    )


def _spatial_payload() -> Dict[str, Any]:
    ring = [[[51.0, 35.0], [51.1, 35.0], [51.1, 35.1], [51.0, 35.1], [51.0, 35.0]]]
    return {
        "window_start": FULL[0],
        "window_end": FULL[1],
        "grid_rows": 1,
        "grid_cols": 1,
        "bbox": [51.0, 35.0, 51.1, 35.1],
        "cells": [{
            "cell_id": "r1c1", "row": 1, "col": 1,
            "west": 51.0, "south": 35.0, "east": 51.1, "north": 35.1,
            "geometry": {"type": "Polygon", "coordinates": ring},
        }],
        "observations": [{
            "cell_id": "r1c1", "metric_key": "ndvi",
            "window_start": JAN[0], "window_end": JAN[1],
            "value": 0.6, "unit": "index",
            "z_score": None, "category": None,
            "quality": "good", "coverage_percent": 100.0, "image_count": 4,
        }],
        "summaries": {
            "ndvi": {
                "metric_key": "ndvi", "window_start": JAN[0], "window_end": JAN[1],
                "n_cells": 1, "n_usable": 1, "n_missing": 0,
                "mean": 0.6, "median": 0.6,
                "anomalous_count": 0, "anomalous_fraction": 0.0,
                "min_coverage_percent": 100.0, "mean_coverage_percent": 100.0,
                "quality_counts": {"good": 1},
                "state": "NORMAL_AREA", "method": "area aggregation",
            }
        },
        "concordance": [],
        "persistence": [],
        "limitations": [],
    }


class _Patches:
    """Patch set with spies for execution counting."""

    def __init__(self, with_spatial: bool = False):
        outcomes = {
            "ndvi": _scalar_outcome("ndvi", 0.65, "index"),
            "ndmi": _scalar_outcome("ndmi", 0.35, "index"),
        }
        self.execute = MagicMock(return_value=(outcomes, []))
        self.geometry = MagicMock(return_value=MagicMock())
        self.with_spatial = with_spatial

    def _optical(self, key: str, context: MetricContext):
        if key == "ndvi":
            return _ndvi_profile()
        raise RuntimeError(f"no fixture for {key}")

    def _no_radar(self, key: str, context: MetricContext):
        raise RuntimeError(f"no fixture for {key}")

    def enter(self, stack: ExitStack):
        stack.enter_context(patch(
            "app.utils.geometry.create_ee_geometry", self.geometry))
        stack.enter_context(patch(
            "app.services.agriculture.executor.execute_metrics", self.execute))
        stack.enter_context(patch(
            "app.services.agriculture.temporal_profile.build_temporal_profile",
            side_effect=self._optical))
        stack.enter_context(patch(
            "app.services.agriculture.radar_profile.build_radar_profile",
            side_effect=self._no_radar))
        if self.with_spatial:
            stack.enter_context(patch(
                "app.services.agriculture.spatial_section.build_spatial_section",
                return_value=_spatial_payload()))
        return self


def _body(ground_truth=None, domains=None):
    body: Dict[str, Any] = {
        "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
        "start_date": FULL[0],
        "end_date": FULL[1],
        "domains": domains if domains is not None else ["vegetation", "water"],
    }
    if ground_truth is not None:
        body["ground_truth"] = ground_truth
    return body


def _post(client, ground_truth=None, domains=None, extra=None):
    body = _body(ground_truth, domains)
    if extra:
        body.update(extra)
    patches = _Patches(with_spatial=True)
    with ExitStack() as stack:
        patches.enter(stack)
        response = client.post("/api/v1/agriculture/analysis", json=body)
    return response, patches


# --------------------------------------------------------------------------
# REQUEST
# --------------------------------------------------------------------------


class TestRequest:
    def test_no_ground_truth(self, client):
        response, _ = _post(client)
        assert response.status_code == 200
        assert response.json()["validation"] is None

    def test_one_valid_reference(self, client):
        response, _ = _post(client, ground_truth=[_ref()])
        assert response.status_code == 200
        assert response.json()["validation"] is not None

    def test_multiple_references(self, client):
        refs = [_ref(), _ref(observation_id="obs-2", source="farmer_observation")]
        response, _ = _post(client, ground_truth=refs)
        assert response.status_code == 200
        ids = {r["observation_id"] for r in response.json()["validation"]["results"]}
        assert {"obs-1", "obs-2"} <= ids

    def test_empty_reference_list(self, client):
        response, _ = _post(client, ground_truth=[])
        assert response.status_code == 200
        assert response.json()["validation"] is None

    def test_malformed_reference(self, client):
        response, _ = _post(client, ground_truth=["not-a-mapping"])
        assert response.status_code == 400

    def test_ground_truth_not_a_list(self, client):
        response, _ = _post(client, ground_truth={"observation_id": "obs-1"})
        assert response.status_code in (400, 422)

    def test_invalid_reference_isolated(self, client):
        response, _ = _post(client, ground_truth=[_ref(variable="canopy_health")])
        assert response.status_code == 200
        data = response.json()
        assert data["evidence_bundles"]
        assert len(data["validation"]["rejected_references"]) == 1

    def test_unknown_source_and_variable_state(self, client):
        refs = [_ref(observation_id="u1", source="clipboard_note"),
                _ref(observation_id="u2", variable="mystery", state=None, value=None)]
        response, _ = _post(client, ground_truth=refs)
        assert response.status_code == 200
        validation = response.json()["validation"]
        assert any(r["observation_id"] == "u1"
                   for r in validation["results"])
        assert any(r["observation_id"] == "u2"
                   for r in validation["rejected_references"])


# --------------------------------------------------------------------------
# INTEGRATION
# --------------------------------------------------------------------------


class TestIntegration:
    def test_scalar_evidence_validation(self, client):
        response, _ = _post(client, ground_truth=[_ref()])
        assert response.status_code == 200
        scalar = [r for r in response.json()["validation"]["results"]
                  if r["metric_key"] == "ndvi" and r["analysis_cell_id"] is None]
        assert scalar
        # Scalar evidence carries no cell; beside a cell-bearing
        # reference the honest outcome is insufficient analysis.
        assert scalar[0]["metric_relationship"] == "METRIC_MATCH"
        assert scalar[0]["status"] == "INSUFFICIENT_ANALYSIS"

    def test_temporal_point_validation(self, client):
        response, _ = _post(client, ground_truth=[_ref()])
        assert response.status_code == 200
        january = [r for r in response.json()["validation"]["results"]
                   if r["metric_key"] == "ndvi"
                   and r["analysis_window_start"] == JAN[0]
                   and r["analysis_window_end"] == JAN[1]]
        assert january
        assert january[0]["temporal_relationship"] == "EXACT_TEMPORAL_MATCH"

    def test_spatial_cell_validation(self, client):
        response, _ = _post(client, ground_truth=[_ref()])
        assert response.status_code == 200
        cells = [r for r in response.json()["validation"]["results"]
                 if r["analysis_cell_id"] == "r1c1" and r["metric_key"] == "ndvi"]
        assert cells
        matched = [r for r in cells if r["status"] == "MATCHED_REFERENCE"]
        assert matched
        assert matched[0]["spatial_relationship"] == "EXACT_SPATIAL_CELL_MATCH"

    def test_validation_without_temporal_or_spatial(self, client):
        patches = _Patches(with_spatial=False)
        with ExitStack() as stack:
            patches.enter(stack)
            response = client.post(
                "/api/v1/agriculture/analysis",
                json={
                    "geometry": {"type": "Point", "coordinates": [51.3, 35.7]},
                    "start_date": FULL[0], "end_date": FULL[1],
                    "domains": ["vegetation", "water"],
                    "ground_truth": [_ref()],
                },
            )
        assert response.status_code == 200
        assert response.json()["validation"]["results"]

    def test_multiple_compatible_references(self, client):
        refs = [_ref(), _ref(observation_id="obs-2")]
        response, _ = _post(client, ground_truth=refs)
        assert response.status_code == 200
        for analysis_key in ("ndvi",):
            ids = sorted(
                r["observation_id"]
                for r in response.json()["validation"]["results"]
                if r["metric_key"] == analysis_key
                and r["analysis_cell_id"] == "r1c1"
            )
            assert "obs-1" in ids and "obs-2" in ids

    def test_metric_mismatch(self, client):
        response, _ = _post(client, ground_truth=[_ref(metric_key="no_such_metric",
                                                       observation_id="o9")])
        assert response.status_code == 200
        assert all(r["observation_id"] != "o9"
                   for r in response.json()["validation"]["results"])

    def test_temporal_mismatch(self, client):
        ref = _ref(window_start=MAR[0], window_end=MAR[1], observed_on="2024-03-15")
        response, _ = _post(client, ground_truth=[ref])
        assert response.status_code == 200
        mismatched = [r for r in response.json()["validation"]["results"]
                      if r["temporal_relationship"] == "INCOMPATIBLE_TEMPORAL_WINDOW"]
        assert mismatched
        assert all(r["status"] == "MISMATCHED_REFERENCE" for r in mismatched)

    def test_spatial_mismatch(self, client):
        response, _ = _post(client, ground_truth=[_ref(cell_id="r9c9")])
        assert response.status_code == 200
        mismatched = [r for r in response.json()["validation"]["results"]
                      if r["spatial_relationship"] == "SPATIAL_MISMATCH"]
        assert mismatched

    def test_semantic_incompatibility(self, client):
        ref = _ref(variable="observed_pest_presence", state="present",
                   value=None, unit="index")
        response, _ = _post(client, ground_truth=[ref])
        assert response.status_code == 200
        flagged = [r for r in response.json()["validation"]["results"]
                   if "SEMANTICALLY_INCOMPATIBLE" in r["limitations"]]
        assert flagged

    def test_provenance_preservation(self, client):
        response, _ = _post(client, ground_truth=[_ref()])
        assert response.status_code == 200
        provinces = [r["provenance"] for r in response.json()["validation"]["results"]]
        assert any(p.get("plot") == "A" for p in provinces)
        assert any(p.get("reference_source") == "field_observation" for p in provinces)
        assert any("COPERNICUS/S2_SR_HARMONIZED" in str(p.values()) for p in provinces)


# --------------------------------------------------------------------------
# RESPONSE
# --------------------------------------------------------------------------


class TestResponse:
    def test_validation_absent_without_references(self, client):
        response, _ = _post(client)
        assert response.json()["validation"] is None

    def test_validation_present_with_references(self, client):
        response, _ = _post(client, ground_truth=[_ref()])
        validation = response.json()["validation"]
        assert set(validation) >= {"results", "rejected_references",
                                   "duplicates", "limitations"}

    def test_old_response_compatibility(self, client):
        plain = _post(client)[0].json()
        validated = _post(client, ground_truth=[_ref()])[0].json()
        assert plain["validation"] is None
        assert validated["validation"] is not None
        assert set(validated) == set(plain)

        def _scrub(node):
            if isinstance(node, dict):
                return {k: _scrub(v) for k, v in node.items()
                        if k != "computed_at"}
            if isinstance(node, list):
                return [_scrub(v) for v in node]
            return node

        for key in ("domain_summaries", "evidence_bundles", "temporal",
                    "overall_sufficiency", "limitations"):
            assert _scrub(validated[key]) == _scrub(plain[key])

    def test_rejected_references_preserved(self, client):
        response, _ = _post(client, ground_truth=[_ref(variable="nope")])
        rejected = response.json()["validation"]["rejected_references"]
        assert len(rejected) == 1
        assert "unknown_variable" in rejected[0]["reasons"]

    def test_duplicates_reported(self, client):
        response, _ = _post(client, ground_truth=[_ref(), _ref()])
        duplicates = response.json()["validation"]["duplicates"]
        assert len(duplicates) == 1
        assert duplicates[0]["observation_id"] == "obs-1"

    def test_limitations_preserved(self, client):
        response, _ = _post(client, ground_truth=[_ref()])
        texts = []
        for result in response.json()["validation"]["results"]:
            texts.extend(result["limitations"])
        assert any("single visit" in text for text in texts)


# --------------------------------------------------------------------------
# CACHE
# --------------------------------------------------------------------------


class TestCache:
    def _two_posts(self, client, first_refs, second_refs):
        patches = _Patches(with_spatial=True)
        with ExitStack() as stack:
            patches.enter(stack)
            first = client.post(
                "/api/v1/agriculture/analysis", json=_body(first_refs))
            second = client.post(
                "/api/v1/agriculture/analysis", json=_body(second_refs))
        return first, second, patches

    def test_same_reference_cache_hit(self, client):
        first, second, patches = self._two_posts(client, [_ref()], [_ref()])
        assert first.status_code == 200 == second.status_code
        assert patches.execute.call_count == 1
        assert first.json()["validation"] == second.json()["validation"]

    def test_different_reference_cache_isolation(self, client):
        first, second, patches = self._two_posts(
            client, [_ref(value=2.0)], [_ref(value=3.0)])
        assert patches.execute.call_count == 2
        first_values = {r["reference_value"] for r in first.json()["validation"]["results"]}
        second_values = {r["reference_value"] for r in second.json()["validation"]["results"]}
        assert first_values != second_values

    def test_no_reference_cache_unchanged(self, client):
        first, second, patches = self._two_posts(client, None, None)
        assert patches.execute.call_count == 1
        assert first.json()["validation"] is None
        assert second.json()["validation"] is None

    def test_cache_hit_avoids_duplicate_analysis(self, client):
        first, second, patches = self._two_posts(client, [_ref()], [_ref()])
        assert patches.execute.call_count == 1
        assert patches.geometry.call_count == 1
        assert second.json()["validation"] is not None

    def test_reference_ordering_behavior(self, client):
        refs = [_ref(), _ref(observation_id="obs-2")]
        first, second, _ = self._two_posts(client, refs, list(reversed(refs)))
        assert first.json()["validation"] == second.json()["validation"]


# --------------------------------------------------------------------------
# SAFETY
# --------------------------------------------------------------------------


class TestSafety:
    def test_no_second_metric_computation(self, client):
        _, patches = _post(client, ground_truth=[_ref(), _ref(observation_id="o2")])
        assert patches.execute.call_count == 1

    def test_no_gee_validation_computation(self, client):
        _, patches = _post(client, ground_truth=[_ref()])
        assert patches.geometry.call_count == 1

    def test_no_biological_inference(self, client):
        response, _ = _post(client, ground_truth=[_ref(variable="observed_pest_presence")])
        assert response.status_code == 200
        for result in response.json()["validation"]["results"]:
            assert result["status"] in VALIDATION_STATUSES
            for verb in ("cause", "due to", "indicates", "proves", "confirms"):
                assert verb not in result["linkage_reason"].lower()

    def test_no_statistical_score(self, client):
        import json as _json

        response, _ = _post(client, ground_truth=[_ref()])
        dump = _json.dumps(response.json()["validation"]).lower()
        for token in ("accuracy", "precision", "recall", "confidence",
                      "probability", "severity", "correlation", "confusion"):
            assert re.search(rf"\b{token}\b", dump) is None, token
        assert re.search(r"\broc\b", dump) is None
        assert re.search(r"\bauc\b", dump) is None
        for result in response.json()["validation"]["results"]:
            assert set(result).isdisjoint(
                {"accuracy", "precision", "recall", "f1", "roc", "auc",
                 "correlation", "confidence", "probability", "risk",
                 "severity", "score"}
            )

    def test_no_interpolation(self, client):
        ref = _ref(window_start=FEB[0], window_end=FEB[1], observed_on="2024-02-10")
        response, _ = _post(client, ground_truth=[ref])
        assert response.status_code == 200
        january = [r for r in response.json()["validation"]["results"]
                   if r["analysis_window_start"] == JAN[0]
                   and r["analysis_window_end"] == JAN[1]
                   and r["temporal_relationship"] != "NO_CANDIDATE_REFERENCE"]
        assert january
        assert all(r["temporal_relationship"] == "INCOMPATIBLE_TEMPORAL_WINDOW"
                   for r in january)
        assert not [r for r in january if r["status"] == "MATCHED_REFERENCE"]

    def test_no_nearest_matching(self, client):
        ref = _ref(window_start=FEB[0], window_end=FEB[1], observed_on="2024-02-10")
        response, _ = _post(client, ground_truth=[ref])
        matched = [r for r in response.json()["validation"]["results"]
                   if r["status"] == "MATCHED_REFERENCE"]
        assert not matched

    def test_no_zero_fill(self, client):
        ref = _ref(value=None, state="present")
        response, _ = _post(client, ground_truth=[ref])
        assert response.status_code == 200
        assert any(r["reference_value"] is None
                   for r in response.json()["validation"]["results"])
