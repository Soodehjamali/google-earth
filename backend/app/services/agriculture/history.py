"""Historical analytics: baseline, trend, change detection (Phase N).

One framework, not a second one. This module **extends** the Phase K
anomaly foundation in :mod:`app.services.agriculture.stress` and reuses
its primitives verbatim: ``shift_window_years`` and ``baseline_windows``
for the whole-year calendar offsets with leap-day folding,
``summarise_baseline`` for the None-exclusion policy, and the
percentile machinery's refusal rules. Nothing here restates those
functions, so the two layers cannot drift.

What this module adds, and its boundary
---------------------------------------
Phase K answered "how does this window compare with the same calendar
window in preceding years?". Phase N adds the rest of the descriptive
historical vocabulary: baseline strategies over month-of-year and
full-period groupings, relative and standardized anomalies, percentile
context, a descriptive trend with an optional Mann-Kendall significance
test, persistence of baseline deviations, and rolling-mean change
detection. Every one of them is **descriptive**:

* a historical anomaly is not a diagnosis,
* a trend is not causality,
* a percentile is a rank within a stated reference population, never a
  probability of any outcome,
* the vegetation season is not the crop calendar.

The module never converts missing data into zero, never interpolates
across gaps, and refuses — rather than degrades — when the reference
population is too small, degenerate, or absent.

Temporal semantics
------------------
The Phase H ``TemporalKind`` contract is enforced, not weakened. A
historical series can only be built from a dataset whose dates are
observations. The four STATIC datasets in the registry (SoilGrids,
NASADEM, SRTM) are refused by :func:`require_temporal_series` with the
machine-readable reason ``static_dataset_no_historical_series``: their
acquisition dates are product metadata, and computing a trend across
them would manufacture a time series out of a single surface.

Statistical method note
-----------------------
The trend is the Theil-Sen median of pairwise slopes — robust to the
outliers that cloud gaps and single-scene noise produce, and defined
for irregularly spaced observations because each pair contributes its
own time denominator. Significance is reported only from the
Mann-Kendall test (with tie correction and continuity correction, and
the normal-approximation p-value computed from ``math.erf``), and only
when the observation count reaches :data:`MIN_TREND_OBS`; below that
the slope is still published, explicitly labelled descriptive. No
advanced statistics package was added: numpy and the standard library
are sufficient.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.core.logging import get_logger
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.phenology import (
    _date_to_decimal_year,
    build_monthly_series_from_context,
    detect_season_events,
)
from app.services.agriculture.quality import (
    MODIS_THRESHOLDS,
    SENTINEL2_THRESHOLDS,
    assess_quality,
    combine_quality,
    describe_quality,
)
from app.services.agriculture.stress import (
    _shift_context,
    percentile_of_value,
    shift_window_years,
    summarise_baseline,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    TemporalKind,
)

logger = get_logger(__name__)

__all__ = [
    # Reason codes
    "STATIC_NO_SERIES_CODE",
    "ZERO_VARIANCE_CODE",
    "MISSING_BASELINE_CODE",
    "INSUFFICIENT_OBSERVATIONS_CODE",
    "EXCESSIVE_MISSING_CODE",
    "INSUFFICIENT_SEASONAL_COVERAGE_CODE",
    "UNSUPPORTED_TEMPORAL_RESOLUTION_CODE",
    "INCOMPATIBLE_SPATIAL_CONTEXT_CODE",
    # Guards
    "require_temporal_series",
    # Baseline machinery
    "BaselineStrategy",
    "BaselineSummary",
    "compute_baseline",
    # Anomaly machinery
    "absolute_anomaly",
    "relative_anomaly",
    "standardized_anomaly",
    # Percentile context
    "PercentileContext",
    "percentile_context",
    # Trend machinery
    "TrendDirection",
    "TrendRecord",
    "theil_sen_slope",
    "mann_kendall",
    "compute_trend",
    # Persistence
    "PersistenceRecord",
    "compute_persistence",
    # Change detection
    "ChangeRecord",
    "largest_rolling_shift",
    # Series carrier
    "ObservationPoint",
    # Metrics
    "NdviAnomalyAbsoluteMetric",
    "NdviAnomalyRelativeMetric",
    "NdviAnomalyStandardizedMetric",
    "NdviPercentileContextMetric",
    "NdviTrendMetric",
    "NdviAnomalyPersistenceMetric",
    "NdviChangeShiftMetric",
    "ClimateTrendMetric",
    "SeasonTimingHistoryMetric",
    "UnavailableStaticHistoryMetric",
    "HISTORY_METRICS",
    "UNAVAILABLE_HISTORY_METRICS",
    "ALL_HISTORY_METRICS",
    "HISTORY_BASELINE_YEARS",
    "HISTORY_MIN_YEARS",
    "generate_historical_comparison",
]


# ==========================================================================
# Machine-readable reason codes
# ==========================================================================

STATIC_NO_SERIES_CODE = "static_dataset_no_historical_series"
ZERO_VARIANCE_CODE = "zero_variance"
MISSING_BASELINE_CODE = "missing_baseline"
INSUFFICIENT_OBSERVATIONS_CODE = "insufficient_observations"
EXCESSIVE_MISSING_CODE = "excessive_missing_data"
INSUFFICIENT_SEASONAL_COVERAGE_CODE = "insufficient_seasonal_coverage"
UNSUPPORTED_TEMPORAL_RESOLUTION_CODE = "unsupported_temporal_resolution"
INCOMPATIBLE_SPATIAL_CONTEXT_CODE = "incompatible_spatial_context"


# ==========================================================================
# The temporal-semantics guard
# ==========================================================================


def require_temporal_series(dataset: Any) -> Optional[str]:
    """Refuse a historical computation on a STATIC dataset.

    A static product's dates record when the surface was surveyed, not
    when observations were made. A "trend" across a single DEM would be
    a trend of nothing. Returns the machine-readable reason when the
    dataset is static and ``None`` when a historical series is
    legitimate.
    """
    if dataset is None:
        return MISSING_BASELINE_CODE
    if getattr(dataset, "temporal_kind", TemporalKind.OBSERVATION) is (
        TemporalKind.STATIC
    ):
        return STATIC_NO_SERIES_CODE
    return None


# ==========================================================================
# Series carrier
# ==========================================================================


@dataclass(frozen=True)
class ObservationPoint:
    """One observation of a series: a real date and a physical value.

    Dates carry the observation's own resolution (a monthly composite is
    dated to its first day). A missing period is absent from the series
    — it is never carried as a zero and never interpolated.
    """

    day: date
    value: float


# ==========================================================================
# Baseline machinery
# ==========================================================================


class BaselineStrategy(str, Enum):
    """How a reference population is grouped before summarising.

    One strategy does not fit every metric: a month-of-year baseline
    respects seasonality but needs several years of data; a full-period
    baseline needs few observations but folds the seasonal cycle into
    the reference, so it is only meaningful for a series without a
    seasonal cycle (or for comparing like-with-like periods). The
    strategy is always stated in the provenance.
    """

    FULL_PERIOD = "full_period"
    MONTH_OF_YEAR = "month_of_year"
    SEASON_OF_YEAR = "season_of_year"


#: Meteorological season of each calendar month (1-based).
_MONTH_SEASON = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}


def _group_key(strategy: BaselineStrategy, day: date) -> Optional[str]:
    """The reference group an observation belongs to, or ``None``."""
    if strategy is BaselineStrategy.FULL_PERIOD:
        return "all"
    if strategy is BaselineStrategy.MONTH_OF_YEAR:
        return f"{day.month:02d}"
    if strategy is BaselineStrategy.SEASON_OF_YEAR:
        return _MONTH_SEASON[day.month]
    return None


@dataclass(frozen=True)
class BaselineSummary:
    """A statistical reference, with everything needed to audit it.

    A baseline is a statistical summary of a stated reference
    population. It is **not** a biological optimum and not a target.
    """

    strategy: BaselineStrategy
    #: The group this summary describes ("all", "01".."12", or a
    #: meteorological season).
    group: str
    mean: float
    std: Optional[float]
    n: int
    #: First and last observation dates that contributed.
    reference_start: date
    reference_end: date
    #: Sample standard deviation denominator warning: with fewer than
    #: MIN_BASELINE_GROUP observations the spread is not trustworthy.
    spread_reliable: bool


def compute_baseline(
    series: Sequence[ObservationPoint],
    strategy: BaselineStrategy,
    group: str = "all",
    min_n: int = 3,
) -> Optional[BaselineSummary]:
    """Summarise the reference population of one group.

    Returns ``None`` when fewer than ``min_n`` observations belong to
    the group — an under-populated reference is refused, never
    approximated. The spread is the sample standard deviation; it is
    flagged unreliable below :data:`MIN_BASELINE_GROUP` observations so
    a standardized anomaly computed from it can refuse honestly.
    """
    values = [
        point.value
        for point in series
        if _group_key(strategy, point.day) == group
    ]
    n = len(values)
    if n < max(min_n, 2):
        return None
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1)) if n >= 2 else None
    members = [
        point
        for point in series
        if _group_key(strategy, point.day) == group
    ]
    return BaselineSummary(
        strategy=strategy,
        group=group,
        mean=mean,
        std=std,
        n=n,
        reference_start=min(point.day for point in members),
        reference_end=max(point.day for point in members),
        spread_reliable=n >= MIN_BASELINE_GROUP,
    )


# ==========================================================================
# Anomaly machinery — extends Phase K's compute_anomaly
# ==========================================================================


def absolute_anomaly(observed: Optional[float], baseline: Optional[float]) -> Optional[float]:
    """``observed - baseline`` in the metric's own unit.

    ``None`` when either side is missing: the absence of a baseline is
    not a zero anomaly (the Phase K rule, restated as a delegation).
    """
    if observed is None or baseline is None:
        return None
    if not (math.isfinite(observed) and math.isfinite(baseline)):
        return None
    return float(observed) - float(baseline)


def relative_anomaly(
    observed: Optional[float], baseline: Optional[float]
) -> Optional[float]:
    """``(observed - baseline) / baseline`` — dimensionless.

    Refused when the baseline is zero or missing: a relative anomaly
    against a zero reference is undefined, and dividing would invent a
    sign for it. The sign of the baseline is preserved (a negative
    baseline is a real quantity for metrics that have one).
    """
    if observed is None or baseline is None:
        return None
    if not (math.isfinite(observed) and math.isfinite(baseline)):
        return None
    if baseline == 0.0:
        return None
    return (float(observed) - float(baseline)) / float(baseline)


def standardized_anomaly(
    observed: Optional[float],
    baseline_mean: Optional[float],
    baseline_std: Optional[float],
) -> Optional[float]:
    """``(observed - mean) / std`` — the dimensionless z-score.

    Refused when the spread is missing, zero, or was computed from too
    few observations to be trustworthy: a zero-variance z-score is
    undefined, and dividing by a tiny spread manufactures an extreme
    score out of noise.
    """
    if observed is None or baseline_mean is None or baseline_std is None:
        return None
    if not all(
        math.isfinite(v)
        for v in (observed, baseline_mean, baseline_std)
    ):
        return None
    if baseline_std <= 0.0:
        return None
    return (float(observed) - float(baseline_mean)) / float(baseline_std)


# ==========================================================================
# Percentile context — reuses Phase K's percentile_of_value
# ==========================================================================


@dataclass(frozen=True)
class PercentileContext:
    """A rank within a stated reference population.

    This is **not** a probability. "90th percentile" means 90 percent of
    the reference population lies below the value — it makes no claim
    about the chance of any future outcome.
    """

    percentile: float
    n: int
    method: str
    reference_start: date
    reference_end: date
    #: How many reference values were exactly equal to the observed
    #: value. The rank counts only strictly-below values, so ties are
    #: visible rather than silently absorbed.
    ties: int


def percentile_context(
    observed: Optional[float],
    series: Sequence[ObservationPoint],
    min_samples: int,
) -> Optional[PercentileContext]:
    """Rank one observation within the series' own reference values.

    The reference population is every value in ``series``; the observed
    value is ranked against it and is not a member of it (the Phase K
    rule). Ties — reference values equal to the observation — are not
    counted as below and are reported separately.
    """
    if observed is None or not math.isfinite(observed):
        return None
    values = [point.value for point in series]
    rank = percentile_of_value(observed, values, min_samples)
    if rank is None:
        return None
    ties = sum(1 for v in values if v == observed)
    return PercentileContext(
        percentile=rank,
        n=len(values),
        method="strict-less-than rank against the reference population "
        "(linear-resolution population, observed value excluded)",
        reference_start=min(point.day for point in series),
        reference_end=max(point.day for point in series),
        ties=ties,
    )


# ==========================================================================
# Trend machinery
# ==========================================================================


class TrendDirection(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    APPROXIMATELY_FLAT = "approximately_flat"
    UNAVAILABLE = "unavailable"


#: Minimum observations before a Mann-Kendall p-value is reported. Below
#: this the slope is still published, but explicitly as descriptive.
MIN_TREND_OBS = 8

#: The flatness convention: a trend whose |slope| implies a change over
#: the observed period smaller than FLAT_FRACTION of the series' own
#: spread is reported as approximately_flat. This is a descriptive
#: reporting convention of this engine, stated in every result.
FLAT_FRACTION = 0.1


@dataclass(frozen=True)
class TrendRecord:
    """A descriptive trend, with its significance test when justified.

    The slope carries the metric's unit per day. The direction is a
    description of the numbers, never of the crop, the soil or the
    weather's cause.
    """

    first_day: date
    first_value: float
    last_day: date
    last_value: float
    n: int
    elapsed_days: int
    slope_per_day: Optional[float]
    direction: TrendDirection
    #: Mann-Kendall outputs; ``None`` when n < MIN_TREND_OBS.
    mk_s: Optional[float] = None
    mk_z: Optional[float] = None
    mk_p: Optional[float] = None
    significant: Optional[bool] = None
    method: str = ""


def theil_sen_slope(
    days: Sequence[date], values: Sequence[float]
) -> Optional[float]:
    """The median of pairwise slopes, in units per day.

    Each pair of distinct-time observations contributes
    ``(v_j - v_i) / (t_j - t_i)``; the median of those pairwise slopes
    is the Theil-Sen estimator. It is robust to outliers and defined
    for irregularly spaced observations. Returns ``None`` with fewer
    than two distinct observation times or a degenerate (all-identical
    time) input.
    """
    n = len(days)
    if n != len(values) or n < 2:
        return None
    t = np.array([(d - days[0]).days for d in days], dtype=float)
    v = np.array(values, dtype=float)
    slopes: List[float] = []
    for i in range(n - 1):
        for j in range(i + 1, n):
            dt = t[j] - t[i]
            if dt > 0:
                slopes.append((v[j] - v[i]) / dt)
    if not slopes:
        return None
    return float(np.median(slopes))


def _normal_cdf(z: float) -> float:
    """The standard normal CDF via ``math.erf`` (no scipy needed)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def mann_kendall(values: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    """The Mann-Kendall S statistic, z score and two-sided p-value.

    The tie correction for the variance is applied, and the z score
    carries the standard continuity correction. Returns ``None`` with
    fewer than two observations. This is the classical non-parametric
    test for a monotonic tendency in an ordered series; it tests the
    *ordering of the values*, so irregular spacing is tolerated by
    construction, and the p-value is the normal-approximation p-value,
    which is stated wherever it is reported.
    """
    n = len(values)
    if n < 2:
        return None
    v = np.array(values, dtype=float)
    s = 0.0
    for i in range(n - 1):
        diff = v[i + 1:] - v[i]
        s += float(np.sign(diff).sum())

    # Tie correction: group equal values.
    _, counts = np.unique(v, return_counts=True)
    tie_term = float(
        sum(t * (t - 1) * (2 * t + 5) for t in counts if t > 1)
    )
    variance = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if variance <= 0.0:
        # Every value identical: S is 0 and the series has no ordering
        # to test. A z-score against zero variance is refused.
        return None

    if s > 0:
        z = (s - 1.0) / math.sqrt(variance)
    elif s < 0:
        z = (s + 1.0) / math.sqrt(variance)
    else:
        z = 0.0

    p = 2.0 * (1.0 - _normal_cdf(abs(z)))
    return s, z, min(p, 1.0)


def compute_trend(
    series: Sequence[ObservationPoint],
    min_n: int = 4,
) -> Optional[TrendRecord]:
    """The descriptive trend of a series, with MK significance when n allows.

    Returns ``None`` with fewer than ``min_n`` observations. The
    direction applies the documented flatness convention: a trend whose
    implied change over the observed period is below FLAT_FRACTION of
    the series' own spread is approximately_flat.
    """
    if len(series) < max(min_n, 2):
        return None

    points = sorted(series, key=lambda p: p.day)
    days = [p.day for p in points]
    values = [p.value for p in points]

    slope = theil_sen_slope(days, values)

    spread = float(np.std(values, ddof=1)) if len(values) >= 2 else 0.0
    elapsed = (days[-1] - days[0]).days

    if slope is None:
        direction = TrendDirection.UNAVAILABLE
    elif spread <= 0.0:
        # An identically-valued series has no direction to report.
        direction = TrendDirection.APPROXIMATELY_FLAT
    else:
        implied = abs(slope) * elapsed
        if implied < FLAT_FRACTION * spread:
            direction = TrendDirection.APPROXIMATELY_FLAT
        elif slope > 0:
            direction = TrendDirection.INCREASING
        else:
            direction = TrendDirection.DECREASING

    mk: Optional[Tuple[float, float, float]] = None
    significant: Optional[bool] = None
    method = "Theil-Sen median of pairwise slopes (descriptive)"
    if len(values) >= MIN_TREND_OBS:
        mk = mann_kendall(values)
        if mk is not None:
            _s, z, p = mk
            significant = p < 0.05
            method = (
                "Theil-Sen median of pairwise slopes; Mann-Kendall test "
                "(tie-corrected, continuity-corrected, normal-approximation "
                "p-value) for significance at alpha=0.05"
            )

    return TrendRecord(
        first_day=days[0],
        first_value=values[0],
        last_day=days[-1],
        last_value=values[-1],
        n=len(values),
        elapsed_days=elapsed,
        slope_per_day=slope,
        direction=direction,
        mk_s=mk[0] if mk else None,
        mk_z=mk[1] if mk else None,
        mk_p=mk[2] if mk else None,
        significant=significant,
        method=method,
    )


# ==========================================================================
# Persistence machinery
# ==========================================================================


@dataclass(frozen=True)
class PersistenceRecord:
    """How long baseline deviations lasted, with gaps honoured.

    A gap — a missing period — breaks a consecutive sequence, because a
    run that spans an unobserved period is a claim about data that does
    not exist. Ties (values exactly at the baseline) count as neither
    above nor below and also break a run.
    """

    longest_run_above: int
    longest_run_below: int
    n_anomalous: int
    n_observed: int
    n_missing: int
    #: The anomalous fraction of *observed* periods. Missing periods are
    #: excluded from the denominator, never counted as anomalous.
    anomalous_fraction: Optional[float]


def compute_persistence(
    series: Sequence[Optional[float]],
    baseline: Optional[float],
    expected_periods: Optional[int] = None,
) -> Optional[PersistenceRecord]:
    """Count baseline deviations across an ordered period sequence.

    ``series`` is ordered by time and carries ``None`` for missing
    periods. A deviation is strict: a value exactly at the baseline is
    not anomalous. Returns ``None`` when there is no baseline or no
    observed period to compare.
    """
    if baseline is None:
        return None
    observed = [v for v in series if v is not None]
    if not observed:
        return None

    longest_above = 0
    longest_below = 0
    run_above = 0
    run_below = 0
    n_above = 0
    n_below = 0

    for value in series:
        if value is None:
            # A gap breaks both runs: the sequence is no longer
            # consecutive, whatever the methodology would like.
            run_above = 0
            run_below = 0
            continue
        if value > baseline:
            n_above += 1
            run_above += 1
            run_below = 0
            longest_above = max(longest_above, run_above)
        elif value < baseline:
            n_below += 1
            run_below += 1
            run_above = 0
            longest_below = max(longest_below, run_below)
        else:
            # A tie at the baseline is a real observation that is not
            # anomalous; it breaks both runs.
            run_above = 0
            run_below = 0

    n_observed = len(observed)
    n_missing = (
        (expected_periods - n_observed)
        if expected_periods is not None and expected_periods >= n_observed
        else len(series) - n_observed
    )
    n_anomalous = n_above + n_below
    return PersistenceRecord(
        longest_run_above=longest_above,
        longest_run_below=longest_below,
        n_anomalous=n_anomalous,
        n_observed=n_observed,
        n_missing=max(n_missing, 0),
        anomalous_fraction=(n_anomalous / n_observed) if n_observed else None,
    )


# ==========================================================================
# Change detection machinery
# ==========================================================================


@dataclass(frozen=True)
class ChangeRecord:
    """One documented change, described and nothing more.

    The magnitude is the difference between the means of two adjacent
    windows of observations. It is not a change point significance test
    and carries no causal interpretation.
    """

    #: The boundary between the two windows.
    boundary_day: date
    before: float
    after: float
    magnitude: float
    #: The before/after window length in observations.
    window: int
    method: str
    n: int


def largest_rolling_shift(
    series: Sequence[ObservationPoint],
    window: int,
) -> Optional[ChangeRecord]:
    """The largest difference between two adjacent rolling means.

    For every candidate boundary, the up-to-``window`` observations
    before it are averaged into ``before`` and the up-to-``window``
    after it into ``after``; the boundary with the largest |after -
    before| is returned. Missing observations reduce the window rather
    than being filled; a boundary with no observations on either side
    cannot be evaluated. Returns ``None`` with fewer than ``2 *
    window`` observations.

    This is deliberately the most conservative change description: one
    number, its two contributing means, and the boundary between them.
    No change-point significance is claimed.
    """
    if window < 1:
        return None
    points = sorted(series, key=lambda p: p.day)
    n = len(points)
    if n < 2 * window:
        return None

    values = [p.value for p in points]
    best: Optional[ChangeRecord] = None
    for boundary in range(window, n - window + 1):
        before_values = values[boundary - window:boundary]
        after_values = values[boundary:boundary + window]
        before = float(np.mean(before_values))
        after = float(np.mean(after_values))
        magnitude = after - before
        if best is None or abs(magnitude) > abs(best.magnitude):
            best = ChangeRecord(
                boundary_day=points[boundary].day,
                before=before,
                after=after,
                magnitude=magnitude,
                window=window,
                method=(
                    f"rolling-mean difference: mean of the {window} "
                    "observation(s) before the boundary minus the mean of "
                    f"the {window} after it; the boundary with the largest "
                    "absolute difference is reported"
                ),
                n=n,
            )
    return best


# ==========================================================================
# Constants for the metric layer
# ==========================================================================

#: Full preceding years gathered for the historical reference.
HISTORY_BASELINE_YEARS = 5

#: Fewer contributing years than this and every reference-dependent
#: statistic is refused.
HISTORY_MIN_YEARS = 3

#: Minimum observations in a reference group before its spread may
#: support a standardized anomaly.
MIN_BASELINE_GROUP = 3

#: Minimum distinct months in the analysis window for a mean to describe.
MIN_ANALYSIS_MONTHS = 3

#: Minimum observation count for the change-detection metric.
MIN_CHANGE_OBS = 12

#: Minimum detected seasons (history years) for a timing anomaly.
MIN_SEASON_HISTORY = 3


# ==========================================================================
# Shared series builders
# ==========================================================================


def _analysis_and_history_windows(
    context: MetricContext, years_back: int
) -> Tuple[List[Tuple[int, date, date]], Optional[str]]:
    """The requested window plus the preceding whole-year windows.

    Returns ``(windows, error)`` where ``windows`` is
    ``[(0, requested_start, requested_end), (1, ...), ...]`` with the
    requested window first. The whole-year offsets and leap-day folding
    are Phase K's ``shift_window_years``; nothing is restated here.
    """
    start = context.start
    end = context.end
    if start is None or end is None or start > end:
        return [], "The requested period cannot be parsed."
    windows: List[Tuple[int, date, date]] = [(0, start, end)]
    for years in range(1, years_back + 1):
        try:
            win_start, win_end = shift_window_years(start, end, years)
        except ValueError as exc:
            return [], str(exc)
        windows.append((years, win_start, win_end))
    return windows, None


def _multiyear_ndvi_series(
    context: MetricContext,
    ee_module: Any,
    years_back: int,
) -> Tuple[List[ObservationPoint], int, int, Optional[str]]:
    """Monthly NDVI values for the analysis window and preceding years.

    Each window is reduced through the phenology engine's own builder,
    so the compositing, masking and monthly aggregation are identical to
    what the phenology metrics publish. A window with no usable months
    contributes nothing (never zeros). Returns ``(series,
    analysis_month_count, contributing_years, error)``.
    """
    windows, error = _analysis_and_history_windows(context, years_back)
    if error:
        return [], 0, 0, error

    series: List[ObservationPoint] = []
    analysis_months = 0
    contributing = 0

    for index, (years, win_start, win_end) in enumerate(windows):
        shifted = _shift_context(context, win_start, win_end)
        monthly, _scenes, _stats = build_monthly_series_from_context(
            shifted, ee_module
        )
        if not monthly:
            continue
        if index > 0:
            contributing += 1
        for value in monthly:
            point = ObservationPoint(
                day=date(value.year, value.month, 1), value=value.value
            )
            series.append(point)
            if index == 0:
                analysis_months += 1

    return series, analysis_months, contributing, None


# ==========================================================================
# Shared metric base
# ==========================================================================


_HISTORY_DISCLAIMER = (
    "This is a descriptive historical statistic. It describes the "
    "numbers and their reference population; it is not a diagnosis, not "
    "a cause, and not a prediction. A trend is not causality, a "
    "percentile is not a probability, and a baseline is a statistical "
    "reference, not a biological optimum."
)


class _NdviHistoryMetric(Metric):
    """Common machinery for the NDVI historical metrics.

    The reference population is the monthly NDVI series of the analysis
    window plus the preceding whole-year windows, built through the
    phenology engine's builder so every value matches what the phenology
    metrics would publish for the same window. The month-of-year
    strategy is the default because a field's NDVI is strongly
    seasonal; comparing a month against all months would fold the
    seasonal cycle into the reference and describe nothing.
    """

    domain = MetricDomain.HISTORY
    dataset_ids = ("COPERNICUS/S2_SR_HARMONIZED",)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = 10
    unit = "index"

    def can_attempt(self, context: MetricContext) -> Tuple[bool, Optional[str]]:
        can, reason = super().can_attempt(context)
        if not can:
            return can, reason
        start = context.start
        end = context.end
        if start is None or end is None:
            return False, "outside_temporal_coverage"
        # The analysis window must carry at least the minimum months, and
        # the reference needs HISTORY_MIN_YEARS full years before it.
        if (end - start).days + 1 < 90:
            return False, "window_too_short"
        return True, None

    def _collect(
        self, context: MetricContext, ee_module: Any
    ) -> Tuple[
        List[ObservationPoint],
        List[ObservationPoint],
        int,
        int,
        Optional[str],
    ]:
        """Split the multi-year series into analysis and reference parts.

        Returns ``(analysis_series, reference_series, contributing_years,
        analysis_month_count, error)``.
        """
        windows, error = _analysis_and_history_windows(
            context, HISTORY_BASELINE_YEARS
        )
        if error:
            return [], [], 0, 0, error

        analysis: List[ObservationPoint] = []
        reference: List[ObservationPoint] = []
        contributing = 0
        for index, (years, win_start, win_end) in enumerate(windows):
            shifted = _shift_context(context, win_start, win_end)
            monthly, _scenes, _stats = build_monthly_series_from_context(
                shifted, ee_module
            )
            if not monthly:
                continue
            if index == 0:
                for value in monthly:
                    analysis.append(
                        ObservationPoint(
                            day=date(value.year, value.month, 1),
                            value=value.value,
                        )
                    )
            else:
                contributing += 1
                for value in monthly:
                    reference.append(
                        ObservationPoint(
                            day=date(value.year, value.month, 1),
                            value=value.value,
                        )
                    )
        analysis_months = len(analysis)
        return analysis, reference, contributing, analysis_months, None

    def _baseline(
        self, reference: Sequence[ObservationPoint], group: str
    ) -> Optional[BaselineSummary]:
        return compute_baseline(
            reference, BaselineStrategy.MONTH_OF_YEAR, group, HISTORY_MIN_YEARS
        )

    def _group_of(self, context: MetricContext) -> Optional[str]:
        """The month-of-year group of the analysis window's middle month.

        A window shorter than a year maps to one dominant month group;
        the middle month of the window is used so the group is stable
        under small boundary changes. A window of a year or more has no
        single month group, and the metric refuses rather than picking
        one arbitrarily.
        """
        start = context.start
        end = context.end
        assert start is not None and end is not None
        if (end - start).days + 1 > 366:
            return None
        middle = start + (end - start) / 2
        return f"{middle.month:02d}"


# ==========================================================================
# 1. Anomaly metrics (absolute, relative, standardized)
# ==========================================================================


class NdviAnomalyAbsoluteMetric(_NdviHistoryMetric):
    """Analysis-window NDVI mean minus its month-of-year baseline.

    .. math::

        anomaly = \\overline{NDVI}_{analysis} - \\mu_{month\\text{-}of\\text{-}year}

    The reference is the mean of the same calendar months in the
    preceding years, from the same product, geometry and reduction, so
    the comparison involves no cross-dataset assumption. The value is in
    the index's own unit. A missing or under-populated baseline is
    refused, never treated as zero.
    """

    key = "ndvi_anomaly_absolute"
    display_name = "NDVI Anomaly vs Historical Baseline"
    display_name_fa = "آنومالی NDVI نسبت به مبنا"
    description = (
        "The analysis window's mean monthly NDVI minus the mean of the "
        "same calendar months in the preceding years (month-of-year "
        "baseline). A positive value means greener than the local "
        "historical reference for those months. Descriptive only."
    )
    limitations = (
        _HISTORY_DISCLAIMER,
        "The reference population is a few years of monthly means; it "
        "separates the window from ordinary interannual variability only "
        "coarsely.",
        "NDVI saturates over dense canopies, so anomalies compress from "
        "above in very productive periods.",
        "Cloud gaps reduce the contributing months; months with no "
        "usable scene are excluded, never filled.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        static_reason = require_temporal_series(dataset)
        if static_reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=static_reason,
                message=(
                    "The primary dataset is a static product; its dates "
                    "are acquisition metadata, not observations, so no "
                    "historical series or anomaly can be computed from "
                    "it."
                ),
                unit=self.unit,
            )

        analysis, reference, contributing, n_months, error = self._collect(
            context, ee
        )
        provenance = self._provenance(
            context, dataset, analysis, reference, contributing
        )

        if error:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=error,
                unit=self.unit,
                provenance=provenance,
            )
        if n_months < MIN_ANALYSIS_MONTHS or not analysis:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {n_months} month(s) with usable NDVI in the "
                    f"analysis window; at least {MIN_ANALYSIS_MONTHS} are "
                    "required, so no anomaly is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if contributing < HISTORY_MIN_YEARS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributing} of the {HISTORY_BASELINE_YEARS} "
                    "preceding years contributed usable monthly NDVI, "
                    f"which is fewer than the {HISTORY_MIN_YEARS} required "
                    "to define a historical baseline, so no anomaly is "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        group = self._group_of(context)
        if group is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The requested window spans more than a year, so it "
                    "has no single month-of-year reference group. Split "
                    "the request into sub-year windows."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        baseline = self._baseline(reference, group)
        if baseline is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The month-of-year reference group {group!r} has too "
                    f"few observations in the preceding "
                    f"{HISTORY_BASELINE_YEARS} years to define a baseline "
                    f"(minimum {HISTORY_MIN_YEARS}), so no anomaly is "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        observed = float(np.mean([p.value for p in analysis]))
        value = absolute_anomaly(observed, baseline.mean)
        if value is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The baseline or the analysis mean is undefined, so "
                    "no anomaly is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        return self._finish(
            context, provenance, value, observed, baseline, analysis
        )

    def _finish(
        self,
        context: MetricContext,
        provenance: Provenance,
        value: float,
        observed: float,
        baseline: BaselineSummary,
        analysis: Sequence[ObservationPoint],
    ) -> MetricResult:
        warnings: List[str] = [
            (
                f"Baseline: month-of-year mean over {baseline.n} reference "
                f"month(s) from the preceding years "
                f"({baseline.reference_start.isoformat()} to "
                f"{baseline.reference_end.isoformat()}); observed analysis "
                f"mean {observed:.3f} over {len(analysis)} month(s)."
            ),
            _HISTORY_DISCLAIMER,
        ]
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=value,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )

    def _provenance(
        self,
        context: MetricContext,
        dataset: Any,
        analysis: Sequence[ObservationPoint],
        reference: Sequence[ObservationPoint],
        contributing: int,
    ) -> Provenance:
        return self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["B4", "B8"],
            formula=(
                "monthly NDVI (phenology engine's compositing); anomaly = "
                "mean(analysis-window monthly values) - month-of-year "
                "baseline mean over the preceding whole years"
            ),
            quality=QualityLevel.MODERATE
            if analysis
            else QualityLevel.INSUFFICIENT,
            image_count=len(analysis) + len(reference),
            aggregation_method=(
                "per-scene spatial mean, calendar-month mean, then "
                "month-of-year grouping across whole-year windows"
            ),
            extra_limitations=self.limitations,
            extra_caveats=(
                f"Reference population: {len(reference)} monthly value(s) "
                f"from {contributing} of {HISTORY_BASELINE_YEARS} "
                "preceding year(s).",
                (
                    f"Analysis months: {len(analysis)} "
                    f"({min((p.day for p in analysis), default=None)} to "
                    f"{max((p.day for p in analysis), default=None)})."
                ),
                "Temporal alignment: the analysis window and every "
                "reference window use the same product, bands, geometry "
                "and reduction, offset only by whole years.",
            ),
        )


class NdviAnomalyRelativeMetric(NdviAnomalyAbsoluteMetric):
    """Relative anomaly: ``(observed - baseline) / baseline``.

    Dimensionless. Refused when the baseline is zero — a relative
    anomaly against a zero reference is undefined, and the refusal is
    the honest answer.
    """

    key = "ndvi_anomaly_relative"
    display_name = "NDVI Relative Anomaly"
    display_name_fa = "آنومالی نسبی NDVI"
    unit = "fraction"
    description = (
        "The NDVI anomaly divided by the month-of-year baseline mean. "
        "Dimensionless: a value of 0.10 means the analysis window ran 10 "
        "percent above its local historical reference. Refused when the "
        "baseline is zero."
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        static_reason = require_temporal_series(dataset)
        if static_reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=static_reason,
                message=(
                    "The primary dataset is a static product; no "
                    "historical series exists to form an anomaly from."
                ),
                unit=self.unit,
            )

        analysis, reference, contributing, n_months, error = self._collect(
            context, ee
        )
        provenance = self._provenance(
            context, dataset, analysis, reference, contributing
        )
        if error or n_months < MIN_ANALYSIS_MONTHS or not analysis:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=error
                or (
                    f"Only {n_months} month(s) with usable NDVI in the "
                    "analysis window, so no anomaly is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if contributing < HISTORY_MIN_YEARS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributing} of the {HISTORY_BASELINE_YEARS} "
                    f"preceding years contributed usable data; at least "
                    f"{HISTORY_MIN_YEARS} are required."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        group = self._group_of(context)
        if group is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The requested window spans more than a year, so it "
                    "has no single month-of-year reference group."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        baseline = self._baseline(reference, group)
        if baseline is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The month-of-year reference group {group!r} is too "
                    "small to define a baseline."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if baseline.mean == 0.0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The baseline mean is exactly zero, so the relative "
                    "anomaly is undefined and is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        observed = float(np.mean([p.value for p in analysis]))
        value = relative_anomaly(observed, baseline.mean)
        if value is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The relative anomaly is undefined for this input."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            (
                f"Baseline mean {baseline.mean:.3f} over {baseline.n} "
                "reference month(s); observed mean "
                f"{observed:.3f} over {len(analysis)} month(s). The value "
                "is a fraction of the baseline, not a probability."
            ),
            _HISTORY_DISCLAIMER,
        ]
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=value,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )


class NdviAnomalyStandardizedMetric(NdviAnomalyAbsoluteMetric):
    """Standardized anomaly (z-score) against the month-of-year baseline.

    ``(observed - mean) / std`` — dimensionless. Refused when the
    group's spread is zero or rests on too few observations: a
    zero-variance z-score is undefined and a thin spread manufactures
    extreme scores from noise.
    """

    key = "ndvi_anomaly_standardized"
    display_name = "NDVI Standardized Anomaly"
    display_name_fa = "آنومالی استاندارد NDVI"
    unit = "z"
    description = (
        "The NDVI anomaly divided by the standard deviation of the "
        "month-of-year reference population. Dimensionless: a z-score of "
        "-1.5 means the window ran one and a half reference standard "
        "deviations below its historical mean. Refused when the spread "
        "is zero or unreliable."
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        static_reason = require_temporal_series(dataset)
        if static_reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=static_reason,
                message=(
                    "The primary dataset is a static product; no "
                    "historical spread exists to standardize against."
                ),
                unit=self.unit,
            )

        analysis, reference, contributing, n_months, error = self._collect(
            context, ee
        )
        provenance = self._provenance(
            context, dataset, analysis, reference, contributing
        )
        if error or n_months < MIN_ANALYSIS_MONTHS or not analysis:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=error
                or (
                    f"Only {n_months} month(s) with usable NDVI in the "
                    "analysis window, so no standardized anomaly is "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if contributing < HISTORY_MIN_YEARS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributing} of the {HISTORY_BASELINE_YEARS} "
                    "preceding years contributed usable data, which is "
                    f"fewer than the {HISTORY_MIN_YEARS} required."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        group = self._group_of(context)
        if group is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The requested window spans more than a year, so it "
                    "has no single month-of-year reference group."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        baseline = self._baseline(reference, group)
        if baseline is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The month-of-year reference group {group!r} is too "
                    "small to define a baseline."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if baseline.std is None or not baseline.spread_reliable:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The reference group's spread rests on {baseline.n} "
                    f"observation(s), below the {MIN_BASELINE_GROUP} "
                    "required for a trustworthy standard deviation, so "
                    "the z-score is refused rather than manufactured."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if baseline.std <= 0.0:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=ZERO_VARIANCE_CODE,
                message=(
                    "The reference population has zero variance, so a "
                    "standardized anomaly is undefined. No z-score is "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        observed = float(np.mean([p.value for p in analysis]))
        value = standardized_anomaly(observed, baseline.mean, baseline.std)
        if value is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The standardized anomaly is undefined for this "
                    "input."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            (
                f"Baseline mean {baseline.mean:.3f}, standard deviation "
                f"{baseline.std:.3f} over {baseline.n} reference "
                "month(s). The z-score is a position within the reference "
                "distribution, not a probability."
            ),
            _HISTORY_DISCLAIMER,
        ]
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=value,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )


# ==========================================================================
# 2. Percentile context metric
# ==========================================================================


class NdviPercentileContextMetric(NdviAnomalyAbsoluteMetric):
    """Where the analysis window's NDVI mean sits in the historical rank.

    The rank is computed against the month-of-year reference population
    by the Phase K percentile machinery: strictly-below counting, the
    observed value excluded from its own population, ties reported, and
    a minimum population enforced. It is a rank, not a probability.
    """

    key = "ndvi_percentile_context"
    display_name = "NDVI Historical Percentile Context"
    display_name_fa = "صدک NDVI در بستر تاریخی"
    unit = "percent"
    description = (
        "The percentile rank of the analysis window's mean NDVI within "
        "the month-of-year reference population of the preceding years. "
        "A rank of 90 means 90 percent of the reference values lie below "
        "it — a rank, not a probability of any outcome."
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        static_reason = require_temporal_series(dataset)
        if static_reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=static_reason,
                message=(
                    "The primary dataset is a static product; there is no "
                    "historical population to rank against."
                ),
                unit=self.unit,
            )

        analysis, reference, contributing, n_months, error = self._collect(
            context, ee
        )
        provenance = self._provenance(
            context, dataset, analysis, reference, contributing
        )
        if error or n_months < MIN_ANALYSIS_MONTHS or not analysis:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=error
                or (
                    f"Only {n_months} month(s) with usable NDVI in the "
                    "analysis window, so no percentile is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if contributing < HISTORY_MIN_YEARS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributing} of the {HISTORY_BASELINE_YEARS} "
                    "preceding years contributed usable data, which is "
                    f"fewer than the {HISTORY_MIN_YEARS} required to "
                    "define a reference population."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        group = self._group_of(context)
        if group is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The requested window spans more than a year, so it "
                    "has no single month-of-year reference group."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        group_series = [
            p
            for p in reference
            if p.day.month == int(group)
        ]
        if len(group_series) < HISTORY_MIN_YEARS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The month-of-year reference population for {group!r} "
                    f"has {len(group_series)} value(s), below the "
                    f"{HISTORY_MIN_YEARS} required for a percentile rank."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        observed = float(np.mean([p.value for p in analysis]))
        context_record = percentile_context(
            observed, group_series, HISTORY_MIN_YEARS
        )
        if context_record is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The percentile could not be computed from the "
                    "reference population."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            (
                f"Reference population: {context_record.n} monthly value(s) "
                f"from {contributing} preceding year(s); "
                f"{context_record.ties} tie(s) at the observed value. This "
                "is a rank within the stated population, not a "
                "probability and not a min-max normalisation."
            ),
            _HISTORY_DISCLAIMER,
        ]
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=context_record.percentile,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )


# ==========================================================================
# 3. Trend metric
# ==========================================================================


class NdviTrendMetric(_NdviHistoryMetric):
    """Descriptive trend of the multi-year monthly NDVI series.

    The slope is the Theil-Sen median of pairwise slopes over the whole
    collected series (analysis window plus the preceding years), in
    index units per day. Significance is the Mann-Kendall test and is
    reported only from :data:`MIN_TREND_OBS` observations; below that
    the slope is still published, labelled descriptive. The direction
    applies the documented flatness convention.
    """

    key = "ndvi_trend"
    display_name = "NDVI Historical Trend"
    display_name_fa = "روند تاریخی NDVI"
    unit = "index/day"
    description = (
        "The Theil-Sen slope of the multi-year monthly NDVI series, in "
        "index units per day, with a Mann-Kendall significance test when "
        "at least eight observations exist. Descriptive: a direction is "
        "a statement about the numbers, not about any cause."
    )
    limitations = (
        _HISTORY_DISCLAIMER,
        "The trend describes the observed series only; it implies "
        "nothing about the next month, the next season or any cause.",
        "Cloud-gap months are absent from the series, and an irregularly "
        "sampled series bounds what any slope can mean; the Theil-Sen "
        "estimator tolerates the irregular spacing but cannot recover "
        "unobserved months.",
        "A statistically significant slope over a few years of a "
        "saturating index is not evidence of a management effect.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        static_reason = require_temporal_series(dataset)
        if static_reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=static_reason,
                message=(
                    "The primary dataset is a static product; its dates "
                    "are metadata and no trend can be computed across it."
                ),
                unit=self.unit,
            )

        windows, error = _analysis_and_history_windows(
            context, HISTORY_BASELINE_YEARS
        )
        if error:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=error,
                unit=self.unit,
            )

        series: List[ObservationPoint] = []
        contributing = 0
        for index, (_years, win_start, win_end) in enumerate(windows):
            shifted = _shift_context(context, win_start, win_end)
            monthly, _scenes, _stats = build_monthly_series_from_context(
                shifted, ee
            )
            if not monthly:
                continue
            if index > 0:
                contributing += 1
            for value in monthly:
                series.append(
                    ObservationPoint(
                        day=date(value.year, value.month, 1),
                        value=value.value,
                    )
                )

        provenance = self._provenance(
            context, dataset, series, contributing
        )

        if contributing < HISTORY_MIN_YEARS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributing} of the {HISTORY_BASELINE_YEARS} "
                    "preceding years contributed usable monthly data, "
                    f"which is fewer than the {HISTORY_MIN_YEARS} required "
                    "to characterise a trend, so none is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        record = compute_trend(series, min_n=MIN_TREND_OBS)
        if record is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {len(series)} monthly observation(s) in the "
                    f"analysis and reference windows; at least "
                    f"{MIN_TREND_OBS} are required before a trend is "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        value = (
            record.slope_per_day if record.slope_per_day is not None else 0.0
        )
        warnings: List[str] = [
            (
                f"Series: {record.n} monthly observation(s) from "
                f"{record.first_day.isoformat()} to "
                f"{record.last_day.isoformat()} "
                f"({record.elapsed_days} days elapsed); direction "
                f"'{record.direction.value}'."
            ),
            (
                f"Method: {record.method}."
                + (
                    ""
                    if record.mk_p is None
                    else f" Mann-Kendall p={record.mk_p:.3f} "
                    f"(z={record.mk_z:.2f}), significance at alpha=0.05: "
                    f"{record.significant}."
                )
            ),
            (
                "The direction is a description of the numbers, not a "
                "cause and not a forecast."
            ),
        ]
        if record.significant is None:
            warnings.append(
                f"With fewer than {MIN_TREND_OBS} observations no "
                "significance test is reported; the slope is descriptive "
                "only."
            )
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=value,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )

    def _provenance(
        self,
        context: MetricContext,
        dataset: Any,
        series: Sequence[ObservationPoint],
        contributing: int,
    ) -> Provenance:
        return self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["B4", "B8"],
            formula=(
                "slope = median over all observation pairs of "
                "(v_j - v_i) / (t_j - t_i) (Theil-Sen); direction from "
                "the documented flatness convention; significance from "
                "the tie-corrected Mann-Kendall test when n >= "
                f"{MIN_TREND_OBS}"
            ),
            quality=QualityLevel.MODERATE if series else (
                QualityLevel.INSUFFICIENT
            ),
            image_count=len(series),
            aggregation_method=(
                "per-scene spatial mean, calendar-month mean, one whole-"
                "year window at a time; the trend is over the collected "
                "monthly series"
            ),
            extra_limitations=self.limitations,
            extra_caveats=(
                f"Reference population: {len(series)} monthly value(s) "
                f"from {contributing} of {HISTORY_BASELINE_YEARS} "
                "preceding year(s) plus the analysis window.",
                "Missing months are absent, not interpolated; the slope "
                "is computed over the observed months only.",
            ),
        )


# ==========================================================================
# 4. Persistence metric
# ==========================================================================


class NdviAnomalyPersistenceMetric(NdviAnomalyAbsoluteMetric):
    """How long monthly NDVI ran above or below its month-of-year baseline.

    The analysis window's months are flagged against the baseline of the
    same calendar months in the preceding years. A missing month breaks
    a consecutive sequence — an unobserved period is not evidence of
    continuation. The value is the anomalous fraction of observed
    months; the longest above/below runs travel in the warnings.
    """

    key = "ndvi_anomaly_persistence"
    display_name = "NDVI Baseline-Deviation Persistence"
    display_name_fa = "پایداری انحراف NDVI از مبنا"
    unit = "fraction"
    description = (
        "The fraction of the analysis window's observed months that ran "
        "above or below their month-of-year historical baseline, with "
        "the longest consecutive runs reported. Missing months break "
        "sequences and are excluded from the denominator. Descriptive "
        "only: persistence of a deviation is not persistence of any "
        "condition or cause."
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        static_reason = require_temporal_series(dataset)
        if static_reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=static_reason,
                message=(
                    "The primary dataset is a static product; there is no "
                    "historical series to measure persistence against."
                ),
                unit=self.unit,
            )

        analysis, reference, contributing, n_months, error = self._collect(
            context, ee
        )
        provenance = self._provenance(
            context, dataset, analysis, reference, contributing
        )
        if error or n_months < MIN_ANALYSIS_MONTHS or not analysis:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=error
                or (
                    f"Only {n_months} month(s) with usable NDVI in the "
                    "analysis window, so no persistence is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if contributing < HISTORY_MIN_YEARS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributing} of the {HISTORY_BASELINE_YEARS} "
                    "preceding years contributed usable data, which is "
                    f"fewer than the {HISTORY_MIN_YEARS} required to "
                    "define the baseline."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        # Per-month persistence: each analysis month is compared with the
        # baseline of its own calendar month, so a June is measured
        # against Junes, never against the annual mean.
        #
        # The comparison sequence is built over the analysis window's
        # full calendar span, not over the observed months alone: a
        # month with no observation — or a month whose reference group
        # could not define a baseline — is a gap, and a gap breaks a
        # consecutive run. A run over the observed months alone would
        # silently claim continuity across unobserved periods.
        month_cursor = analysis[0].day
        window_end = context.end
        assert window_end is not None
        sequence: List[Optional[float]] = []
        baseline_notes: List[str] = []
        while month_cursor <= window_end:
            group = f"{month_cursor.month:02d}"
            baseline = self._baseline(reference, group)
            observed_value = next(
                (
                    p.value
                    for p in analysis
                    if (p.day.year, p.day.month)
                    == (month_cursor.year, month_cursor.month)
                ),
                None,
            )
            if baseline is None:
                sequence.append(None)
                baseline_notes.append(
                    f"{group}: no defensible baseline (gap)"
                )
            elif observed_value is None:
                sequence.append(None)
                baseline_notes.append(f"{group}: no observation (gap)")
            else:
                # The deviation from the month's own baseline is what is
                # flagged: a positive deviation runs above, a negative
                # one below, and a value exactly at the baseline is a
                # tie that breaks both runs.
                sequence.append(observed_value - baseline.mean)
                baseline_notes.append(f"{group}: baseline {baseline.mean:.3f}")
            if month_cursor.month == 12:
                month_cursor = date(month_cursor.year + 1, 1, 1)
            else:
                month_cursor = date(
                    month_cursor.year, month_cursor.month + 1, 1
                )

        record = compute_persistence(
            sequence, 0.0, expected_periods=len(sequence)
        )
        if record is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No analysis month had a defensible month-of-year "
                    "baseline, so no persistence is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        value = record.anomalous_fraction if (
            record.anomalous_fraction is not None
        ) else 0.0
        warnings: List[str] = [
            (
                f"{record.n_anomalous} of {record.n_observed} observed "
                "month(s) ran above or below their month-of-year "
                "baseline; longest run above "
                f"{record.longest_run_above} month(s), below "
                f"{record.longest_run_below} month(s)."
            ),
            (
                f"{record.n_missing} month(s) were gaps (no observation, "
                "or no defensible baseline) and are excluded from the "
                "denominator; every gap breaks a consecutive run. "
                "Month baselines: " + "; ".join(baseline_notes) + "."
            ),
            _HISTORY_DISCLAIMER,
        ]
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=value,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )


# ==========================================================================
# 5. Change-detection metric
# ==========================================================================


class NdviChangeShiftMetric(_NdviHistoryMetric):
    """The largest rolling-mean difference in the multi-year NDVI series.

    For every candidate boundary the means of the six observations
    before and after it are compared; the boundary with the largest
    absolute difference is reported with its two contributing means.
    This is a description of one difference, not a change-point
    significance test, and it carries no causal interpretation.
    """

    key = "ndvi_change_shift"
    display_name = "NDVI Rolling-Shift Change Detection"
    display_name_fa = "آشکارسازی تغییر NDVI"
    unit = "index"

    #: Observations averaged on each side of a candidate boundary.
    CHANGE_WINDOW_MONTHS = 6

    description = (
        "The largest difference between the means of the six monthly "
        "NDVI values before and after any boundary in the multi-year "
        "series, with the boundary and both means reported. A "
        "conservative descriptive change record, not a change-point "
        "significance test."
    )
    limitations = (
        _HISTORY_DISCLAIMER,
        "The reported boundary is the one with the largest difference, "
        "which is a selection over noisy data; no significance is "
        "claimed and the magnitude must be read against the series' own "
        "variability.",
        "Missing months reduce the windows rather than being filled, so "
        "a 'before' and 'after' pair can rest on different month mixes.",
        "The difference describes the index, not any management event, "
        "weather event or cause.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        static_reason = require_temporal_series(dataset)
        if static_reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=static_reason,
                message=(
                    "The primary dataset is a static product; no series "
                    "exists across which a change could be detected."
                ),
                unit=self.unit,
            )

        windows, error = _analysis_and_history_windows(
            context, HISTORY_BASELINE_YEARS
        )
        if error:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=error,
                unit=self.unit,
            )

        series: List[ObservationPoint] = []
        contributing = 0
        for index, (_years, win_start, win_end) in enumerate(windows):
            shifted = _shift_context(context, win_start, win_end)
            monthly, _scenes, _stats = build_monthly_series_from_context(
                shifted, ee
            )
            if not monthly:
                continue
            if index > 0:
                contributing += 1
            for value in monthly:
                series.append(
                    ObservationPoint(
                        day=date(value.year, value.month, 1),
                        value=value.value,
                    )
                )

        provenance = self._provenance(
            context, dataset, series, contributing
        )

        if contributing < HISTORY_MIN_YEARS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributing} of the {HISTORY_BASELINE_YEARS} "
                    "preceding years contributed usable data, which is "
                    f"fewer than the {HISTORY_MIN_YEARS} required for a "
                    "multi-year change analysis."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        window = self.CHANGE_WINDOW_MONTHS
        if len(series) < MIN_CHANGE_OBS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {len(series)} monthly observation(s); at least "
                    f"{MIN_CHANGE_OBS} are required before a rolling "
                    "shift is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        record = largest_rolling_shift(series, window)
        if record is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The series is too short to place two "
                    f"{window}-observation windows on either side of any "
                    "boundary."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            (
                f"Boundary {record.boundary_day.isoformat()}: before mean "
                f"{record.before:.3f}, after mean {record.after:.3f}, "
                f"difference {record.magnitude:+.3f} (window "
                f"{record.window} observation(s) on each side)."
            ),
            (
                "This is the largest of the candidate differences, a "
                "descriptive selection over the series. It is not a "
                "change-point significance test and not a cause."
            ),
            _HISTORY_DISCLAIMER,
        ]
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=record.magnitude,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )

    def _provenance(
        self,
        context: MetricContext,
        dataset: Any,
        series: Sequence[ObservationPoint],
        contributing: int,
    ) -> Provenance:
        return self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["B4", "B8"],
            formula=(
                "for each boundary: mean of the "
                f"{self.CHANGE_WINDOW_MONTHS} observations before it minus "
                f"the mean of the {self.CHANGE_WINDOW_MONTHS} after it; "
                "the boundary with the largest absolute difference is "
                "reported"
            ),
            quality=QualityLevel.MODERATE if series else (
                QualityLevel.INSUFFICIENT
            ),
            image_count=len(series),
            aggregation_method=(
                "per-scene spatial mean, calendar-month mean, rolling "
                "means of "
                f"{self.CHANGE_WINDOW_MONTHS} on each side of every "
                "candidate boundary"
            ),
            extra_limitations=self.limitations,
            extra_caveats=(
                f"Reference population: {len(series)} monthly value(s) "
                f"from {contributing} of {HISTORY_BASELINE_YEARS} "
                "preceding year(s) plus the analysis window.",
                "No change-point significance test is applied; the "
                "magnitude is a raw difference of means.",
            ),
        )


# ==========================================================================
# 6. Climate trend metric (ERA5, band-selectable)
# ==========================================================================


class ClimateTrendMetric(Metric):
    """Descriptive trend of an ERA5-Land band's monthly means.

    The band is selectable through the ``history_era5_band`` option
    (default: ``temperature_2m``). Each whole-year window is reduced
    once through the climate module's shared helper, whose per-day
    spatial means are aggregated into calendar-month means in pure
    Python. The trend machinery is the same Theil-Sen + Mann-Kendall
    pair the NDVI trend uses.
    """

    key = "climate_trend"
    display_name = "Climate Monthly Trend (ERA5-Land)"
    display_name_fa = "روند ماهانه اقلیم (ERA5-Land)"
    unit = "unit/month"

    domain = MetricDomain.HISTORY
    dataset_ids = ("ECMWF/ERA5_LAND/DAILY_AGGR",)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = 11132

    description = (
        "The Theil-Sen slope of an ERA5-Land band's monthly means over "
        "the requested window and the preceding years, with a "
        "Mann-Kendall significance test when enough observations exist. "
        "The band is selectable; the slope's unit follows the band's "
        "declared unit per month of elapsed time. Descriptive only."
    )
    limitations = (
        _HISTORY_DISCLAIMER,
        "ERA5-Land is a reanalysis at roughly 11 km: the trend describes "
        "a modelled regional series, not a field measurement.",
        "A trend over a few years of a reanalysis band is dominated by "
        "interannual variability; significance over such a short series "
        "is a weak statement.",
        "The slope's unit is the band's own unit per 30.44-day month; it "
        "is not a rate of any physical process.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        from app.services.agriculture.climate import (
            ERA5_WORKING_SCALE,
            _reduce_era5_band,
        )
        from app.services.agriculture.registry import get_dataset

        band_name = context.option(
            "history_era5_band", "temperature_2m"
        )
        dataset = get_dataset(self.dataset_ids[0])
        static_reason = require_temporal_series(dataset)
        if static_reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=static_reason,
                message=(
                    "The primary dataset is a static product; no climate "
                    "series exists across it."
                ),
                unit=self.unit,
            )

        windows, error = _analysis_and_history_windows(
            context, HISTORY_BASELINE_YEARS
        )
        if error:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=error,
                unit=self.unit,
            )

        days: List[date] = []
        values: List[float] = []
        contributing = 0
        for index, (_years, win_start, win_end) in enumerate(windows):
            shifted = _shift_context(context, win_start, win_end)
            _stats, _day_count, daily = _reduce_era5_band(
                shifted, ee, band_name
            )
            if not daily:
                continue
            if index > 0:
                contributing += 1
            # Aggregate the per-day spatial means into calendar-month
            # means, in Python, without filling anything. The per-day
            # values arrive in collection order starting at the window
            # start, one per day.
            by_month: Dict[Tuple[int, int], List[float]] = {}
            for day_index, value in enumerate(daily):
                day = win_start + timedelta(days=day_index)
                if day > win_end:
                    break
                key = (day.year, day.month)
                by_month.setdefault(key, []).append(value)
            for (year, month), month_values in sorted(by_month.items()):
                days.append(date(year, month, 1))
                values.append(float(np.mean(month_values)))

        provenance = self._provenance(
            context, dataset, band_name, len(values), contributing
        )

        if contributing < HISTORY_MIN_YEARS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributing} of the {HISTORY_BASELINE_YEARS} "
                    "preceding years contributed usable data, which is "
                    f"fewer than the {HISTORY_MIN_YEARS} required to "
                    "characterise a trend."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        record = compute_trend(
            [
                ObservationPoint(day=day, value=value)
                for day, value in zip(days, values)
            ],
            min_n=MIN_TREND_OBS,
        )
        if record is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {len(values)} monthly observation(s) for band "
                    f"{band_name!r}; at least {MIN_TREND_OBS} are "
                    "required before a trend is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        slope_per_day = record.slope_per_day or 0.0
        value = slope_per_day * 30.44  # days per mean month
        warnings: List[str] = [
            (
                f"Band {band_name!r}: {record.n} monthly mean(s) from "
                f"{record.first_day.isoformat()} to "
                f"{record.last_day.isoformat()}; direction "
                f"'{record.direction.value}'."
            ),
            (
                f"Method: {record.method}."
                + (
                    ""
                    if record.mk_p is None
                    else f" Mann-Kendall p={record.mk_p:.3f} "
                    f"(z={record.mk_z:.2f}), significance at alpha=0.05: "
                    f"{record.significant}."
                )
            ),
            (
                "The slope is expressed per 30.44-day month for "
                "readability; it is a descriptive rate of the modelled "
                "series, not of any physical process."
            ),
        ]
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=value,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )

    def _provenance(
        self,
        context: MetricContext,
        dataset: Any,
        band_name: str,
        n_values: int,
        contributing: int,
    ) -> Provenance:
        return self.build_provenance(
            context=context,
            dataset=dataset,
            bands=[band_name],
            formula=(
                "per-day spatial means (climate module's shared "
                "reduction) aggregated into calendar-month means; slope = "
                "Theil-Sen median of pairwise slopes per day, reported "
                "per 30.44-day month; significance from the tie-corrected "
                f"Mann-Kendall test when n >= {MIN_TREND_OBS}"
            ),
            quality=QualityLevel.MODERATE if n_values else (
                QualityLevel.INSUFFICIENT
            ),
            image_count=n_values,
            aggregation_method=(
                "per-day spatial mean, calendar-month mean, one whole-"
                "year window at a time"
            ),
            extra_limitations=self.limitations,
            extra_caveats=(
                f"Reference population: {n_values} monthly value(s) from "
                f"{contributing} of {HISTORY_BASELINE_YEARS} preceding "
                "year(s) plus the analysis window.",
                "The requested band's own unit conversion is applied "
                "exactly once by the shared reduction helper.",
            ),
        )


# ==========================================================================
# 7. Phenology season-timing history
# ==========================================================================


class SeasonTimingHistoryMetric(Metric):
    """Vegetation season timing against preceding years' seasons.

    For the analysis year and each preceding whole year, the phenology
    engine detects the season on that year's own monthly series — same
    smoothing, same threshold, same gap rules. The value is the onset
    anomaly in days: the analysis season's onset day-of-year minus the
    mean onset day-of-year of the detected history seasons. The peak,
    end and length anomalies travel in the warnings.

    The vegetation season is not the crop calendar: none of these
    anomalies is a planting, flowering or harvest shift.
    """

    key = "season_timing_history"
    display_name = "Season Timing vs Historical Seasons"
    display_name_fa = "زمان‌بندی فصل نسبت به سال‌های گذشته"
    unit = "days"

    domain = MetricDomain.HISTORY
    dataset_ids = ("COPERNICUS/S2_SR_HARMONIZED",)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = 10

    description = (
        "The vegetation season's onset day-of-year minus the mean onset "
        "day-of-year of the seasons detected in the preceding years, on "
        "each year's own monthly NDVI series. Positive means later than "
        "the historical reference. Peak, end and length anomalies are "
        "reported alongside. This is vegetation-signal timing, not a "
        "crop-calendar shift."
    )
    limitations = (
        _HISTORY_DISCLAIMER,
        "The vegetation season is bounded by the amplitude-midpoint "
        "threshold on a smoothed monthly NDVI series; it is not a "
        "planting-to-harvest window and a timing anomaly is not a "
        "crop-calendar shift.",
        "A year whose season cannot be certified (too few months, an "
        "excessive gap, an unbounded span) contributes nothing to the "
        "reference rather than a fabricated date.",
        "Cloud cover at a season's shoulder delays the observed crossing "
        "independently of the vegetation's behaviour.",
        "Only years with a detected event of the same kind are compared; "
        "the reference population can therefore be smaller than the "
        "number of years requested.",
    )

    def can_attempt(self, context: MetricContext) -> Tuple[bool, Optional[str]]:
        can, reason = super().can_attempt(context)
        if not can:
            return can, reason
        start = context.start
        end = context.end
        if start is None or end is None:
            return False, "outside_temporal_coverage"
        # Each compared year must be a window the phenology engine can
        # certify: at least its own MIN_WINDOW_DAYS span.
        if (end - start).days + 1 < 180:
            return False, "window_too_short"
        return True, None

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        static_reason = require_temporal_series(dataset)
        if static_reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=static_reason,
                message=(
                    "The primary dataset is a static product; no seasonal "
                    "series exists across it."
                ),
                unit=self.unit,
            )

        windows, error = _analysis_and_history_windows(
            context, HISTORY_BASELINE_YEARS
        )
        if error:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=error,
                unit=self.unit,
            )

        def detect(window_start: date, window_end: date):
            shifted = _shift_context(context, window_start, window_end)
            monthly, _scenes, _stats = build_monthly_series_from_context(
                shifted, ee
            )
            if not monthly:
                return None
            return detect_season_events(monthly, window_start, window_end)

        def doy(value: Optional[date]) -> Optional[float]:
            if value is None:
                return None
            return float(value.timetuple().tm_yday)

        analysis_events = detect(windows[0][1], windows[0][2])
        history: Dict[str, List[float]] = {
            "onset": [],
            "peak": [],
            "end": [],
            "length": [],
        }
        contributing_years = 0
        for _years, win_start, win_end in windows[1:]:
            events = detect(win_start, win_end)
            if events is None:
                continue
            year_values = {
                "onset": doy(events.sos),
                "peak": doy(events.peak),
                "end": doy(events.eos),
                "length": (
                    float(events.los_days)
                    if events.los_days is not None
                    else None
                ),
            }
            contributed_any = False
            for name, value in year_values.items():
                if value is not None:
                    history[name].append(value)
                    contributed_any = True
            if contributed_any:
                contributing_years += 1

        provenance = self._provenance(
            context, dataset, contributing_years, history
        )

        if analysis_events is None or analysis_events.sos is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The phenology engine could not certify a season in "
                    "the analysis window (too few months, an excessive "
                    "gap, or no bounded span), so no timing anomaly is "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if len(history["onset"]) < MIN_SEASON_HISTORY:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {len(history['onset'])} of the "
                    f"{HISTORY_BASELINE_YEARS} preceding years yielded a "
                    f"certified season onset; at least "
                    f"{MIN_SEASON_HISTORY} are required to define a "
                    "timing reference, so no anomaly is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        onset_doy = doy(analysis_events.sos)
        assert onset_doy is not None
        onset_reference = float(np.mean(history["onset"]))
        value = onset_doy - onset_reference

        def anomaly_line(name: str, analysis_value: Optional[float]) -> str:
            values = history[name]
            if analysis_value is None or not values:
                return f"{name}: not comparable (no reference)."
            return (
                f"{name} anomaly: {analysis_value - float(np.mean(values)):+.1f} "
                f"(analysis {analysis_value:.0f} vs mean of "
                f"{len(values)} history season(s) "
                f"{float(np.mean(values)):.1f})"
            )

        warnings: List[str] = [
            (
                f"Onset: analysis day-of-year {onset_doy:.0f} vs mean "
                f"{onset_reference:.1f} over "
                f"{len(history['onset'])} history season(s)."
            ),
            anomaly_line(
                "peak", doy(analysis_events.peak)
            ),
            anomaly_line("end", doy(analysis_events.eos)),
            anomaly_line(
                "length",
                (
                    float(analysis_events.los_days)
                    if analysis_events.los_days is not None
                    else None
                ),
            ),
            (
                "These anomalies describe the vegetation signal's timing "
                "against preceding years' signals. They are not planting, "
                "flowering or harvest shifts and imply no cause."
            ),
            _HISTORY_DISCLAIMER,
        ]
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=value,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )

    def _provenance(
        self,
        context: MetricContext,
        dataset: Any,
        contributing_years: int,
        history: Dict[str, List[float]],
    ) -> Provenance:
        return self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["B4", "B8"],
            formula=(
                "per year: the phenology engine's season detection on "
                "that year's monthly NDVI series; onset anomaly = "
                "analysis onset day-of-year - mean onset day-of-year of "
                "the certified history seasons; peak, end and length "
                "anomalies computed the same way"
            ),
            quality=QualityLevel.MODERATE,
            image_count=contributing_years + 1,
            aggregation_method=(
                "one whole-year window per year; the phenology engine's "
                "own compositing, smoothing, threshold and gap rules "
                "apply unchanged in every window"
            ),
            extra_limitations=self.limitations,
            extra_caveats=(
                f"History seasons contributing an onset: "
                f"{len(history['onset'])} of {HISTORY_BASELINE_YEARS} "
                "preceding year(s).",
                (
                    f"Seasons contributing a length: "
                    f"{len(history['length'])}; a peak: "
                    f"{len(history['peak'])}; an end: "
                    f"{len(history['end'])}."
                ),
                "Years without a certified event of a given kind are "
                "excluded from that event's reference, never filled.",
            ),
        )


# ==========================================================================
# 8. The static-dataset refusal, demonstrated in the catalog
# ==========================================================================


class UnavailableStaticHistoryMetric(Metric):
    """Historical trend of a static surface — refused by the contract.

    NASADEM and SRTM are single-acquisition surfaces: their dates are
    product metadata, and a "trend" or "anomaly" across one would be a
    trend of nothing. The metric exists so the catalog answers the
    question with the exact machine-readable reason the framework
    enforces everywhere else.
    """

    key = "terrain_historical_trend"
    display_name = "Terrain Historical Trend (not computable)"
    display_name_fa = "روند تاریخی توپوگرافی (محاسبه‌ناپذیر)"
    unit = "m/year"

    domain = MetricDomain.HISTORY
    dataset_ids = ("NASA/NASADEM_HGT/001",)
    measurement_basis = MeasurementBasis.INFERENCE
    default_scale = 30

    unavailable_code = STATIC_NO_SERIES_CODE
    unavailable_reason = (
        "Not computable. The primary dataset (NASADEM) is a STATIC "
        "product: its temporal_kind declares that its dates record the "
        "February 2000 acquisition, not observations, and the surface "
        "has no time dimension. A historical trend, baseline or anomaly "
        "across a single-acquisition surface would manufacture a time "
        "series out of product metadata. The Phase H TemporalKind "
        "contract is enforced here, not weakened; historical analysis "
        "requires an OBSERVATION dataset."
    )
    description = (
        "A terrain trend over time. Not computable: NASADEM is a "
        "single-acquisition static surface with no time dimension."
    )
    limitations = (
        "Not computable. See the unavailable reason for the full "
        "argument.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        provenance = None
        try:
            dataset = self.primary_dataset()
            provenance = self.build_provenance(
                context=context,
                dataset=dataset,
                bands=[],
                formula="not computed",
                quality=QualityLevel.UNAVAILABLE,
                image_count=0,
                aggregation_method="not applicable",
            )
        except Exception:  # noqa: BLE001 - provenance is optional here
            provenance = None
        return MetricResult.unavailable(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            reason=self.unavailable_code,
            message=self.unavailable_reason,
            unit=self.unit,
            provenance=provenance,
        )

    def metadata(self) -> Dict[str, Any]:
        metadata = super().metadata()
        metadata["available"] = False
        metadata["unavailable_code"] = self.unavailable_code
        metadata["unavailable_reason"] = self.unavailable_reason
        return metadata


# ==========================================================================
# Collections
# ==========================================================================


HISTORY_METRICS: Tuple[Metric, ...] = (
    NdviAnomalyAbsoluteMetric(),
    NdviAnomalyRelativeMetric(),
    NdviAnomalyStandardizedMetric(),
    NdviPercentileContextMetric(),
    NdviTrendMetric(),
    NdviAnomalyPersistenceMetric(),
    NdviChangeShiftMetric(),
    ClimateTrendMetric(),
    SeasonTimingHistoryMetric(),
)

UNAVAILABLE_HISTORY_METRICS: Tuple[Metric, ...] = (
    UnavailableStaticHistoryMetric(),
)

ALL_HISTORY_METRICS: Tuple[Metric, ...] = (
    HISTORY_METRICS + UNAVAILABLE_HISTORY_METRICS
)


# ==========================================================================
# 10-Year Same-Period Historical Comparison Service (Phase P-AGRI-HIST-10Y)
# ==========================================================================

import hashlib
import json
from datetime import datetime

from app.schemas.agriculture import (
    HistoricalComparisonRequest,
    HistoricalComparisonResponse,
    HistoricalMetricTrend,
    HistoricalYearRecord,
    PointGeometry,
    PolygonGeometry,
)
from app.services.cache_service import cache_service
from app.services.earth_engine import initialize_earth_engine

HISTORICAL_CACHE_TTL = 43200

HIST_METRIC_META: Dict[str, Dict[str, Any]] = {
    "ndvi": {
        "display_name": "NDVI (Vegetation Index)",
        "display_name_fa": "شاخص پوشش گیاهی (NDVI)",
        "unit": "index",
        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "higher_is_better": True,
    },
    "evi": {
        "display_name": "EVI (Enhanced Vegetation Index)",
        "display_name_fa": "شاخص پوشش گیاهی پیشرفته (EVI)",
        "unit": "index",
        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "higher_is_better": True,
    },
    "ndre": {
        "display_name": "NDRE (Red Edge Chlorophyll)",
        "display_name_fa": "شاخص لبه قرمز کلروفیل (NDRE)",
        "unit": "index",
        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "higher_is_better": True,
    },
    "savi": {
        "display_name": "SAVI (Soil-Adjusted Vegetation Index)",
        "display_name_fa": "شاخص تعدیل‌شده خاک (SAVI)",
        "unit": "index",
        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "higher_is_better": True,
    },
    "msavi": {
        "display_name": "MSAVI (Modified Soil-Adjusted Index)",
        "display_name_fa": "شاخص اصلاح‌شده خاک (MSAVI)",
        "unit": "index",
        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "higher_is_better": True,
    },
    "ndmi": {
        "display_name": "NDMI (Canopy Moisture Index)",
        "display_name_fa": "شاخص رطوبت کانوپی (NDMI)",
        "unit": "index",
        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "higher_is_better": True,
    },
    "ndwi": {
        "display_name": "NDWI (Water Index)",
        "display_name_fa": "شاخص محتوای آب (NDWI)",
        "unit": "index",
        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "higher_is_better": True,
    },
    "msi": {
        "display_name": "MSI (Moisture Stress Index)",
        "display_name_fa": "شاخص تنش رطوبتی (MSI)",
        "unit": "index",
        "dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "higher_is_better": False,  # Higher MSI means more moisture stress
    },
    "lst_day": {
        "display_name": "Day Land Surface Temperature",
        "display_name_fa": "دمای روزانه سطح زمین (LST)",
        "unit": "°C",
        "dataset": "MODIS/061/MOD11A2",
        "higher_is_better": False,
    },
    "temperature_mean": {
        "display_name": "Mean Air Temperature (2m)",
        "display_name_fa": "میانگین دمای هوا (۲ متر)",
        "unit": "°C",
        "dataset": "ECMWF/ERA5_LAND/DAILY_AGGR",
        "higher_is_better": None,
    },
    "precipitation": {
        "display_name": "Total Precipitation",
        "display_name_fa": "مجموع بارش",
        "unit": "mm",
        "dataset": "ECMWF/ERA5_LAND/DAILY_AGGR",
        "higher_is_better": True,
    },
    "sar_vh": {
        "display_name": "Sentinel-1 Radar VH Backscatter",
        "display_name_fa": "پراکندگی راداری سنتینل-۱ (VH)",
        "unit": "dB",
        "dataset": "COPERNICUS/S1_GRD",
        "higher_is_better": True,
    },
    "soil_moisture": {
        "display_name": "Root-Zone Soil Moisture (0–100 cm)",
        "display_name_fa": "رطوبت خاک ناحیه ریشه (۰ تا ۱۰۰ سانتی‌متر)",
        "unit": "m³/m³",
        "dataset": "ECMWF/ERA5_LAND/DAILY_AGGR",
        "higher_is_better": True,
    },
}

HIST_DOMAIN_METRICS: Dict[str, List[str]] = {
    "vegetation": ["ndvi", "evi", "ndre", "savi", "msavi"],
    "water": ["ndmi", "ndwi", "msi"],
    "stress": ["msi", "ndmi", "lst_day"],
    "thermal": ["lst_day", "temperature_mean"],
    "climate": ["temperature_mean", "precipitation"],
    "radar": ["sar_vh"],
    "phenology": ["ndvi", "ndre"],
    "soil": ["soil_moisture"],
    "history": ["ndvi", "ndmi", "ndre", "msi"],
}


def _build_hist_cache_key(request: HistoricalComparisonRequest, metrics: List[str]) -> str:
    """Deterministic MD5 cache key for historical requests."""
    geom_dict = (
        request.geometry.model_dump()
        if hasattr(request.geometry, "model_dump")
        else dict(request.geometry)
    )
    payload = {
        "geom": geom_dict,
        "start": request.start_date,
        "end": request.end_date,
        "domain": request.domain,
        "metrics": sorted(metrics),
        "cloud": request.cloud_max_percent,
    }
    raw = json.dumps(payload, sort_keys=True)
    return f"agri:hist10y:{hashlib.md5(raw.encode('utf-8')).hexdigest()}"


def _format_same_period_label(start_d: date, end_d: date) -> Tuple[str, str]:
    """Format same-period labels in English and Jalali."""
    months_en = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    en_label = f"{months_en[start_d.month - 1]} {start_d.day} – {months_en[end_d.month - 1]} {end_d.day}"
    try:
        from app.utils.dates import gregorian_to_jalali
        j_start = gregorian_to_jalali(start_d)
        j_end = gregorian_to_jalali(end_d)
        fa_months = [
            "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
            "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
        ]
        fa_label = f"{j_start.day} {fa_months[j_start.month - 1]} تا {j_end.day} {fa_months[j_end.month - 1]}"
    except Exception:
        fa_label = f"{start_d.month}/{start_d.day} تا {end_d.month}/{end_d.day}"
    return fa_label, en_label


def _compute_hist_ee_geometry(request: HistoricalComparisonRequest, ee: Any) -> Tuple[Any, float]:
    """Convert request geometry to EE geometry and compute scale."""
    geom = request.geometry
    if isinstance(geom, PointGeometry) or (isinstance(geom, dict) and geom.get("type") == "Point"):
        coords = geom.coordinates if hasattr(geom, "coordinates") else geom["coordinates"]
        lon, lat = coords[0], coords[1]
        region = ee.Geometry.Point([lon, lat]).buffer(60)
        return region, 10.0
    elif isinstance(geom, PolygonGeometry) or (isinstance(geom, dict) and geom.get("type") == "Polygon"):
        coords = geom.coordinates if hasattr(geom, "coordinates") else geom["coordinates"]
        return ee.Geometry.Polygon(coords), 10.0
    else:
        coords_raw = geom.coordinates if hasattr(geom, "coordinates") else geom.get("coordinates", [0, 0])
        if isinstance(coords_raw[0], (int, float)):
            region = ee.Geometry.Point([coords_raw[0], coords_raw[1]]).buffer(60)
            return region, 10.0
        return ee.Geometry.Polygon(coords_raw), 10.0


def _calculate_10y_trend(
    years_data: List[Tuple[int, Optional[float]]],
    meta: Dict[str, Any],
) -> HistoricalMetricTrend:
    """Calculate Theil-Sen trend and baseline comparison for a metric."""
    metric_key = meta.get("metric", "")
    valid_points = [(yr, val) for yr, val in years_data if val is not None and not math.isnan(val)]

    # Needs at least 3 years to compute any defensible trend
    if len(valid_points) < 3:
        current_val = years_data[0][1] if years_data and years_data[0][1] is not None else None
        return HistoricalMetricTrend(
            metric_key=metric_key,
            display_name=meta.get("display_name", metric_key),
            display_name_fa=meta.get("display_name_fa", metric_key),
            unit=meta.get("unit", ""),
            current_value=current_val,
            trend_direction="insufficient_evidence",
            trend_label_fa="شواهد ناکافی (کمتر از ۳ سال داده)",
            trend_label_en="Insufficient evidence (< 3 observations)",
            sufficiency="insufficient",
            scientific_summary_fa="تعداد مشاهدات تاریخی برای تعیین روند معتبر کافی نیست.",
            scientific_summary_en="Historical observations are insufficient to characterize a trend.",
        )

    sorted_pts = sorted(valid_points, key=lambda x: x[0])
    years = [p[0] for p in sorted_pts]
    values = [p[1] for p in sorted_pts]

    current_yr = years_data[0][0]
    hist_values = [p[1] for p in sorted_pts if p[0] != current_yr]
    current_val = next((val for yr, val in years_data if yr == current_yr and val is not None), None)

    median_val = float(np.median(hist_values)) if hist_values else (float(np.median(values)) if values else None)
    mean_val = float(np.mean(hist_values)) if hist_values else (float(np.mean(values)) if values else None)

    delta = None
    if current_val is not None and median_val is not None:
        delta = round(current_val - median_val, 4)

    days_mock = [date(y, 1, 1) for y in years]
    daily_slope = theil_sen_slope(days_mock, values)
    yearly_slope = (daily_slope * 365.25) if daily_slope is not None else None

    val_spread = float(np.std(values)) if len(values) >= 2 else 0.0
    higher_is_better = meta.get("higher_is_better", True)

    if yearly_slope is None or val_spread == 0:
        trend_dir = "stable"
        label_fa = "پایدار"
        label_en = "Stable"
    else:
        total_span = (years[-1] - years[0])
        implied_shift = abs(yearly_slope * total_span)
        if implied_shift < 0.15 * val_spread:
            trend_dir = "stable"
            label_fa = "پایدار"
            label_en = "Stable"
        elif yearly_slope > 0:
            if higher_is_better is True:
                trend_dir = "improving"
                label_fa = "رو به بهبود"
                label_en = "Improving"
            elif higher_is_better is False:
                trend_dir = "declining"
                label_fa = "افزایش تنش (نامساعد)"
                label_en = "Increasing stress"
            else:
                trend_dir = "increasing"
                label_fa = "افزایشی"
                label_en = "Increasing"
        else:
            if higher_is_better is True:
                trend_dir = "declining"
                label_fa = "رو به کاهش"
                label_en = "Declining"
            elif higher_is_better is False:
                trend_dir = "improving"
                label_fa = "کاهش تنش (بهبود)"
                label_en = "Decreasing stress"
            else:
                trend_dir = "decreasing"
                label_fa = "کاهشی"
                label_en = "Decreasing"

    if delta is not None and median_val is not None:
        if abs(delta) < 0.01:
            comparison_fa = "نزدیک به میانه ۱۰ ساله"
            comparison_en = "near the 10-year historical median"
        elif delta > 0:
            comparison_fa = f"{abs(delta):.3f} بالاتر از میانه ۱۰ ساله"
            comparison_en = f"{abs(delta):.3f} above the 10-year median"
        else:
            comparison_fa = f"{abs(delta):.3f} پایین‌تر از میانه ۱۰ ساله"
            comparison_en = f"{abs(delta):.3f} below the 10-year median"
    else:
        comparison_fa = "پایه تاریخی ناکافی"
        comparison_en = "insufficient historical baseline"

    curr_val_str = f"{current_val:.3f}" if current_val is not None else "—"
    summary_fa = (
        f"روند ۱۰ ساله دوره مشابه: {label_fa}. "
        f"مقدار دوره جاری ({curr_val_str}) {comparison_fa} است."
    )
    summary_en = (
        f"10-year same-period trend: {label_en}. "
        f"Current period value ({curr_val_str}) is {comparison_en}."
    )

    return HistoricalMetricTrend(
        metric_key=metric_key,
        display_name=meta.get("display_name", metric_key),
        display_name_fa=meta.get("display_name_fa", metric_key),
        unit=meta.get("unit", ""),
        current_value=round(current_val, 4) if current_val is not None else None,
        baseline_median=round(median_val, 4) if median_val is not None else None,
        baseline_mean=round(mean_val, 4) if mean_val is not None else None,
        delta_from_baseline=delta,
        trend_direction=trend_dir,
        trend_slope_per_year=round(yearly_slope, 5) if yearly_slope is not None else None,
        trend_label_fa=label_fa,
        trend_label_en=label_en,
        sufficiency="sufficient" if len(valid_points) >= 6 else "partial",
        scientific_summary_fa=summary_fa,
        scientific_summary_en=summary_en,
    )


def generate_historical_comparison(
    request: HistoricalComparisonRequest,
) -> HistoricalComparisonResponse:
    """Generate 10-year same-period historical comparison using real GEE satellite data.

    Preserves exact calendar windows across the preceding 10 years.
    Never fabricates missing years or values.
    """
    try:
        start_d = datetime.strptime(request.start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(request.end_date, "%Y-%m-%d").date()
    except Exception as exc:
        raise ValueError(f"Invalid date format: {exc}")

    if start_d >= end_d:
        raise ValueError("start_date must be strictly before end_date")

    windows: List[Tuple[int, date, date]] = [(0, start_d, end_d)]
    for y in range(1, 10):
        try:
            w_s, w_e = shift_window_years(start_d, end_d, y)
            windows.append((y, w_s, w_e))
        except Exception as exc:
            logger.warning(f"Failed to shift window by {y} years: {exc}")

    fa_label, en_label = _format_same_period_label(start_d, end_d)

    domain_key = (request.domain or "vegetation").lower()
    if request.metric_keys:
        metrics_to_run = [m for m in request.metric_keys if m in HIST_METRIC_META]
    elif domain_key in HIST_DOMAIN_METRICS:
        metrics_to_run = HIST_DOMAIN_METRICS[domain_key]
    else:
        metrics_to_run = HIST_DOMAIN_METRICS["vegetation"]

    if not metrics_to_run:
        metrics_to_run = ["ndvi"]

    limitations = [
        "داده‌های تاریخی بازتاب‌دهنده میانگین‌های ماهواره‌ای دوره مشابه در سال‌های گذشته هستند و علت بیولوژیکی تغییرات را اثبات نمی‌کنند.",
        "در سال‌های با پوشش ابری بالا یا عدم حضور ماهواره (پیش از سال ۲۰۱۷ در برخی سنجنده‌ها)، داده به صورت صریح ناموجود (Unavailable) گزارش شده است.",
    ]
    if domain_key == "soil":
        limitations.append("⛔ داده‌های شیمیایی خاک (شوری، عناصر، pH) در داده‌های ماهواره‌ای تاریخی موجود نیست و نیازمند آزمون خاک است.")
    if domain_key == "productivity":
        limitations.append("⛔ برآورد تناژ یا عملکرد محصول در داده‌های تاریخی کالیبره نشده و غیرفعال است.")

    cache_key = _build_hist_cache_key(request, metrics_to_run)
    try:
        cached = cache_service.get(cache_key)
        if cached:
            logger.info(f"Historical comparison cache hit for {cache_key}")
            return HistoricalComparisonResponse.model_validate(cached)
    except Exception as exc:
        logger.warning(f"Cache lookup failed: {exc}")

    try:
        initialize_earth_engine()
        import ee
    except Exception as exc:
        logger.error(f"Earth Engine init failed: {exc}")
        records = [
            HistoricalYearRecord(
                year=w_s.year,
                start_date=w_s.isoformat(),
                end_date=w_e.isoformat(),
                status="unavailable",
                scene_count=0,
                metrics={m: None for m in metrics_to_run},
            )
            for idx, w_s, w_e in windows
        ]
        return HistoricalComparisonResponse(
            requested_period={"start_date": request.start_date, "end_date": request.end_date},
            same_period_label_fa=fa_label,
            same_period_label_en=en_label,
            domain=domain_key,
            available_metrics=metrics_to_run,
            years=records,
            trends={},
            limitations=["Earth Engine service unavailable."],
        )

    region, scale = _compute_hist_ee_geometry(request, ee)

    s2_metrics = [m for m in metrics_to_run if HIST_METRIC_META[m]["dataset"] == "COPERNICUS/S2_SR_HARMONIZED"]
    other_metrics = [m for m in metrics_to_run if HIST_METRIC_META[m]["dataset"] != "COPERNICUS/S2_SR_HARMONIZED"]

    year_eval_dict = {}

    for idx, w_s, w_e in windows:
        yr_key = str(w_s.year)
        w_dict = {}

        if s2_metrics:
            col = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(region)
                .filterDate(w_s.isoformat(), w_e.isoformat())
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", request.cloud_max_percent))
            )
            cnt = col.size()
            w_dict["s2_count"] = cnt

            def add_all_indices(img: Any) -> Any:
                ndvi = img.normalizedDifference(["B8", "B4"]).rename("ndvi")
                ndmi = img.normalizedDifference(["B8", "B11"]).rename("ndmi")
                ndwi = img.normalizedDifference(["B3", "B8"]).rename("ndwi")
                ndre = img.normalizedDifference(["B8A", "B5"]).rename("ndre")
                msi = img.select("B11").divide(img.select("B8")).rename("msi")
                evi = img.expression(
                    "2.5 * ((b('B8') - b('B4')) / (b('B8') + 6 * b('B4') - 7.5 * b('B2') + 1))"
                ).rename("evi")
                savi = img.expression(
                    "((b('B8') - b('B4')) / (b('B8') + b('B4') + 0.5)) * 1.5"
                ).rename("savi")
                msavi = img.expression(
                    "(2 * b('B8') + 1 - sqrt(pow((2 * b('B8') + 1), 2) - 8 * (b('B8') - b('B4')))) / 2"
                ).rename("msavi")
                return img.addBands([ndvi, ndmi, ndwi, ndre, msi, evi, savi, msavi])

            masked_zeros = ee.Image.constant(0).mask(ee.Image.constant(0))
            dummy_img = ee.Image([masked_zeros.rename(m) for m in s2_metrics])
            med = ee.Image(
                ee.Algorithms.If(
                    cnt.gt(0),
                    col.map(add_all_indices).median(),
                    dummy_img,
                )
            )
            reduced = med.select(s2_metrics).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region,
                scale=scale,
                bestEffort=True,
                maxPixels=1000000,
            )
            for m in s2_metrics:
                w_dict[m] = reduced.get(m)

        for m in other_metrics:
            if m == "lst_day":
                m_col = (
                    ee.ImageCollection("MODIS/061/MOD11A2")
                    .filterBounds(region)
                    .filterDate(w_s.isoformat(), w_e.isoformat())
                )
                m_cnt = m_col.size()
                m_dummy = ee.Image.constant(0).mask(ee.Image.constant(0)).rename("LST_Day_1km")
                m_img = ee.Image(
                    ee.Algorithms.If(
                        m_cnt.gt(0),
                        m_col.select("LST_Day_1km").mean().multiply(0.02).subtract(273.15),
                        m_dummy,
                    )
                )
                w_dict[m] = m_img.reduceRegion(
                    reducer=ee.Reducer.mean(), geometry=region, scale=1000
                ).get("LST_Day_1km")
            elif m == "temperature_mean":
                c_col = (
                    ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
                    .filterBounds(region)
                    .filterDate(w_s.isoformat(), w_e.isoformat())
                )
                c_img = c_col.select("temperature_2m").mean().subtract(273.15)
                w_dict[m] = c_img.reduceRegion(
                    reducer=ee.Reducer.mean(), geometry=region, scale=11132
                ).get("temperature_2m")
            elif m == "precipitation":
                p_col = (
                    ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
                    .filterBounds(region)
                    .filterDate(w_s.isoformat(), w_e.isoformat())
                )
                p_img = p_col.select("total_precipitation_sum").sum().multiply(1000.0)
                w_dict[m] = p_img.reduceRegion(
                    reducer=ee.Reducer.mean(), geometry=region, scale=11132
                ).get("total_precipitation_sum")
            elif m == "sar_vh":
                s1_col = (
                    ee.ImageCollection("COPERNICUS/S1_GRD")
                    .filterBounds(region)
                    .filterDate(w_s.isoformat(), w_e.isoformat())
                    .filter(ee.Filter.eq("instrumentMode", "IW"))
                )
                s1_cnt = s1_col.size()
                s1_dummy = ee.Image.constant(0).mask(ee.Image.constant(0)).rename("VH")
                s1_img = ee.Image(
                    ee.Algorithms.If(
                        s1_cnt.gt(0),
                        s1_col.select("VH").mean(),
                        s1_dummy,
                    )
                )
                w_dict[m] = s1_img.reduceRegion(
                    reducer=ee.Reducer.mean(), geometry=region, scale=10
                ).get("VH")
            elif m == "soil_moisture":
                sm_col = (
                    ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
                    .filterBounds(region)
                    .filterDate(w_s.isoformat(), w_e.isoformat())
                )
                # Weighted root-zone average 0-100 cm: layer 1 (7cm) + layer 2 (21cm) + layer 3 (72cm)
                sm_img = sm_col.select([
                    "volumetric_soil_water_layer_1",
                    "volumetric_soil_water_layer_2",
                    "volumetric_soil_water_layer_3",
                ]).mean()
                rz_expr = sm_img.expression(
                    "(l1 * 7.0 + l2 * 21.0 + l3 * 72.0) / 100.0",
                    {
                        "l1": sm_img.select("volumetric_soil_water_layer_1"),
                        "l2": sm_img.select("volumetric_soil_water_layer_2"),
                        "l3": sm_img.select("volumetric_soil_water_layer_3"),
                    },
                ).rename("soil_moisture")
                w_dict[m] = rz_expr.reduceRegion(
                    reducer=ee.Reducer.first(), geometry=region.centroid(1), scale=11132
                ).get("soil_moisture")

        year_eval_dict[yr_key] = ee.Dictionary(w_dict)

    try:
        combined_dict = ee.Dictionary(year_eval_dict).getInfo()
    except Exception as exc:
        logger.error(f"GEE batched evaluation failed: {exc}")
        combined_dict = {}

    year_records: List[HistoricalYearRecord] = []
    metric_series: Dict[str, List[Tuple[int, Optional[float]]]] = {m: [] for m in metrics_to_run}

    for idx, w_s, w_e in windows:
        yr = w_s.year
        yr_key = str(yr)
        raw_vals = combined_dict.get(yr_key, {})
        scene_count = int(raw_vals.get("s2_count", 0))

        record_metrics: Dict[str, Optional[float]] = {}
        for m in metrics_to_run:
            val = raw_vals.get(m)
            if val is not None and isinstance(val, (int, float)) and not math.isnan(val):
                record_metrics[m] = round(float(val), 4)
            else:
                record_metrics[m] = None
            metric_series[m].append((yr, record_metrics[m]))

        has_any_val = any(v is not None for v in record_metrics.values())
        if idx == 0:
            status = "current"
        elif has_any_val:
            status = "available" if scene_count >= 5 else "partial"
        else:
            status = "unavailable"

        year_records.append(
            HistoricalYearRecord(
                year=yr,
                start_date=w_s.isoformat(),
                end_date=w_e.isoformat(),
                status=status,
                scene_count=scene_count,
                metrics=record_metrics,
            )
        )

    trends: Dict[str, HistoricalMetricTrend] = {}
    for m in metrics_to_run:
        meta = {**HIST_METRIC_META[m], "metric": m}
        trends[m] = _calculate_10y_trend(metric_series[m], meta)

    response = HistoricalComparisonResponse(
        requested_period={"start_date": request.start_date, "end_date": request.end_date},
        same_period_label_fa=fa_label,
        same_period_label_en=en_label,
        domain=domain_key,
        available_metrics=metrics_to_run,
        years=year_records,
        trends=trends,
        limitations=limitations,
    )

    try:
        cache_service.set(cache_key, response.model_dump())
    except Exception as exc:
        logger.warning(f"Failed to cache historical comparison: {exc}")

    return response

