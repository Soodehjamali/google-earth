"""Sentinel-1 radar temporal profile foundation (P2.3).

Deterministic monthly radar observations for the registered
Sentinel-1 metrics, built by running each metric's own production
computation once per intersecting calendar month.  This layer is a
measurement and profile foundation only: it observes and reports,
never interpolates, never fills, and never interprets.

Sentinel-1 radar backscatter is sensitive to multiple factors,
including vegetation structure and biomass, surface roughness,
soil moisture, viewing geometry, incidence angle, acquisition
conditions, and processing choices.  VV, VH, VH/VV, and RVI are
measurements and derived measurements, not biological diagnoses:
temporal radar changes do not uniquely identify pests or diseases,
and any future interpretation must combine radar with other
evidence while accounting for acquisition, geometry, and
seasonality effects.  This phase makes no causal claim.

Registered radar metrics (CD-3 audit — every entry below traces
registry to metric compute to the Sentinel-1 composite path):

* ``vv`` — VV co-polarized backscatter mean, decibels.
* ``vh`` — VH cross-polarized backscatter mean, decibels.
* ``vh_vv`` — cross-polarization ratio as a decibel difference
  (``VH - VV``), computed by the registered metric on the shared
  composite, never recombined here from two profile values.
* ``rvi`` — dual-polarization Radar Vegetation Index
  (``4*VH/(VV+VH)`` in linear power), dimensionless ratio,
  produced by the registered metric's own verified image algebra.

All four share one production contract
(:class:`app.services.agriculture.radar._RadarMetric`): the
homogeneous ``build_s1_composite`` subset (IW mode,
dual-polarization VV+VH, descending pass, temporal mean in native
decibels, no cloud mask because none exists for SAR), reduction at
the 10 m IW GRD scale, ``SAR_THRESHOLDS`` quality assessment, and
the same provenance shape.  RVI differs only in unit and
expression, so it is genuinely supported here; the P1.1 candidate
list excluded it as a scoping choice, not a readiness statement.

Reused machinery (nothing re-derived):

* per-month computation from each metric's own ``compute`` via a
  sub-context carrying the caller's geometry, scale, and options
  (the P1.1 sibling-compute pattern);
* calendar-month iteration via
  :func:`app.services.agriculture.temporal_profile.month_windows`
  and window validation via
  :func:`app.utils.dates.validate_date_range`;
* geometry via :class:`app.services.agriculture.base.MetricContext`
  (opaque geometry plus serialisable ``geometry_key`` — no new
  grid, no reprojection, no normalization beyond existing
  utilities);
* quality vocabulary and missing-data semantics from the shared
  :class:`MetricResult` / :class:`Provenance` types.

Temporal behavior: every intersecting calendar month is emitted
exactly once, in chronological order.  A month that cannot be
computed — no acquisitions, full invalidity, non-finite
reduction, or a raised exception — becomes a missing point with
``value=None``, never a zero and never an interpolation of its
neighbours.  One monthly observation corresponds to exactly one
requested calendar window: no merging, no nearest-matching, no
orbit substitution, no geometry or window changes.

Historical compatibility: each profile keeps ``(window, value,
unit, quality, coverage, image_count)`` order per metric, and
:func:`to_temporal_profile` adapts a radar profile to the generic
P1.2 profile shape for later baseline processing.  No Z-scores,
no anomaly categories, no persistence, no breakpoints, and no
cut-offs are implemented here.

Non-goals of this phase: cause attribution, anomaly or risk
logic of any kind, model inference, thermal inputs, new datasets,
endpoints, charts, and cache changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Type

from app.core.logging import get_logger
from app.services.agriculture.base import Metric, MetricContext
from app.services.agriculture.radar import (
    S1_DATASET_ID,
    S1_MODE,
    S1_PASS,
    S1_SCALE,
    RVIMetric,
    VHBackscatterMetric,
    VHVVRatioMetric,
    VVBackscatterMetric,
)
from app.services.agriculture.temporal_profile import month_windows
from app.utils.dates import validate_date_range

logger = get_logger(__name__)

__all__ = [
    "SUPPORTED_RADAR_PROFILE_METRICS",
    "STEP_CALENDAR_MONTH",
    "RadarProfilePoint",
    "RadarProfile",
    "build_radar_profile",
    "usable_values",
    "to_temporal_profile",
    "radar_metadata",
]

#: Metric classes eligible for radar temporal profiles, keyed by
#: registry key.  Every entry is a per-window Sentinel-1 observation
#: metric sharing the homogeneous IW / VV+VH / descending-pass
#: composite contract.
SUPPORTED_RADAR_PROFILE_METRICS: Dict[str, Type[Metric]] = {
    "vv": VVBackscatterMetric,
    "vh": VHBackscatterMetric,
    "vh_vv": VHVVRatioMetric,
    "rvi": RVIMetric,
}

#: Temporal step identifier published on every profile.
STEP_CALENDAR_MONTH = "calendar_month"


@dataclass(frozen=True)
class RadarProfilePoint:
    """One monthly observation of a radar metric.

    A missing observation is ``value=None`` with whatever quality
    the failed window reported (``"unavailable"`` when nothing ran
    at all).  Missing is structural: consumers must render gaps,
    never interpolate.  The full metric provenance for the month is
    preserved alongside the value so no derivation detail is lost.
    """

    window_start: str
    window_end: str
    value: Optional[float]
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.3 API contract models."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "value": self.value,
            "unit": self.unit,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
            "image_count": self.image_count,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class RadarProfile:
    """A chronological sequence of monthly radar observations."""

    metric_key: str
    dataset_id: Optional[str]
    unit: str
    polarizations: Tuple[str, ...]
    mode: str
    orbit_pass: str
    scale_m: int
    window_start: str
    window_end: str
    step: str = STEP_CALENDAR_MONTH
    points: Tuple[RadarProfilePoint, ...] = field(default_factory=tuple)

    @property
    def n_points(self) -> int:
        """Total months emitted, including missing ones."""
        return len(self.points)

    @property
    def n_usable(self) -> int:
        """Months carrying a finite value."""
        return sum(1 for point in self.points if _is_usable_value(point.value))

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.3 API contract models."""
        return {
            "metric_key": self.metric_key,
            "dataset_id": self.dataset_id,
            "unit": self.unit,
            "polarizations": list(self.polarizations),
            "mode": self.mode,
            "orbit_pass": self.orbit_pass,
            "scale_m": self.scale_m,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "points": [point.to_dict() for point in self.points],
        }


def _is_usable_value(value: Any) -> bool:
    """Finite numbers only: None, NaN, infinities, and bools are gaps."""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def radar_metadata(metric_key: str) -> Dict[str, Any]:
    """Radar acquisition contract for a supported metric.

    Polarizations come from the metric's own declaration; mode,
    pass, scale, and dataset come from the production Sentinel-1
    constants.  Nothing here is inferred: it restates what the
    composite filter enforces server-side on every window.
    """
    if metric_key not in SUPPORTED_RADAR_PROFILE_METRICS:
        supported = ", ".join(sorted(SUPPORTED_RADAR_PROFILE_METRICS))
        raise ValueError(
            f"Radar profiles are not supported for {metric_key!r}. "
            f"Supported radar metrics: {supported}."
        )
    probe = SUPPORTED_RADAR_PROFILE_METRICS[metric_key]()
    return {
        "metric_key": metric_key,
        "dataset_id": probe.primary_dataset_id,
        "unit": probe.unit,
        "polarizations": tuple(probe.required_polarizations),
        "mode": S1_MODE,
        "orbit_pass": S1_PASS,
        "scale_m": S1_SCALE,
    }


def usable_values(profile: RadarProfile) -> List[float]:
    """Finite observation values in chronological order, gaps dropped.

    Structural input for a later baseline layer.  This helper
    selects; it never fills, smooths, or otherwise transforms.
    """
    return [
        float(point.value)
        for point in profile.points
        if _is_usable_value(point.value)
    ]


def _missing_point(
    window_start: str, window_end: str, unit: str, quality: str = "unavailable"
) -> RadarProfilePoint:
    return RadarProfilePoint(
        window_start=window_start,
        window_end=window_end,
        value=None,
        unit=unit,
        quality=quality,
        coverage_percent=None,
        image_count=None,
        provenance={},
    )


def _point_from_result(
    window_start: str,
    window_end: str,
    unit: str,
    result: Any,
) -> RadarProfilePoint:
    """Translate one sub-window metric result into a profile point."""
    value = result.value if _is_usable_value(result.value) else None
    provenance = result.provenance
    quality = "unavailable"
    image_count: Optional[int] = None
    provenance_dict: Dict[str, Any] = {}
    if provenance is not None:
        quality_level = provenance.quality_level
        quality = (
            quality_level.value
            if hasattr(quality_level, "value")
            else str(quality_level)
        )
        image_count = provenance.image_count
        provenance_dict = provenance.to_dict()
    coverage: Optional[float] = None
    stats = result.stats
    if stats is not None:
        raw_coverage = getattr(stats, "coverage_percent", None)
        if isinstance(raw_coverage, (int, float)) and math.isfinite(raw_coverage):
            coverage = float(raw_coverage)
    return RadarProfilePoint(
        window_start=window_start,
        window_end=window_end,
        value=float(value) if value is not None else None,
        unit=unit,
        quality=quality,
        coverage_percent=coverage,
        image_count=image_count,
        provenance=provenance_dict,
    )


def build_radar_profile(
    metric_key: str, context: MetricContext
) -> RadarProfile:
    """Build the monthly observation profile for one radar metric.

    Every intersecting calendar month is emitted exactly once, in
    chronological order, by running the metric's own ``compute`` on
    that month's sub-context (geometry, scale, and options carried
    over unchanged).  A month that cannot be computed — no
    acquisitions, full invalidity, non-finite reduction, or a
    raised exception — becomes a missing point, never a zero and
    never an interpolation of its neighbours.

    Raises:
        ValueError: when ``metric_key`` is not a supported radar
            profile metric (unknown keys and incompatible
            registered kinds alike; the message lists what is
            supported).  No silent substitution is ever performed.
        DateRangeError: when the requested window is malformed or
            empty, via the repository's own window validation.
    """
    if metric_key not in SUPPORTED_RADAR_PROFILE_METRICS:
        supported = ", ".join(sorted(SUPPORTED_RADAR_PROFILE_METRICS))
        raise ValueError(
            f"Radar profiles are not supported for {metric_key!r}. "
            f"Supported radar metrics: {supported}."
        )
    validate_date_range(context.start_date, context.end_date)

    metric_cls = SUPPORTED_RADAR_PROFILE_METRICS[metric_key]
    probe = metric_cls()
    meta = radar_metadata(metric_key)

    windows = month_windows(context.start_date, context.end_date)

    can_attempt, _reason = probe.can_attempt(context)
    if not can_attempt:
        logger.warning(
            "Radar profile for %s: requested window %s to %s is "
            "outside the source coverage, emitting %d missing month(s) "
            "without running observations.",
            metric_key,
            context.start_date,
            context.end_date,
            len(windows),
        )
        return RadarProfile(
            metric_key=metric_key,
            dataset_id=meta["dataset_id"],
            unit=probe.unit,
            polarizations=meta["polarizations"],
            mode=meta["mode"],
            orbit_pass=meta["orbit_pass"],
            scale_m=meta["scale_m"],
            window_start=context.start_date,
            window_end=context.end_date,
            points=tuple(
                _missing_point(window_start, window_end, probe.unit)
                for window_start, window_end in windows
            ),
        )

    points: List[RadarProfilePoint] = []
    for window_start, window_end in windows:
        sub_context = replace(
            context, start_date=window_start, end_date=window_end
        )
        try:
            result = metric_cls().compute(sub_context)
        except Exception as exc:  # noqa: BLE001 - one month cannot sink the profile
            logger.warning(
                "Radar profile for %s: month %s to %s failed (%s); "
                "recording a missing observation.",
                metric_key,
                window_start,
                window_end,
                type(exc).__name__,
            )
            points.append(_missing_point(window_start, window_end, probe.unit))
            continue
        if result is None:
            points.append(_missing_point(window_start, window_end, probe.unit))
            continue
        points.append(_point_from_result(window_start, window_end, probe.unit, result))

    return RadarProfile(
        metric_key=metric_key,
        dataset_id=meta["dataset_id"],
        unit=probe.unit,
        polarizations=meta["polarizations"],
        mode=meta["mode"],
        orbit_pass=meta["orbit_pass"],
        scale_m=meta["scale_m"],
        window_start=context.start_date,
        window_end=context.end_date,
        points=tuple(points),
    )


def to_temporal_profile(profile: RadarProfile) -> TemporalProfile:
    """Adapt a radar profile to the generic P1.2 profile shape.

    Carries each month's value with its unit, quality, coverage,
    and image count, so the generic P1.2 baseline machinery can
    consume the series in a later phase without any new anomaly
    engine.  Nothing is scored here; adaptation is not analysis.
    """
    from app.services.agriculture.temporal_profile import (
        TemporalProfile,
        TemporalProfilePoint,
    )

    return TemporalProfile(
        metric_key=profile.metric_key,
        dataset_id=profile.dataset_id,
        unit=profile.unit,
        window_start=profile.window_start,
        window_end=profile.window_end,
        step=profile.step,
        points=tuple(
            TemporalProfilePoint(
                window_start=point.window_start,
                window_end=point.window_end,
                value=point.value,
                unit=point.unit,
                quality=point.quality,
                coverage_percent=point.coverage_percent,
                image_count=point.image_count,
            )
            for point in profile.points
        ),
    )
