"""P5.3-S contract tests: P1.5 spatial intelligence inside /analysis.

Locks that POST /api/v1/agriculture/analysis returns existing
scalar fields unchanged plus an additive ``spatial`` section
built by existing P1.5 builders: deterministic grid cells with
verbatim geometry, per-cell observations with preserved
missing/quality semantics, area summaries, per-cell
concordance, and honestly insufficient single-window
persistence.

Only the Earth Engine-touching ``evaluate_grid`` is mocked, and
only with hand-built REAL CellObservation dataclass instances;
grid generation, aggregation, concordance, persistence, and
serialization all run for real. No network, no credentials.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.v1 import agriculture
from app.core.exceptions import AppException
from app.schemas.agriculture import AgriculturalAnalysisResponse
from app.services.agriculture.base import MetricContext
from app.services.agriculture.spatial_profile import (
    CellObservation,
    grid_cells,
)
from app.services.agriculture.spatial_section import (
    GRID_COLS,
    GRID_ROWS,
    eligible_spatial_metrics,
)
from app.services.cache_service import cache_service
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    TemporalKind,
)

POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [51.0, 35.0], [52.0, 35.0], [52.0, 36.0],
        [51.0, 36.0], [51.0, 35.0],
    ]],
}
POINT = {"type": "Point", "coordinates": [51.5, 35.5]}
WINDOW = ("2024-01-01", "2024-01-31")

# Per-cell plans over the 3x3 grid (row-major r00c00..r02c02).
NDVI_VALUES = [0.62, 0.65, None, 0.70, 0.72, 0.68, 0.55, None, 0.66]
NDVI_CATS = ["ABOVE_BASELINE", "BELOW_BASELINE", None,
             "ABOVE_BASELINE", "ABOVE_BASELINE", "ABOVE_BASELINE",
             None, None, None]
NDMI_VALUES = [0.30, 0.32, 0.35, None, 0.40, 0.42, 0.28, None, None]
NDMI_CATS = ["BELOW_BASELINE", None, None,
             "BELOW_BASELINE", "BELOW_BASELINE", None,
             None, None, None]
VV_VALUES = [-8.0, -8.2, -8.1, -7.9, -8.3, -8.4, -8.6, None, -8.1]
VV_CATS = ["ABOVE_BASELINE", None, None,
           "ABOVE_BASELINE", None, None,
           None, None, None]


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


def _observations(metric_key, values, categories, unit):
    return tuple(
        CellObservation(
            cell_id=f"r{r // 3:02d}c{r % 3:02d}",
            metric_key=metric_key,
            window_start=WINDOW[0],
            window_end=WINDOW[1],
            value=value,
            unit=unit,
            z_score=None,
            category=category,
            quality="good" if value is not None else "insufficient",
            coverage_percent=100.0 if value is not None else None,
            image_count=4 if value is not None else None,
        )
        for r, (value, category) in enumerate(zip(values, categories))
    )


def _grid_evaluator(key: str, context, cells):
    plans = {
        "ndvi": (NDVI_VALUES, NDVI_CATS, "index"),
        "ndmi": (NDMI_VALUES, NDMI_CATS, "index"),
        "vv": (VV_VALUES, VV_CATS, "dB"),
    }
    if key not in plans:
        raise RuntimeError(f"no fixture for {key}")
    values, categories, unit = plans[key]
    assert [c.cell_id for c in cells] == [
        f"r{r // 3:02d}c{r % 3:02d}" for r in range(9)
    ]
    return _observations(key, values, categories, unit)


def _scalar_outcomes() -> Dict[str, Any]:
    from app.services.agriculture.catalog import get_metric

    metric = get_metric("ndvi")
    result = MetricResult(
        metric_key="ndvi",
        display_name=metric.display_name,
        display_name_fa=metric.display_name_fa,
        status="ok",
        value=0.65,
        unit=metric.unit,
        provenance=Provenance(
            source_dataset_id="COPERNICUS/S2_SR_HARMONIZED",
            source_dataset_name=metric.display_name,
            bands=[],
            formula="",
            unit=metric.unit,
            spatial_resolution="10 m",
            temporal_resolution="5 days",
            measurement_basis=metric.measurement_basis,
            quality_level=QualityLevel.GOOD,
            temporal_kind=TemporalKind.OBSERVATION,
            requested_start="2024-01-01",
            requested_end="2024-01-31",
        ),
        warnings=[],
    )
    outcome = MagicMock()
    outcome.result = result
    outcome.metric_key = "ndvi"
    return {"ndvi": outcome}


def _post(client, domains, geometry=None, lon=51.3):
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.utils.geometry.create_ee_geometry",
            return_value=MagicMock()))
        stack.enter_context(patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(_scalar_outcomes(), [])))
        stack.enter_context(patch(
            "app.services.agriculture.temporal_section.build_temporal_section",
            return_value={}))
        stack.enter_context(patch(
            "app.services.agriculture.spatial_profile.evaluate_grid",
            side_effect=_grid_evaluator))
        return client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": geometry or {
                    "type": "Point", "coordinates": [lon, 35.7]},
                "start_date": WINDOW[0],
                "end_date": WINDOW[1],
                "domains": domains,
            },
        )


# --------------------------------------------------------------------------
# 1-5. Additive contract, scalars/synthesis/bundles unchanged
# --------------------------------------------------------------------------


def test_spatial_section_is_additive(client):
    data = _post(client, ["vegetation", "water"], geometry=POLYGON).json()
    assert "spatial" in data
    assert data["spatial"] is not None
    assert data["spatial"]["window_start"] == WINDOW[0]
    assert data["spatial"]["window_end"] == WINDOW[1]


def test_scalar_fields_unchanged(client):
    data = _post(client, ["vegetation", "water"], geometry=POLYGON).json()
    for field in ("domain_summaries", "evidence_bundles",
                  "overall_sufficiency", "available_domains", "metadata"):
        assert field in data, field
    veg_keys = [i["metric_key"]
                for i in data["evidence_bundles"]["vegetation"]["items"]]
    assert "ndvi" in veg_keys
    ndvi_item = next(i for i in data["evidence_bundles"]["vegetation"]["items"]
                     if i["metric_key"] == "ndvi")
    assert ndvi_item["value"] == pytest.approx(0.65)


# --------------------------------------------------------------------------
# 6-18. Cells, observations, missing/quality/provenance semantics
# --------------------------------------------------------------------------


def test_grid_cells_verbatim(client):
    from app.services.agriculture.spatial_profile import grid_cells

    spatial = _post(client, ["vegetation", "water"],
                    geometry=POLYGON).json()["spatial"]
    assert spatial["grid_rows"] == GRID_ROWS == 3
    assert spatial["grid_cols"] == GRID_COLS == 3
    assert spatial["bbox"] == pytest.approx([51.0, 35.0, 52.0, 36.0])
    assert len(spatial["cells"]) == 9
    expected = [cell.to_dict() for cell in
                grid_cells((51.0, 35.0, 52.0, 36.0), 3, 3)]
    assert spatial["cells"] == expected  # geometry travels verbatim
    first = spatial["cells"][0]
    assert first["cell_id"] == "r00c00"
    assert (first["row"], first["col"]) == (0, 0)
    ring = first["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]  # closed ring preserved
    assert [c["cell_id"] for c in spatial["cells"]] == [
        f"r{r // 3:02d}c{r % 3:02d}" for r in range(9)]


def test_observations_preserve_identity_and_units(client):
    spatial = _post(client, ["vegetation", "water"],
                    geometry=POLYGON).json()["spatial"]
    by_metric: Dict[str, List] = {}
    for obs in spatial["observations"]:
        by_metric.setdefault(obs["metric_key"], []).append(obs)
    assert set(by_metric) == {"ndvi", "ndmi", "vv"}
    assert [o["value"] for o in by_metric["ndvi"]] == NDVI_VALUES
    assert [o["value"] for o in by_metric["vv"]] == VV_VALUES
    assert {o["unit"] for o in by_metric["vv"]} == {"dB"}
    assert {o["unit"] for o in by_metric["ndvi"]} == {"index"}
    assert [o["window_start"] for o in by_metric["ndvi"]] == [WINDOW[0]] * 9


def test_null_insufficient_unavailable_preserved(client):
    spatial = _post(client, ["vegetation", "water"],
                    geometry=POLYGON).json()["spatial"]
    ndvi = [o for o in spatial["observations"]
            if o["metric_key"] == "ndvi"]
    gap = next(o for o in ndvi if o["cell_id"] == "r00c02")
    assert gap["value"] is None
    assert gap["value"] != 0
    assert gap["quality"] == "insufficient"
    assert gap["coverage_percent"] is None
    good = next(o for o in ndvi if o["cell_id"] == "r00c00")
    assert good["quality"] == "good"
    assert good["coverage_percent"] == pytest.approx(100.0)
    assert good["image_count"] == 4


def test_observation_shape_has_no_fabricated_fields(client):
    spatial = _post(client, ["vegetation", "water"],
                    geometry=POLYGON).json()["spatial"]
    allowed = {"cell_id", "metric_key", "window_start", "window_end",
               "value", "unit", "z_score", "category", "quality",
               "coverage_percent", "image_count"}
    for obs in spatial["observations"]:
        assert set(obs) <= allowed, set(obs) - allowed


# --------------------------------------------------------------------------
# 19-24. Summary, concentration, concordance, persistence
# --------------------------------------------------------------------------


def test_spatial_summary_preserved(client):
    spatial = _post(client, ["vegetation", "water"],
                    geometry=POLYGON).json()["spatial"]
    summary = spatial["summaries"]["ndvi"]
    usable = [v for v in NDVI_VALUES if v is not None]
    assert summary["n_cells"] == 9
    assert summary["n_usable"] == 7
    assert summary["n_missing"] == 2
    assert summary["mean"] == pytest.approx(statistics.mean(usable))
    assert summary["median"] == pytest.approx(statistics.median(usable))
    assert summary["anomalous_count"] == 5
    assert summary["anomalous_fraction"] == pytest.approx(5 / 7)
    assert summary["quality_counts"] == {"good": 7}
    assert summary["state"] == "CONCENTRATED_ANOMALY"


def test_concentration_state_without_majority(client):
    spatial = _post(client, ["vegetation", "water"],
                    geometry=POLYGON).json()["spatial"]
    assert spatial["summaries"]["ndmi"]["state"] == "ANOMALOUS_AREA"
    assert spatial["summaries"]["vv"]["state"] == "ANOMALOUS_AREA"


def test_cell_concordance_states(client):
    spatial = _post(client, ["vegetation", "water"],
                    geometry=POLYGON).json()["spatial"]
    by_cell = {c["cell_id"]: c for c in spatial["concordance"]}
    assert len(by_cell) == 9
    assert by_cell["r00c00"]["state"] == "MIXED_METRICS"
    assert by_cell["r00c00"]["anomalous_metrics"] == [
        "ndmi", "ndvi", "vv"]
    assert by_cell["r00c01"]["state"] == "SINGLE_METRIC_ANOMALY"
    assert by_cell["r00c01"]["anomalous_metrics"] == ["ndvi"]
    assert by_cell["r02c00"]["state"] == "NO_CONCORDANCE"
    assert by_cell["r02c00"]["anomalous_metrics"] == []
    assert by_cell["r02c01"]["state"] == "INSUFFICIENT"
    assert by_cell["r01c01"]["metrics"] == ["ndmi", "ndvi", "vv"]


def test_cell_persistence_honestly_insufficient(client):
    spatial = _post(client, ["vegetation", "water"],
                    geometry=POLYGON).json()["spatial"]
    assert len(spatial["persistence"]) == 9
    for entry in spatial["persistence"]:
        assert entry["state"] == "INSUFFICIENT"
        assert entry["n_observed"] == 0
        assert entry["n_missing"] == 1
    assert any("single requested window" in entry
               for entry in spatial["limitations"])


def test_unsupported_metric_never_substituted(client):
    data = _post(client, ["vegetation", "water", "thermal"],
                 geometry=POLYGON).json()["spatial"]
    metrics = {o["metric_key"] for o in data["observations"]}
    assert "temperature_mean" not in metrics
    assert "rvi" not in metrics
    assert metrics <= {"ndvi", "ndmi", "ndre", "msi", "vv", "vh", "vh_vv"}
    assert eligible_spatial_metrics(["ndvi", "temperature_mean", "rvi"]) == [
        "ndvi"]


# --------------------------------------------------------------------------
# 25-29. Request behavior and isolation
# --------------------------------------------------------------------------


def test_spatial_none_without_eligible_metrics(client):
    data = _post(client, ["soil"], geometry=POLYGON).json()
    assert data["spatial"] is None


def test_unrelated_domains_trigger_no_spatial_work(client):
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.utils.geometry.create_ee_geometry",
            return_value=MagicMock()))
        stack.enter_context(patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(_scalar_outcomes(), [])))
        probe = stack.enter_context(patch(
            "app.services.agriculture.spatial_profile.evaluate_grid"))
        response = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": POLYGON,
                "start_date": WINDOW[0],
                "end_date": WINDOW[1],
                "domains": ["soil"],
            },
        )
    assert response.status_code == 200
    assert response.json()["spatial"] is None
    assert probe.call_count == 0


def test_point_geometry_yields_explicit_limitation(client):
    spatial = _post(client, ["vegetation"], geometry=POINT).json()["spatial"]
    assert spatial is not None
    assert spatial["cells"] == []
    assert spatial["observations"] == []
    assert any("polygon" in entry for entry in spatial["limitations"])


def test_per_key_failure_isolated(client):
    from contextlib import ExitStack

    def _flaky(key: str, context, cells):
        if key == "ndvi":
            raise RuntimeError("simulated cell failure")
        return _grid_evaluator(key, context, cells)

    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.utils.geometry.create_ee_geometry",
            return_value=MagicMock()))
        stack.enter_context(patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(_scalar_outcomes(), [])))
        stack.enter_context(patch(
            "app.services.agriculture.spatial_profile.evaluate_grid",
            side_effect=_flaky))
        response = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": POLYGON,
                "start_date": WINDOW[0],
                "end_date": WINDOW[1],
                "domains": ["vegetation", "water"],
            },
        )
    assert response.status_code == 200
    spatial = response.json()["spatial"]
    metrics = {o["metric_key"] for o in spatial["observations"]}
    assert "ndvi" not in metrics
    assert {"ndmi", "vv"} <= metrics
    assert any("ndvi" in entry for entry in spatial["limitations"])


def test_whole_spatial_failure_leaves_analysis_valid(client):
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.utils.geometry.create_ee_geometry",
            return_value=MagicMock()))
        stack.enter_context(patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(_scalar_outcomes(), [])))
        stack.enter_context(patch(
            "app.services.agriculture.spatial_profile.evaluate_grid",
            side_effect=RuntimeError("all cells failed")))
        response = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": POLYGON,
                "start_date": WINDOW[0],
                "end_date": WINDOW[1],
                "domains": ["vegetation"],
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["evidence_bundles"]["vegetation"]["items"]
    assert data["spatial"]["observations"] == []
    assert any("no spatial metric produced observations" in entry
               for entry in data["spatial"]["limitations"])


# --------------------------------------------------------------------------
# 30-33. Cache behavior
# --------------------------------------------------------------------------


def test_legacy_cached_response_remains_valid():
    legacy = {
        "request_id": "old",
        "domain_summaries": {},
        "cross_domain_statements": [],
        "overall_sufficiency": "insufficient",
        "evidence_bundles": {},
        "available_domains": [],
        "unavailable_domains": [],
        "limitations": [],
        "metadata": {},
    }
    model = AgriculturalAnalysisResponse.model_validate(legacy)
    assert model.spatial is None
    assert model.temporal is None


def test_spatial_response_round_trip(client):
    data = _post(client, ["vegetation", "water"], geometry=POLYGON).json()
    model = AgriculturalAnalysisResponse.model_validate(data)
    assert AgriculturalAnalysisResponse.model_validate(
        model.model_dump()) == model
    assert json.loads(json.dumps(data))["spatial"]["summaries"]["ndvi"][
        "state"] == "CONCENTRATED_ANOMALY"


def test_cache_hit_returns_spatial_without_recompute(client):
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.utils.geometry.create_ee_geometry",
            return_value=MagicMock()))
        executor = stack.enter_context(patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(_scalar_outcomes(), [])))
        probe = stack.enter_context(patch(
            "app.services.agriculture.spatial_profile.evaluate_grid",
            side_effect=_grid_evaluator))
        body = {
            "geometry": POLYGON,
            "start_date": WINDOW[0],
            "end_date": WINDOW[1],
            "domains": ["vegetation", "water"],
        }
        first = client.post("/api/v1/agriculture/analysis", json=body)
        calls_after_first = probe.call_count
        assert calls_after_first > 0
        second = client.post("/api/v1/agriculture/analysis", json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert executor.call_count == 1
    assert probe.call_count == calls_after_first  # cache hit: no recompute
    assert second.json()["spatial"]["summaries"]["ndvi"]["n_usable"] == 7


# --------------------------------------------------------------------------
# 34-40. Scientific safeguards
# --------------------------------------------------------------------------


def test_no_new_ee_path_or_duplicated_algorithms():
    code = (Path(__file__).resolve().parents[2] / "app" / "services" /
            "agriculture" / "spatial_section.py")
    text = code.read_text(encoding="utf-8")
    for snippet in ("import ee", "ImageCollection", "filterDate",
                    "reduceRegion", "getInfo"):
        assert snippet not in text, snippet
    for snippet in ("def grid_cells", "def evaluate_grid",
                    "def evaluate_cell", "def aggregate_cells",
                    "def cell_concordance", "def track_cell_persistence",
                    "def bbox_of_geojson", "statistics.mean",
                    "statistics.median"):
        assert snippet not in text, snippet
    for snippet in ("MIN_VALID_CELLS =", "CONCENTRATION_MIN_FRACTION =",
                    '"score"', "'score'", "risk_score", "severity",
                    "probability", "confidence", "pest", "disease",
                    "canopy", "heat", "hotspot"):
        assert snippet not in text, snippet
