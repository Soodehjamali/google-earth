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
