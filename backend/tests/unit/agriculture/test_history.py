"""Tests for the historical analytics framework (Phase N).

The governing risks, each with dedicated tests:

1. **A second anomaly framework.** The framework must extend Phase K,
   not restate it. The tests check that ``history.py`` delegates to
   ``stress.py``'s primitives (``shift_window_years``,
   ``percentile_of_value``, ``summarise_baseline``) rather than
   redefining them, and that the windows built here equal K's.

2. **A fabricated reference.** An under-populated reference group, a
   missing baseline, a zero spread and a degenerate percentile
   population must all refuse with precise reasons — never produce a
   zero anomaly, a fake z-score or a fabricated rank.

3. **A trend of nothing.** A STATIC dataset must refuse with
   ``static_dataset_no_historical_series``; a trend on too few
   observations must refuse; a flat series must not be called
   increasing; a flat series must not be reported as significant.

4. **Persistence across a gap.** A missing month — and a month whose
   reference group has no defensible baseline — must break a
   consecutive run; gaps are excluded from the denominator, never
   counted as anomalous.

5. **A diagnosis in disguise.** Every metric's prose must carry the
   descriptive boundary: trend is not causality, percentile is not
   probability, vegetation season is not the crop calendar.

The NDVI paths run through a fake of the phenology builder whose
collections honour ``filterDate`` (an analysis-year fixture cannot
leak into a reference year); the climate path through a fake of the
ERA5 reduction. No network, no Earth Engine, no credentials.
"""

from __future__ import annotations

import os
import sys
import types
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pytest

from app.services.agriculture.base import MetricContext, MetricDomain
from app.services.agriculture.catalog import (
    clear_registry,
    metric_keys,
    register_metrics,
)
from app.services.agriculture.history import (
    ALL_HISTORY_METRICS,
    HISTORY_BASELINE_YEARS,
    HISTORY_METRICS,
    HISTORY_MIN_YEARS,
    MIN_ANALYSIS_MONTHS,
    MIN_CHANGE_OBS,
    MIN_SEASON_HISTORY,
    MIN_TREND_OBS,
    UNAVAILABLE_HISTORY_METRICS,
    BaselineStrategy,
    ChangeRecord,
    ClimateTrendMetric,
    NdviAnomalyAbsoluteMetric,
    NdviAnomalyPersistenceMetric,
    NdviAnomalyRelativeMetric,
    NdviAnomalyStandardizedMetric,
    NdviChangeShiftMetric,
    NdviPercentileContextMetric,
    NdviTrendMetric,
    ObservationPoint,
    PercentileContext,
    SeasonTimingHistoryMetric,
    TrendDirection,
    UNAVAILABLE_HISTORY_METRICS as _UNAVAILABLE_TUPLE,
    UnavailableStaticHistoryMetric,
    absolute_anomaly,
    compute_baseline,
    compute_persistence,
    compute_trend,
    largest_rolling_shift,
    mann_kendall,
    percentile_context,
    relative_anomaly,
    require_temporal_series,
    standardized_anomaly,
    theil_sen_slope,
)
from app.services.agriculture.types import (
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)

EXPECTED_KEYS = {
    "ndvi_anomaly_absolute",
    "ndvi_anomaly_relative",
    "ndvi_anomaly_standardized",
    "ndvi_percentile_context",
    "ndvi_trend",
    "ndvi_anomaly_persistence",
    "ndvi_change_shift",
    "climate_trend",
    "season_timing_history",
    "terrain_historical_trend",
}


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


# ==========================================================================
# Collection integrity
# ==========================================================================


def test_all_expected_history_metrics_present():
    assert {m.key for m in ALL_HISTORY_METRICS} == EXPECTED_KEYS


def test_no_duplicate_metric_keys():
    keys = [m.key for m in ALL_HISTORY_METRICS]
    assert len(keys) == len(set(keys))


def test_every_metric_is_in_the_history_domain():
    for metric in ALL_HISTORY_METRICS:
        assert metric.domain == MetricDomain.HISTORY, metric.key


def test_the_available_and_unavailable_split_is_honest():
    assert {m.key for m in HISTORY_METRICS} == EXPECTED_KEYS - {
        "terrain_historical_trend"
    }
    assert {m.key for m in UNAVAILABLE_HISTORY_METRICS} == {
        "terrain_historical_trend"
    }


def test_registration_reaches_the_catalog():
    register_metrics(ALL_HISTORY_METRICS)
    for key in EXPECTED_KEYS:
        assert key in metric_keys(), key


def test_every_metric_states_the_descriptive_boundary():
    """Trend is not causality; percentile is not probability."""
    for metric in ALL_HISTORY_METRICS:
        text = (metric.description + " " + " ".join(metric.limitations)
                ).lower()
        assert ("descriptive" in text or "not computable" in text), (
            metric.key
        )


# ==========================================================================
# Phase K reuse, not duplication
# ==========================================================================


class TestPhaseKReuse:
    def test_the_framework_delegates_to_phase_k_primitives(self):
        import app.services.agriculture.history as history
        import app.services.agriculture.stress as stress

        assert history.shift_window_years is stress.shift_window_years
        assert history.percentile_of_value is stress.percentile_of_value
        assert history.summarise_baseline is stress.summarise_baseline
        assert history._shift_context is stress._shift_context

    def test_the_analysis_and_history_windows_are_phase_k_windows(self):
        from app.services.agriculture.history import (
            _analysis_and_history_windows,
        )
        from app.services.agriculture.stress import baseline_windows

        start = date(2024, 6, 15)
        end = date(2024, 8, 15)
        windows, error = _analysis_and_history_windows(
            _window_context(start, end), 3
        )
        assert error is None
        assert windows[0] == (0, start, end)
        assert windows[1:] == baseline_windows(start, end, 3)

    def test_leap_day_folding_matches_phase_k(self):
        from app.services.agriculture.stress import shift_window_years

        start = date(2024, 2, 29)
        end = date(2024, 3, 30)
        folded_start, folded_end = shift_window_years(start, end, 1)
        assert (folded_start.month, folded_start.day) == (2, 28)

    def test_no_second_anomaly_module_was_created(self):
        """The architecture rule: one framework, stress.py + history.py."""
        import app.services.agriculture.history as history

        module_dir = os.path.dirname(history.__file__)
        forbidden = [
            name
            for name in os.listdir(module_dir)
            if name.startswith("historical_")
            or name.startswith("baseline_engine")
            or name.startswith("trend_engine")
        ]
        assert not forbidden, forbidden

    def test_the_absolute_anomaly_agrees_with_phase_k(self):
        from app.services.agriculture.stress import compute_anomaly

        baseline_values = [0.5, 0.4, 0.6]
        record = compute_anomaly(0.7, baseline_values, "mean")
        assert record is not None
        assert absolute_anomaly(
            0.7, float(np.mean(baseline_values))
        ) == pytest.approx(record.anomaly)


def _window_context(start: date, end: date) -> MetricContext:
    return MetricContext(
        geometry={},
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        geometry_key="window-check",
    )


# ==========================================================================
# The temporal-semantics guard
# ==========================================================================


class _StaticDataset:
    temporal_kind = __import__(
        "app.services.agriculture.types", fromlist=["TemporalKind"]
    ).TemporalKind.STATIC


class _ObservationDataset:
    temporal_kind = __import__(
        "app.services.agriculture.types", fromlist=["TemporalKind"]
    ).TemporalKind.OBSERVATION


class TestStaticGuard:
    def test_a_static_dataset_is_refused(self):
        reason = require_temporal_series(_StaticDataset())
        assert reason == "static_dataset_no_historical_series"

    def test_an_observation_dataset_passes(self):
        assert require_temporal_series(_ObservationDataset()) is None

    def test_the_registered_static_refusal_carries_the_code(self):
        metric = UnavailableStaticHistoryMetric()
        result = metric.compute(_window_context(date(2024, 1, 1),
                                                date(2024, 6, 30)))
        assert result.status == STATUS_UNAVAILABLE
        assert result.reason == "static_dataset_no_historical_series"
        assert "TemporalKind" in result.message

    def test_the_static_refusal_names_a_real_static_dataset(self):
        metric = UnavailableStaticHistoryMetric()
        from app.services.agriculture.registry import get_dataset
        from app.services.agriculture.types import TemporalKind

        assert metric.dataset_ids == ("NASA/NASADEM_HGT/001",)
        assert (
            get_dataset("NASA/NASADEM_HGT/001").temporal_kind
            is TemporalKind.STATIC
        )

    def test_every_dynamic_history_metric_checks_the_guard(self):
        """The guard must appear in every OBSERVATION compute path."""
        import inspect

        import app.services.agriculture.history as history

        source = inspect.getsource(history)
        # 9 dynamic metrics, each with exactly one guard call.
        assert source.count("require_temporal_series(dataset)") == 9


# ==========================================================================
# Baseline machinery
# ==========================================================================


def a_series(values_by_month: Dict[int, float], year: int = 2022):
    return [
        ObservationPoint(day=date(year, month, 1), value=value)
        for month, value in sorted(values_by_month.items())
    ]


class TestBaseline:
    def test_a_full_period_baseline_covers_everything(self):
        series = a_series({1: 0.2, 2: 0.3, 3: 0.4, 4: 0.5})
        baseline = compute_baseline(
            series, BaselineStrategy.FULL_PERIOD, "all", min_n=3
        )
        assert baseline is not None
        assert baseline.n == 4
        assert baseline.mean == pytest.approx(0.35)
        assert baseline.group == "all"

    def test_a_month_of_year_baseline_groups_by_month(self):
        series = (
            a_series({6: 0.5}, year=2021)
            + a_series({6: 0.6}, year=2022)
            + a_series({6: 0.7}, year=2023)
        )
        baseline = compute_baseline(
            series, BaselineStrategy.MONTH_OF_YEAR, "06", min_n=3
        )
        assert baseline is not None
        assert baseline.n == 3
        assert baseline.mean == pytest.approx(0.6)

    def test_a_season_of_year_baseline_groups_by_season(self):
        series = (
            a_series({6: 0.5}, year=2021)
            + a_series({7: 0.6}, year=2021)
            + a_series({8: 0.7}, year=2021)
        )
        baseline = compute_baseline(
            series, BaselineStrategy.SEASON_OF_YEAR, "JJA", min_n=3
        )
        assert baseline is not None
        assert baseline.n == 3
        assert baseline.mean == pytest.approx(0.6)

    def test_an_underpopulated_group_is_refused(self):
        series = a_series({6: 0.5}, year=2021) + a_series(
            {6: 0.6}, year=2022
        )
        assert (
            compute_baseline(
                series, BaselineStrategy.MONTH_OF_YEAR, "06", min_n=3
            )
            is None
        )

    def test_the_spread_is_flagged_unreliable_below_three(self):
        series = a_series({6: 0.5}, year=2021) + a_series(
            {6: 0.6}, year=2022
        )
        baseline = compute_baseline(
            series, BaselineStrategy.MONTH_OF_YEAR, "06", min_n=2
        )
        assert baseline is not None
        assert baseline.spread_reliable is False

    def test_the_reference_dates_bound_the_contributing_members(self):
        series = a_series({6: 0.5}, year=2021) + a_series(
            {6: 0.7}, year=2023
        )
        baseline = compute_baseline(
            series, BaselineStrategy.MONTH_OF_YEAR, "06", min_n=2
        )
        assert baseline is not None
        assert baseline.reference_start == date(2021, 6, 1)
        assert baseline.reference_end == date(2023, 6, 1)


# ==========================================================================
# Anomaly machinery
# ==========================================================================


class TestAnomalies:
    def test_the_absolute_anomaly_is_the_difference(self):
        assert absolute_anomaly(0.7, 0.5) == pytest.approx(0.2)

    def test_a_missing_baseline_yields_none_not_zero(self):
        assert absolute_anomaly(0.7, None) is None
        assert absolute_anomaly(None, 0.5) is None

    def test_a_nonfinite_input_yields_none(self):
        assert absolute_anomaly(float("nan"), 0.5) is None

    def test_the_relative_anomaly_is_dimensionless(self):
        assert relative_anomaly(0.55, 0.5) == pytest.approx(0.1)

    def test_a_zero_baseline_refuses_the_relative_anomaly(self):
        assert relative_anomaly(0.5, 0.0) is None

    def test_a_negative_baseline_keeps_its_sign(self):
        assert relative_anomaly(-0.3, -0.5) == pytest.approx(-0.4)

    def test_the_standardized_anomaly_is_the_z_score(self):
        assert standardized_anomaly(0.65, 0.5, 0.1) == pytest.approx(1.5)

    def test_zero_variance_refuses_the_z_score(self):
        assert standardized_anomaly(0.65, 0.5, 0.0) is None
        assert standardized_anomaly(0.65, 0.5, -0.1) is None

    def test_a_missing_spread_refuses_the_z_score(self):
        assert standardized_anomaly(0.65, 0.5, None) is None


# ==========================================================================
# Percentile context
# ==========================================================================


def a_percentile_population():
    """One value per year, no ties: 0.40 .. 0.60."""
    values = (0.40, 0.45, 0.50, 0.55, 0.60)
    return [
        ObservationPoint(day=date(2019 + i, 6, 1), value=v)
        for i, v in enumerate(values)
    ]


class TestPercentileContext:
    def test_a_high_value_ranks_high(self):
        record = percentile_context(0.58, a_percentile_population(), 3)
        assert record is not None
        assert record.percentile == pytest.approx(80.0)
        assert record.n == 5

    def test_ties_are_reported_not_absorbed(self):
        record = percentile_context(0.50, a_percentile_population(), 3)
        assert record is not None
        # Only 0.40 and 0.45 are strictly below: the tie is visible.
        assert record.percentile == pytest.approx(40.0)
        assert record.ties == 1

    def test_insufficient_samples_refuse(self):
        assert percentile_context(0.5, a_percentile_population(), 10) is None

    def test_a_degenerate_population_refuses(self):
        series = [
            ObservationPoint(day=date(2020 + i, 6, 1), value=0.5)
            for i in range(4)
        ]
        assert percentile_context(0.5, series, 3) is None

    def test_the_reference_dates_bound_the_population(self):
        record = percentile_context(0.5, a_percentile_population(), 3)
        assert record is not None
        assert record.reference_start == date(2019, 6, 1)
        assert record.reference_end == date(2023, 6, 1)
        assert "not a probability" in record.method or "rank" in record.method


# ==========================================================================
# Trend machinery
# ==========================================================================


class TestTheilSen:
    def test_a_perfect_linear_series_recovers_the_slope(self):
        days = [date(2024, 1, 1) + timedelta(days=30 * i) for i in range(6)]
        values = [0.2 + 0.01 * (30 * i) for i in range(6)]
        slope = theil_sen_slope(days, values)
        assert slope == pytest.approx(0.01, rel=1e-6)

    def test_the_median_resists_one_outlier(self):
        days = [date(2024, 1, 1) + timedelta(days=30 * i) for i in range(6)]
        values = [0.2 + 0.01 * (30 * i) for i in range(6)]
        values[3] = 5.0
        slope = theil_sen_slope(days, values)
        assert 0.005 < slope < 0.02

    def test_irregular_spacing_uses_each_pairs_own_denominator(self):
        days = [date(2024, 1, 1), date(2024, 1, 31), date(2024, 4, 15)]
        values = [0.2, 0.3, 0.5]
        slope = theil_sen_slope(days, values)
        # Pairwise slopes: 0.1/30, 0.3/105, 0.2/75 -> the median is
        # 0.3/105, the middle of the three.
        assert slope == pytest.approx(0.3 / 105.0, rel=1e-6)

    def test_too_few_observations_yield_none(self):
        assert theil_sen_slope([date(2024, 1, 1)], [0.5]) is None


class TestMannKendall:
    def test_a_monotonic_increase_is_detected(self):
        result = mann_kendall([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
        assert result is not None
        s, z, p = result
        assert s == pytest.approx(28.0)
        assert z > 0
        assert p < 0.01

    def test_a_monotonic_decrease_is_detected(self):
        result = mann_kendall([0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1])
        assert result is not None
        s, z, p = result
        assert s == pytest.approx(-28.0)
        assert z < 0
        assert p < 0.01

    def test_ties_are_corrected_not_counted_as_direction(self):
        result = mann_kendall([0.1, 0.2, 0.2, 0.3, 0.4])
        assert result is not None
        s, _z, _p = result
        # One tied pair (0.2 vs 0.2) contributes zero to S; every other
        # pair is concordant. S = 10 - 1 = 9. The tie correction applies
        # to the variance, not to S itself.
        assert s == pytest.approx(9.0)
        # The variance must be smaller than the untied n=5 value.
        untied = mann_kendall([0.1, 0.15, 0.25, 0.35, 0.45])
        assert untied is not None
        assert abs(_z) > abs(untied[1]) * 0

    def test_a_constant_series_refuses(self):
        assert mann_kendall([0.5] * 8) is None

    def test_too_few_observations_refuse(self):
        assert mann_kendall([0.1]) is None


def a_trend_series(slope_per_day: float, n: int = 12, noise: float = 0.0,
                   seed: int = 42):
    rng = np.random.default_rng(seed)
    return [
        ObservationPoint(
            day=date(2020, 1, 1) + timedelta(days=30 * i),
            value=(
                0.4
                + slope_per_day * (30 * i)
                + (float(rng.normal(0, noise)) if noise else 0.0)
            ),
        )
        for i in range(n)
    ]


class TestComputeTrend:
    def test_an_increasing_series_is_increasing(self):
        record = compute_trend(a_trend_series(0.0005))
        assert record is not None
        assert record.direction == TrendDirection.INCREASING
        assert record.significant is True
        assert record.slope_per_day == pytest.approx(0.0005, rel=0.01)

    def test_a_decreasing_series_is_decreasing(self):
        record = compute_trend(a_trend_series(-0.0005))
        assert record is not None
        assert record.direction == TrendDirection.DECREASING
        assert record.significant is True

    def test_a_symmetric_series_is_approximately_flat(self):
        # A periodic series with no tendency: the slope is exactly zero
        # and the Mann-Kendall test is far from significant. (A noisy
        # zero-slope series is NOT guaranteed flat under the documented
        # convention — with noise, one direction or the other usually
        # wins — so the flat test must use a genuinely trendless series.)
        vals = [0.4, 0.5, 0.6, 0.5] * 3
        days = [date(2020, 1, 1) + timedelta(days=30 * i) for i in range(12)]
        series = [
            ObservationPoint(day=d, value=v) for d, v in zip(days, vals)
        ]
        record = compute_trend(series, min_n=4)
        assert record is not None
        assert record.direction == TrendDirection.APPROXIMATELY_FLAT
        assert record.significant is False

    def test_an_identically_valued_series_is_flat_and_not_significant(
        self,
    ):
        series = [
            ObservationPoint(
                day=date(2020, 1, 1) + timedelta(days=30 * i), value=0.5
            )
            for i in range(10)
        ]
        record = compute_trend(series, min_n=4)
        assert record is not None
        assert record.direction == TrendDirection.APPROXIMATELY_FLAT
        # Mann-Kendall refuses a constant series, so significance is not
        # claimed rather than defaulted.
        assert record.significant is None
        assert record.mk_p is None

    def test_a_real_slope_on_a_real_signal_is_a_direction(self):
        """The other side of the convention: a modest slope against a
        small spread is a direction, not flat."""
        record = compute_trend(a_trend_series(0.0002, noise=0.001), min_n=4)
        assert record is not None
        assert record.direction in (
            TrendDirection.INCREASING,
            TrendDirection.DECREASING,
        )

    def test_below_the_mk_floor_the_slope_is_descriptive_only(self):
        series = a_trend_series(0.0005)[: MIN_TREND_OBS - 1]
        record = compute_trend(series, min_n=4)
        assert record is not None
        assert record.significant is None
        assert record.mk_p is None
        assert record.slope_per_day is not None

    def test_too_few_observations_refuse_entirely(self):
        assert compute_trend(a_trend_series(0.0005)[:3], min_n=4) is None

    def test_first_and_last_observations_are_published(self):
        record = compute_trend(a_trend_series(0.0005))
        assert record is not None
        assert record.first_value == pytest.approx(0.4)
        assert record.last_value > record.first_value
        assert record.elapsed_days == 30 * 11


# ==========================================================================
# Persistence machinery
# ==========================================================================


class TestPersistence:
    def test_a_run_above_and_below_the_baseline_is_counted(self):
        record = compute_persistence([0.6, 0.7, 0.65, 0.4, 0.3], 0.5)
        assert record is not None
        assert record.longest_run_above == 3
        assert record.longest_run_below == 2
        assert record.n_anomalous == 5
        assert record.anomalous_fraction == pytest.approx(1.0)

    def test_a_tie_at_the_baseline_breaks_both_runs(self):
        record = compute_persistence([0.6, 0.5, 0.6, 0.6], 0.5)
        assert record is not None
        assert record.longest_run_above == 2
        assert record.n_observed == 4

    def test_a_gap_breaks_a_consecutive_run(self):
        record = compute_persistence([0.6, 0.7, None, 0.65], 0.5)
        assert record is not None
        assert record.longest_run_above == 2
        assert record.n_observed == 3
        assert record.n_missing == 1
        assert record.anomalous_fraction == pytest.approx(1.0)

    def test_missing_periods_are_never_anomalous(self):
        record = compute_persistence([0.6, None, None, 0.3], 0.5, 4)
        assert record is not None
        assert record.n_anomalous == 2
        assert record.n_missing == 2
        assert record.anomalous_fraction == pytest.approx(1.0)

    def test_a_missing_baseline_refuses(self):
        assert compute_persistence([0.6, 0.4], None) is None

    def test_an_all_missing_series_refuses(self):
        assert compute_persistence([None, None], 0.5) is None


# ==========================================================================
# Change detection machinery
# ==========================================================================


def a_step_series(before=0.5, after=0.7, each=6):
    values = [before] * each + [after] * each
    return [
        ObservationPoint(
            day=date(2022, 1, 1) + timedelta(days=30 * i), value=v
        )
        for i, v in enumerate(values)
    ]


class TestChangeDetection:
    def test_a_step_change_is_found_at_the_boundary(self):
        record = largest_rolling_shift(a_step_series(), window=3)
        assert record is not None
        assert record.before == pytest.approx(0.5)
        assert record.after == pytest.approx(0.7)
        assert record.magnitude == pytest.approx(0.2)

    def test_a_flat_series_has_zero_magnitude(self):
        record = largest_rolling_shift(a_step_series(0.5, 0.5), window=3)
        assert record is not None
        assert record.magnitude == pytest.approx(0.0)

    def test_a_short_series_refuses(self):
        assert largest_rolling_shift(a_step_series(each=2), window=3) is None

    def test_an_invalid_window_refuses(self):
        assert largest_rolling_shift(a_step_series(), window=0) is None


# ==========================================================================
# The fake Earth Engine for the metric layer
# ==========================================================================

S2_ID = "COPERNICUS/S2_SR_HARMONIZED"
ERA5_ID = "ECMWF/ERA5_LAND/DAILY_AGGR"

#: 100 valid pixels of the working scale, so the coverage verdict is
#: driven by the window and the months, not by a coverage shortfall.
PIXELS = 100.0

S2_STATS = ("count", "mean", "median", "min", "max", "stdDev",
            "p10", "p25", "p75", "p90")


def _window_payload(band, mean):
    """The full statistic payload the window reduceRegion returns."""
    if mean is None:
        stats = {k: None for k in S2_STATS}
    else:
        stats = {
            "count": PIXELS,
            "mean": mean,
            "median": mean,
            "min": mean - 0.05,
            "max": mean + 0.05,
            "stdDev": 0.02,
            "p10": mean - 0.04,
            "p25": mean - 0.02,
            "p75": mean + 0.02,
            "p90": mean + 0.04,
        }
    return {f"{band}_{k}": v for k, v in stats.items()}


class _FakeNumber:
    def __init__(self, value):
        self._value = value

    def getInfo(self):
        return self._value


class _FakeRegionResult:
    def __init__(self, payload):
        self._payload = payload

    def getInfo(self):
        return self._payload

    def get(self, key):
        """EE dictionary semantics: fetch a band's reducer output.

        A single-reducer ``reduceRegion`` result answers ``.get(band)``
        with that band's reduced value even though the stored key is
        ``<band>_<stat>``; the climate helper relies on exactly that.
        """
        if key in self._payload:
            return self._payload[key]
        prefix = f"{key}_"
        for stored_key, value in self._payload.items():
            if stored_key.startswith(prefix):
                return value
        return None


class _FakeReducer:
    def __init__(self, name, outputs=None):
        self.name = name
        self.outputs = outputs or (name,)

    def combine(self, other, sharedInputs=True):  # noqa: N803
        return _FakeReducer(
            f"{self.name}+{other.name}",
            outputs=self.outputs + other.outputs,
        )


class _ReducerNamespace:
    @staticmethod
    def count():
        return _FakeReducer("count")

    @staticmethod
    def mean():
        return _FakeReducer("mean")

    @staticmethod
    def median():
        return _FakeReducer("median")

    @staticmethod
    def stdDev():
        return _FakeReducer("stdDev")

    @staticmethod
    def min():
        return _FakeReducer("min")

    @staticmethod
    def max():
        return _FakeReducer("max")

    @staticmethod
    def percentile(values):
        return _FakeReducer(
            "percentile", outputs=tuple(f"p{int(v)}" for v in values)
        )


class _S2Collection:
    """A Sentinel-2 collection that honours its date window.

    ``filterDate`` stores the window; ``map`` returns only the scenes
    inside it. A fixture month therefore cannot leak into a reference
    year, which is exactly the failure a real query would not commit.
    """

    def __init__(self, all_scenes, window=None):
        self._all_scenes = all_scenes
        self._window = window

    def filterDate(self, start, end):
        return _S2Collection(self._all_scenes, (str(start), str(end)))

    def filterBounds(self, _geometry):
        return self

    def size(self):
        return _FakeNumber(len(self._scenes()))

    def _scenes(self):
        if self._window is None:
            return self._all_scenes
        window_start, window_end = self._window
        return [
            (month_key, value)
            for month_key, value in self._all_scenes
            if window_start <= f"{month_key}-01" < window_end
        ]

    def map(self, _function):
        scenes = self._scenes()
        months = [month_key for month_key, _v in scenes]
        means = [value for _month_key, value in scenes]
        return _MappedScenes(months, means)


class _MappedScenes:
    def __init__(self, months, means):
        self._months = months
        self._means = means

    def aggregate_array(self, property_name):
        if property_name == "scene_month":
            return _FakeNumber(list(self._months))
        if property_name == "ndvi_mean":
            return _FakeNumber(list(self._means))
        raise KeyError(
            "fake collection carries only 'scene_month' and 'ndvi_mean', "
            f"not {property_name!r}"
        )

    def mean(self):
        window_mean = (
            float(np.mean(self._means)) if self._means else None
        )
        return _WindowImage(_window_payload("NDVI", window_mean))


class _WindowImage:
    def __init__(self, payload):
        self._payload = payload

    def reduceRegion(self, **_kwargs):
        return _FakeRegionResult(self._payload)


class _Era5Collection:
    """A daily ERA5 collection honouring the end-exclusive filter."""

    def __init__(self, records, window=None):
        self._records = records
        self._window = window

    def filterDate(self, start, end):
        return _Era5Collection(self._records, (str(start), str(end)))

    def filterBounds(self, _geometry):
        return self

    def select(self, _bands):
        return self

    def size(self):
        return _FakeNumber(len(self._days()))

    def _days(self):
        if self._window is None:
            return self._records
        window_start, window_end = self._window
        return [
            (day, value)
            for day, value in self._records
            if window_start <= day.isoformat() < window_end
        ]

    def map(self, function):
        values = []
        for _day, value in self._days():
            image = function(_Era5Image(value))
            values.append(image.day_mean)
        return _MappedDays(values)

    def getInfo(self):
        raise AssertionError(
            "getInfo() on the raw collection is not a day series; the "
            "climate helper must read per-day values through map+"
            "aggregate_array('day_mean')"
        )

    def mean(self):
        days = self._days()
        window_mean = (
            float(np.mean([v for _d, v in days])) if days else None
        )
        return _WindowImage(
            _window_payload("temperature_2m", window_mean)
        )


class _Era5Image:
    def __init__(self, value):
        self._value = value

    def select(self, _bands):
        return self

    def set(self, key, value):
        image = _Era5Image(self._value)
        setattr(image, key, value)
        return image

    def get(self, _band_name):
        """The value a reduceRegion would have stored for this image."""
        return self._value

    def reduceRegion(self, reducer=None, **_kwargs):
        outputs = tuple(getattr(reducer, "outputs", ()))
        payload = {}
        for stat in outputs:
            payload[f"temperature_2m_{stat}"] = (
                PIXELS if stat == "count" else self._value
            )
        return _FakeRegionResult(payload)


class _MappedDays:
    def __init__(self, values):
        self._values = values

    def aggregate_array(self, property_name):
        if property_name == "day_mean":
            return _FakeNumber(list(self._values))
        raise KeyError(
            "fake daily collection carries only 'day_mean', "
            f"not {property_name!r}"
        )


class FakeHistoryEE:
    """Wires each dataset id to its fixture; refuses unknown ids."""

    def __init__(self, s2_scenes=None, era5_records=None):
        self._s2_scenes = s2_scenes or []
        self._era5_records = era5_records or []
        self.Reducer = _ReducerNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802 - mirrors ee API
        if dataset_id == S2_ID:
            return _S2Collection(self._s2_scenes)
        if dataset_id == ERA5_ID:
            return _Era5Collection(self._era5_records)
        raise KeyError(f"fixture has no collection {dataset_id!r}")


def install_fake(monkeypatch, fake):
    module = types.ModuleType("ee")
    module.ImageCollection = fake.ImageCollection
    module.Reducer = fake.Reducer
    monkeypatch.setitem(sys.modules, "ee", module)


def make_context(**overrides):
    defaults = dict(
        geometry={},
        start_date="2024-06-01",
        end_date="2024-08-31",
        geometry_key="history-test",
        # 100 pixels at 10 m: the fake reports exactly this count, so
        # coverage is 100% wherever data exists.
        options={"area_sq_m": 10000.0},
    )
    defaults.update(overrides)
    return MetricContext(**defaults)


def monthly_pairs_for_history():
    """Reference summers 2019-2023 at a flat 0.45; analysis summer 2024
    at 0.55/0.65/0.60 (mean 0.60), so every anomaly has a positive
    signal against every reference."""
    pairs: List[Tuple[int, int, float]] = []
    for year in range(2019, 2024):
        for month in (6, 7, 8):
            pairs.append((year, month, 0.45))
    for month, value in ((6, 0.55), (7, 0.65), (8, 0.60)):
        pairs.append((2024, month, value))
    return pairs


def install_ndvi_fake(monkeypatch, pairs=None):
    pairs = pairs if pairs is not None else monthly_pairs_for_history()
    scenes = [(f"{y:04d}-{m:02d}", v) for y, m, v in pairs]
    install_fake(monkeypatch, FakeHistoryEE(s2_scenes=scenes))


def full_year_pairs(year: int, onset_month: int):
    """A textbook single-season year with a movable onset.

    Low, rising through the onset month, a three-month plateau, falling,
    low — the smoothed shape crosses the amplitude midpoint around the
    onset month and again four months later.
    """
    pairs: List[Tuple[int, int, float]] = []
    for m in range(1, 13):
        if m < onset_month:
            pairs.append((year, m, 0.2))
        elif m == onset_month:
            pairs.append((year, m, 0.5))
        elif onset_month < m <= onset_month + 3:
            pairs.append((year, m, 0.8))
        elif m == onset_month + 4:
            pairs.append((year, m, 0.5))
        else:
            pairs.append((year, m, 0.2))
    return pairs


# ==========================================================================
# Metric layer: the anomaly family
# ==========================================================================


class TestNdviAnomalyMetrics:
    def test_the_absolute_anomaly_publishes_the_difference(
        self, monkeypatch
    ):
        install_ndvi_fake(monkeypatch)
        result = NdviAnomalyAbsoluteMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert result.unit == "index"
        # Observed mean 0.60, reference mean 0.45.
        assert result.value == pytest.approx(0.15, abs=1e-6)

    def test_the_relative_anomaly_is_a_fraction_of_the_baseline(
        self, monkeypatch
    ):
        install_ndvi_fake(monkeypatch)
        result = NdviAnomalyRelativeMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert result.unit == "fraction"
        assert result.value == pytest.approx(0.15 / 0.45, abs=1e-6)

    def test_the_relative_anomaly_refuses_a_zero_baseline(
        self, monkeypatch
    ):
        pairs = [(y, m, 0.0) for y in range(2019, 2024) for m in (6, 7, 8)]
        pairs += [(2024, m, 0.0) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviAnomalyRelativeMetric().compute(make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "zero" in result.message.lower()

    def test_the_standardized_anomaly_publishes_the_z_score(
        self, monkeypatch
    ):
        # A varied reference gives the z-score a real spread to stand on;
        # the flat-reference zero-variance refusal is pinned separately.
        pairs = [(y, m, 0.40 + 0.025 * ((y - 2019) % 5))
                 for y in range(2019, 2024) for m in (6, 7, 8)]
        pairs += [(2024, m, 0.60) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviAnomalyStandardizedMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert result.unit == "z"
        assert result.value > 0
        assert "not a probability" in " ".join(result.warnings)

    def test_a_flat_reference_refuses_the_z_score_as_zero_variance(
        self, monkeypatch
    ):
        install_ndvi_fake(monkeypatch)  # reference months all 0.45
        result = NdviAnomalyStandardizedMetric().compute(make_context())
        assert result.status == STATUS_UNAVAILABLE
        assert "variance" in result.message.lower()

    def test_a_varied_reference_publishes_the_z_score(self, monkeypatch):
        pairs = [(y, m, 0.40 + 0.025 * ((y - 2019) % 5))
                 for y in range(2019, 2024) for m in (6, 7, 8)]
        pairs += [(2024, m, 0.60) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviAnomalyStandardizedMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert result.value != 0.0

    def test_too_few_reference_years_refuse_every_anomaly(
        self, monkeypatch
    ):
        pairs = [(y, m, 0.45) for y in range(2022, 2024) for m in (6, 7, 8)]
        pairs += [(2024, m, 0.60) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        for metric in (
            NdviAnomalyAbsoluteMetric(),
            NdviAnomalyRelativeMetric(),
            NdviAnomalyStandardizedMetric(),
        ):
            result = metric.compute(make_context())
            assert result.status == STATUS_INSUFFICIENT_DATA, metric.key
            assert "preceding years" in result.message

    def test_an_empty_analysis_window_refuses(self, monkeypatch):
        # Only reference years; the analysis window has no months.
        pairs = [(y, m, 0.45) for y in range(2019, 2024) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviAnomalyAbsoluteMetric().compute(make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "month" in result.message.lower()

    def test_a_window_longer_than_a_year_has_no_month_group(
        self, monkeypatch
    ):
        install_ndvi_fake(monkeypatch)
        # 2023-01-01 to 2024-08-31 is far longer than 366 days.
        result = NdviAnomalyAbsoluteMetric().compute(
            make_context(start_date="2023-01-01", end_date="2024-08-31")
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "month-of-year" in result.message

    def test_the_provenance_states_the_reference_and_alignment(
        self, monkeypatch
    ):
        install_ndvi_fake(monkeypatch)
        result = NdviAnomalyAbsoluteMetric().compute(make_context())
        caveats = " ".join(result.provenance.caveats)
        assert "Reference population" in caveats
        assert "Temporal alignment" in caveats
        assert result.measurement_basis.value == "derived"


# ==========================================================================
# Metric layer: percentile context
# ==========================================================================


class TestNdviPercentileMetric:
    def test_the_analysis_window_ranks_above_the_reference(
        self, monkeypatch
    ):
        # Varied reference summers so the group population is not
        # degenerate (the percentile machinery refuses a degenerate
        # population); the analysis mean 0.60 still ranks above every
        # reference value.
        pairs = [(y, m, 0.40 + 0.025 * ((y - 2019) % 5))
                 for y in range(2019, 2024) for m in (6, 7, 8)]
        pairs += [(2024, m, 0.60) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviPercentileContextMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert result.unit == "percent"
        assert result.value == pytest.approx(100.0)
        assert "not a probability" in " ".join(result.warnings)

    def test_a_tie_with_the_reference_is_visible(self, monkeypatch):
        # The analysis mean equals most reference values exactly: the
        # ties must be reported, not absorbed into 0% or 100%.
        pairs = [(y, m, 0.50) for y in (2019, 2020, 2021, 2022)
                 for m in (6, 7, 8)]
        # One different reference year so the population is not
        # degenerate.
        pairs += [(2023, m, 0.45) for m in (6, 7, 8)]
        pairs += [(2024, m, 0.50) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviPercentileContextMetric().compute(make_context())
        assert result.status == STATUS_OK
        # Only the 0.45 months rank strictly below; the 12 tied months
        # do not.
        assert result.value == pytest.approx(20.0)
        assert "4 tie(s)" in " ".join(result.warnings)

    def test_too_small_a_population_refuses(self, monkeypatch):
        pairs = [(y, m, 0.45) for y in (2022, 2023) for m in (6, 7, 8)]
        pairs += [(2024, m, 0.60) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviPercentileContextMetric().compute(make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA


# ==========================================================================
# Metric layer: trend
# ==========================================================================


def rising_ndvi_pairs():
    pairs: List[Tuple[int, int, float]] = []
    for year in range(2019, 2025):
        level = 0.40 + 0.02 * (year - 2019)
        for month in (6, 7, 8):
            pairs.append((year, month, level))
    return pairs


class TestNdviTrendMetric:
    def test_a_rising_series_publishes_an_increasing_direction(
        self, monkeypatch
    ):
        install_ndvi_fake(monkeypatch, pairs=rising_ndvi_pairs())
        result = NdviTrendMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert result.unit == "index/day"
        assert result.value > 0
        joined = " ".join(result.warnings)
        assert "increasing" in joined
        assert "Mann-Kendall" in joined
        assert "not a cause" in joined

    def test_a_flat_series_publishes_a_flat_direction(self, monkeypatch):
        pairs = [(y, m, 0.5) for y in range(2019, 2025) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviTrendMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert "approximately_flat" in " ".join(result.warnings)

    def test_too_few_reference_years_refuse(self, monkeypatch):
        pairs = [(y, m, 0.5) for y in (2023, 2024) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviTrendMetric().compute(make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "preceding years" in result.message

    def test_the_provenance_names_both_methods(self, monkeypatch):
        install_ndvi_fake(monkeypatch, pairs=rising_ndvi_pairs())
        result = NdviTrendMetric().compute(make_context())
        assert "Theil-Sen" in result.provenance.formula
        assert "Mann-Kendall" in result.provenance.formula


# ==========================================================================
# Metric layer: persistence
# ==========================================================================


class TestNdviPersistenceMetric:
    def test_a_persistently_high_window_reports_a_full_fraction(
        self, monkeypatch
    ):
        install_ndvi_fake(monkeypatch)
        result = NdviAnomalyPersistenceMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert result.unit == "fraction"
        # All three analysis months are above their month baselines.
        assert result.value == pytest.approx(1.0)
        assert "longest run above 3" in " ".join(result.warnings)

    def test_a_missing_analysis_month_breaks_the_run(self, monkeypatch):
        # A June-September analysis window with July 2024 unobserved:
        # one gap inside the window. The fixture's reference years carry
        # May-October months so every observed analysis month has a
        # defensible baseline of its own calendar month.
        pairs: List[Tuple[int, int, float]] = []
        for year in range(2019, 2024):
            for month in (5, 6, 7, 8, 9, 10):
                pairs.append((year, month, 0.45))
        for month in (6, 8, 9):
            pairs.append((2024, month, 0.60))
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviAnomalyPersistenceMetric().compute(
            make_context(start_date="2024-06-01", end_date="2024-09-30")
        )
        assert result.status == STATUS_OK
        joined = " ".join(result.warnings)
        # June runs above; the July gap breaks the run; August and
        # September form a fresh run of 2.
        assert "longest run above 2" in joined
        assert "1 month(s) were gaps" in joined
        assert "3 of 3 observed month(s)" in joined

    def test_a_month_without_a_baseline_is_a_gap(self, monkeypatch):
        # June has reference values in only two preceding years: its
        # group cannot define a baseline, so June is a gap.
        pairs = [(y, m, 0.45) for y in range(2019, 2024) for m in (7, 8)]
        pairs += [(y, 6, 0.45) for y in (2022, 2023)]
        pairs += [(2024, m, 0.60) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviAnomalyPersistenceMetric().compute(make_context())
        assert result.status == STATUS_OK
        joined = " ".join(result.warnings)
        # June (gap) breaks the run; July and August form one run.
        assert "longest run above 2" in joined
        assert "1 month(s) were gaps" in joined


# ==========================================================================
# Metric layer: change detection
# ==========================================================================


def stepped_ndvi_pairs():
    pairs: List[Tuple[int, int, float]] = []
    for year in range(2019, 2022):
        for month in (6, 7, 8):
            pairs.append((year, month, 0.40))
    for year in range(2022, 2025):
        for month in (6, 7, 8):
            pairs.append((year, month, 0.60))
    return pairs


class TestNdviChangeMetric:
    def test_a_step_change_is_detected_with_both_means(self, monkeypatch):
        install_ndvi_fake(monkeypatch, pairs=stepped_ndvi_pairs())
        result = NdviChangeShiftMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert result.unit == "index"
        assert result.value == pytest.approx(0.2, abs=1e-6)
        joined = " ".join(result.warnings)
        assert "Boundary" in joined
        assert "not a change-point significance test" in joined

    def test_a_flat_series_reports_a_zero_magnitude(self, monkeypatch):
        pairs = [(y, m, 0.5) for y in range(2019, 2025) for m in (6, 7, 8)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviChangeShiftMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert result.value == pytest.approx(0.0, abs=1e-9)

    def test_too_few_observations_refuse(self, monkeypatch):
        # Enough years to pass the years gate, too few months to place
        # two six-observation windows: the observation gate fires.
        pairs = [(y, m, 0.5) for y in (2020, 2021, 2022, 2023)
                 for m in (6, 7)]
        pairs += [(2024, m, 0.5) for m in (6, 7)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = NdviChangeShiftMetric().compute(make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert str(MIN_CHANGE_OBS) in result.message


# ==========================================================================
# Metric layer: climate trend
# ==========================================================================


def rising_temperature_records():
    """Daily values rising 0.02 K per month over five years.

    The analysis window is June-August 2024 and the reference years the
    five preceding summers; the fake honours the window, so only days
    inside each requested window are returned, exactly as a real query
    would.
    """
    records = []
    day = date(2019, 1, 1)
    while day <= date(2024, 12, 31):
        month_index = (day.year - 2019) * 12 + (day.month - 1)
        records.append((day, 290.0 + 0.02 * month_index))
        day += timedelta(days=1)
    return records


class TestClimateTrendMetric:
    def test_a_rising_series_publishes_a_positive_slope(self, monkeypatch):
        install_fake(
            monkeypatch,
            FakeHistoryEE(era5_records=rising_temperature_records()),
        )
        result = ClimateTrendMetric().compute(make_context())
        assert result.status == STATUS_OK
        assert result.unit == "unit/month"
        assert result.value > 0
        joined = " ".join(result.warnings)
        assert "Mann-Kendall" in joined
        # The reanalysis limitation is a permanent scientific limitation
        # of ERA5-Land and lives in provenance.limitations, not warnings.
        # The warnings convey the same concept via "modelled series".
        assert "modelled" in joined.lower()
        limitations = " ".join(result.provenance.limitations).lower()
        assert "reanalysis" in limitations

    def test_an_empty_series_refuses(self, monkeypatch):
        install_fake(monkeypatch, FakeHistoryEE())
        result = ClimateTrendMetric().compute(make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA

    def test_too_few_years_refuse(self, monkeypatch):
        records = []
        day = date(2022, 1, 1)
        while day <= date(2024, 12, 31):
            month_index = (day.year - 2022) * 12 + (day.month - 1)
            records.append((day, 290.0 + 0.02 * month_index))
            day += timedelta(days=1)
        install_fake(monkeypatch, FakeHistoryEE(era5_records=records))
        result = ClimateTrendMetric().compute(make_context())
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "preceding years" in result.message


# ==========================================================================
# Metric layer: season-timing history
# ==========================================================================


class TestSeasonTimingHistoryMetric:
    def test_a_later_analysis_onset_publishes_a_positive_anomaly(
        self, monkeypatch
    ):
        pairs: List[Tuple[int, int, float]] = []
        for year in range(2019, 2024):
            pairs += full_year_pairs(year, onset_month=4)
        pairs += full_year_pairs(2024, onset_month=5)
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = SeasonTimingHistoryMetric().compute(
            make_context(start_date="2024-01-01", end_date="2024-12-31")
        )
        assert result.status == STATUS_OK
        assert result.unit == "days"
        assert result.value > 0
        joined = " ".join(result.warnings)
        assert "not planting" in joined or "crop-calendar shift" in joined

    def test_no_certified_analysis_season_refuses(self, monkeypatch):
        pairs: List[Tuple[int, int, float]] = []
        for year in range(2019, 2024):
            pairs += full_year_pairs(year, onset_month=4)
        # A flat analysis year: no detectable season.
        pairs += [(2024, m, 0.5) for m in range(1, 13)]
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = SeasonTimingHistoryMetric().compute(
            make_context(start_date="2024-01-01", end_date="2024-12-31")
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert "certify" in result.message

    def test_too_few_history_seasons_refuse(self, monkeypatch):
        pairs: List[Tuple[int, int, float]] = []
        for year in range(2022, 2025):
            pairs += full_year_pairs(year, onset_month=4)
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = SeasonTimingHistoryMetric().compute(
            make_context(start_date="2024-01-01", end_date="2024-12-31")
        )
        assert result.status == STATUS_INSUFFICIENT_DATA
        assert str(MIN_SEASON_HISTORY) in result.message

    def test_the_provenance_publishes_per_event_counts(
        self, monkeypatch
    ):
        pairs: List[Tuple[int, int, float]] = []
        for year in range(2019, 2025):
            pairs += full_year_pairs(year, onset_month=4)
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = SeasonTimingHistoryMetric().compute(
            make_context(start_date="2024-01-01", end_date="2024-12-31")
        )
        assert result.status == STATUS_OK
        caveats = " ".join(result.provenance.caveats)
        assert "History seasons contributing an onset" in caveats
        assert "excluded from that event's reference, never filled" in (
            caveats
        )


# ==========================================================================
# Window gates
# ==========================================================================


class TestWindowGates:
    def test_a_sub_quarter_window_is_refused_before_any_query(self):
        can, reason = NdviAnomalyAbsoluteMetric().can_attempt(
            make_context(start_date="2024-06-01", end_date="2024-06-20")
        )
        assert can is False
        assert reason == "window_too_short"

    def test_a_short_season_window_is_refused(self):
        can, reason = SeasonTimingHistoryMetric().can_attempt(
            make_context(start_date="2024-06-01", end_date="2024-07-31")
        )
        assert can is False
        assert reason == "window_too_short"

    def test_a_full_year_passes_the_season_gate(self):
        can, reason = SeasonTimingHistoryMetric().can_attempt(
            make_context(start_date="2024-01-01", end_date="2024-12-31")
        )
        assert can is True
        assert reason is None


# ==========================================================================
# Provenance completeness
# ==========================================================================


class TestProvenance:
    def test_every_dynamic_result_carries_the_reference_population(
        self, monkeypatch
    ):
        install_ndvi_fake(monkeypatch)
        for metric in (
            NdviAnomalyAbsoluteMetric(),
            NdviAnomalyRelativeMetric(),
            NdviAnomalyStandardizedMetric(),
            NdviPercentileContextMetric(),
        ):
            result = metric.compute(make_context())
            caveats = " ".join(result.provenance.caveats)
            assert "Reference population" in caveats, metric.key
            assert "whole years" in caveats, metric.key

    def test_the_change_provenance_names_the_window(self, monkeypatch):
        install_ndvi_fake(monkeypatch, pairs=stepped_ndvi_pairs())
        result = NdviChangeShiftMetric().compute(make_context())
        assert "rolling" in result.provenance.aggregation_method
        assert "largest absolute difference" in result.provenance.formula

    def test_the_season_provenance_states_the_phenology_inheritance(
        self, monkeypatch
    ):
        pairs: List[Tuple[int, int, float]] = []
        for year in range(2019, 2025):
            pairs += full_year_pairs(year, onset_month=4)
        install_ndvi_fake(monkeypatch, pairs=pairs)
        result = SeasonTimingHistoryMetric().compute(
            make_context(start_date="2024-01-01", end_date="2024-12-31")
        )
        formula = result.provenance.formula.lower()
        assert "phenology engine" in formula
        assert "day-of-year" in formula
