"""Tests for the P1.2 baseline and standardized-anomaly engine.

All statistics run over hand-built temporal profiles, so no Earth
Engine fixture is needed: the engine consumes profiles, and P1.1
already proves profiles come out of real metrics.  Expected values
are hand-computed with the standard library, never with the engine
under test.
"""

from __future__ import annotations

import statistics
from typing import List, Optional

import pytest

from app.services.agriculture.baseline_anomaly import (
    CATEGORY_ABOVE_BASELINE,
    CATEGORY_BELOW_BASELINE,
    CATEGORY_INSUFFICIENT_BASELINE,
    CATEGORY_NORMAL,
    MIN_PROFILE_BASELINE_N,
    PROFILE_PERCENTILE_MIN_SAMPLES,
    AnomalyProfile,
    ProfileBaseline,
    build_baseline,
    classify_z,
    score_profile,
)
from app.services.agriculture.temporal_profile import (
    TemporalProfile,
    TemporalProfilePoint,
    usable_values,
)


def _months(
    values: List[Optional[float]],
    start_year: int = 2024,
    start_month: int = 1,
    unit: str = "index",
    quality: str = "good",
    coverage: float = 100.0,
    image_count: int = 6,
) -> List[TemporalProfilePoint]:
    points: List[TemporalProfilePoint] = []
    year, month = start_year, start_month
    for value in values:
        window_start = f"{year:04d}-{month:02d}-01"
        last_day = 30 if month in (4, 6, 9, 11) else 31
        if month == 2:
            last_day = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
        points.append(
            TemporalProfilePoint(
                window_start=window_start,
                window_end=f"{year:04d}-{month:02d}-{last_day:02d}",
                value=value,
                unit=unit,
                quality=quality if value is not None else "insufficient",
                coverage_percent=coverage if value is not None else None,
                image_count=image_count if value is not None else None,
            )
        )
        month += 1
        if month > 12:
            month = 1
            year += 1
    return points


def _profile(
    values: List[Optional[float]],
    metric_key: str = "ndvi",
    unit: str = "index",
    **kwargs: Any,
) -> TemporalProfile:
    points = _months(values, unit=unit, **kwargs)
    return TemporalProfile(
        metric_key=metric_key,
        dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        unit=unit,
        window_start=points[0].window_start,
        window_end=points[-1].window_end,
        points=tuple(points),
    )


# ==========================================================================
# Baseline statistics
# ==========================================================================


def test_valid_baseline_matches_hand_computation():
    values = [0.50, 0.60, 0.70, 0.80]
    baseline = build_baseline(_profile(values))
    assert isinstance(baseline, ProfileBaseline)
    assert baseline.metric_key == "ndvi"
    assert baseline.strategy == "full_period"
    assert baseline.n_observations == 4
    assert baseline.n_usable == 4
    assert baseline.mean == pytest.approx(statistics.mean(values))
    assert baseline.std == pytest.approx(statistics.stdev(values))
    assert baseline.minimum == pytest.approx(0.50)
    assert baseline.maximum == pytest.approx(0.80)
    assert baseline.median == pytest.approx(0.65)
    assert baseline.reference_start == "2024-01-01"
    assert baseline.reference_end == "2024-04-01"
    assert baseline.window_start == "2024-01-01"
    assert baseline.window_end == "2024-04-30"
    assert baseline.spread_reliable is True
    assert baseline.quality_counts == {"good": 4}
    assert baseline.mean_coverage_percent == pytest.approx(100.0)


def test_missing_months_lower_the_population_but_never_enter_it():
    baseline = build_baseline(_profile([0.50, None, 0.70, None, 0.90]))
    assert baseline is not None
    assert baseline.n_observations == 5
    assert baseline.n_usable == 3
    assert baseline.mean == pytest.approx((0.50 + 0.70 + 0.90) / 3)
    assert baseline.reference_start == "2024-01-01"
    assert baseline.reference_end == "2024-05-01"


def test_zero_is_a_real_observation_not_a_gap():
    baseline = build_baseline(_profile([0.0, 0.40, 0.80]))
    assert baseline is not None
    assert baseline.n_usable == 3
    assert baseline.mean == pytest.approx(0.40)
    assert baseline.minimum == pytest.approx(0.0)


def test_negative_values_work_end_to_end():
    values = [-12.5, -11.0, -13.0, -12.0]
    profile = _profile(values, metric_key="vh", unit="dB")
    baseline = build_baseline(profile)
    assert baseline is not None
    assert baseline.mean == pytest.approx(statistics.mean(values))
    assert baseline.std == pytest.approx(statistics.stdev(values))
    scored = score_profile(profile)
    assert scored.unit == "dB"
    assert scored.metric_key == "vh"
    for point in scored.points:
        assert point.z_score == pytest.approx(
            (point.value - baseline.mean) / baseline.std
        )


def test_non_finite_values_are_excluded():
    baseline = build_baseline(
        _profile([0.50, float("inf"), float("nan"), 0.70, 0.90])
    )
    assert baseline is not None
    assert baseline.n_usable == 3
    assert baseline.mean == pytest.approx((0.50 + 0.70 + 0.90) / 3)


# ==========================================================================
# Sufficiency refusals
# ==========================================================================


def test_no_usable_months_is_insufficient():
    assert build_baseline(_profile([None, None, None])) is None


def test_fewer_than_minimum_months_is_insufficient():
    assert MIN_PROFILE_BASELINE_N == 3
    assert build_baseline(_profile([0.50])) is None
    assert build_baseline(_profile([0.50, 0.60])) is None
    assert build_baseline(_profile([0.50, 0.60, 0.70])) is not None


def test_zero_variance_is_insufficient():
    assert build_baseline(_profile([0.50, 0.50, 0.50, 0.50])) is None


def test_near_zero_float_dust_is_insufficient_variance():
    # Ten identical monthly floats accumulate summation dust (~1e-16)
    # instead of an exact-zero spread; standardizing against it
    # would manufacture extreme z-scores out of noise.
    assert build_baseline(_profile([0.60] * 10)) is None
    assert build_baseline(_profile([0.30] * 10)) is None


def test_insufficient_baseline_scores_nothing():
    scored = score_profile(_profile([0.50, 0.60]))
    assert scored.baseline is None
    assert scored.n_scored == 0
    for point in scored.points:
        assert point.z_score is None
        assert point.percentile is None
        assert point.category == CATEGORY_INSUFFICIENT_BASELINE


def test_zero_variance_scores_nothing():
    scored = score_profile(_profile([0.40, 0.40, 0.40, 0.40]))
    assert scored.baseline is None
    assert all(p.category == CATEGORY_INSUFFICIENT_BASELINE for p in scored.points)


# ==========================================================================
# Z-scores and categories
# ==========================================================================


def test_z_scores_are_deterministic_and_hand_computed():
    values = [0.42, 0.55, 0.61, 0.48, 0.70]
    scored = score_profile(_profile(values))
    assert scored.baseline is not None
    mean = statistics.mean(values)
    std = statistics.stdev(values)
    for point, value in zip(scored.points, values):
        assert point.z_score == pytest.approx((value - mean) / std)


def test_below_above_and_normal_categories():
    scored = score_profile(_profile([0.40, 0.50, 0.60]))
    by_value = {point.value: point for point in scored.points}
    assert by_value[0.40].category == CATEGORY_BELOW_BASELINE
    assert by_value[0.60].category == CATEGORY_ABOVE_BASELINE
    assert by_value[0.50].category == CATEGORY_NORMAL
    assert by_value[0.50].z_score == pytest.approx(0.0)


def test_classify_z_unit_boundaries():
    assert classify_z(None) == CATEGORY_INSUFFICIENT_BASELINE
    assert classify_z(float("nan")) == CATEGORY_INSUFFICIENT_BASELINE
    assert classify_z(float("inf")) == CATEGORY_INSUFFICIENT_BASELINE
    assert classify_z(True) == CATEGORY_INSUFFICIENT_BASELINE
    assert classify_z(0.0) == CATEGORY_NORMAL
    assert classify_z(-0.001) == CATEGORY_BELOW_BASELINE
    assert classify_z(2.5) == CATEGORY_ABOVE_BASELINE


def test_missing_months_keep_insufficient_category_in_scored_output():
    scored = score_profile(_profile([0.40, None, 0.60, 0.50]))
    assert scored.baseline is not None
    missing = [p for p in scored.points if p.value is None]
    assert len(missing) == 1
    assert missing[0].category == CATEGORY_INSUFFICIENT_BASELINE
    assert missing[0].z_score is None


# ==========================================================================
# Percentiles
# ==========================================================================


def test_percentile_is_strict_less_rank_against_others():
    values = [float(v) for v in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]
    scored = score_profile(_profile(values))
    assert scored.baseline is not None
    target = next(p for p in scored.points if p.value == 5.0)
    # Four of the other nine reference months lie strictly below.
    assert target.percentile == pytest.approx(4.0 / 9.0 * 100.0)
    assert target.category == CATEGORY_BELOW_BASELINE


def test_percentile_refused_below_sample_floor():
    # Three usable months: enough for a baseline, but leave-one-out
    # leaves two reference months, below the rank-resolution floor.
    scored = score_profile(_profile([0.40, 0.50, 0.60]))
    assert scored.baseline is not None
    for point in scored.points:
        assert point.z_score is not None
        assert point.percentile is None


def test_percentile_refused_for_degenerate_reference():
    # Four equal months plus one odd month: baseline spread exists,
    # but ranking the odd month sees an all-equal population.
    scored = score_profile(
        _profile([0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.90])
    )
    assert scored.baseline is not None
    odd = next(p for p in scored.points if p.value == 0.90)
    assert odd.z_score is not None
    assert odd.percentile is None


# ==========================================================================
# Traceability: ordering, provenance, multiple metrics
# ==========================================================================


def test_temporal_ordering_is_preserved():
    scored = score_profile(_profile([0.61, 0.42, 0.70, 0.48, 0.55]))
    starts = [point.window_start for point in scored.points]
    assert starts == sorted(starts)
    assert [point.value for point in scored.points] == [
        pytest.approx(v) for v in (0.61, 0.42, 0.70, 0.48, 0.55)
    ]


def test_provenance_fields_pass_through_untouched():
    profile = _profile(
        [0.50, 0.60, 0.70],
        metric_key="vv",
        unit="dB",
        quality="moderate",
        coverage=83.5,
        image_count=3,
    )
    scored = score_profile(profile)
    assert scored.metric_key == "vv"
    for point in scored.points:
        assert point.unit == "dB"
        assert point.quality == "moderate"
        assert point.coverage_percent == pytest.approx(83.5)
        assert point.image_count == 3


def test_multiple_metrics_score_independently():
    optical = score_profile(_profile([0.50, 0.60, 0.70, 0.80]))
    radar = score_profile(
        _profile([-12.0, -11.0, -13.0, -10.5], metric_key="vh", unit="dB")
    )
    assert optical.baseline is not None and radar.baseline is not None
    assert optical.baseline.mean != pytest.approx(radar.baseline.mean)
    assert optical.points[0].category == CATEGORY_BELOW_BASELINE
    assert radar.points[0].category == CATEGORY_BELOW_BASELINE
    assert optical.unit == "index" and radar.unit == "dB"


# ==========================================================================
# Contract round-trip
# ==========================================================================


def test_to_dict_round_trips_through_the_api_contract_models():
    from app.schemas.agriculture import AnomalyProfileModel, ProfileBaselineModel

    scored = score_profile(_profile([0.42, 0.55, 0.61, 0.48, 0.70]))
    assert scored.baseline is not None
    baseline_model = ProfileBaselineModel(**scored.baseline.to_dict())
    assert baseline_model.metric_key == "ndvi"
    assert baseline_model.n_usable == 5
    assert baseline_model.std == pytest.approx(scored.baseline.std)
    model = AnomalyProfileModel(**scored.to_dict())
    assert model.metric_key == "ndvi"
    assert len(model.points) == 5
    assert model.baseline is not None
    assert model.baseline.mean == pytest.approx(scored.baseline.mean)
    assert model.points[0].category in (
        CATEGORY_NORMAL,
        CATEGORY_BELOW_BASELINE,
        CATEGORY_ABOVE_BASELINE,
        CATEGORY_INSUFFICIENT_BASELINE,
    )


def test_insufficient_profile_round_trips_with_null_baseline():
    from app.schemas.agriculture import AnomalyProfileModel

    scored = score_profile(_profile([0.50]))
    model = AnomalyProfileModel(**scored.to_dict())
    assert model.baseline is None
    assert model.points[0].z_score is None
    assert model.points[0].category == CATEGORY_INSUFFICIENT_BASELINE


# ==========================================================================
# Scientific-contract guards
# ==========================================================================


def test_engine_states_no_cause_without_encoding_any():
    import app.services.agriculture.baseline_anomaly as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "does NOT identify the cause" in source
    # Denial prose is required ("no risk scores"); what must never
    # appear is an implementation of one: identifiers, models, or
    # training machinery.
    for token in (
        "risk_score",
        "severity_level",
        "pest_risk",
        "probability_of",
        "machine learning",
        "sklearn",
        "torch",
        "tensorflow",
        "training data",
    ):
        assert token not in source.lower(), token


def test_module_touches_no_database_or_network():
    import app.services.agriculture.baseline_anomaly as module

    source = open(module.__file__, encoding="utf-8").read().lower()
    for token in ("sqlite", "postgres", "sqlalchemy", "requests.get", "urllib"):
        assert token not in source, token
