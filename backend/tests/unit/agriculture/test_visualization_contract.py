"""Tests for the P5.1 agriculture visualization contract.

Locks that P1-P4 service outputs validate unchanged against the
backend Pydantic mirrors: temporal values, backend-owned
baseline/anomaly/change statistics, missing/unavailable semantics,
units, physical quantities, dataset identity, provenance, source
separation (LST vs ERA5, NDMI vs NDWI), spatial geometry,
categorical-state preservation, evidence-pattern identity, thermal
context identity, and deterministic serialization.

Fixtures build the full P4.2-P4.4 chain directly in Python plus
real P2.5 months; no Earth Engine is involved. No network and no
credentials are required.
"""

from __future__ import annotations

import json
import statistics
from typing import Any, Dict, List, Optional

import pytest
from pydantic import TypeAdapter

from app.schemas.agriculture import (
    AnomalyPointModel,
    CellObservationModel,
    ChangeProfileModel,
    DeviationPersistenceModel,
    EvidencePatternModel,
    MonthChangeModel,
    PatternEvidenceModel,
    ProfileBaselineModel,
    ProvenanceResponse,
    SpatialCellModel,
    ThermalAnomalyPointModel,
    ThermalChangeModel,
    ThermalConcordanceAnalysisModel,
    ThermalConcordanceMonthModel,
    ThermalHarmonizedProfileModel,
    ThermalMetricAnalysisModel,
    ThermalPairAnalysisModel,
    ThermalSideEvidenceModel,
    ThermalSourceProfileModel,
)
from app.services.agriculture.concordance import (
    analyze_concordance,
    make_evidence,
)
from app.services.agriculture.pattern_engine import (
    evaluate_concordance_month,
    evidence_from_anomaly_point,
)
from app.services.agriculture.spatial_profile import (
    CellObservation,
    SpatialCell,
)
from app.services.agriculture.thermal_anomaly import analyze_thermal_metric
from app.services.agriculture.thermal_concordance import (
    SOURCE_ROLE_AIR,
    SOURCE_ROLE_LST,
    analyze_thermal_concordance,
)
from app.services.agriculture.thermal_profile import (
    ThermalProfilePoint,
    ThermalSourceProfile,
    month_windows,
)
from app.services.agriculture.temporal_profile import TemporalProfilePoint

LST_DATASET = "MODIS/061/MOD11A2"
AIR_DATASET = "ECMWF/ERA5_LAND/DAILY_AGGR"

LST_VALUES = [20.0, 22.0, None, 28.0, 30.0, 29.0]
AIR_VALUES = [15.0, 16.0, 17.0, 18.0, 19.0, 20.0]

ANOMALY_VOCAB = {
    "NORMAL", "BELOW_BASELINE", "ABOVE_BASELINE", "INSUFFICIENT_BASELINE",
}
DIRECTION_VOCAB = {"INCREASE", "DECREASE", "STABLE", "INSUFFICIENT"}
RAPID_VOCAB = {
    "RAPID_INCREASE", "RAPID_DECREASE", "NOT_RAPID", "INSUFFICIENT",
}
PERSISTENCE_VOCAB = {"PERSISTENT", "NO_PERSISTENCE", "INSUFFICIENT"}
P25_VOCAB = {
    "MULTI_SENSOR_CONCORDANT", "OPTICAL_ONLY", "RADAR_ONLY",
    "DIVERGENT", "MIXED_EVIDENCE", "INSUFFICIENT_EVIDENCE",
}
THERMAL_REL_VOCAB = {
    "THERMAL_CONCORDANT", "THERMAL_DIVERGENT", "THERMAL_MIXED_EVIDENCE",
    "THERMAL_ONLY", "THERMAL_CONTEXT_CONCORDANT",
    "THERMAL_CONTEXT_DIVERGENT", "THERMAL_CONTEXT_MIXED_EVIDENCE",
    "THERMAL_CONTEXT_ONLY", "INSUFFICIENT_EVIDENCE",
}


def _point(window, value, dataset_id, band, quantity, resolution,
           quality="good"):
    return ThermalProfilePoint(
        window_start=window[0],
        window_end=window[1],
        value=value,
        unit="degC",
        quality=quality,
        coverage_percent=100.0,
        image_count=6,
        source_dataset_id=dataset_id,
        source_band=band,
        physical_quantity=quantity,
        aggregation_method="time mean, then spatial mean",
        temporal_resolution=resolution,
        provenance={
            "source_dataset_id": dataset_id,
            "bands": [band],
            "formula": "celsius = kelvin - 273.15",
            "unit": "degC",
            "image_count": 6,
        },
    )


def _source(values, kind):
    windows = month_windows("2024-01-01", "2024-06-30")
    if kind == "lst":
        args = (LST_DATASET, "LST_Day_1km", "land_surface_temperature",
                "8 days", "land_surface_temperature_day", "LST_PROFILE",
                "product")
    else:
        args = (AIR_DATASET, "temperature_2m", "air_temperature_2m",
                "daily", "temperature_mean", "AIR_TEMPERATURE_PROFILE",
                "modelled")
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
        window_start=windows[0][0],
        window_end=windows[-1][1],
        limitations=(),
        points=tuple(
            _point(w, v, dataset_id, band, quantity, res)
            for w, v in zip(windows, values)
        ),
    )


def _chain():
    lst = analyze_thermal_metric(_source(LST_VALUES, "lst"))
    air = analyze_thermal_metric(_source(AIR_VALUES, "air"))
    windows = month_windows("2024-01-01", "2024-06-30")
    items = []
    for window in windows:
        items.append(make_evidence(
            family="optical", metric_id="ndvi",
            window_start=window[0], window_end=window[1],
            value=0.6, unit="index", quality="good",
            coverage_percent=100.0, image_count=4,
            state_kind="anomaly", state="ABOVE_BASELINE",
            provenance={"family": "optical"},
        ))
        items.append(make_evidence(
            family="radar", metric_id="vv",
            window_start=window[0], window_end=window[1],
            value=-8.0, unit="dB", quality="good",
            coverage_percent=100.0, image_count=4,
            state_kind="anomaly", state="ABOVE_BASELINE",
            provenance={"family": "radar"},
        ))
    p25_months = analyze_concordance(items).months
    concordance = analyze_thermal_concordance(p25_months, lst, air)
    return lst, air, p25_months, concordance


# --------------------------------------------------------------------------
# 1-4. Temporal values and backend-owned statistics
# --------------------------------------------------------------------------


def test_temporal_values_remain_unchanged():
    lst, _, _, _ = _chain()
    model = ThermalSourceProfileModel.model_validate(lst.source.to_dict())
    assert [p.value for p in model.points] == LST_VALUES
    assert model.points[2].value is None
    assert model.unit == "degC"


def test_baseline_remains_backend_owned():
    lst, _, _, _ = _chain()
    usable = [v for v in LST_VALUES if v is not None]
    model = ThermalMetricAnalysisModel.model_validate(lst.to_dict())
    assert model.baseline is not None
    assert model.baseline.mean == pytest.approx(statistics.mean(usable))
    assert model.baseline.std == pytest.approx(statistics.stdev(usable))
    assert model.baseline.minimum == pytest.approx(min(usable))
    assert model.baseline.maximum == pytest.approx(max(usable))
    assert model.baseline.median == pytest.approx(statistics.median(usable))


def test_anomaly_remains_backend_owned():
    lst, _, _, _ = _chain()
    model = ThermalMetricAnalysisModel.model_validate(lst.to_dict())
    assert model.baseline is not None
    mean, std = model.baseline.mean, model.baseline.std
    assert std is not None
    for entry, raw in zip(model.anomalies, LST_VALUES):
        assert isinstance(entry, ThermalAnomalyPointModel)
        assert isinstance(entry, AnomalyPointModel)
        if raw is None:
            assert entry.value is None
            assert entry.z_score is None
        else:
            assert entry.value == pytest.approx(raw)
            assert entry.z_score == pytest.approx((raw - mean) / std)


def test_change_remains_backend_owned():
    lst, _, _, _ = _chain()
    model = ThermalMetricAnalysisModel.model_validate(lst.to_dict())
    second = model.changes[1]
    assert isinstance(second, ThermalChangeModel)
    assert isinstance(second, MonthChangeModel)
    assert second.absolute_change == pytest.approx(22.0 - 20.0)
    assert second.previous_value == pytest.approx(20.0)
    assert second.days_elapsed == 31
    assert second.rate_per_day == pytest.approx(2.0 / 31.0)
    assert second.direction in DIRECTION_VOCAB
    assert second.rapid in RAPID_VOCAB


# --------------------------------------------------------------------------
# 5-10. Missingness, units, quantities, datasets, provenance
# --------------------------------------------------------------------------


def test_missing_values_remain_missing():
    lst, _, _, concordance = _chain()
    model = ThermalMetricAnalysisModel.model_validate(lst.to_dict())
    gap = model.anomalies[2]
    assert gap.value is None
    assert gap.z_score is None
    assert gap.percentile is None
    assert gap.category == "INSUFFICIENT_BASELINE"
    assert gap.value != 0
    month = concordance.months[2].to_dict()
    assert month["lst"]["value"] is None


def test_unavailable_remains_unavailable():
    source = _source([None, 20.0, 30.0], "lst")
    points = tuple(
        ThermalProfilePoint(
            window_start=p.window_start, window_end=p.window_end,
            value=p.value, unit=p.unit,
            quality="unavailable" if p.value is None else p.quality,
            coverage_percent=p.coverage_percent,
            image_count=p.image_count,
            source_dataset_id=p.source_dataset_id,
            source_band=p.source_band,
            physical_quantity=p.physical_quantity,
            aggregation_method=p.aggregation_method,
            temporal_resolution=p.temporal_resolution,
            provenance=p.provenance,
        )
        for p in source.points
    )
    rebuilt = ThermalSourceProfile(
        profile_kind=source.profile_kind, metric_key=source.metric_key,
        dataset_id=source.dataset_id,
        fallback_dataset_id=source.fallback_dataset_id, band=source.band,
        unit=source.unit, physical_quantity=source.physical_quantity,
        physical_quantity_label=source.physical_quantity_label,
        measurement_basis=source.measurement_basis,
        temporal_resolution=source.temporal_resolution,
        aggregation_method=source.aggregation_method,
        window_start=source.window_start, window_end=source.window_end,
        limitations=source.limitations, points=points,
    )
    model = ThermalSourceProfileModel.model_validate(rebuilt.to_dict())
    assert model.points[0].quality == "unavailable"
    assert model.points[0].value is None


def test_units_preserved_across_layers():
    lst, air, _, concordance = _chain()
    assert ThermalMetricAnalysisModel.model_validate(
        lst.to_dict()).unit == "degC"
    assert ThermalMetricAnalysisModel.model_validate(
        air.to_dict()).unit == "degC"
    payload = concordance.to_dict()
    for month in payload["months"]:
        assert month["lst"]["unit"] == "degC"
        assert month["air"]["unit"] == "degC"


def test_physical_quantities_preserved_across_layers():
    lst, air, _, concordance = _chain()
    lst_model = ThermalSourceProfileModel.model_validate(lst.to_dict())
    air_model = ThermalSourceProfileModel.model_validate(air.to_dict())
    assert lst_model.physical_quantity == "land_surface_temperature"
    assert air_model.physical_quantity == "air_temperature_2m"
    for month in concordance.to_dict()["months"]:
        assert month["lst"]["physical_quantity"] == (
            "land_surface_temperature")
        assert month["air"]["physical_quantity"] == "air_temperature_2m"


def test_dataset_identity_preserved_across_layers():
    lst, air, _, concordance = _chain()
    assert ThermalMetricAnalysisModel.model_validate(
        lst.to_dict()).dataset_id == LST_DATASET
    assert ThermalMetricAnalysisModel.model_validate(
        air.to_dict()).dataset_id == AIR_DATASET
    for month in concordance.to_dict()["months"]:
        assert month["lst"]["dataset_id"] == LST_DATASET
        assert month["air"]["dataset_id"] == AIR_DATASET
        assert month["lst"]["band"] == "LST_Day_1km"
        assert month["air"]["band"] == "temperature_2m"


def test_provenance_preserved_across_layers():
    lst, _, _, concordance = _chain()
    model = ThermalMetricAnalysisModel.model_validate(lst.to_dict())
    assert model.anomalies[0].thermal_provenance["source_dataset_id"] == (
        LST_DATASET)
    assert model.anomalies[0].thermal_provenance["bands"] == ["LST_Day_1km"]
    assert model.changes[1].thermal_provenance["source_dataset_id"] == (
        LST_DATASET)
    month = concordance.to_dict()["months"][0]
    assert month["lst"]["provenance"]["source_dataset_id"] == LST_DATASET


# --------------------------------------------------------------------------
# 11-13. Separation and no frontend statistics
# --------------------------------------------------------------------------


def test_lst_and_era5_remain_separate():
    from app.services.agriculture.thermal_anomaly import (
        analyze_thermal_pair,
    )
    pair = analyze_thermal_pair(
        _source(LST_VALUES, "lst"), _source(AIR_VALUES, "air"))
    pair_model = ThermalPairAnalysisModel.model_validate(pair.to_dict())
    assert pair_model.lst.physical_quantity == "land_surface_temperature"
    assert pair_model.air.physical_quantity == "air_temperature_2m"

    def iter_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from iter_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from iter_keys(item)

    assert "temperature" not in set(iter_keys(pair_model.model_dump()))


def test_harmonized_sides_remain_separate():
    from app.services.agriculture.thermal_profile import (
        harmonize_thermal_monthly,
    )
    lst_source, air_source = _source(LST_VALUES, "lst"), _source(
        AIR_VALUES, "air")
    harmonized = harmonize_thermal_monthly(lst_source, air_source)
    model = ThermalHarmonizedProfileModel.model_validate(
        harmonized.to_dict())

    def iter_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from iter_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from iter_keys(item)

    keys = set(iter_keys(model.model_dump()))
    assert "lst_celsius" in keys
    assert "air_temperature_celsius" in keys
    assert "temperature" not in keys
    assert "canopy_temperature" not in keys


def test_ndmi_and_ndwi_remain_separate():
    from app.services.agriculture import indices as indices_mod
    from app.services.agriculture import register_all_metrics
    from app.services.agriculture.catalog import get_metric

    register_all_metrics()
    assert indices_mod.FORMULA_TEXT["ndmi"] != indices_mod.FORMULA_TEXT["ndwi"]
    assert indices_mod.BAND_ROLES["ndmi"] != indices_mod.BAND_ROLES["ndwi"]
    ndmi, ndwi = get_metric("ndmi"), get_metric("ndwi")
    assert type(ndmi) is not type(ndwi)
    assert ndmi.key == "ndmi" and ndwi.key == "ndwi"


def test_models_carry_no_frontend_statistical_fields():
    models = [
        ThermalSourceProfileModel, ThermalMetricAnalysisModel,
        ThermalPairAnalysisModel, ThermalConcordanceAnalysisModel,
        ThermalAnomalyPointModel, ThermalChangeModel,
    ]
    for model in models:
        fields = set(model.model_fields)
        assert not ({"threshold", "severity", "risk", "score",
                     "confidence", "probability"} & fields), model.__name__


# --------------------------------------------------------------------------
# 14-16. Spatial geometry and evidence-pattern identity
# --------------------------------------------------------------------------


def test_spatial_geometry_preserved():
    geometry = {
        "type": "Polygon",
        "coordinates": [[[51.0, 35.0], [52.0, 35.0],
                         [52.0, 36.0], [51.0, 36.0], [51.0, 35.0]]],
    }
    cell = SpatialCell(
        cell_id="r0c0", row=0, col=0, west=51.0, south=35.0,
        east=52.0, north=36.0, geometry=geometry,
    )
    observation = CellObservation(
        cell_id="r0c0", metric_key="ndvi",
        window_start="2024-01-01", window_end="2024-01-31",
        value=0.62, unit="index", z_score=1.2,
        category="ABOVE_BASELINE", quality="good",
        coverage_percent=100.0, image_count=4,
    )
    cell_model = SpatialCellModel.model_validate(cell.to_dict())
    obs_model = CellObservationModel.model_validate(observation.to_dict())
    assert cell_model.geometry == geometry
    assert cell_model.cell_id == "r0c0"
    assert (cell_model.west, cell_model.south,
            cell_model.east, cell_model.north) == (51.0, 35.0, 52.0, 36.0)
    assert obs_model.value == pytest.approx(0.62)
    assert obs_model.category == "ABOVE_BASELINE"


def test_evidence_pattern_identity_preserved():
    _, _, p25_months, _ = _chain()
    adapted_point = TemporalProfilePoint(
        window_start="2024-01-01", window_end="2024-01-31",
        value=28.0, unit="degC", quality="good",
        coverage_percent=100.0, image_count=6,
    )
    evidence = evidence_from_anomaly_point(
        "thermal_anomaly", "land_surface_temperature_day", "LST",
        "thermal", adapted_point, category="ABOVE_BASELINE",
        provenance={"source_dataset_id": LST_DATASET},
    )
    evidence_model = PatternEvidenceModel.model_validate(evidence.to_dict())
    assert evidence_model.metric_id == "land_surface_temperature_day"
    assert evidence_model.anomaly_state == "ABOVE_BASELINE"
    assert evidence_model.window_start == "2024-01-01"
    patterns = evaluate_concordance_month(p25_months[0])
    assert patterns, "concordant fixture must yield a pattern"
    pattern_model = EvidencePatternModel.model_validate(patterns[0].to_dict())
    assert pattern_model.window_start == "2024-01-01"
    assert pattern_model.status in {
        "OBSERVED", "NOT_OBSERVED", "INSUFFICIENT_EVIDENCE",
    }


def test_categorical_states_preserved_verbatim():
    lst, _, p25_months, concordance = _chain()
    lst_model = ThermalMetricAnalysisModel.model_validate(lst.to_dict())
    assert {p.category for p in lst_model.anomalies} <= ANOMALY_VOCAB
    assert {c.direction for c in lst_model.changes} <= DIRECTION_VOCAB
    assert {c.rapid for c in lst_model.changes} <= RAPID_VOCAB
    assert lst_model.persistence.state in {
        "PERSISTENT", "NO_PERSISTENCE", "INSUFFICIENT",
    }
    assert {m.state for m in p25_months} <= P25_VOCAB
    payload = concordance.to_dict()
    assert {m["lst_relationship"] for m in payload["months"]} <= (
        THERMAL_REL_VOCAB)
    assert {m["air_relationship"] for m in payload["months"]} <= (
        THERMAL_REL_VOCAB)


# --------------------------------------------------------------------------
# 17-18. Thermal context identity and deterministic serialization
# --------------------------------------------------------------------------


def test_thermal_context_identity_preserved():
    _, _, _, concordance = _chain()
    model = ThermalConcordanceAnalysisModel.model_validate(
        concordance.to_dict())
    assert model.rule_id == "P44_THERMAL_CONCORDANCE_V1"
    for month in model.months:
        assert isinstance(month, ThermalConcordanceMonthModel)
        assert month.lst is not None and month.air is not None
        assert isinstance(month.lst, ThermalSideEvidenceModel)
        assert month.lst.source_role == SOURCE_ROLE_LST
        assert month.air.source_role == SOURCE_ROLE_AIR
        assert month.p25_rule_id == "P25_CONCORDANCE_V1"
    by_start = {m.window_start: m for m in model.months}
    # Usable LST months count three observational sensors
    # (S2, S1, LST); the March LST gap leaves two.
    assert by_start["2024-01-01"].observational_sensor_count == 3
    assert by_start["2024-03-01"].observational_sensor_count == 2
    assert all(
        m.meteorological_context_present for m in model.months)


def test_deterministic_serialization_round_trip():
    first = analyze_thermal_concordance(
        analyze_concordance([
            make_evidence(
                family="optical", metric_id="ndvi",
                window_start=w[0], window_end=w[1], value=0.6,
                unit="index", quality="good", coverage_percent=100.0,
                image_count=4, state_kind="anomaly",
                state="ABOVE_BASELINE", provenance={},
            )
            for w in month_windows("2024-01-01", "2024-06-30")
        ]).months,
        analyze_thermal_metric(_source(LST_VALUES, "lst")),
        analyze_thermal_metric(_source(AIR_VALUES, "air")),
    ).to_dict()
    second = analyze_thermal_concordance(
        analyze_concordance([
            make_evidence(
                family="optical", metric_id="ndvi",
                window_start=w[0], window_end=w[1], value=0.6,
                unit="index", quality="good", coverage_percent=100.0,
                image_count=4, state_kind="anomaly",
                state="ABOVE_BASELINE", provenance={},
            )
            for w in month_windows("2024-01-01", "2024-06-30")
        ]).months,
        analyze_thermal_metric(_source(LST_VALUES, "lst")),
        analyze_thermal_metric(_source(AIR_VALUES, "air")),
    ).to_dict()
    assert json.loads(json.dumps(first)) == json.loads(json.dumps(second))
    model = ThermalConcordanceAnalysisModel.model_validate(first)
    assert ThermalConcordanceAnalysisModel.model_validate(
        model.model_dump()).model_dump() == model.model_dump()
