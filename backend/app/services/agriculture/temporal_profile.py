"""Multi-year temporal profiles over registered agricultural metrics.

P1.1 foundation for the Pest & Disease Early Warning layer.
Infrastructure only: this module builds structured observation
sequences and performs no diagnosis, no ML, no scoring, and no
anomaly arithmetic.

A temporal profile re-evaluates one already-registered metric over
the calendar months intersecting a requested window, reusing that
metric's own verified ``compute`` per sub-window (the same pattern
the interannual anomaly metrics use for baseline windows).  Each
point therefore carries exactly the value, quality, coverage, and
provenance the metric itself would publish for that month — nothing
is interpolated, nothing is filled, and missing months stay missing
instead of becoming zero.

Month iteration reuses :func:`app.utils.dates.get_monthly_periods`
(the repository's date-window abstraction; edge months snap to
calendar-month boundaries, consistent with the phenology
calendar-month means).  Window validation reuses
:func:`app.utils.dates.validate_date_range`.

Supported profile metrics (P1.1 candidates; all registered DERIVED
window metrics — RVI is registered but outside the P1.1 candidate
list and stays unsupported until a later phase asks for it):

* ``ndvi``, ``ndmi``, ``ndre``, ``msi`` (Sentinel-2)
* ``vv``, ``vh``, ``vh_vv`` (Sentinel-1)

Static products, cumulative totals, anomalies, and proxies are
deliberately unsupported: a profile needs repeatable per-window
observations of the same physical quantity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Type

from app.core.logging import get_logger
from app.services.agriculture.base import Metric, MetricContext
from app.services.agriculture.radar import (
    VHBackscatterMetric,
    VHVVRatioMetric,
    VVBackscatterMetric,
)
from app.services.agriculture.vegetation import NDREMetric, NDVIMetric
from app.services.agriculture.water import MSIMetric, NDMIMetric
from app.utils.dates import get_monthly_periods, validate_date_range

logger = get_logger(__name__)

__all__ = [
    "SUPPORTED_PROFILE_METRICS",
    "TemporalProfilePoint",
    "TemporalProfile",
    "month_windows",
    "build_temporal_profile",
    "usable_values",
]

#: Metric classes eligible for temporal profiles, keyed by registry key.
#: Every entry is a per-window observation metric; nothing cumulative,
#: static, derived-anomaly, or proxy is admitted.
SUPPORTED_PROFILE_METRICS: Dict[str, Type[Metric]] = {
    "ndvi": NDVIMetric,
    "ndmi": NDMIMetric,
    "ndre": NDREMetric,
    "msi": MSIMetric,
    "vv": VVBackscatterMetric,
    "vh": VHBackscatterMetric,
    "vh_vv": VHVVRatioMetric,
}

#: Temporal step identifier published on every profile.
STEP_CALENDAR_MONTH = "calendar_month"


@dataclass(frozen=True)
class TemporalProfilePoint:
    """One monthly observation of a metric.

    A missing observation is ``value=None`` with whatever quality the
    failed window reported (``"unavailable"`` when nothing ran at
    all).  Missing is structural: consumers must render gaps, never
    interpolate.
    """

    window_start: str
    window_end: str
    value: Optional[float]
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None


@dataclass(frozen=True)
class TemporalProfile:
    """A chronological sequence of monthly observations for one metric."""

    metric_key: str
    dataset_id: Optional[str]
    unit: str
    window_start: str
    window_end: str
    step: str = STEP_CALENDAR_MONTH
    points: Tuple[TemporalProfilePoint, ...] = field(default_factory=tuple)

    @property
    def n_points(self) -> int:
        """Total months emitted, including missing ones."""
        return len(self.points)

    @property
    def n_usable(self) -> int:
        """Months carrying a finite value."""
        return sum(1 for point in self.points if _is_usable_value(point.value))

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.1 API contract models."""
        return {
            "metric_key": self.metric_key,
            "dataset_id": self.dataset_id,
            "unit": self.unit,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "points": [
                {
                    "window_start": point.window_start,
                    "window_end": point.window_end,
                    "value": point.value,
                    "unit": point.unit,
                    "quality": point.quality,
                    "coverage_percent": point.coverage_percent,
                    "image_count": point.image_count,
                }
                for point in self.points
            ],
        }


def _is_usable_value(value: Any) -> bool:
    """Finite numbers only: None, NaN, infinities, and bools are gaps."""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def month_windows(start_date: str, end_date: str) -> List[Tuple[str, str]]:
    """Calendar-month sub-windows intersecting ``[start_date, end_date]``.

    Thin wrapper over the repository's :func:`get_monthly_periods`
    so profile code depends on one documented month semantic.
    """
    return [
        (window_start, window_end)
        for window_start, window_end in get_monthly_periods(start_date, end_date)
    ]


def usable_values(profile: TemporalProfile) -> List[float]:
    """Finite observation values in chronological order, gaps dropped.

    Structural input for the next phase's baseline statistics (mean,
    standard deviation, percentile, anomaly).  This helper selects;
    it never fills, smooths, or otherwise transforms.
    """
    return [
        float(point.value)
        for point in profile.points
        if _is_usable_value(point.value)
    ]


def _missing_point(
    window_start: str, window_end: str, unit: str, quality: str = "unavailable"
) -> TemporalProfilePoint:
    return TemporalProfilePoint(
        window_start=window_start,
        window_end=window_end,
        value=None,
        unit=unit,
        quality=quality,
        coverage_percent=None,
        image_count=None,
    )


def _point_from_result(
    window_start: str,
    window_end: str,
    unit: str,
    result: Any,
) -> TemporalProfilePoint:
    """Translate one sub-window metric result into a profile point."""
    value = result.value if _is_usable_value(result.value) else None
    provenance = result.provenance
    quality = "unavailable"
    image_count: Optional[int] = None
    if provenance is not None:
        quality_level = provenance.quality_level
        quality = (
            quality_level.value
            if hasattr(quality_level, "value")
            else str(quality_level)
        )
        image_count = provenance.image_count
    coverage: Optional[float] = None
    stats = result.stats
    if stats is not None:
        raw_coverage = getattr(stats, "coverage_percent", None)
        if isinstance(raw_coverage, (int, float)) and math.isfinite(raw_coverage):
            coverage = float(raw_coverage)
    return TemporalProfilePoint(
        window_start=window_start,
        window_end=window_end,
        value=float(value) if value is not None else None,
        unit=unit,
        quality=quality,
        coverage_percent=coverage,
        image_count=image_count,
    )


def build_temporal_profile(
    metric_key: str, context: MetricContext
) -> TemporalProfile:
    """Build the monthly observation profile for one supported metric.

    Every intersecting calendar month is emitted exactly once, in
    chronological order, by running the metric's own ``compute`` on
    that month's sub-context (geometry, scale, cloud tolerance, and
    options carried over unchanged).  A month that cannot be computed
    — no scenes, full masking, non-finite reduction, or a raised
    exception — becomes a missing point, never a zero and never an
    interpolation of its neighbours.

    Raises:
        ValueError: when ``metric_key`` is not a supported profile
            metric (unknown keys and incompatible registered kinds
            alike; the message lists what is supported).
        DateRangeError: when the requested window is malformed or
            empty, via the repository's own window validation.
    """
    if metric_key not in SUPPORTED_PROFILE_METRICS:
        supported = ", ".join(sorted(SUPPORTED_PROFILE_METRICS))
        raise ValueError(
            f"Temporal profiles are not supported for {metric_key!r}. "
            f"Supported profile metrics: {supported}."
        )
    validate_date_range(context.start_date, context.end_date)

    metric_cls = SUPPORTED_PROFILE_METRICS[metric_key]
    probe = metric_cls()
    dataset_id = probe.primary_dataset_id
    unit = probe.unit

    windows = month_windows(context.start_date, context.end_date)

    can_attempt, _reason = probe.can_attempt(context)
    if not can_attempt:
        logger.warning(
            "Temporal profile for %s: requested window %s to %s is "
            "outside the source coverage, emitting %d missing month(s) "
            "without running observations.",
            metric_key,
            context.start_date,
            context.end_date,
            len(windows),
        )
        return TemporalProfile(
            metric_key=metric_key,
            dataset_id=dataset_id,
            unit=unit,
            window_start=context.start_date,
            window_end=context.end_date,
            points=tuple(
                _missing_point(window_start, window_end, unit)
                for window_start, window_end in windows
            ),
        )

    points: List[TemporalProfilePoint] = []
    for window_start, window_end in windows:
        sub_context = replace(
            context, start_date=window_start, end_date=window_end
        )
        try:
            result = metric_cls().compute(sub_context)
        except Exception as exc:  # noqa: BLE001 - one month cannot sink the profile
            logger.warning(
                "Temporal profile for %s: month %s to %s failed (%s); "
                "recording a missing observation.",
                metric_key,
                window_start,
                window_end,
                type(exc).__name__,
            )
            points.append(_missing_point(window_start, window_end, unit))
            continue
        if result is None:
            points.append(_missing_point(window_start, window_end, unit))
            continue
        points.append(_point_from_result(window_start, window_end, unit, result))

    return TemporalProfile(
        metric_key=metric_key,
        dataset_id=dataset_id,
        unit=unit,
        window_start=context.start_date,
        window_end=context.end_date,
        points=tuple(points),
    )
