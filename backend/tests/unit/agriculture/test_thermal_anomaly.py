"""Tests for the P4.3 thermal anomaly and change analysis layer.

Locks the thin-adapter contract over P1.2/P1.3: independent LST and
ERA5 air-temperature baselines with reused mean/sample-std/min/max/
median, minimum-sample and near-zero-spread refusals, reused
z-scores and leave-one-out percentiles, neutral anomaly
categories, reused absolute/relative/per-day changes with
direction and rapid-change labels, one-month gap bridging with
longer-gap refusal, reused persistence semantics, strict source
separation (never pooled, no combined score, no canopy or stress
claims), provenance preservation, serialization round-trips, and
determinism.

Fixtures are P4.2 source profiles built directly in Python; the
statistics under test never touch Earth Engine. No network and no
credentials are required.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any, List, Optional

import pytest

from app.services.agriculture.baseline_anomaly import classify_z
from app.services.agriculture.change_profile import (
    classify_direction,
    classify_rapid,
)
from app.services.agriculture.thermal_anomaly import (
    SUPPORTED_THERMAL_ANOMALY_METRICS,
    ThermalMetricAnalysis,
    ThermalPairAnalysis,
    analyze_thermal_metric,
    analyze_thermal_pair,
    analyze_thermal_set,
    to_temporal_profile,
    usable_months,
)
from app.services.agriculture.thermal_profile import (
    AIR_METRIC_KEY,
    LST_METRIC_KEY,
    THERMAL_PROFILE_KIND_AIR,
    THERMAL_PROFILE_KIND_LST,
    ThermalProfilePoint,
    ThermalSourceProfile,
    month_windows,
)

LST_DATASET = "MODIS/061/MOD11A2"
LST_BAND = "LST_Day_1km"
AIR_DATASET = "ECMWF/ERA5_LAND/DAILY_AGGR"
AIR_BAND = "temperature_2m"

LST_SEASONAL = [
    20.0, 21.0, 22.5, 24.0, 26.0, 28.5,
    30.0, 29.5, 27.0, 24.5, 22.0, 20.5,
]
AIR_SEASONAL = [
    4.0, 5.0, 8.0, 12.0, 16.0, 20.0,
    22.0, 21.5, 18.0, 13.0, 8.5, 5.5,
]

ALLOWED_ANOMALY = {
    "NORMAL", "BELOW_BASELINE", "ABOVE_BASELINE", "INSUFFICIENT_BASELINE",
}
ALLOWED_DIRECTION = {"INCREASE", "DECREASE", "STABLE", "INSUFFICIENT"}
ALLOWED_RAPID = {
    "RAPID_INCREASE", "RAPID_DECREASE", "NOT_RAPID", "INSUFFICIENT",
}
ALLOWED_PERSISTENCE = {"NO_PERSISTENCE", "PERSISTENT", "INSUFFICIENT"}


# --------------------------------------------------------------------------
# Fixture builders (P4.2 source profiles, no EE)
# --------------------------------------------------------------------------


def _point(
    window_start: str,
    window_end: str,
    value: Optional[float],
    dataset_id: str,
    band: str,
    physical_quantity: str,
    temporal_resolution: str,
) -> ThermalProfilePoint:
    return ThermalProfilePoint(
        window_start=window_start,
        window_end=window_end,
        value=value,
        unit="degC",
        quality="good",
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
    kind: str = "lst",
    end_date: Optional[str] = None,
) -> ThermalSourceProfile:
    if kind == "lst":
        dataset_id, band = LST_DATASET, LST_BAND
        quantity, label = (
            "land_surface_temperature",
            "land-surface / skin temperature",
        )
        basis, resolution = "product", "8 days"
        metric_key, profile_kind = LST_METRIC_KEY, THERMAL_PROFILE_KIND_LST
    else:
        dataset_id, band = AIR_DATASET, AIR_BAND
        quantity, label = "air_temperature_2m", "modelled 2 m air temperature"
        basis, resolution = "modelled", "daily"
        metric_key, profile_kind = AIR_METRIC_KEY, THERMAL_PROFILE_KIND_AIR
    windows = month_windows("2024-01-01", end_date or "2024-12-31")
    assert len(windows) == len(values)
    return ThermalSourceProfile(
        profile_kind=profile_kind,
        metric_key=metric_key,
        dataset_id=dataset_id,
        fallback_dataset_id=None,
        band=band,
        unit="degC",
        physical_quantity=quantity,
        physical_quantity_label=label,
        measurement_basis=basis,
        temporal_resolution=resolution,
        aggregation_method="time mean, then spatial mean",
        window_start=windows[0][0],
        window_end=windows[-1][1],
        limitations=(),
        points=tuple(
            _point(start, end, value, dataset_id, band, quantity, resolution)
            for (start, end), value in zip(windows, values)
        ),
    )


def _lst(values: List[Optional[float]], **kwargs) -> ThermalSourceProfile:
    return _source_profile(values, kind="lst", **kwargs)


def _air(values: List[Optional[float]], **kwargs) -> ThermalSourceProfile:
    return _source_profile(values, kind="air", **kwargs)


def _months(n: int) -> List[str]:
    end = f"2024-{n:02d}-28" if n == 2 else f"2024-{n:02d}-30"
    if n in (1, 3, 5, 7, 8, 10, 12):
        end = f"2024-{n:02d}-31"
    if n == 2:
        end = "2024-02-29"
    return [start for start, _ in month_windows("2024-01-01", end)]


# --------------------------------------------------------------------------
# Baseline / anomaly
# --------------------------------------------------------------------------


def test_lst_baseline_statistics_reuse_p12():
    analysis = analyze_thermal_metric(_lst(LST_SEASONAL))
    baseline = analysis.baseline
    assert baseline is not None
    assert baseline.metric_key == LST_METRIC_KEY
    assert baseline.strategy == "full_period"
    assert baseline.n_usable == 12
    assert baseline.n_observations == 12
    assert baseline.mean == pytest.approx(statistics.mean(LST_SEASONAL))
    assert baseline.std == pytest.approx(statistics.stdev(LST_SEASONAL))
    assert baseline.minimum == pytest.approx(min(LST_SEASONAL))
    assert baseline.maximum == pytest.approx(max(LST_SEASONAL))
    assert baseline.median == pytest.approx(statistics.median(LST_SEASONAL))


def test_era5_baseline_statistics_reuse_p12():
    analysis = analyze_thermal_metric(_air(AIR_SEASONAL))
    baseline = analysis.baseline
    assert baseline is not None
    assert baseline.metric_key == AIR_METRIC_KEY
    assert baseline.mean == pytest.approx(statistics.mean(AIR_SEASONAL))
    assert baseline.std == pytest.approx(statistics.stdev(AIR_SEASONAL))
    assert baseline.minimum == pytest.approx(min(AIR_SEASONAL))
    assert baseline.maximum == pytest.approx(max(AIR_SEASONAL))
    assert baseline.median == pytest.approx(statistics.median(AIR_SEASONAL))
    assert analysis.physical_quantity == "air_temperature_2m"
    assert analysis.measurement_basis == "modelled"


def test_baselines_are_independent_populations():
    pair = analyze_thermal_pair(_lst(LST_SEASONAL), _air(AIR_SEASONAL))
    assert pair.lst.baseline is not None
    assert pair.air.baseline is not None
    pooled = statistics.mean(LST_SEASONAL + AIR_SEASONAL)
    assert pair.lst.baseline.mean == pytest.approx(
        statistics.mean(LST_SEASONAL)
    )
    assert pair.air.baseline.mean == pytest.approx(
        statistics.mean(AIR_SEASONAL)
    )
    assert pair.lst.baseline.mean != pytest.approx(pooled)
    assert pair.air.baseline.mean != pytest.approx(pooled)
    assert pair.lst.baseline.mean != pytest.approx(pair.air.baseline.mean)


def test_spread_is_sample_std_not_population_std():
    analysis = analyze_thermal_metric(_lst(LST_SEASONAL))
    assert analysis.baseline is not None
    assert analysis.baseline.std == pytest.approx(
        statistics.stdev(LST_SEASONAL)
    )
    assert analysis.baseline.std != pytest.approx(
        statistics.pstdev(LST_SEASONAL)
    )


def test_minimum_baseline_sample_refused_with_reason():
    analysis = analyze_thermal_metric(
        _lst([10.0, 20.0], end_date="2024-02-29")
    )
    assert analysis.baseline is None
    assert analysis.baseline_refusal_reason == "insufficient_usable_months"
    assert analysis.anomalies.n_scored == 0
    for point in analysis.anomalies.points:
        assert point.z_score is None
        assert point.category == "INSUFFICIENT_BASELINE"


def test_near_zero_spread_refused_with_reason():
    analysis = analyze_thermal_metric(
        _lst([25.0] * 6, end_date="2024-06-30")
    )
    assert analysis.baseline is None
    assert analysis.baseline_refusal_reason == "near_zero_spread"
    assert analysis.anomalies.n_scored == 0
    assert all(
        point.z_score is None for point in analysis.anomalies.points
    )


def test_z_scores_reuse_standardized_anomaly():
    from app.services.agriculture.history import standardized_anomaly

    analysis = analyze_thermal_metric(
        _lst([10.0, 20.0, 30.0], end_date="2024-03-31")
    )
    assert analysis.baseline is not None
    mean, std = 20.0, statistics.stdev([10.0, 20.0, 30.0])
    for point, expected_value in zip(
        analysis.anomalies.points, [10.0, 20.0, 30.0]
    ):
        assert point.z_score == pytest.approx(
            standardized_anomaly(expected_value, mean, std)
        )
        assert point.z_score == pytest.approx((expected_value - mean) / std)
    assert [p.category for p in analysis.anomalies.points] == [
        "BELOW_BASELINE",
        "NORMAL",
        "ABOVE_BASELINE",
    ]


def test_percentile_reuse_with_rank_resolution_floor():
    analysis = analyze_thermal_metric(_lst(LST_SEASONAL))
    assert analysis.baseline is not None
    by_value = {p.value: p for p in analysis.anomalies.points}
    # Leave-one-out: the maximum ranks above every other month.
    assert by_value[30.0].percentile == pytest.approx(100.0)
    # ... and the minimum ranks above none.
    assert by_value[20.0].percentile == pytest.approx(0.0)


def test_leave_one_out_percentile_excludes_self():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 9.0]
    analysis = analyze_thermal_metric(
        _lst(values, end_date="2024-10-31")
    )
    assert analysis.baseline is not None
    nines = [
        p for p in analysis.anomalies.points if p.value == pytest.approx(9.0)
    ]
    assert len(nines) == 2
    # Nine others surround each 9: eight strictly below out of nine.
    for point in nines:
        assert point.percentile == pytest.approx(800.0 / 9.0)
    # A pooled self-inclusive rank would read 80.0 instead.
    assert nines[0].percentile != pytest.approx(80.0)


def test_anomaly_categories_are_neutral_p12_set():
    analysis = analyze_thermal_metric(
        _lst([10.0, 20.0, 30.0], end_date="2024-03-31")
    )
    categories = {p.category for p in analysis.anomalies.points}
    assert categories <= ALLOWED_ANOMALY
    assert categories == {"BELOW_BASELINE", "NORMAL", "ABOVE_BASELINE"}
    assert classify_z(0.0) == "NORMAL"


def test_missing_month_carries_no_anomaly():
    analysis = analyze_thermal_metric(
        _lst([10.0, None, 30.0, 40.0, 50.0], end_date="2024-05-31")
    )
    assert analysis.baseline is not None
    gap = analysis.anomalies.points[1]
    assert gap.value is None
    assert gap.z_score is None
    assert gap.percentile is None
    assert gap.category == "INSUFFICIENT_BASELINE"
    assert analysis.anomalies.n_scored == 4


def test_single_month_profile_records_refusal():
    analysis = analyze_thermal_metric(
        _lst([10.0], end_date="2024-01-31")
    )
    assert analysis.baseline is None
    assert analysis.baseline_refusal_reason == "insufficient_usable_months"
    payload = analysis.to_dict()
    assert payload["baseline"] is None
    assert payload["baseline_refusal_reason"] == (
        "insufficient_usable_months"
    )


# --------------------------------------------------------------------------
# Change
# --------------------------------------------------------------------------


def test_lst_absolute_change_and_predecessor():
    analysis = analyze_thermal_metric(_lst(LST_SEASONAL))
    changes = analysis.changes
    assert len(changes) == 12
    first, second = changes[0], changes[1]
    assert first.absolute_change is None
    assert first.direction == "INSUFFICIENT"
    assert second.absolute_change == pytest.approx(21.0 - 20.0)
    assert second.previous_window_start == "2024-01-01"
    assert second.previous_value == pytest.approx(20.0)
    assert second.value == pytest.approx(21.0)


def test_era5_absolute_change():
    analysis = analyze_thermal_metric(_air(AIR_SEASONAL))
    assert analysis.changes[1].absolute_change == pytest.approx(5.0 - 4.0)
    assert analysis.changes[1].previous_value == pytest.approx(4.0)


def test_relative_change_and_rate_per_day():
    analysis = analyze_thermal_metric(_lst(LST_SEASONAL))
    second = analysis.changes[1]
    assert second.relative_change == pytest.approx(1.0 / 20.0)
    # 2024-02-01 minus 2024-01-01 is 31 days.
    assert second.days_elapsed == 31
    assert second.rate_per_day == pytest.approx(1.0 / 31.0)


def test_zero_previous_value_refuses_relative_only():
    analysis = analyze_thermal_metric(
        _lst([0.0, 5.0, 7.0], end_date="2024-03-31")
    )
    second = analysis.changes[1]
    assert second.absolute_change == pytest.approx(5.0)
    assert second.relative_change is None
    assert second.direction == "INCREASE"
    assert second.rate_per_day == pytest.approx(5.0 / 31.0)


def test_direction_labels_follow_p13_spread_rule():
    analysis = analyze_thermal_metric(
        _lst([10.0, 30.0, 20.0, 20.5], end_date="2024-04-30")
    )
    assert [c.direction for c in analysis.changes] == [
        "INSUFFICIENT",
        "INCREASE",
        "DECREASE",
        "STABLE",
    ]


def test_rapid_change_labels_follow_p13_multiple():
    rising = analyze_thermal_metric(
        _lst([10.0, 10.0, 10.0, 10.0, 40.0], end_date="2024-05-31")
    )
    assert [c.rapid for c in rising.changes] == [
        "INSUFFICIENT",
        "NOT_RAPID",
        "NOT_RAPID",
        "NOT_RAPID",
        "RAPID_INCREASE",
    ]
    falling = analyze_thermal_metric(
        _lst([40.0, 10.0, 10.0, 10.0, 10.0], end_date="2024-05-31")
    )
    assert falling.changes[1].rapid == "RAPID_DECREASE"
    assert falling.changes[1].direction == "DECREASE"


def test_reference_spread_matches_baseline_std():
    analysis = analyze_thermal_metric(_lst(LST_SEASONAL))
    assert analysis.baseline is not None
    spread = analysis.baseline.std
    for change in analysis.changes:
        assert change.direction == classify_direction(
            change.absolute_change, spread
        )
        assert change.rapid == classify_rapid(
            change.absolute_change, spread
        )


def test_one_month_gap_is_bridged():
    analysis = analyze_thermal_metric(
        _lst([10.0, None, 14.0, 16.0], end_date="2024-04-30")
    )
    changes = analysis.changes
    assert changes[1].absolute_change is None
    assert changes[1].direction == "INSUFFICIENT"
    assert changes[2].absolute_change == pytest.approx(4.0)
    assert changes[2].previous_window_start == "2024-01-01"
    assert changes[3].absolute_change == pytest.approx(2.0)
    assert changes[3].previous_window_start == "2024-03-01"


def test_longer_gap_refuses_change():
    analysis = analyze_thermal_metric(
        _lst([10.0, None, None, 16.0], end_date="2024-04-30")
    )
    last = analysis.changes[3]
    assert last.absolute_change is None
    assert last.relative_change is None
    assert last.rate_per_day is None
    assert last.direction == "INSUFFICIENT"
    assert last.rapid == "INSUFFICIENT"


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_persistence_reuse_over_z_scores():
    analysis = analyze_thermal_metric(
        _lst([0.0, 0.0, 0.0, 10.0, 10.0, 10.0], end_date="2024-06-30")
    )
    persistence = analysis.persistence
    assert persistence.longest_run_below == 3
    assert persistence.longest_run_above == 3
    assert persistence.n_anomalous == 6
    assert persistence.n_observed == 6
    assert persistence.state == "PERSISTENT"


def test_minimum_run_below_threshold_is_not_persistent():
    analysis = analyze_thermal_metric(
        _lst([10.0, 20.0, 30.0], end_date="2024-03-31")
    )
    persistence = analysis.persistence
    assert persistence.longest_run_below == 1
    assert persistence.longest_run_above == 1
    assert persistence.n_anomalous == 2
    assert persistence.state == "NO_PERSISTENCE"


def test_gap_breaks_persistence_runs():
    analysis = analyze_thermal_metric(
        _lst([20.0, 22.0, None, 22.0, 22.0], end_date="2024-05-31")
    )
    persistence = analysis.persistence
    # Without the gap the above-baseline run would reach four; the
    # missing month splits it into runs of one and two.
    assert persistence.longest_run_above == 2
    assert persistence.n_missing == 1
    assert persistence.state == "NO_PERSISTENCE"


def test_exact_zero_tie_breaks_persistence_runs():
    analysis = analyze_thermal_metric(
        _lst([10.0, 20.0, 30.0], end_date="2024-03-31")
    )
    middle = analysis.anomalies.points[1]
    assert middle.z_score == pytest.approx(0.0)
    assert middle.category == "NORMAL"
    persistence = analysis.persistence
    assert persistence.longest_run_below == 1
    assert persistence.longest_run_above == 1
    assert persistence.n_anomalous == 2


# --------------------------------------------------------------------------
# Separation and scientific safeguards
# --------------------------------------------------------------------------


def test_pair_payload_holds_alignment_only():
    pair = analyze_thermal_pair(_lst(LST_SEASONAL), _air(AIR_SEASONAL))
    payload = pair.to_dict()
    assert set(payload) == {
        "lst",
        "air",
        "alignment",
        "alignment_method",
        "limitations",
    }
    assert payload["alignment"] == "calendar_month"
    assert pair.lst.baseline is not None and pair.air.baseline is not None
    assert pair.lst.baseline.mean != pytest.approx(pair.air.baseline.mean)


def test_no_generic_temperature_anomaly_identity():
    analysis = analyze_thermal_metric(_lst(LST_SEASONAL))
    payload = analysis.to_dict()

    def iter_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from iter_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from iter_keys(item)

    keys = set(iter_keys(payload))
    assert "temperature_anomaly" not in keys
    assert "temperature" not in keys
    assert "canopy_temperature" not in keys
    assert payload["profile_kind"] == THERMAL_PROFILE_KIND_LST
    assert payload["physical_quantity"] == "land_surface_temperature"
    for entry in payload["anomalies"] + payload["changes"]:
        assert entry["profile_kind"] == THERMAL_PROFILE_KIND_LST
        assert entry["physical_quantity"] == "land_surface_temperature"


def _non_limitation_strings(node: Any, in_limitations: bool = False):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _non_limitation_strings(
                value, in_limitations or key == "limitations"
            )
    elif isinstance(node, list):
        for item in node:
            yield from _non_limitation_strings(item, in_limitations)
    elif isinstance(node, str) and not in_limitations:
        yield node


def test_no_canopy_claims_outside_limitations():
    pair = analyze_thermal_pair(_lst(LST_SEASONAL), _air(AIR_SEASONAL))
    for side in (pair.lst.to_dict(), pair.air.to_dict()):
        text = " ".join(_non_limitation_strings(side)).lower()
        assert "canopy" not in text
        limitations = " ".join(side["limitations"])
        assert "NOT canopy temperature" in limitations or (
            "not canopy temperature" in limitations.lower()
        )


def test_no_stress_severity_or_thermal_labels():
    pair = analyze_thermal_pair(_lst(LST_SEASONAL), _air(AIR_SEASONAL))
    for side in (pair.lst.to_dict(), pair.air.to_dict()):
        blob = json.dumps(side).lower()
        for snippet in (
            "stress",
            "hot",
            "cold",
            "heat",
            "severe",
            "risk",
            "shock",
            "heat_wave",
            "heatwave",
        ):
            assert snippet not in blob, snippet
    assert {p.category for p in pair.lst.anomalies.points} <= ALLOWED_ANOMALY
    assert {c.direction for c in pair.lst.changes} <= ALLOWED_DIRECTION
    assert {c.rapid for c in pair.lst.changes} <= ALLOWED_RAPID


def test_no_biological_interpretation_anywhere():
    pair = analyze_thermal_pair(_lst(LST_SEASONAL), _air(AIR_SEASONAL))
    blob = json.dumps(pair.to_dict()).lower()
    for snippet in (
        "pest",
        "disease",
        "pathogen",
        "infection",
        "nutrient",
        "chlorosis",
        "water stress",
        "irrigation",
    ):
        assert snippet not in blob, snippet


def test_no_combined_score_and_no_breakpoint():
    pair = analyze_thermal_pair(_lst(LST_SEASONAL), _air(AIR_SEASONAL))
    payload = pair.to_dict()

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
        "risk",
        "probability",
        "severity",
        "breakpoint",
        "temperature",
    ):
        assert forbidden not in keys, forbidden
    assert pair.lst.persistence.state in ALLOWED_PERSISTENCE


def test_provenance_preserves_physical_quantity_and_methods():
    pair = analyze_thermal_pair(_lst(LST_SEASONAL), _air(AIR_SEASONAL))
    lst_payload, air_payload = pair.lst.to_dict(), pair.air.to_dict()
    assert lst_payload["dataset_id"] == LST_DATASET
    assert lst_payload["band"] == LST_BAND
    assert lst_payload["measurement_basis"] == "product"
    assert air_payload["dataset_id"] == AIR_DATASET
    assert air_payload["band"] == AIR_BAND
    assert air_payload["measurement_basis"] == "modelled"
    for entry in lst_payload["anomalies"][:2] + lst_payload["changes"][:2]:
        assert entry["thermal_provenance"]["source_dataset_id"] == (
            LST_DATASET
        )
        assert entry["unit"] == "degC"
    methods = lst_payload["methods"]
    assert "P1.2" in methods["baseline"] and "P1.2" in methods["anomaly"]
    assert "P1.3" in methods["change"] and "P1.3" in methods["persistence"]
    assert (
        "land-surface / skin temperature"
        in lst_payload["physical_quantity_label"]
    )
    assert "modelled 2 m air temperature" in air_payload[
        "physical_quantity_label"
    ]


def test_serialization_round_trip():
    pair = analyze_thermal_pair(_lst(LST_SEASONAL), _air(AIR_SEASONAL))
    blob = json.loads(json.dumps(pair.lst.to_dict()))
    rebuilt = ThermalMetricAnalysis.from_dict(blob)
    assert rebuilt.to_dict() == pair.lst.to_dict()
    pair_blob = json.loads(json.dumps(pair.to_dict()))
    rebuilt_pair = ThermalPairAnalysis.from_dict(pair_blob)
    assert rebuilt_pair.to_dict() == pair.to_dict()


def test_repeated_evaluation_is_deterministic():
    first = analyze_thermal_pair(
        _lst(LST_SEASONAL), _air(AIR_SEASONAL)
    ).to_dict()
    second = analyze_thermal_pair(
        _lst(LST_SEASONAL), _air(AIR_SEASONAL)
    ).to_dict()
    assert first == second


# --------------------------------------------------------------------------
# Static and source safeguards
# --------------------------------------------------------------------------


def test_no_duplicated_p12_p13_formulas():
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "services"
        / "agriculture"
        / "thermal_anomaly.py"
    )
    code = re.sub(
        r'""".*?"""', "", path.read_text(encoding="utf-8"), flags=re.DOTALL
    )
    for snippet in (
        "import numpy",
        "np.",
        "ddof",
        "def compute_baseline",
        "def standardized_anomaly",
        "def percentile_context",
        "def month_changes",
        "def compute_persistence",
        "def score_profile",
        "def analyze_changes",
        "canopy_temperature",
        "pest",
        "disease",
        "risk",
        "probability",
        "severity",
    ):
        assert snippet not in code, f"thermal_anomaly: {snippet!r}"
    # Reuse is by import, not by copy.
    assert "score_profile" in code
    assert "analyze_changes" in code


def test_no_hidden_thresholds_or_scores():
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "services"
        / "agriculture"
        / "thermal_anomaly.py"
    )
    code = re.sub(
        r'""".*?"""', "", path.read_text(encoding="utf-8"), flags=re.DOTALL
    )
    assert "2.0" not in code
    assert "0.1" not in code
    assert "RAPID_STD_MULTIPLE" not in code
    assert "FLAT_FRACTION" not in code
    assert "PERSISTENCE_MIN_RUN" not in code
    assert re.search(r"(?m)^[A-Z_]+\s*=\s*[\d.]", code) is None


def test_positive_affine_rescaling_keeps_all_verdicts():
    values = [20.0, 21.0, 22.5, 24.0, 26.0, 28.5, 30.0, 29.5]
    rescaled = [2.0 * value + 5.0 for value in values]
    kwargs = {"end_date": "2024-08-31"}
    plain = analyze_thermal_metric(_lst(values, **kwargs))
    scaled = analyze_thermal_metric(_lst(rescaled, **kwargs))
    assert plain.baseline is not None and scaled.baseline is not None
    # The baselines genuinely differ, so the test is non-vacuous.
    assert scaled.baseline.mean != pytest.approx(plain.baseline.mean)
    assert [p.category for p in plain.anomalies.points] == [
        p.category for p in scaled.anomalies.points
    ]
    assert [c.direction for c in plain.changes] == [
        c.direction for c in scaled.changes
    ]
    assert [c.rapid for c in plain.changes] == [
        c.rapid for c in scaled.changes
    ]
    assert plain.persistence.state == scaled.persistence.state


# --------------------------------------------------------------------------
# Adapter and contract guards
# --------------------------------------------------------------------------


def test_to_temporal_profile_passes_observations_through():
    source = _lst(LST_SEASONAL)
    adapted = to_temporal_profile(source)
    assert adapted.metric_key == LST_METRIC_KEY
    assert adapted.dataset_id == LST_DATASET
    assert adapted.unit == "degC"
    assert adapted.window_start == source.window_start
    assert adapted.window_end == source.window_end
    assert adapted.n_points == source.n_points
    for origin, adapted_point in zip(source.points, adapted.points):
        assert adapted_point.window_start == origin.window_start
        assert adapted_point.window_end == origin.window_end
        assert adapted_point.value == origin.value
        assert adapted_point.unit == origin.unit
        assert adapted_point.quality == origin.quality
        assert adapted_point.coverage_percent == origin.coverage_percent
        assert adapted_point.image_count == origin.image_count


def test_unsupported_metrics_refused_without_substitution():
    source = _lst(LST_SEASONAL)
    foreign = ThermalSourceProfile(
        profile_kind="OTHER",
        metric_key="ndvi",
        dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        fallback_dataset_id=None,
        band="B8",
        unit="index",
        physical_quantity="ndvi",
        physical_quantity_label="vegetation index",
        measurement_basis="derived",
        temporal_resolution="5 days",
        aggregation_method="time mean, then spatial mean",
        window_start=source.window_start,
        window_end=source.window_end,
        limitations=(),
        points=source.points,
    )
    with pytest.raises(ValueError):
        to_temporal_profile(foreign)
    with pytest.raises(ValueError):
        analyze_thermal_metric(foreign)
    with pytest.raises(ValueError):
        analyze_thermal_set([source, foreign])
    lst = _lst(LST_SEASONAL)
    air = _air(AIR_SEASONAL)
    with pytest.raises(ValueError):
        analyze_thermal_pair(air, lst)
    with pytest.raises(ValueError):
        analyze_thermal_pair(air, air)
    assert set(SUPPORTED_THERMAL_ANOMALY_METRICS) == {
        LST_METRIC_KEY,
        AIR_METRIC_KEY,
    }


def test_usable_months_hook_and_set_analysis():
    source = _lst([10.0, None, 30.0, 40.0, 50.0], end_date="2024-05-31")
    analysis = analyze_thermal_metric(source)
    assert usable_months(analysis) == [10.0, 30.0, 40.0, 50.0]
    pair = analyze_thermal_set([source, _air(AIR_SEASONAL)])
    assert [item.metric_key for item in pair] == [
        LST_METRIC_KEY,
        AIR_METRIC_KEY,
    ]


def test_month_helper_produces_exact_calendar_windows():
    assert _months(3) == ["2024-01-01", "2024-02-01", "2024-03-01"]
