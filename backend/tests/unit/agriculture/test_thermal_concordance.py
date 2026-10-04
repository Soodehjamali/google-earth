"""Tests for the P4.4 thermal context concordance layer.

Locks the additive contract over P2.5 and P4.3: thermal orientation
from established P4.3 states, exact source roles (MODIS LST as
remote-sensing observation, ERA5 as modelled meteorological
context), same-month LST/optical/radar relationships, separate
ERA5 context relationships, exact-window matching, P2.5 reuse
without recomputation or double-counting, missing/quality
semantics, provenance, determinism, serialization, and the
no-score/no-biology/no-threshold safeguards.

P2.5 months are built with the real ``make_evidence`` /
``analyze_concordance`` and consumed verbatim; P4.3 analyses are
built from direct source-profile fixtures. Nothing touches Earth
Engine. No network and no credentials are required.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.services.agriculture.concordance import (
    CONCORDANCE_RULE_ID,
    analyze_concordance,
    make_evidence,
)
from app.services.agriculture.thermal_anomaly import analyze_thermal_metric
from app.services.agriculture.thermal_concordance import (
    AGREEMENT_OPPOSITE,
    AGREEMENT_SAME,
    AIR_CONCORDANT,
    AIR_DIVERGENT,
    AIR_ONLY,
    LST_CONCORDANT,
    LST_DIVERGENT,
    LST_MIXED,
    LST_ONLY,
    RELATIONSHIP_INSUFFICIENT,
    SOURCE_ROLE_AIR,
    SOURCE_ROLE_LST,
    THERMAL_CONCORDANCE_RULE_ID,
    ThermalConcordanceAnalysis,
    ThermalConcordanceMonth,
    ThermalSideEvidence,
    analyze_thermal_concordance,
    side_evidence,
    thermal_orientation,
)
from app.services.agriculture.thermal_profile import (
    AIR_METRIC_KEY,
    LST_METRIC_KEY,
    ThermalProfilePoint,
    ThermalSourceProfile,
    month_windows,
)

LST_DATASET = "MODIS/061/MOD11A2"
LST_BAND = "LST_Day_1km"
AIR_DATASET = "ECMWF/ERA5_LAND/DAILY_AGGR"
AIR_BAND = "temperature_2m"

JAN = ("2024-01-01", "2024-01-31")
FEB = ("2024-02-01", "2024-02-29")
MAR = ("2024-03-01", "2024-03-31")


# --------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------


def _point(
    window: tuple,
    value: Optional[float],
    dataset_id: str,
    band: str,
    physical_quantity: str,
    temporal_resolution: str,
    quality: str = "good",
) -> ThermalProfilePoint:
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
        physical_quantity=physical_quantity,
        aggregation_method="time mean, then spatial mean",
        temporal_resolution=temporal_resolution,
        provenance={
            "source_dataset_id": dataset_id,
            "bands": [band],
            "formula": "celsius = kelvin - 273.15",
            "unit": "degC",
            "image_count": 6,
        },
    )


def _source_profile(
    values: List[Optional[float]],
    kind: str,
    windows: List[tuple],
    quality: str = "good",
) -> ThermalSourceProfile:
    if kind == "lst":
        dataset_id, band = LST_DATASET, LST_BAND
        quantity = "land_surface_temperature"
        basis, resolution = "product", "8 days"
        metric_key, profile_kind = LST_METRIC_KEY, "LST_PROFILE"
    else:
        dataset_id, band = AIR_DATASET, AIR_BAND
        quantity = "air_temperature_2m"
        basis, resolution = "modelled", "daily"
        metric_key, profile_kind = AIR_METRIC_KEY, "AIR_TEMPERATURE_PROFILE"
    assert len(windows) == len(values)
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
        temporal_resolution=resolution,
        aggregation_method="time mean, then spatial mean",
        window_start=windows[0][0],
        window_end=windows[-1][1],
        limitations=(),
        points=tuple(
            _point(w, v, dataset_id, band, quantity, resolution, quality)
            for w, v in zip(windows, values)
        ),
    )


def _q1(values: List[Optional[float]], kind: str = "lst",
         quality: str = "good") -> ThermalSourceProfile:
    return _source_profile(values, kind, [JAN, FEB, MAR], quality)


def _p25(specs: List[tuple]):
    """Build real P2.5 months from (family, metric, window, value, state)."""
    items = [
        make_evidence(
            family=family,
            metric_id=metric_id,
            window_start=window[0],
            window_end=window[1],
            value=value,
            unit="index" if family == "optical" else "dB",
            quality="good",
            coverage_percent=100.0,
            image_count=4,
            state_kind="anomaly",
            state=state,
            provenance={"family": family, "metric_id": metric_id},
        )
        for family, metric_id, window, value, state in specs
    ]
    return analyze_concordance(items).months


def _up_optical_radar(window: tuple):
    return [
        ("optical", "ndvi", window, 0.6, "ABOVE_BASELINE"),
        ("radar", "vv", window, -8.0, "ABOVE_BASELINE"),
    ]


def _down_optical_radar(window: tuple):
    return [
        ("optical", "ndvi", window, 0.3, "BELOW_BASELINE"),
        ("radar", "vv", window, -12.0, "BELOW_BASELINE"),
    ]


# --------------------------------------------------------------------------
# Orientation from P4.3 states
# --------------------------------------------------------------------------


def test_lst_orientation_from_anomaly_categories():
    analysis = analyze_thermal_metric(_q1([10.0, 20.0, 30.0]))
    oriented = {
        item.window_start: item for item in side_evidence(analysis)
    }
    assert oriented["2024-01-01"].orientation == "DOWN"
    assert oriented["2024-01-01"].orientation_source == "anomaly"
    assert oriented["2024-01-01"].source_state == "BELOW_BASELINE"
    assert oriented["2024-02-01"].orientation == "NEUTRAL"
    assert oriented["2024-03-01"].orientation == "UP"
    assert oriented["2024-03-01"].source_state == "ABOVE_BASELINE"


def test_lst_orientation_from_change_fallback():
    # Two usable months refuse the baseline; February still carries
    # a P1.3 change direction, January carries none.
    analysis = analyze_thermal_metric(
        _source_profile([10.0, 20.0], "lst", [JAN, FEB])
    )
    assert analysis.baseline is None
    oriented = {
        item.window_start: item for item in side_evidence(analysis)
    }
    assert oriented["2024-01-01"].orientation == "INSUFFICIENT"
    assert oriented["2024-02-01"].orientation == "UP"
    assert oriented["2024-02-01"].orientation_source == "change"
    assert oriented["2024-02-01"].source_state == "INCREASE"


def test_era5_orientation_with_context_role():
    analysis = analyze_thermal_metric(_q1([30.0, 20.0, 10.0], kind="air"))
    oriented = {
        item.window_start: item for item in side_evidence(analysis)
    }
    assert oriented["2024-01-01"].orientation == "UP"
    assert oriented["2024-03-01"].orientation == "DOWN"
    for item in oriented.values():
        assert item.source_role == SOURCE_ROLE_AIR
        assert item.physical_quantity == "air_temperature_2m"
        assert item.metric_id == AIR_METRIC_KEY
        assert item.dataset_id == AIR_DATASET


def test_physical_quantity_identity_preserved():
    lst = analyze_thermal_metric(_q1([10.0, 20.0, 30.0]))
    air = analyze_thermal_metric(_q1([30.0, 20.0, 10.0], kind="air"))
    lst_item = thermal_orientation(lst, "2024-03-01")
    air_item = thermal_orientation(air, "2024-03-01")
    assert lst_item.physical_quantity == "land_surface_temperature"
    assert lst_item.dataset_id == LST_DATASET
    assert lst_item.band == LST_BAND
    assert lst_item.metric_id == LST_METRIC_KEY
    assert air_item.physical_quantity == "air_temperature_2m"
    assert air_item.value == pytest.approx(10.0)
    assert lst_item.value == pytest.approx(30.0)


def test_source_role_identity_is_exact():
    lst = analyze_thermal_metric(_q1([10.0, 20.0, 30.0]))
    air = analyze_thermal_metric(_q1([30.0, 20.0, 10.0], kind="air"))
    assert SOURCE_ROLE_LST == "REMOTE_SENSING_LAND_SURFACE"
    assert SOURCE_ROLE_AIR == "METEOROLOGICAL_CONTEXT"
    assert thermal_orientation(lst, "2024-01-01").source_role == (
        SOURCE_ROLE_LST
    )
    assert thermal_orientation(air, "2024-01-01").source_role == (
        SOURCE_ROLE_AIR
    )


# --------------------------------------------------------------------------
# LST relationships with optical/radar evidence
# --------------------------------------------------------------------------


def test_lst_optical_agreement_is_concordant():
    months = _p25([("optical", "ndvi", JAN, 0.6, "ABOVE_BASELINE")])
    assert months[0].state == "OPTICAL_ONLY"
    result = analyze_thermal_concordance(
        months, analyze_thermal_metric(_q1([30.0, 20.0, 10.0])), None
    )
    month = result.months[0]
    assert month.lst_relationship == LST_CONCORDANT == "THERMAL_CONCORDANT"
    assert month.optical_orientation == "UP"
    assert "aligned" in " ".join(month.explanations)


def test_lst_radar_agreement_is_concordant():
    months = _p25([("radar", "vv", JAN, -8.0, "ABOVE_BASELINE")])
    assert months[0].state == "RADAR_ONLY"
    result = analyze_thermal_concordance(
        months, analyze_thermal_metric(_q1([30.0, 20.0, 10.0])), None
    )
    assert result.months[0].lst_relationship == LST_CONCORDANT
    assert result.months[0].radar_orientation == "UP"


def test_lst_divergence_against_down_evidence():
    months = _p25(_down_optical_radar(JAN))
    result = analyze_thermal_concordance(
        months, analyze_thermal_metric(_q1([10.0, 20.0, 30.0])), None
    )
    # January LST reads DOWN while optical and radar read DOWN.
    january = next(
        m for m in result.months if m.window_start == "2024-01-01"
    )
    assert january.lst is not None and january.lst.orientation == "DOWN"
    assert january.lst_relationship == LST_CONCORDANT
    # March LST reads UP against DOWN externals: divergent.
    up_result = analyze_thermal_concordance(
        _p25(_down_optical_radar(MAR)),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        None,
    )
    march = next(
        m for m in up_result.months if m.window_start == "2024-03-01"
    )
    assert march.lst_relationship == LST_DIVERGENT


def test_lst_mixed_evidence_cases():
    # Optical UP against radar DOWN with LST UP: partly aligned.
    months = _p25(
        [
            ("optical", "ndvi", JAN, 0.6, "ABOVE_BASELINE"),
            ("radar", "vv", JAN, -12.0, "BELOW_BASELINE"),
        ]
    )
    assert months[0].state == "DIVERGENT"
    result = analyze_thermal_concordance(
        months, analyze_thermal_metric(_q1([10.0, 20.0, 30.0])), None
    )
    january = next(
        m for m in result.months if m.window_start == "2024-01-01"
    )
    assert january.lst is not None and january.lst.orientation == "DOWN"
    # LST DOWN matches radar DOWN but opposes optical UP.
    assert january.lst_relationship == "THERMAL_MIXED_EVIDENCE"
    # LST UP against all-NEUTRAL externals is neither aligned nor
    # opposing, hence mixed.
    neutral = _p25(
        [
            ("optical", "ndvi", MAR, 0.5, "NORMAL"),
            ("radar", "vv", MAR, -10.0, "NORMAL"),
        ]
    )
    neutral_result = analyze_thermal_concordance(
        neutral, analyze_thermal_metric(_q1([10.0, 20.0, 30.0])), None
    )
    neutral_march = next(
        m for m in neutral_result.months if m.window_start == "2024-03-01"
    )
    assert neutral_march.lst_relationship == LST_MIXED


# --------------------------------------------------------------------------
# ERA5 meteorological context
# --------------------------------------------------------------------------


def test_era5_context_agreement_names_model_status():
    months = _p25(_up_optical_radar(JAN))
    result = analyze_thermal_concordance(
        months, None, analyze_thermal_metric(_q1([10.0, 20.0, 30.0],
                                                kind="air"))
    )
    january = next(
        m for m in result.months if m.window_start == "2024-01-01"
    )
    # Air [10,20,30]: January reads BELOW (DOWN) while externals
    # read UP, so January diverges; agreement naming is checked
    # on a matching fixture below.
    assert january.air_relationship == "THERMAL_CONTEXT_DIVERGENT"
    matching = analyze_thermal_concordance(
        _p25(_down_optical_radar(JAN)),
        None,
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0], kind="air")),
    )
    matched = next(
        m for m in matching.months if m.window_start == "2024-01-01"
    )
    assert matched.air_relationship == AIR_CONCORDANT == (
        "THERMAL_CONTEXT_CONCORDANT"
    )
    text = " ".join(matched.explanations)
    assert "modelled 2 m air temperature" in text
    assert "not an independent satellite observation" in text


def test_era5_context_divergence():
    months = _p25(_down_optical_radar(MAR))
    result = analyze_thermal_concordance(
        months, None, analyze_thermal_metric(_q1([30.0, 20.0, 10.0],
                                                kind="air"))
    )
    # March air reads BELOW while externals read BELOW too; use
    # January (air UP) for the divergent check via a JAN fixture.
    jan_months = _p25(_down_optical_radar(JAN))
    jan_result = analyze_thermal_concordance(
        jan_months, None,
        analyze_thermal_metric(_q1([30.0, 20.0, 10.0], kind="air")),
    )
    january = next(
        m for m in jan_result.months if m.window_start == "2024-01-01"
    )
    assert january.air is not None and january.air.orientation == "UP"
    assert january.air_relationship == AIR_DIVERGENT
    march = next(
        m for m in result.months if m.window_start == "2024-03-01"
    )
    assert march.air_relationship == AIR_CONCORDANT


def test_era5_never_counted_as_satellite_sensor():
    months = _p25(_up_optical_radar(JAN))
    result = analyze_thermal_concordance(
        months,
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0], kind="air")),
    )
    january = next(
        m for m in result.months if m.window_start == "2024-01-01"
    )
    # S2 + S1 + LST are the three observational sources; ERA5 is
    # present as context and counted nowhere.
    assert january.observational_sensor_count == 3
    assert january.meteorological_context_present is True
    assert "not an independent satellite observation" in " ".join(
        january.explanations
    )


# --------------------------------------------------------------------------
# LST/ERA5 separation
# --------------------------------------------------------------------------


def test_lst_and_era5_orient_independently():
    months = _p25(_down_optical_radar(JAN))
    result = analyze_thermal_concordance(
        months,
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        analyze_thermal_metric(_q1([30.0, 20.0, 10.0], kind="air")),
    )
    january = next(
        m for m in result.months if m.window_start == "2024-01-01"
    )
    assert january.lst is not None and january.lst.orientation == "DOWN"
    assert january.air is not None and january.air.orientation == "UP"
    assert january.lst_relationship == LST_CONCORDANT
    assert january.air_relationship == AIR_DIVERGENT
    assert january.lst_era5_agreement == AGREEMENT_OPPOSITE


def test_no_lst_air_subtraction_or_differential():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(JAN)),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        analyze_thermal_metric(_q1([30.0, 20.0, 10.0], kind="air")),
    )
    payload = result.to_dict()

    def iter_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from iter_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from iter_keys(item)

    keys = set(iter_keys(payload))
    for forbidden in (
        "differential",
        "difference",
        "lst_minus_air",
        "delta",
        "canopy_temperature",
        "temperature",
    ):
        assert forbidden not in keys, forbidden


def test_no_canopy_temperature_field_or_claim():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(JAN)),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        analyze_thermal_metric(_q1([30.0, 20.0, 10.0], kind="air")),
    )
    blob = json.dumps(result.to_dict())

    def iter_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from iter_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from iter_keys(item)

    assert "canopy_temperature" not in set(iter_keys(result.to_dict()))
    assert "canopy temperature" not in blob.lower() or (
        "NOT canopy temperature" in blob
    )


# --------------------------------------------------------------------------
# P2.5 reuse without modification or double-counting
# --------------------------------------------------------------------------


def test_p25_state_preserved_verbatim_and_inputs_untouched():
    months = _p25(
        _up_optical_radar(JAN)
        + [
            ("optical", "ndvi", FEB, 0.6, "ABOVE_BASELINE"),
            ("radar", "vv", FEB, -12.0, "BELOW_BASELINE"),
        ]
    )
    before = [month.to_dict() for month in months]
    result = analyze_thermal_concordance(
        months, analyze_thermal_metric(_q1([10.0, 20.0, 30.0])), None
    )
    assert [month.to_dict() for month in months] == before
    by_start = {m.window_start: m for m in result.months}
    assert by_start["2024-01-01"].p25_state == "MULTI_SENSOR_CONCORDANT"
    assert by_start["2024-02-01"].p25_state == "DIVERGENT"
    assert by_start["2024-01-01"].p25_rule_id == CONCORDANCE_RULE_ID


def test_established_concordance_not_recounted():
    months = _p25(
        _up_optical_radar(JAN)
        + [("red_edge", "re_slope_b4_b5", JAN, 0.02, "ABOVE_BASELINE")]
    )
    assert months[0].state == "MULTI_SENSOR_CONCORDANT"
    result = analyze_thermal_concordance(
        months, analyze_thermal_metric(_q1([30.0, 20.0, 10.0])), None
    )
    march_free = [m for m in result.months if m.window_start == JAN[0]]
    assert len(march_free) == 1
    month = march_free[0]
    # S2 counts once despite optical + red-edge families; S1 once;
    # LST once. Red-edge is recorded, never promoted.
    assert month.observational_sensor_count == 3
    assert month.red_edge_orientation == "UP"
    assert month.lst_relationship == LST_CONCORDANT
    assert "restated unchanged" in " ".join(month.explanations)


def test_exact_window_matching_only():
    months = _p25(_up_optical_radar(JAN))
    result = analyze_thermal_concordance(
        months,
        analyze_thermal_metric(
            _source_profile([10.0, 20.0], "lst", [JAN, FEB])
        ),
        None,
    )
    by_start = {m.window_start: m for m in result.months}
    assert set(by_start) == {"2024-01-01", "2024-02-01"}
    # January pairs P2.5 UP with unusable thermal (first month, no
    # baseline, no change): insufficient, not a negative finding.
    assert by_start["2024-01-01"].lst_relationship == (
        RELATIONSHIP_INSUFFICIENT
    )
    # February carries usable thermal evidence (change-derived UP)
    # with no P2.5 month: thermal-only, nothing borrowed.
    assert by_start["2024-02-01"].lst_relationship == LST_ONLY
    assert by_start["2024-02-01"].lst is not None
    assert by_start["2024-02-01"].lst.orientation == "UP"


def test_adjacent_months_stay_independent():
    months = _p25(_up_optical_radar(JAN) + _up_optical_radar(FEB))
    result = analyze_thermal_concordance(
        months, analyze_thermal_metric(_q1([10.0, 20.0, 30.0])), None
    )
    by_start = {m.window_start: m for m in result.months}
    # January LST reads DOWN against UP externals; February LST
    # reads NORMAL against UP externals: independent verdicts.
    assert by_start["2024-01-01"].lst_relationship == LST_DIVERGENT
    assert by_start["2024-02-01"].lst_relationship == "THERMAL_MIXED_EVIDENCE"


# --------------------------------------------------------------------------
# Missing and quality semantics
# --------------------------------------------------------------------------


def test_missing_thermal_value_is_not_negative_evidence():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(FEB)),
        analyze_thermal_metric(_q1([10.0, None, 30.0])),
        None,
    )
    by_start = {m.window_start: m for m in result.months}
    assert by_start["2024-02-01"].lst_relationship == (
        RELATIONSHIP_INSUFFICIENT
    )
    assert by_start["2024-02-01"].lst is not None
    assert by_start["2024-02-01"].lst.orientation == "INSUFFICIENT"


def test_missing_p25_month_yields_thermal_only():
    result = analyze_thermal_concordance(
        [],
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0], kind="air")),
    )
    assert result.n_months == 3
    for month in result.months:
        assert month.p25_state is None
        assert month.lst_relationship == LST_ONLY
        assert month.air_relationship == AIR_ONLY
        assert "No P2.5 month exists" in " ".join(month.explanations)


def test_insufficient_single_month_thermal_profile():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(JAN)),
        analyze_thermal_metric(_source_profile([20.0], "lst", [JAN])),
        None,
    )
    month = result.months[0]
    assert month.lst is not None
    assert month.lst.orientation == "INSUFFICIENT"
    assert month.lst_relationship == RELATIONSHIP_INSUFFICIENT


def test_unavailable_quality_preserved_without_promotion():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(JAN)),
        analyze_thermal_metric(_q1([None, 20.0, 30.0],
                                  quality="unavailable")),
        None,
    )
    january = next(
        m for m in result.months if m.window_start == "2024-01-01"
    )
    assert january.lst is not None
    assert january.lst.quality == "unavailable"
    assert january.lst.orientation == "INSUFFICIENT"
    assert january.lst_relationship == RELATIONSHIP_INSUFFICIENT


def test_poor_but_usable_quality_propagates():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(MAR)),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0], quality="poor")),
        None,
    )
    march = next(
        m for m in result.months if m.window_start == "2024-03-01"
    )
    assert march.lst is not None
    assert march.lst.quality == "poor"
    assert march.lst.coverage_percent == pytest.approx(100.0)
    assert march.lst.orientation == "UP"
    assert march.lst_relationship == LST_CONCORDANT


# --------------------------------------------------------------------------
# Provenance, determinism, serialization
# --------------------------------------------------------------------------


def test_provenance_propagation_from_both_layers():
    months = _p25(_up_optical_radar(JAN))
    result = analyze_thermal_concordance(
        months, analyze_thermal_metric(_q1([10.0, 20.0, 30.0])), None
    )
    month = result.months[0]
    assert month.lst is not None
    assert month.lst.provenance["source_dataset_id"] == LST_DATASET
    assert month.optical_orientation == "UP"
    assert month.radar_orientation == "UP"
    assert month.p25_rule_id == CONCORDANCE_RULE_ID


def test_rule_and_method_provenance():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(JAN)),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        None,
    )
    assert result.rule_id == THERMAL_CONCORDANCE_RULE_ID
    assert result.months[0].rule_id == THERMAL_CONCORDANCE_RULE_ID
    payload = result.to_dict()
    assert payload["rule_id"] == "P44_THERMAL_CONCORDANCE_V1"
    assert payload["months"][0]["rule_id"] == (
        "P44_THERMAL_CONCORDANCE_V1"
    )
    assert "P2.5" in payload["methods"]["orientation"]
    assert "P4.3" in payload["methods"]["orientation"]


def test_repeated_evaluation_is_deterministic():
    kwargs = {
        "concordance_months": _p25(_up_optical_radar(JAN)),
        "lst_analysis": analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        "air_analysis": analyze_thermal_metric(
            _q1([30.0, 20.0, 10.0], kind="air")
        ),
    }
    assert analyze_thermal_concordance(**kwargs).to_dict() == (
        analyze_thermal_concordance(**kwargs).to_dict()
    )


def test_serialization_round_trip_with_roles():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(JAN)),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        analyze_thermal_metric(_q1([30.0, 20.0, 10.0], kind="air")),
    )
    blob = json.loads(json.dumps(result.to_dict()))
    rebuilt = ThermalConcordanceAnalysis.from_dict(blob)
    assert rebuilt.to_dict() == result.to_dict()
    month = ThermalConcordanceMonth.from_dict(blob["months"][0])
    assert month.lst is not None and month.air is not None
    assert month.lst.source_role == SOURCE_ROLE_LST
    assert month.air.source_role == SOURCE_ROLE_AIR
    side = ThermalSideEvidence.from_dict(month.lst.to_dict())
    assert side.to_dict() == month.lst.to_dict()


# --------------------------------------------------------------------------
# Safeguards: scores, biology, thresholds, raw access
# --------------------------------------------------------------------------


def test_no_score_confidence_or_ranking():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(JAN)),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        analyze_thermal_metric(_q1([30.0, 20.0, 10.0], kind="air")),
    )
    payload = result.to_dict()

    def iter_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from iter_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from iter_keys(item)

    keys = set(iter_keys(payload))
    for forbidden in (
        "score",
        "confidence",
        "risk",
        "probability",
        "severity",
        "priority",
        "winner",
        "ranking",
        "weight",
        "weights",
    ):
        assert forbidden not in keys, forbidden
    blob = json.dumps(payload).replace("score_profile", "method_ref")
    assert "score" not in blob.lower()
    assert "confidence" not in blob.lower()


def test_no_biological_interpretation():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(JAN)),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0])),
        analyze_thermal_metric(_q1([30.0, 20.0, 10.0], kind="air")),
    )
    blob = json.dumps(result.to_dict()).lower()
    for snippet in (
        "pest",
        "disease",
        "defoliation",
        "fungal",
        "nutrient",
        "drought",
        "stress",
        "heat",
        "cold",
    ):
        assert snippet not in blob, snippet
    limitations = " ".join(result.to_dict()["limitations"]).lower()
    assert "biological condition" in limitations


def test_no_new_threshold_in_module():
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "services"
        / "agriculture"
        / "thermal_concordance.py"
    )
    code = re.sub(
        r'""".*?"""', "", path.read_text(encoding="utf-8"), flags=re.DOTALL
    )
    assert "2.0" not in code
    assert "0.1" not in code
    assert "FLAT_FRACTION" not in code
    assert "RAPID_STD_MULTIPLE" not in code
    assert "threshold" not in code.lower()
    assert re.search(r"(?m)^[A-Z_]+\s*=\s*[\d.]+$", code) is None
    assert "def month_orientation" not in code
    assert "def analyze_concordance" not in code
    assert "def score_profile" not in code
    assert "def analyze_changes" not in code


def test_no_raw_gee_access_in_module():
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "services"
        / "agriculture"
        / "thermal_concordance.py"
    )
    code = re.sub(
        r'""".*?"""', "", path.read_text(encoding="utf-8"), flags=re.DOTALL
    )
    for snippet in (
        "import ee",
        "ImageCollection",
        "filterDate",
        "filterBounds",
        "reduceRegion",
        "getInfo",
        "aggregate_array",
    ):
        assert snippet not in code, f"thermal_concordance: {snippet!r}"


def test_mixed_evidence_selects_no_winner():
    months = _p25(
        [
            ("optical", "ndvi", JAN, 0.6, "ABOVE_BASELINE"),
            ("radar", "vv", JAN, -12.0, "BELOW_BASELINE"),
        ]
    )
    result = analyze_thermal_concordance(
        months, analyze_thermal_metric(_q1([10.0, 20.0, 30.0])), None
    )
    january = next(
        m for m in result.months if m.window_start == "2024-01-01"
    )
    assert january.lst_relationship == "THERMAL_MIXED_EVIDENCE"
    payload = january.to_dict()

    def iter_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from iter_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from iter_keys(item)

    keys = set(iter_keys(payload))
    assert not ({"winner", "ranking", "score"} & keys)
    assert january.optical_orientation == "UP"
    assert january.radar_orientation == "DOWN"
    assert "partly align and partly oppose" in " ".join(
        january.explanations
    )


def test_magnitude_perturbation_keeps_verdicts():
    values = [20.0, 21.0, 22.5, 24.0, 26.0, 28.5, 30.0, 29.5]
    windows = month_windows("2024-01-01", "2024-08-31")
    plain = analyze_thermal_metric(_source_profile(values, "lst", windows))
    scaled = analyze_thermal_metric(
        _source_profile([2.0 * v + 5.0 for v in values], "lst", windows)
    )
    specs = []
    for window in windows:
        specs.append(("optical", "ndvi", window, 0.6, "ABOVE_BASELINE"))
        specs.append(("radar", "vv", window, -8.0, "ABOVE_BASELINE"))
    months = _p25(specs)
    first = analyze_thermal_concordance(months, plain, None)
    second = analyze_thermal_concordance(months, scaled, None)
    assert [m.lst_relationship for m in first.months] == [
        m.lst_relationship for m in second.months
    ]
    assert [m.lst.orientation for m in first.months] == [
        m.lst.orientation for m in second.months
    ]


def test_summary_tallies_are_counts_not_scores():
    result = analyze_thermal_concordance(
        _p25(_up_optical_radar(JAN) + _down_optical_radar(FEB)),
        analyze_thermal_metric(_q1([30.0, 20.0, 10.0])),
        analyze_thermal_metric(_q1([10.0, 20.0, 30.0], kind="air")),
    )
    payload = result.to_dict()
    summary = payload["summary"]
    # January externals read UP: LST UP aligns, air DOWN opposes.
    # February externals read DOWN: LST NORMAL is mixed, air
    # NORMAL is mixed. March is thermal-only on both sides.
    assert summary["n_months"] == 3
    assert summary["n_lst_concordant"] == 1
    assert summary["n_lst_mixed"] == 1
    assert summary["n_lst_only"] == 1
    assert summary["n_air_divergent"] == 1
    assert summary["n_air_mixed"] == 1
    assert summary["n_air_only"] == 1
    assert isinstance(summary["n_lst_concordant"], int)
