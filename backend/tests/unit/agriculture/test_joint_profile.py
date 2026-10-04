"""Tests for the P1.4 NDVI-moisture joint temporal analysis.

Profiles are built directly (P1.1 proves they come out of real
metrics); anomalies and changes come from the pure P1.2/P1.3
engines.  No Earth Engine fixture is needed.  Expected numbers are
hand-computed inline, never with the engine under test.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from app.services.agriculture.baseline_anomaly import score_profile
from app.services.agriculture.change_profile import analyze_changes
from app.services.agriculture.joint_profile import (
    MIN_CORRELATION_PAIRS,
    MIN_LAG_PAIRS,
    NDVI_KEY,
    SUPPORTED_MOISTURE_KEYS,
    align_profiles,
    analyze_joint,
    divergence_of,
    joint_anomaly_state,
    lead_lag_analysis,
    pearson_correlation,
    scatter_dataset,
)
from app.services.agriculture.temporal_profile import (
    TemporalProfile,
    TemporalProfilePoint,
)


def _months(
    values: List[Optional[float]],
    start_year: int = 2024,
    start_month: int = 1,
    unit: str = "index",
    quality: str = "good",
) -> List[TemporalProfilePoint]:
    points: List[TemporalProfilePoint] = []
    year, month = start_year, start_month
    for value in values:
        window_start = f"{year:04d}-{month:02d}-01"
        last_day = 30 if month in (4, 6, 9, 11) else 31
        if month == 2:
            leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
            last_day = 29 if leap else 28
        points.append(
            TemporalProfilePoint(
                window_start=window_start,
                window_end=f"{year:04d}-{month:02d}-{last_day:02d}",
                value=value,
                unit=unit,
                quality=quality if value is not None else "insufficient",
                coverage_percent=100.0 if value is not None else None,
                image_count=6 if value is not None else None,
            )
        )
        month += 1
        if month > 12:
            month = 1
            year += 1
    return points


def _profile(
    key: str,
    values: List[Optional[float]],
    unit: str = "index",
    **kwargs,
) -> TemporalProfile:
    points = _months(values, unit=unit, **kwargs)
    dataset = (
        "COPERNICUS/S1_GRD" if unit == "dB" else "COPERNICUS/S2_SR_HARMONIZED"
    )
    return TemporalProfile(
        metric_key=key,
        dataset_id=dataset,
        unit=unit,
        window_start=points[0].window_start,
        window_end=points[-1].window_end,
        points=tuple(points),
    )


def _ndvi(values: List[Optional[float]], **kwargs) -> TemporalProfile:
    return _profile("ndvi", values, **kwargs)


def _ndmi(values: List[Optional[float]], **kwargs) -> TemporalProfile:
    return _profile("ndmi", values, **kwargs)


# ==========================================================================
# Metric identity and alignment
# ==========================================================================


def test_moisture_metric_is_ndmi_not_renamed_ndwi():
    assert NDVI_KEY == "ndvi"
    assert SUPPORTED_MOISTURE_KEYS == ("ndmi",)
    assert MIN_LAG_PAIRS == 3
    assert MIN_CORRELATION_PAIRS == 8
    with pytest.raises(ValueError, match="McFeeters"):
        align_profiles(_ndvi([0.5, 0.6, 0.7]), _profile("ndwi", [0.1, 0.2, 0.3]))
    with pytest.raises(ValueError, match="ndvi"):
        align_profiles(_profile("evi", [0.5, 0.6, 0.7]), _ndmi([0.1, 0.2, 0.3]))


def test_exact_monthly_alignment_with_full_overlap():
    joint = align_profiles(
        _ndvi([0.60, 0.62, 0.58]),
        _ndmi([0.30, 0.32, 0.28]),
    )
    assert joint.ndvi_key == "ndvi"
    assert joint.moisture_key == "ndmi"
    assert len(joint.points) == 3
    assert all(p.availability == "BOTH" for p in joint.points)
    assert joint.points[0].window_start == "2024-01-01"
    assert [p.ndvi for p in joint.points] == [
        pytest.approx(0.60),
        pytest.approx(0.62),
        pytest.approx(0.58),
    ]
    assert joint.n_paired == 3


def test_missing_sides_are_explicit():
    joint = align_profiles(
        _ndvi([0.60, None, 0.58]),
        _ndmi([None, 0.32, 0.28]),
    )
    assert [p.availability for p in joint.points] == [
        "NDVI_ONLY",
        "MOISTURE_ONLY",
        "BOTH",
    ]
    assert joint.n_paired == 1
    assert joint.points[0].moisture is None
    assert joint.points[1].ndvi is None


def test_both_missing_month_is_neither():
    joint = align_profiles(
        _ndvi([0.60, None]),
        _ndmi([0.30, None]),
    )
    assert joint.points[1].availability == "NEITHER"
    assert joint.points[1].ndvi is None
    assert joint.points[1].moisture is None


def test_mismatched_months_union_without_matching():
    ndvi = _profile("ndvi", [0.6, 0.6, 0.6, 0.6, 0.6, 0.6])
    moisture = _profile(
        "ndmi", [0.3, 0.3, 0.3, 0.3, 0.3, 0.3], start_month=3
    )
    joint = align_profiles(ndvi, moisture)
    assert len(joint.points) == 8
    assert [p.availability for p in joint.points] == (
        ["NDVI_ONLY"] * 2 + ["BOTH"] * 4 + ["MOISTURE_ONLY"] * 2
    )
    assert joint.window_start == "2024-01-01"
    assert joint.window_end == "2024-08-31"


def test_anomaly_attachment_by_window():
    ndvi = _ndvi([0.60, 0.62, 0.58, 0.61, 0.59, 0.63, 0.57, 0.64, 0.56, 0.65])
    ndmi = _ndmi([0.30, 0.32, 0.28, 0.31, 0.29, 0.33, 0.27, 0.34, 0.26, 0.35])
    joint = align_profiles(ndvi, ndmi, score_profile(ndvi), score_profile(ndmi))
    assert all(p.ndvi_z is not None for p in joint.points)
    assert all(p.moisture_z is not None for p in joint.points)
    assert joint.points[0].ndvi_quality == "good"
    assert joint.points[0].moisture_coverage == pytest.approx(100.0)


def test_miswired_anomaly_or_change_profiles_are_refused():
    ndvi = _ndvi([0.5, 0.6, 0.7])
    ndmi = _ndmi([0.3, 0.3, 0.3])
    wrong_anomalies = score_profile(_profile("evi", [0.5, 0.6, 0.7]))
    with pytest.raises(ValueError, match="miswired"):
        analyze_joint(ndvi, ndmi, ndvi_anomalies=wrong_anomalies)
    wrong_changes = analyze_changes(_profile("evi", [0.5, 0.6, 0.7, 0.8]))
    with pytest.raises(ValueError, match="miswired"):
        analyze_joint(ndvi, ndmi, ndvi_changes=wrong_changes)


# ==========================================================================
# Joint changes and divergence
# ==========================================================================


def _joint_with_changes(ndvi_values, moisture_values):
    ndvi = _ndvi(ndvi_values)
    moisture = _ndmi(moisture_values)
    return analyze_joint(
        ndvi,
        moisture,
        score_profile(ndvi),
        score_profile(moisture),
        analyze_changes(ndvi, score_profile(ndvi)),
        analyze_changes(moisture, score_profile(moisture)),
    )


def test_both_decrease_pattern():
    result = _joint_with_changes(
        [0.70, 0.65, 0.60, 0.55, 0.50, 0.45],
        [0.40, 0.36, 0.32, 0.28, 0.24, 0.20],
    )
    change = result.changes[1]
    assert change.pattern == "BOTH_DECREASE"
    assert change.divergence == "CONCURRENT_DECLINE"
    assert change.ndvi_change == pytest.approx(-0.05)
    assert change.moisture_change == pytest.approx(-0.04)
    assert change.ndvi_direction == "DECREASE"
    assert change.moisture_direction == "DECREASE"
    assert change.previous_window_start == "2024-01-01"
    assert change.days_elapsed == 31


def test_both_increase_pattern():
    result = _joint_with_changes(
        [0.40, 0.45, 0.50, 0.55, 0.60, 0.65],
        [0.20, 0.24, 0.28, 0.32, 0.36, 0.40],
    )
    assert result.changes[2].pattern == "BOTH_INCREASE"
    assert result.changes[2].divergence == "NO_DIVERGENCE"


def test_divergent_pattern():
    result = _joint_with_changes(
        [0.40, 0.45, 0.50, 0.55, 0.60, 0.65],
        [0.40, 0.36, 0.32, 0.28, 0.24, 0.20],
    )
    change = result.changes[1]
    assert change.pattern == "DIVERGENT"
    assert change.divergence == "NO_DIVERGENCE"


def test_moisture_down_ndvi_stable_pattern():
    # Constant NDVI has no spread, so the exact-zero rule applies and
    # every step is STABLE while moisture falls steadily.
    ndvi_values = [0.60] * 8
    moisture_values = [0.50, 0.45, 0.40, 0.35, 0.30, 0.25, 0.20, 0.15]
    result = _joint_with_changes(ndvi_values, moisture_values)
    change = result.changes[1]
    assert change.moisture_direction == "DECREASE"
    assert change.ndvi_direction == "STABLE"
    assert change.pattern == "NDVI_STABLE_MOISTURE_DECREASE"
    assert change.divergence == "MOISTURE_DOWN_NDVI_STABLE"


def test_ndvi_down_moisture_stable_pattern():
    ndvi_values = [0.70, 0.60, 0.50, 0.40, 0.30, 0.25, 0.22, 0.20]
    moisture_values = [0.30] * 8
    result = _joint_with_changes(ndvi_values, moisture_values)
    change = result.changes[1]
    assert change.ndvi_direction == "DECREASE"
    assert change.moisture_direction == "STABLE"
    assert change.pattern == "NDVI_DECREASE_MOISTURE_STABLE"
    assert change.divergence == "NDVI_DOWN_MOISTURE_STABLE"


def test_joint_change_without_change_profiles_is_insufficient():
    result = analyze_joint(
        _ndvi([0.70, 0.65, 0.60]),
        _ndmi([0.40, 0.36, 0.32]),
    )
    assert all(c.pattern == "INSUFFICIENT" for c in result.changes)
    assert all(c.divergence == "INSUFFICIENT" for c in result.changes)


def test_divergence_helper_table():
    assert divergence_of("BOTH_DECREASE") == "CONCURRENT_DECLINE"
    assert divergence_of("NDVI_STABLE_MOISTURE_DECREASE") == (
        "MOISTURE_DOWN_NDVI_STABLE"
    )
    assert divergence_of("NDVI_DECREASE_MOISTURE_STABLE") == (
        "NDVI_DOWN_MOISTURE_STABLE"
    )
    assert divergence_of("INSUFFICIENT") == "INSUFFICIENT"
    assert divergence_of("BOTH_INCREASE") == "NO_DIVERGENCE"
    assert divergence_of("DIVERGENT") == "NO_DIVERGENCE"


# ==========================================================================
# Lead/lag analysis
# ==========================================================================


def _leading_pair():
    moisture = _ndmi([0.5] * 5 + [0.1] + [0.5] * 4)
    ndvi = _ndvi([0.7] * 6 + [0.2] + [0.7] * 3)
    return moisture, ndvi


def test_lag_zero_one_two_evaluated_explicitly():
    moisture, ndvi = _leading_pair()
    joint = align_profiles(ndvi, moisture, score_profile(ndvi), score_profile(moisture))
    lags = lead_lag_analysis(joint)
    assert [lag.lag_months for lag in lags] == [0, 1, 2]
    assert [lag.n_paired for lag in lags] == [10, 9, 8]
    assert all(lag.sufficient for lag in lags)


def test_moisture_lead_scores_highest_agreement_at_lag_one():
    moisture, ndvi = _leading_pair()
    joint = align_profiles(ndvi, moisture, score_profile(ndvi), score_profile(moisture))
    lags = {lag.lag_months: lag for lag in lead_lag_analysis(joint)}
    assert lags[1].agreement == pytest.approx(1.0)
    assert lags[0].agreement == pytest.approx(0.8)
    assert lags[1].agreement > lags[0].agreement
    assert lags[1].agreement > lags[2].agreement


def test_insufficient_lag_observations():
    joint = align_profiles(_ndvi([0.6, 0.5, 0.4]), _ndmi([0.3, 0.3, 0.3]))
    lags = {lag.lag_months: lag for lag in lead_lag_analysis(joint)}
    # No anomaly profiles supplied: no z-scores, so no lag is assessable.
    assert all(lag.sufficient is False for lag in lags.values())
    assert all(lag.agreement is None for lag in lags.values())
    assert all(lag.correlation is None for lag in lags.values())


def test_zero_variance_kills_correlation_but_keeps_counts():
    joint = align_profiles(
        _ndvi([0.6] * 10),
        _ndmi([0.3] * 10),
        score_profile(_ndvi([0.6] * 10)),
        score_profile(_ndmi([0.3] * 10)),
    )
    lags = lead_lag_analysis(joint)
    assert all(lag.n_paired == 0 for lag in lags)
    assert all(lag.sufficient is False for lag in lags)
    data = joint  # scatter checked below; joint itself carries no numbers invented
    assert data.n_paired == 10


def test_non_finite_values_excluded_everywhere():
    joint = align_profiles(
        _ndvi([0.6, float("nan"), 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6]),
        _ndmi([0.3] * 10),
    )
    assert joint.points[1].availability == "MOISTURE_ONLY"
    assert joint.n_paired == 9
    assert pearson_correlation(
        [1.0, 2.0, 3.0, float("nan"), 5.0, 6.0, 7.0, 8.0, 9.0],
        [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0],
    ) is None


# ==========================================================================
# Scatter, correlation, trajectory
# ==========================================================================


def test_scatter_preserves_traceability_in_order():
    result = _joint_with_changes(
        [0.70, 0.65, 0.60, 0.55, 0.50, 0.45, 0.40, 0.35, 0.30, 0.25],
        [0.40, 0.38, 0.36, 0.34, 0.32, 0.30, 0.28, 0.26, 0.24, 0.22],
    )
    assert result.scatter is not None
    assert result.scatter.n_paired == 10
    assert result.scatter.ndvi_key == "ndvi"
    assert result.scatter.moisture_key == "ndmi"
    first = result.scatter.points[0]
    assert first.window_start == "2024-01-01"
    assert first.ndvi == pytest.approx(0.70)
    assert first.moisture == pytest.approx(0.40)
    assert first.ndvi_z is not None and first.moisture_z is not None
    assert [p.window_start for p in result.scatter.points] == sorted(
        p.window_start for p in result.scatter.points
    )
    # Both sides decline perfectly linearly: correlation is exact.
    assert result.scatter.correlation == pytest.approx(1.0)


def test_correlation_needs_pairs_and_variance():
    assert pearson_correlation([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) is None  # too few
    assert pearson_correlation([1.0] * 8, list(range(8))) is None  # flat x
    assert pearson_correlation(list(range(8)), [1.0] * 8) is None  # flat y
    assert pearson_correlation([1.0, 2.0], [1.0]) is None  # length mismatch
    assert pearson_correlation(
        [float(v) for v in range(10)], [float(v) * 2.0 + 1.0 for v in range(10)]
    ) == pytest.approx(1.0)
    assert pearson_correlation(
        [float(v) for v in range(10)], [float(9 - v) for v in range(10)]
    ) == pytest.approx(-1.0)


def test_trajectory_is_chronological_triples():
    result = _joint_with_changes(
        [0.70, 0.65, 0.60, 0.55],
        [0.40, 0.36, 0.32, 0.28],
    )
    assert result.scatter is not None
    trajectory = result.scatter.trajectory
    assert [t[0] for t in trajectory] == sorted(t[0] for t in trajectory)
    assert trajectory[0] == ("2024-01-01", pytest.approx(0.70), pytest.approx(0.40))
    # The trajectory never collapses to the summary number.
    assert len(trajectory) == result.scatter.n_paired


def test_scatter_skips_unpaired_months():
    joint = align_profiles(
        _ndvi([0.60, None, 0.58]),
        _ndmi([None, 0.32, 0.28]),
    )
    data = scatter_dataset(joint)
    assert data.n_paired == 1
    assert data.points[0].window_start == "2024-03-01"


# ==========================================================================
# Baseline-aware joint states
# ==========================================================================


def test_joint_anomaly_state_table():
    from app.services.agriculture.joint_profile import (
        JOINT_BOTH_ABOVE,
        JOINT_BOTH_BELOW,
        JOINT_INSUFFICIENT,
        JOINT_MIXED,
        JOINT_MOISTURE_BELOW,
        JOINT_NDVI_BELOW,
        JOINT_NEUTRAL,
        joint_anomaly_state,
    )

    assert joint_anomaly_state(-1.5, -0.5) == JOINT_BOTH_BELOW
    assert joint_anomaly_state(1.5, 0.5) == JOINT_BOTH_ABOVE
    assert joint_anomaly_state(-1.5, 0.5) == JOINT_MIXED
    assert joint_anomaly_state(1.5, -0.5) == JOINT_MIXED
    assert joint_anomaly_state(-1.5, None) == JOINT_NDVI_BELOW
    assert joint_anomaly_state(None, -0.5) == JOINT_MOISTURE_BELOW
    assert joint_anomaly_state(-1.5, 0.0) == JOINT_NDVI_BELOW
    assert joint_anomaly_state(0.0, 0.0) == JOINT_NEUTRAL
    assert joint_anomaly_state(0.0, None) == JOINT_NEUTRAL
    assert joint_anomaly_state(1.5, None) == JOINT_NEUTRAL
    assert joint_anomaly_state(None, None) == JOINT_INSUFFICIENT


# ==========================================================================
# Multiple profiles, determinism, provenance, round-trip
# ==========================================================================


def test_multiple_independent_profiles_do_not_cross_talk():
    first = analyze_joint(
        _ndvi([0.6, 0.5, 0.4]),
        _ndmi([0.3, 0.3, 0.3]),
    )
    second = analyze_joint(
        _ndvi([0.4, 0.5, 0.6], start_year=2025),
        _ndmi([0.2, 0.2, 0.2], start_year=2025),
    )
    assert first.window_start == "2024-01-01"
    assert second.window_start == "2025-01-01"
    assert first.joint.points[0].ndvi == pytest.approx(0.6)
    assert second.joint.points[0].ndvi == pytest.approx(0.4)


def test_deterministic_output():
    kwargs = {
        "ndvi_anomalies": score_profile(_ndvi([0.6, 0.5, 0.4, 0.45, 0.5, 0.55])),
        "moisture_anomalies": score_profile(_ndmi([0.3, 0.32, 0.28, 0.3, 0.31, 0.29])),
    }
    ndvi = _ndvi([0.6, 0.5, 0.4, 0.45, 0.5, 0.55])
    ndmi = _ndmi([0.3, 0.32, 0.28, 0.3, 0.31, 0.29])
    first = analyze_joint(ndvi, ndmi, **kwargs)
    second = analyze_joint(ndvi, ndmi, **kwargs)
    assert first == second


def test_provenance_fields_survive_the_joint_path():
    ndvi = _ndvi([0.60, 0.62, 0.58, 0.61, 0.59, 0.63, 0.57, 0.64, 0.56, 0.65])
    ndmi = _ndmi([0.30, 0.32, 0.28, 0.31, 0.29, 0.33, 0.27, 0.34, 0.26, 0.35])
    result = analyze_joint(ndvi, ndmi, score_profile(ndvi), score_profile(ndmi))
    point = result.joint.points[0]
    assert point.ndvi_quality == "good"
    assert point.moisture_quality == "good"
    assert point.ndvi_coverage == pytest.approx(100.0)
    assert point.moisture_coverage == pytest.approx(100.0)
    assert result.ndvi_key == "ndvi" and result.moisture_key == "ndmi"


def test_pydantic_round_trip():
    from app.schemas.agriculture import JointAnalysisModel

    result = _joint_with_changes(
        [0.70, 0.65, 0.60, 0.55, 0.50, 0.45, 0.40, 0.35, 0.30, 0.25],
        [0.40, 0.38, 0.36, 0.34, 0.32, 0.30, 0.28, 0.26, 0.24, 0.22],
    )
    model = JointAnalysisModel(**result.to_dict())
    assert model.ndvi_key == "ndvi"
    assert model.moisture_key == "ndmi"
    assert len(model.joint.points) == 10
    assert len(model.changes) == 10
    assert [lag.lag_months for lag in model.lags] == [0, 1, 2]
    assert model.scatter is not None
    assert model.scatter.n_paired == 10
    assert model.joint.points[0].availability == "BOTH"


# ==========================================================================
# Scientific-contract guards
# ==========================================================================


def test_no_diagnostic_or_ml_language_in_production_logic():
    import app.services.agriculture.joint_profile as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "NOT evidence sufficient" in source
    for token in (
        "pest_risk",
        "pest-risk",
        "severity_level",
        "probability_of",
        "machine learning",
        "sklearn",
        "torch",
        "tensorflow",
        "training data",
        "defoliation",
        "pest damage",
    ):
        assert token not in source.lower(), token


def test_module_touches_no_database_or_network():
    import app.services.agriculture.joint_profile as module

    source = open(module.__file__, encoding="utf-8").read().lower()
    for token in ("sqlite", "postgres", "sqlalchemy", "requests.get", "urllib"):
        assert token not in source, token
