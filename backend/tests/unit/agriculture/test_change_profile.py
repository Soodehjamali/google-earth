"""Tests for the P1.3 temporal change and breakpoint engine.

Profiles and anomaly profiles are built directly (and through the
P1.2 scorer, which is pure), so no Earth Engine fixture is needed:
P1.1 already proves profiles come out of real metrics.  Expected
numbers are hand-computed inline, never with the engine under test.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from app.services.agriculture.baseline_anomaly import score_profile
from app.services.agriculture.change_profile import (
    BREAK_WINDOW_MONTHS,
    CHANGE_MAX_GAP_MONTHS,
    BREAK_WINDOW_MONTHS,
    CHANGE_MAX_GAP_MONTHS,
    DIRECTION_DECREASE,
    DIRECTION_INCREASE,
    DIRECTION_INSUFFICIENT,
    DIRECTION_STABLE,
    PERSISTENCE_INSUFFICIENT,
    PERSISTENCE_NONE,
    PERSISTENCE_PERSISTENT,
    PERSISTENCE_PERSISTENT,
    RAPID_DECREASE,
    RAPID_INCREASE,
    RAPID_INSUFFICIENT,
    RAPID_NOT_RAPID,
    RAPID_STD_MULTIPLE,
    analyze_changes,
    classify_direction,
    classify_rapid,
    detect_breakpoint,
    month_changes,
    persistence_of,
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
    values: List[Optional[float]],
    metric_key: str = "ndvi",
    unit: str = "index",
    **kwargs,
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
# Observation-to-observation change
# ==========================================================================


def test_consecutive_monthly_changes():
    changes = month_changes(_profile([0.50, 0.60, 0.55, 0.70]))
    assert len(changes) == 4
    first = changes[0]
    assert first.previous_value is None
    assert first.absolute_change is None
    assert first.direction == DIRECTION_INSUFFICIENT
    assert [c.absolute_change for c in changes[1:]] == [
        pytest.approx(0.10),
        pytest.approx(-0.05),
        pytest.approx(0.15),
    ]
    assert changes[1].previous_window_start == "2024-01-01"
    assert changes[1].days_elapsed == 31
    assert changes[1].rate_per_day == pytest.approx(0.10 / 31)


def test_single_missing_month_is_bridged_not_connected_as_adjacent():
    changes = month_changes(_profile([0.50, None, 0.70]))
    assert changes[1].absolute_change is None
    assert changes[1].direction == DIRECTION_INSUFFICIENT
    third = changes[2]
    assert third.absolute_change == pytest.approx(0.20)
    assert third.previous_window_start == "2024-01-01"
    assert third.days_elapsed == 60  # Jan 1 -> Mar 1 in leap-year 2024


def test_two_missing_months_refuse_the_change():
    changes = month_changes(_profile([0.50, None, None, 0.80]))
    assert changes[3].absolute_change is None
    assert changes[3].previous_value is None
    assert changes[3].direction == DIRECTION_INSUFFICIENT


def test_zero_values_and_zero_denominator():
    changes = month_changes(_profile([0.0, 0.50, 0.0]))
    assert changes[1].absolute_change == pytest.approx(0.50)
    assert changes[1].relative_change is None  # previous is zero: refused
    assert changes[2].absolute_change == pytest.approx(-0.50)
    assert changes[2].relative_change == pytest.approx(-1.0)


def test_negative_values_keep_direction_in_relative_change():
    changes = month_changes(_profile([-12.0, -11.0, -13.5], unit="dB"))
    assert changes[1].absolute_change == pytest.approx(1.0)
    assert changes[1].relative_change == pytest.approx(1.0 / 12.0)
    assert changes[1].relative_change > 0  # sign follows the direction
    assert changes[2].absolute_change == pytest.approx(-2.5)


# ==========================================================================
# Direction and rapid flags
# ==========================================================================


def test_direction_with_and_without_spread():
    assert classify_direction(0.005, 0.10) == DIRECTION_STABLE
    assert classify_direction(0.05, 0.10) == DIRECTION_INCREASE
    assert classify_direction(-0.05, 0.10) == DIRECTION_DECREASE
    assert classify_direction(0.0, None) == DIRECTION_STABLE
    assert classify_direction(0.001, None) == DIRECTION_INCREASE
    assert classify_direction(None, 0.10) == DIRECTION_INSUFFICIENT
    assert classify_direction(0.05, 0.0) == DIRECTION_INCREASE  # no spread: exact rule


def test_rapid_flags_against_two_sigma():
    assert RAPID_STD_MULTIPLE == 2.0
    assert CHANGE_MAX_GAP_MONTHS == 1
    assert BREAK_WINDOW_MONTHS == 3
    assert classify_rapid(0.25, 0.10) == RAPID_INCREASE
    assert classify_rapid(-0.25, 0.10) == RAPID_DECREASE
    assert classify_rapid(0.05, 0.10) == RAPID_NOT_RAPID
    assert classify_rapid(0.25, None) == RAPID_INSUFFICIENT
    assert classify_rapid(0.25, 0.0) == RAPID_INSUFFICIENT
    assert classify_rapid(None, 0.10) == RAPID_INSUFFICIENT


def test_rapid_and_direction_flow_into_month_changes():
    profile = _profile([0.50, 0.52, 0.90, 0.91])
    anomalies = score_profile(profile)
    assert anomalies.baseline is not None
    changes = month_changes(profile, anomalies, reference_spread=0.05)
    jump = changes[2]
    assert jump.absolute_change == pytest.approx(0.38)
    assert jump.direction == DIRECTION_INCREASE
    assert jump.rapid == RAPID_INCREASE  # 0.38 > 2 x 0.05
    assert changes[1].z_score is not None  # anomaly attachment
    calm = month_changes(profile, anomalies, reference_spread=5.0)
    assert calm[2].rapid == RAPID_NOT_RAPID
    assert calm[2].direction == DIRECTION_STABLE
    assert changes[0].direction == DIRECTION_INSUFFICIENT


# ==========================================================================
# Persistence
# ==========================================================================


def test_persistent_deviation_detected():
    values = [0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.9, 0.9, 0.9, 0.9]
    result = persistence_of(score_profile(_profile(values)))
    assert result.state == PERSISTENCE_PERSISTENT
    assert result.longest_run_below == 3
    assert result.n_observed == 10
    assert result.n_missing == 0


def test_gap_breaks_only_the_run_it_interrupts():
    values = [0.1, 0.1, None, 0.1, 0.1, 0.9, 0.9, 0.9, 0.9, 0.9]
    result = persistence_of(score_profile(_profile(values)))
    assert result.longest_run_below == 2  # the gap broke the below-run
    assert result.longest_run_above == 5
    assert result.state == PERSISTENCE_PERSISTENT  # via the unbroken above-run
    assert result.n_missing == 1
    assert result.n_observed == 9


def test_alternating_deviation_is_not_persistent():
    result = persistence_of(score_profile(_profile([0.1, 0.9] * 5)))
    assert result.state == PERSISTENCE_NONE
    assert result.longest_run_below == 1
    assert result.longest_run_above == 1


def test_persistence_insufficient_without_baseline():
    result = persistence_of(score_profile(_profile([0.50, 0.60])))
    assert result.state == PERSISTENCE_INSUFFICIENT
    assert result.longest_run_below == 0
    assert result.n_observed == 2


# ==========================================================================
# Breakpoints
# ==========================================================================


def test_step_change_yields_breakpoint_with_levels():
    values = [0.80] * 6 + [0.30] * 6
    record = detect_breakpoint(_profile(values))
    assert record is not None
    assert record.onset_window_start == "2024-07-01"
    assert record.onset_window_end == "2024-07-31"
    assert record.direction == DIRECTION_DECREASE
    assert record.pre_level == pytest.approx(0.80)
    assert record.post_level == pytest.approx(0.30)
    assert record.magnitude == pytest.approx(-0.50)
    assert record.window_months == BREAK_WINDOW_MONTHS
    assert record.n_usable == 12
    assert record.method != ""


def test_constant_series_yields_no_breakpoint():
    assert detect_breakpoint(_profile([0.50] * 12)) is None


def test_insufficient_pre_post_windows_yield_no_breakpoint():
    assert detect_breakpoint(_profile([0.80, 0.80, 0.30, 0.30, 0.30])) is None
    assert detect_breakpoint(_profile([0.80, 0.30])) is None


def test_gap_spanning_boundary_is_refused():
    values = [0.80] * 6 + [None, None] + [0.30] * 6
    assert detect_breakpoint(_profile(values)) is None


def test_breakpoint_inside_gappy_series_still_found_when_clean():
    # Step at month 4 with a far-away gap elsewhere: the winning
    # boundary sits in clean months and is reported.
    values = [0.80, 0.80, 0.80, 0.30, 0.30, 0.30, 0.30, 0.30, 0.30, None, 0.30, 0.30]
    record = detect_breakpoint(_profile(values))
    assert record is not None
    assert record.onset_window_start == "2024-04-01"
    assert record.direction == DIRECTION_DECREASE


# ==========================================================================
# Full analysis, determinism, provenance, multi-metric, multi-year
# ==========================================================================


def test_analyze_changes_bundles_everything_deterministically():
    values = [0.50, 0.55, 0.90, 0.88, 0.52, 0.50, 0.49, 0.51, 0.50, 0.52, 0.53, 0.51]
    profile = _profile(values)
    anomalies = score_profile(profile)
    first = analyze_changes(profile, anomalies)
    second = analyze_changes(profile, anomalies)
    assert first == second
    assert first.metric_key == "ndvi"
    assert first.unit == "index"
    assert len(first.changes) == 12
    assert first.n_computed == 11
    assert first.breakpoint is not None
    assert first.persistence.state in (
        PERSISTENCE_PERSISTENT,
        PERSISTENCE_NONE,
        PERSISTENCE_INSUFFICIENT,
    )


def test_analyze_without_anomalies_marks_persistence_insufficient():
    result = analyze_changes(_profile([0.50, 0.60, 0.70, 0.80]))
    assert result.persistence.state == PERSISTENCE_INSUFFICIENT
    assert result.persistence.n_observed == 4
    assert all(change.z_score is None for change in result.changes)


def test_provenance_fields_pass_through_untouched():
    profile = _profile(
        [0.50, 0.60, 0.70], metric_key="vv", unit="dB", quality="moderate"
    )
    result = analyze_changes(profile, score_profile(profile))
    assert result.metric_key == "vv"
    for change in result.changes:
        assert change.unit == "dB"
        assert change.quality == "moderate"
    assert result.changes[1].coverage_percent == pytest.approx(100.0)
    assert result.changes[1].image_count == 6


def test_multiple_metrics_stay_independent():
    optical = analyze_changes(
        _profile([0.50, 0.60, 0.70, 0.80]),
        score_profile(_profile([0.50, 0.60, 0.70, 0.80])),
    )
    radar = analyze_changes(
        _profile([-12.0, -11.0, -13.0, -10.5], metric_key="vh", unit="dB"),
        score_profile(
            _profile([-12.0, -11.0, -13.0, -10.5], metric_key="vh", unit="dB")
        ),
    )
    assert optical.unit == "index" and radar.unit == "dB"
    assert optical.changes[1].absolute_change == pytest.approx(0.10)
    assert radar.changes[1].absolute_change == pytest.approx(1.0)


def test_one_two_three_year_profiles():
    one_year = analyze_changes(_profile([0.50] * 12))
    assert len(one_year.changes) == 12
    assert one_year.n_computed == 11
    two_year = analyze_changes(_profile([0.50] * 24))
    assert len(two_year.changes) == 24
    three_year = analyze_changes(_profile([0.80] * 18 + [0.30] * 18))
    assert len(three_year.changes) == 36
    assert three_year.breakpoint is not None
    assert three_year.breakpoint.onset_window_start == "2025-07-01"


# ==========================================================================
# Contract round-trip
# ==========================================================================


def test_to_dict_round_trips_through_the_api_contract_models():
    from app.schemas.agriculture import ChangeProfileModel

    values = [0.80] * 6 + [0.30] * 6
    result = analyze_changes(_profile(values), score_profile(_profile(values)))
    model = ChangeProfileModel(**result.to_dict())
    assert model.metric_key == "ndvi"
    assert len(model.changes) == 12
    assert model.changes[1].absolute_change == pytest.approx(0.0)
    assert model.changes[1].direction == DIRECTION_STABLE
    assert model.breakpoint is not None
    assert model.breakpoint.direction == DIRECTION_DECREASE
    assert model.persistence.state == PERSISTENCE_PERSISTENT


def test_null_breakpoint_round_trips():
    from app.schemas.agriculture import ChangeProfileModel

    result = analyze_changes(_profile([0.50] * 12))
    model = ChangeProfileModel(**result.to_dict())
    assert model.breakpoint is None
    assert all(c.direction == DIRECTION_STABLE for c in model.changes[1:])


# ==========================================================================
# Scientific-contract guards
# ==========================================================================


def test_classifications_use_only_neutral_vocabulary():
    import app.services.agriculture.change_profile as module

    allowed_states = {
        "INCREASE",
        "DECREASE",
        "STABLE",
        "INSUFFICIENT",
        "RAPID_INCREASE",
        "RAPID_DECREASE",
        "NOT_RAPID",
        "NO_PERSISTENCE",
        "PERSISTENT",
    }
    assert {module.DIRECTION_INCREASE, module.DIRECTION_DECREASE,
            module.DIRECTION_STABLE, module.DIRECTION_INSUFFICIENT} <= allowed_states
    assert {module.RAPID_INCREASE, module.RAPID_DECREASE,
            module.RAPID_NOT_RAPID, module.RAPID_INSUFFICIENT} <= allowed_states | {"INSUFFICIENT"}
    assert {module.PERSISTENCE_NONE, module.PERSISTENCE_PERSISTENT,
            module.PERSISTENCE_INSUFFICIENT} <= allowed_states | {"INSUFFICIENT", "NO_PERSISTENCE"}


def test_no_causal_or_ml_language_in_production_code():
    import app.services.agriculture.change_profile as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "must not select" in source  # the no-cause mandate is stated
    for token in (
        "risk_score",
        "pest_risk",
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
    import app.services.agriculture.change_profile as module

    source = open(module.__file__, encoding="utf-8").read().lower()
    for token in ("sqlite", "postgres", "sqlalchemy", "requests.get", "urllib"):
        assert token not in source, token
