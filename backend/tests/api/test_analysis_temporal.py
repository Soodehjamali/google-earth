"""P5.3 contract tests: temporal intelligence inside /analysis.

Locks that POST /api/v1/agriculture/analysis returns existing
scalar fields unchanged plus an additive ``temporal`` section
built by existing P1-P4 builders: optical/radar profiles with
backend-owned anomaly/change, joint analysis, P2.5 concordance,
and separate thermal LST/air payloads with harmonization,
pair analysis, and thermal concordance.

Only the Earth Engine-touching profile builders are mocked, and
only with hand-built REAL dataclass instances; every downstream
computation (baselines, anomalies, changes, joint, concordance,
thermal analyses) runs for real. No network, no credentials.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.v1 import agriculture
from app.core.exceptions import AppException
from app.schemas.agriculture import AgriculturalAnalysisResponse
from app.services.agriculture.base import MetricContext
from app.services.agriculture.radar_profile import (
    RadarProfile,
    RadarProfilePoint,
)
from app.services.agriculture.temporal_profile import (
    TemporalProfile,
    TemporalProfilePoint,
)
from app.services.agriculture.thermal_profile import (
    ThermalProfilePoint as ThermalPoint,
)
from app.services.agriculture.thermal_profile import (
    ThermalSourceProfile,
)
from app.services.cache_service import cache_service
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    TemporalKind,
)

WINDOWS = [
    ("2024-01-01", "2024-01-31"),
    ("2024-02-01", "2024-02-29"),
    ("2024-03-01", "2024-03-31"),
    ("2024-04-01", "2024-04-30"),
]

NDVI_VALUES = [0.6, None, 0.7, 0.65]
NDMI_VALUES = [0.3, 0.35, 0.4, 0.38]
VV_VALUES = [-8.0, -8.5, -9.0, -8.2]
RVI_VALUES = [0.5, 0.55, None, 0.6]
LST_VALUES = [26.0, 27.0, 28.0, 29.0]
AIR_VALUES = [15.0, 16.0, 17.0, 18.0]


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


def _profile(key, values, unit="index",
             dataset="COPERNICUS/S2_SR_HARMONIZED") -> TemporalProfile:
    return TemporalProfile(
        metric_key=key,
        dataset_id=dataset,
        unit=unit,
        window_start=WINDOWS[0][0],
        window_end=WINDOWS[-1][1],
        points=tuple(
            TemporalProfilePoint(
                window_start=w[0], window_end=w[1], value=v, unit=unit,
                quality="good" if v is not None else "insufficient",
                coverage_percent=100.0 if v is not None else 0.0,
                image_count=4,
            )
            for w, v in zip(WINDOWS, values)
        ),
    )


def _radar_profile(key, values, unit="dB") -> RadarProfile:
    from app.services.agriculture.radar import S1_MODE, S1_PASS, S1_SCALE

    dataset = "COPERNICUS/S1_GRD"
    polars = ("VV", "VH") if key != "rvi" else ("VV", "VH")
    return RadarProfile(
        metric_key=key,
        dataset_id=dataset,
        unit="ratio" if key == "rvi" else unit,
        polarizations=polars,
        mode=S1_MODE,
        orbit_pass=S1_PASS,
        scale_m=S1_SCALE,
        window_start=WINDOWS[0][0],
        window_end=WINDOWS[-1][1],
        points=tuple(
            RadarProfilePoint(
                window_start=w[0], window_end=w[1], value=v,
                unit="ratio" if key == "rvi" else unit,
                quality="good" if v is not None else "insufficient",
                coverage_percent=100.0 if v is not None else 0.0,
                image_count=4,
                provenance={"dataset": dataset},
            )
            for w, v in zip(WINDOWS, values)
        ),
    )


def _thermal_source(kind, values) -> ThermalSourceProfile:
    if kind == "lst":
        args = ("MODIS/061/MOD11A2", "LST_Day_1km",
                "land_surface_temperature", "8 days",
                "land_surface_temperature_day", "LST_PROFILE", "product")
    else:
        args = ("ECMWF/ERA5_LAND/DAILY_AGGR", "temperature_2m",
                "air_temperature_2m", "daily", "temperature_mean",
                "AIR_TEMPERATURE_PROFILE", "modelled")
    dataset_id, band, quantity, res, metric_key, profile_kind, basis = args
    return ThermalSourceProfile(
        profile_kind=profile_kind,
        metric_key=metric_key,
        dataset_id=dataset_id,
        fallback_dataset_id=None,
        band=band,
        unit="degC",
        physical_quantity=quantity,
        physical_quantity_label=quantity,
        measurement_basis=basis,
        temporal_resolution=res,
        aggregation_method="time mean, then spatial mean",
        window_start=WINDOWS[0][0],
        window_end=WINDOWS[-1][1],
        limitations=(),
        points=tuple(
            ThermalPoint(
                window_start=w[0], window_end=w[1], value=v, unit="degC",
                quality="good" if v is not None else "insufficient",
                coverage_percent=100.0 if v is not None else 0.0,
                image_count=6,
                source_dataset_id=dataset_id,
                source_band=band,
                physical_quantity=quantity,
                aggregation_method="time mean, then spatial mean",
                temporal_resolution=res,
                provenance={
                    "source_dataset_id": dataset_id,
                    "bands": [band],
                    "formula": "celsius = kelvin - 273.15",
                    "unit": "degC",
                    "image_count": 6,
                },
            )
            for w, v in zip(WINDOWS, values)
        ),
    )


OPTICAL_FIXTURES = {
    "ndvi": lambda: _profile("ndvi", NDVI_VALUES),
    "ndmi": lambda: _profile("ndmi", NDMI_VALUES),
}
RADAR_FIXTURES = {
    "vv": lambda: _radar_profile("vv", VV_VALUES),
    "rvi": lambda: _radar_profile("rvi", RVI_VALUES),
}
THERMAL_FIXTURES = {
    "lst": lambda: _thermal_source("lst", LST_VALUES),
    "air": lambda: _thermal_source("air", AIR_VALUES),
}


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
            requested_end="2024-04-30",
        ),
        warnings=[],
    )
    outcome = MagicMock()
    outcome.result = result
    outcome.metric_key = "ndvi"
    return {"ndvi": outcome}


def _patches(fixtures=True):
    patches = [
        patch("app.utils.geometry.create_ee_geometry",
              return_value=MagicMock()),
        patch("app.services.agriculture.executor.execute_metrics",
              return_value=(_scalar_outcomes(), [])),
    ]
    if fixtures:

        def _optical(key: str, context: MetricContext):
            if key in OPTICAL_FIXTURES:
                return OPTICAL_FIXTURES[key]()
            raise RuntimeError(f"no fixture for {key}")

        def _radar(key: str, context: MetricContext):
            if key in RADAR_FIXTURES:
                return RADAR_FIXTURES[key]()
            raise RuntimeError(f"no fixture for {key}")

        def _lst(context: MetricContext):
            return THERMAL_FIXTURES["lst"]()

        def _air(context: MetricContext):
            return THERMAL_FIXTURES["air"]()

        patches.extend([
            patch("app.services.agriculture.temporal_profile.build_temporal_profile",
                  side_effect=_optical),
            patch("app.services.agriculture.radar_profile.build_radar_profile",
                  side_effect=_radar),
            patch("app.services.agriculture.thermal_profile.build_lst_profile",
                  side_effect=_lst),
            patch("app.services.agriculture.thermal_profile.build_air_temperature_profile",
                  side_effect=_air),
        ])
    return patches


def _post(client, domains, start="2024-01-01", end="2024-04-30",
          lon=51.3):
    from contextlib import ExitStack

    with ExitStack() as stack:
        for patcher in _patches():
            stack.enter_context(patcher)
        return client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": {"type": "Point", "coordinates": [lon, 35.7]},
                "start_date": start,
                "end_date": end,
                "domains": domains,
            },
        )


# --------------------------------------------------------------------------
# 1-2. Scalars intact, temporal additive
# --------------------------------------------------------------------------


def test_scalar_fields_intact(client):
    response = _post(client, ["vegetation", "water", "thermal"])
    assert response.status_code == 200
    data = response.json()
    for field in ("domain_summaries", "evidence_bundles",
                  "overall_sufficiency", "available_domains", "metadata"):
        assert field in data, field
    veg_keys = [i["metric_key"]
                for i in data["evidence_bundles"]["vegetation"]["items"]]
    assert "ndvi" in veg_keys
    ndvi_item = next(i for i in data["evidence_bundles"]["vegetation"]["items"]
                     if i["metric_key"] == "ndvi")
    assert ndvi_item["value"] == pytest.approx(0.65)


def test_temporal_section_is_additive(client):
    data = _post(client, ["vegetation", "water", "thermal"]).json()
    assert "temporal" in data
    assert data["temporal"] is not None
    assert data["temporal"]["window_start"] == "2024-01-01"
    assert data["temporal"]["window_end"] == "2024-04-30"


# --------------------------------------------------------------------------
# 3-12. Optical / radar / thermal profiles serialize
# --------------------------------------------------------------------------


def test_optical_profiles_serialize(client):
    temporal = _post(client, ["vegetation", "water", "thermal"]).json()["temporal"]
    ndvi = temporal["profiles"]["ndvi"]
    assert [p["value"] for p in ndvi["points"]] == [0.6, None, 0.7, 0.65]
    assert [(p["window_start"], p["window_end"]) for p in ndvi["points"]] == WINDOWS
    assert ndvi["unit"] == "index"
    assert ndvi["dataset_id"] == "COPERNICUS/S2_SR_HARMONIZED"
    ndmi = temporal["profiles"]["ndmi"]
    assert [p["value"] for p in ndmi["points"]] == NDMI_VALUES


def test_radar_profiles_serialize_with_units(client):
    temporal = _post(client, ["vegetation", "water", "thermal"]).json()["temporal"]
    vv = temporal["radar_profiles"]["vv"]
    assert [p["value"] for p in vv["points"]] == VV_VALUES
    assert vv["unit"] == "dB"
    rvi = temporal["radar_profiles"]["rvi"]
    assert [p["value"] for p in rvi["points"]] == RVI_VALUES
    assert rvi["unit"] == "ratio"


def test_thermal_profiles_serialize_separately(client):
    temporal = _post(client, ["vegetation", "water", "thermal"]).json()["temporal"]
    assert set(temporal["thermal_profiles"]) == {
        "land_surface_temperature_day", "temperature_mean"}
    lst = temporal["thermal_profiles"]["land_surface_temperature_day"]
    air = temporal["thermal_profiles"]["temperature_mean"]
    assert [p["value"] for p in lst["points"]] == LST_VALUES
    assert [p["value"] for p in air["points"]] == AIR_VALUES
    assert lst["physical_quantity"] == "land_surface_temperature"
    assert air["physical_quantity"] == "air_temperature_2m"
    assert lst["unit"] == air["unit"] == "degC"

    def iter_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from iter_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from iter_keys(item)

    assert "temperature" not in set(iter_keys(temporal["thermal_profiles"]))


# --------------------------------------------------------------------------
# 13-18. Months, nulls, statuses, quality, coverage, units, datasets
# --------------------------------------------------------------------------


def test_exact_month_identity_and_nulls(client):
    temporal = _post(client, ["vegetation", "water", "thermal"]).json()["temporal"]
    ndvi_points = temporal["profiles"]["ndvi"]["points"]
    assert [(p["window_start"], p["window_end"]) for p in ndvi_points] == WINDOWS
    assert ndvi_points[1]["value"] is None
    assert ndvi_points[1]["quality"] == "insufficient"
    gap_anomaly = temporal["anomalies"]["ndvi"]["points"][1]
    assert gap_anomaly["value"] is None
    assert gap_anomaly["z_score"] is None
    assert gap_anomaly["category"] == "INSUFFICIENT_BASELINE"


def test_quality_coverage_units_datasets_preserved(client):
    temporal = _post(client, ["vegetation", "water", "thermal"]).json()["temporal"]
    point = temporal["profiles"]["ndvi"]["points"][0]
    assert point["quality"] == "good"
    assert point["coverage_percent"] == pytest.approx(100.0)
    assert temporal["anomalies"]["ndvi"]["unit"] == "index"
    lst_point = temporal["thermal_profiles"][
        "land_surface_temperature_day"]["points"][0]
    assert lst_point["source_dataset_id"] == "MODIS/061/MOD11A2"
    assert lst_point["source_band"] == "LST_Day_1km"
    air_point = temporal["thermal_profiles"]["temperature_mean"]["points"][0]
    assert air_point["source_dataset_id"] == "ECMWF/ERA5_LAND/DAILY_AGGR"
    assert air_point["source_band"] == "temperature_2m"


# --------------------------------------------------------------------------
# 19-25. Baseline, anomaly, change, persistence, joint, provenance
# --------------------------------------------------------------------------


def test_baseline_anomaly_change_persistence_preserved(client):
    import statistics

    temporal = _post(client, ["vegetation", "water", "thermal"]).json()["temporal"]
    baseline = temporal["anomalies"]["ndvi"]["baseline"]
    usable = [v for v in NDVI_VALUES if v is not None]
    assert baseline["mean"] == pytest.approx(statistics.mean(usable))
    assert baseline["std"] == pytest.approx(statistics.stdev(usable))
    scored = temporal["anomalies"]["ndvi"]["points"][0]
    assert scored["z_score"] == pytest.approx(
        (0.6 - statistics.mean(usable)) / statistics.stdev(usable))
    assert scored["category"] == "BELOW_BASELINE"
    assert scored["percentile"] is None  # reference too small for a rank
    change = temporal["changes"]["ndvi"]["changes"][3]
    assert change["absolute_change"] == pytest.approx(0.65 - 0.7)
    assert change["direction"] == "DECREASE"
    persistence = temporal["changes"]["ndvi"]["persistence"]
    assert persistence["state"] in {
        "PERSISTENT", "NO_PERSISTENCE", "INSUFFICIENT"}
    assert temporal["joint"] is not None
    assert temporal["joint"]["ndvi_key"] == "ndvi"
    assert temporal["joint"]["moisture_key"] == "ndmi"


def test_thermal_analysis_and_provenance_preserved(client):
    temporal = _post(client, ["vegetation", "water", "thermal"]).json()["temporal"]
    lst_analysis = temporal["thermal_analyses"]["land_surface_temperature_day"]
    assert lst_analysis["baseline"] is not None
    assert lst_analysis["anomalies"][0]["z_score"] is not None
    assert lst_analysis["anomalies"][0]["thermal_provenance"][
        "source_dataset_id"] == "MODIS/061/MOD11A2"
    assert lst_analysis["physical_quantity"] == "land_surface_temperature"
    assert lst_analysis["measurement_basis"] == "product"
    air_analysis = temporal["thermal_analyses"]["temperature_mean"]
    assert air_analysis["physical_quantity"] == "air_temperature_2m"
    assert temporal["thermal_harmonized"] is not None
    assert temporal["thermal_pair"]["alignment"] == "calendar_month"
    assert temporal["thermal_concordance"]["rule_id"] == (
        "P44_THERMAL_CONCORDANCE_V1")


def test_p25_state_valid_and_untouched_semantics(client):
    temporal = _post(client, ["vegetation", "water", "thermal"]).json()["temporal"]
    concordance = temporal["concordance"]
    assert concordance["rule_id"] == "P25_CONCORDANCE_V1"
    assert {m["state"] for m in concordance["months"]} <= {
        "MULTI_SENSOR_CONCORDANT", "OPTICAL_ONLY", "RADAR_ONLY",
        "DIVERGENT", "MIXED_EVIDENCE", "INSUFFICIENT_EVIDENCE"}


# --------------------------------------------------------------------------
# 26-31. Scalars/P3 unchanged, round-trip, cache, cap, isolation
# --------------------------------------------------------------------------


def test_scalar_outputs_unchanged_alongside_temporal(client):
    data = _post(client, ["vegetation", "water", "thermal"]).json()
    assert data["metadata"]["metrics_executed"] == "1"
    assert "temporal" in data and data["temporal"] is not None


def test_response_round_trip_validates(client):
    data = _post(client, ["vegetation", "water", "thermal"]).json()
    model = AgriculturalAnalysisResponse.model_validate(data)
    assert AgriculturalAnalysisResponse.model_validate(
        model.model_dump()) == model


def test_cached_response_round_trip_with_temporal(client):
    from contextlib import ExitStack
    from unittest.mock import MagicMock

    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.utils.geometry.create_ee_geometry",
            return_value=MagicMock()))
        executor = stack.enter_context(patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(_scalar_outcomes(), [])))
        stack.enter_context(patch(
            "app.services.agriculture.temporal_profile.build_temporal_profile",
            side_effect=lambda key, ctx: OPTICAL_FIXTURES[key]()))
        stack.enter_context(patch(
            "app.services.agriculture.radar_profile.build_radar_profile",
            side_effect=lambda key, ctx: RADAR_FIXTURES[key]()))
        stack.enter_context(patch(
            "app.services.agriculture.thermal_profile.build_lst_profile",
            side_effect=lambda ctx: THERMAL_FIXTURES["lst"]()))
        stack.enter_context(patch(
            "app.services.agriculture.thermal_profile.build_air_temperature_profile",
            side_effect=lambda ctx: THERMAL_FIXTURES["air"]()))
        body = {
            "geometry": {"type": "Point", "coordinates": [51.9, 35.7]},
            "start_date": "2024-01-01",
            "end_date": "2024-04-30",
            "domains": ["vegetation", "water", "thermal"],
        }
        first = client.post("/api/v1/agriculture/analysis", json=body)
        second = client.post("/api/v1/agriculture/analysis", json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert executor.call_count == 1  # second request served from cache
    assert second.json()["temporal"]["profiles"]["ndvi"]["points"][0][
        "value"] == pytest.approx(0.6)


def test_cache_key_separates_materially_different_requests():
    from app.api.v1.agriculture import _build_analysis_cache_key
    from app.schemas.agriculture import AgricultureAnalysisRequest

    def _request(domains, lon=51.3):
        return AgricultureAnalysisRequest(
            geometry={"type": "Point", "coordinates": [lon, 35.7]},
            start_date="2024-01-01",
            end_date="2024-04-30",
            domains=domains,
        )

    base = _build_analysis_cache_key(_request(["vegetation"]))
    assert _build_analysis_cache_key(_request(["vegetation"])) == base
    assert _build_analysis_cache_key(
        _request(["vegetation", "thermal"])) != base
    assert _build_analysis_cache_key(_request(["vegetation"], lon=52.0)) != base


def test_long_window_yields_bounded_empty_section(client):
    data = _post(client, ["vegetation"],
                 start="2020-01-01", end="2024-06-01").json()
    temporal = data["temporal"]
    assert temporal["profiles"] == {}
    assert temporal["radar_profiles"] == {}
    assert temporal["thermal_profiles"] == {}
    assert any("36-month" in entry for entry in temporal["limitations"])


def test_per_key_failure_isolated(client):
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.utils.geometry.create_ee_geometry",
            return_value=MagicMock()))
        stack.enter_context(patch(
            "app.services.agriculture.executor.execute_metrics",
            return_value=(_scalar_outcomes(), [])))

        def _optical(key: str, context: MetricContext):
            if key == "ndvi":
                raise RuntimeError("simulated EE failure")
            return OPTICAL_FIXTURES[key]()

        stack.enter_context(patch(
            "app.services.agriculture.temporal_profile.build_temporal_profile",
            side_effect=_optical))
        response = client.post(
            "/api/v1/agriculture/analysis",
            json={
                "geometry": {"type": "Point", "coordinates": [51.4, 35.7]},
                "start_date": "2024-01-01",
                "end_date": "2024-04-30",
                "domains": ["vegetation", "water"],
            },
        )
    assert response.status_code == 200
    temporal = response.json()["temporal"]
    assert "ndvi" not in temporal["profiles"]
    assert temporal["profiles"]["ndmi"]["points"][0]["value"] == (
        pytest.approx(0.3))
    assert any("ndvi" in entry for entry in temporal["limitations"])


def test_thermal_gated_by_domain_selection(client):
    data = _post(client, ["vegetation"]).json()["temporal"]
    assert data["thermal_profiles"] == {}
    assert data["thermal_analyses"] == {}
    assert data["thermal_harmonized"] is None
    assert data["thermal_concordance"] is None
    assert "ndvi" in data["profiles"] or data["limitations"]


def test_soil_only_request_has_empty_temporal_section(client):
    data = _post(client, ["soil"]).json()
    assert data["temporal"] is not None
    assert data["temporal"]["profiles"] == {}
    assert data["temporal"]["radar_profiles"] == {}
    assert data["temporal"]["thermal_profiles"] == {}
    assert data["temporal"]["limitations"] == []


# --------------------------------------------------------------------------
# 32-35. No new GEE path, no duplicated formulas, P3 untouched
# --------------------------------------------------------------------------


def test_no_new_gee_path_or_duplicated_formulas():
    code = Path(__file__).resolve().parents[2] / "app" / "services" / \
        "agriculture" / "temporal_section.py"
    text = code.read_text(encoding="utf-8")
    for snippet in ("import ee", "ImageCollection", "filterDate",
                    "reduceRegion", "getInfo"):
        assert snippet not in text, snippet
    for snippet in ("np.mean", "np.std", "ddof", "def compute_baseline",
                    "def standardized_anomaly", "def percentile_context",
                    "def month_changes", "def compute_persistence",
                    "def score_profile", "def analyze_changes",
                    "def analyze_joint", "def harmonize_thermal_monthly"):
        assert snippet not in text, snippet
    for snippet in ("pattern_engine", "synthesis", "canopy_temperature",
                    "heat_stress", "thermal_stress", "LST - ERA5",
                    "risk", "probability"):
        assert snippet not in text, snippet
