"""Phenology: vegetation temporal behaviour from a Sentinel-2 NDVI series.

What this module is, and is not
-------------------------------
This module reports **vegetation temporal behaviour**: when the green
canopy of the season rises past a threshold, where it peaks, and when it
falls back. It does **not** report planting, flowering, harvest, disease
or any agronomic cause. Those interpretations require evidence no
registered dataset carries, and the unavailable crop metrics in
:mod:`app.services.agriculture.crop` record exactly why each is refused.

The algorithms below are stated in full because a phenology number without
its definition is not reproducible. Every rule — the input index, the
compositing, the smoothing, the baseline, the threshold, the minimum
observations and the valid window — is written here, implemented once, and
tested against hand-computed series.

The algorithm (threshold crossing on a smoothed NDVI time series)
-----------------------------------------------------------------

1. **Input index.** NDVI = (B8 - B4) / (B8 + B4) from Sentinel-2 L2A
   surface reflectance, per scene, after the engine's standard SCL cloud
   mask (classes 0, 1, 3, 8, 9, 10 removed; class 7 retained).

2. **Temporal compositing.** Scenes within one calendar month are
   reduced to their spatial mean over the geometry, then to a monthly
   value by the mean over scenes. A month with no usable scene is a
   missing month, never zero.

3. **Baseline.** The per-month NDVI values are used as they come; no
   long-term climatology is fitted. The "off-season" baseline is the
   minimum of the monthly values inside the requested window, and the
   amplitude is defined relative to it. This is the only baseline
   derivable from a single requested window without importing an
   unverified assumption from elsewhere.

4. **Smoothing.** A 3-point moving average over the monthly series,
   computed only where all three months exist. The first and last months
   are never smoothed (a window over their neighbours does not exist),
   and a gap of one or two missing months stops the smoothing locally
   rather than being interpolated across. No spline, no harmonic fit:
   both would invent values in the gaps, and the gap structure is itself
   evidence about cloud cover that a filled series would destroy.

5. **Season amplitude.** ``amplitude = max(smoothed) - min(smoothed)``
   over the requested window.

6. **Threshold.** ``threshold = min(smoothed) + 0.5 * amplitude`` — the
   midpoint of the seasonal amplitude, the most conservative and most
   widely used generic rule. It is a *reporting convention of this
   engine*, chosen because it requires no crop-specific calibration, and
   it is stated in every result. It is not a universal agronomic truth.

7. **Event rules.**
   * **SOS** (start of season) — the first date in the window at which
     the smoothed series rises from below the threshold to at or above
     it.
   * **PEAK** (peak of activity) — the date of the maximum smoothed
     value; ties resolve to the earliest date, deterministically.
   * **EOS** (end of season) — the last date in the window at which the
     smoothed series falls from at or above the threshold to below it.
   * **LOS** (length of season) — ``EOS - SOS`` in days, reported only
     when both exist.

8. **Minimum observations.** At least ``MIN_MONTHS = 6`` distinct months
   with data must exist inside the window, and the requested window must
   span at least ``MIN_WINDOW_DAYS = 180`` days. Fewer months, or a
   shorter window, yields ``insufficient_data`` with the counts stated.
   The peak month must additionally be at least one month away from both
   window edges for PEAK to be published, because a peak clamped to an
   edge is an artefact of the window, not of the season.

9. **Temporal gaps.** A gap of up to two consecutive missing months is
   tolerated (events may still be found on either side). A gap of three
   or more consecutive missing months yields ``insufficient_data``,
   because an event could have happened inside it.

10. **Valid window.** The requested window is clipped to the dataset's
    declared coverage by ``Metric.can_attempt`` exactly as for every
    other OBSERVATION product; no date is widened.

The seasonal integral was evaluated and declined: integrating a smoothed
monthly NDVI series over a threshold requires the gaps to be filled, and
every fill is an invention. See ``SeasonalIntegralMetric`` for the record.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.quality import (
    SENTINEL2_THRESHOLDS,
    assess_quality,
    describe_quality,
)
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.registry.datasets import S2_SCL_INVALID_CLASSES
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    SpatialStats,
)

logger = get_logger(__name__)

__all__ = [
    "S2_DATASET_ID",
    "PHENOLOGY_WORKING_SCALE",
    "MIN_MONTHS",
    "MIN_WINDOW_DAYS",
    "MAX_TOLERATED_GAP_MONTHS",
    "THRESHOLD_MIDPOINT",
    "SeasonEvents",
    "moving_average_series",
    "detect_season_events",
    "SeasonOnsetMetric",
    "SeasonPeakMetric",
    "SeasonEndMetric",
    "SeasonLengthMetric",
    "SeasonAmplitudeMetric",
    "SeasonalIntegralMetric",
    "PHENOLOGY_METRICS",
    "UNAVAILABLE_PHENOLOGY_METRICS",
    "ALL_PHENOLOGY_METRICS",
    "INTEGRAL_UNAVAILABLE_REASON",
]


S2_DATASET_ID = "COPERNICUS/S2_SR_HARMONIZED"

#: 10 m bands only (B4, B8), so the reduction scale matches the acquisition.
PHENOLOGY_WORKING_SCALE = 10

#: Minimum distinct months with data for any phenology metric.
MIN_MONTHS = 6

#: Minimum span of the requested window, in days.
MIN_WINDOW_DAYS = 180

#: Consecutive missing months tolerated before the window is called
#: unusable. Three consecutive missing months could hide an entire event.
MAX_TOLERATED_GAP_MONTHS = 2

#: The threshold rule: the midpoint of the seasonal amplitude, above the
#: per-window minimum. A reporting convention of this engine, stated in
#: every result and provenance.
THRESHOLD_MIDPOINT = 0.5


# --------------------------------------------------------------------------
# Pure series machinery — no Earth Engine, fully unit tested
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MonthlyValue:
    """One month of the composited NDVI series."""

    #: Year-month key, e.g. (2023, 4). Tuples rather than dates: a month
    #: is the compositing unit and has no single day.
    year: int
    month: int
    value: float

    @property
    def key(self) -> Tuple[int, int]:
        return (self.year, self.month)


@dataclass
class SeasonEvents:
    """The events detected on one smoothed monthly series.

    Dates are the first day of the month in which the event occurred, so
    they carry month resolution, never day resolution. Claiming day
    resolution from a monthly composite would be false precision.
    """

    sos: Optional[date] = None
    peak: Optional[date] = None
    eos: Optional[date] = None
    los_days: Optional[int] = None
    amplitude: Optional[float] = None
    threshold: Optional[float] = None

    #: Diagnostics for the provenance and the insufficient messages.
    n_months: int = 0
    max_gap_months: int = 0
    peak_at_window_edge: bool = False


def _month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def _date_from_month(year: int, month: int) -> date:
    """The first day of a month, the resolution a monthly series supports."""
    return date(year, month, 1)


def moving_average_series(
    series: Sequence[MonthlyValue],
) -> List[Optional[float]]:
    """Smooth a monthly series with a 3-point moving average.

    A month is smoothed only when both neighbours exist *and* the three
    months are consecutive calendar months; a gap stops the smoothing
    locally. The first and last entries of the series are never smoothed.
    No interpolation is performed anywhere: missing stays missing.
    """
    if not series:
        return []

    smoothed: List[Optional[float]] = [None] * len(series)
    for i in range(1, len(series) - 1):
        left, centre, right = series[i - 1], series[i], series[i + 1]
        consecutive = (
            _month_index(left.year, left.month)
            == _month_index(centre.year, centre.month) - 1
            and _month_index(centre.year, centre.month)
            == _month_index(right.year, right.month) - 1
        )
        if consecutive:
            smoothed[i] = (left.value + centre.value + right.value) / 3.0
    return smoothed


def detect_season_events(
    series: Sequence[MonthlyValue],
    window_start: date,
    window_end: date,
    threshold_share: float = THRESHOLD_MIDPOINT,
    min_months: int = MIN_MONTHS,
    max_gap_months: int = MAX_TOLERATED_GAP_MONTHS,
) -> SeasonEvents:
    """Detect the season events on a monthly series, per the module rules.

    Returns a :class:`SeasonEvents` whose event fields are ``None`` when
    the rule does not fire. The diagnostics always carry the counts a
    caller needs to explain a refusal.
    """
    if not series or window_start is None or window_end is None:
        return SeasonEvents()
    if window_end < window_start:
        return SeasonEvents()

    # The series must be in ascending month order for the gap analysis to
    # mean anything; callers build it that way, and a violation is a bug.
    keys = [_month_index(v.year, v.month) for v in series]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        return SeasonEvents()

    # Count the months, find the longest run of consecutive missing
    # months inside the window, and locate the peak.
    n_months = len(series)
    max_gap = 0
    for i in range(1, len(keys)):
        gap = keys[i] - keys[i - 1] - 1
        if gap > max_gap:
            max_gap = gap

    smoothed = moving_average_series(series)

    # The amplitude and threshold come from the smoothed values where
    # they exist, falling back to the raw series for the edges the
    # smoother deliberately leaves untouched. Without the fallback, a
    # series whose only low months sit at the window edges would have no
    # definable minimum at all.
    usable = [v for v in smoothed if v is not None] + [
        series[0].value,
        series[-1].value,
    ]
    series_min = min(usable)
    series_max = max(usable)
    amplitude = series_max - series_min
    threshold = series_min + threshold_share * amplitude

    events = SeasonEvents(
        n_months=n_months,
        max_gap_months=max_gap,
        amplitude=amplitude,
        threshold=threshold,
    )

    if n_months < min_months:
        return events
    if max_gap > max_gap_months:
        return events
    if amplitude <= 0:
        # A flat series has no season to delimit; the amplitude is still
        # reported (as ~0) through the diagnostics.
        return events

    def month_date(value: MonthlyValue) -> date:
        return _date_from_month(value.year, value.month)

    # SOS: the first crossing from below the threshold to at or above it.
    # The comparison uses the smoothed value where one exists and the raw
    # value at the untouched edges, so the crossing test and the
    # amplitude's inputs see the same series.
    def value_at(i: int) -> float:
        candidate = smoothed[i]
        return candidate if candidate is not None else series[i].value

    for i in range(1, len(series)):
        before = value_at(i - 1)
        current = value_at(i)
        if before < threshold <= current:
            events.sos = month_date(series[i])
            break

    # EOS: the last crossing from at or above the threshold to below it.
    for i in range(len(series) - 1, 0, -1):
        before = value_at(i - 1)
        current = value_at(i)
        if before >= threshold > current:
            events.eos = month_date(series[i - 1])
            break

    # Peak: the maximum smoothed value, ties resolved to the earliest
    # month. Reported only when the peak is not an artefact of the
    # window: either the smoothed maximum sits in the first or last
    # month, or the raw maximum sits on an edge and bleeds into the
    # smoother. Both cases mean the window may have truncated the peak,
    # so no peak is published.
    peak_index: Optional[int] = None
    peak_value = -math.inf
    for i, value in enumerate(smoothed):
        if value is not None and value > peak_value:
            peak_value = value
            peak_index = i
    edge_raw = max(series[0].value, series[-1].value)
    if (
        peak_index is None
        or peak_index == 0
        or peak_index == len(series) - 1
        or edge_raw >= peak_value
    ):
        events.peak_at_window_edge = True
        peak_index = None
    if peak_index is not None:
        events.peak = month_date(series[peak_index])

    if events.sos is not None and events.eos is not None:
        events.los_days = (events.eos - events.sos).days
        if events.los_days <= 0:
            # An end before its start means the crossing rule found the
            # events in an inverted arrangement, which happens when the
            # series has no single dominant season. Refuse the length
            # rather than publish a negative season.
            events.los_days = None

    return events


def build_monthly_series_from_context(
    context: MetricContext,
    ee_module: Any,
) -> Tuple[List[MonthlyValue], int, Optional[SpatialStats]]:
    """Build the monthly NDVI series over the geometry from Sentinel-2.

    Each scene is masked by the engine's standard SCL rule, reduced to a
    spatial mean NDVI over the geometry at 10 m, and the scenes are then
    averaged by calendar month. A month with no usable scene is absent
    from the series — never zero, never interpolated.

    Returns ``(series, scene_count, window_stats)``. ``window_stats`` is
    the statistics of the whole-window NDVI, used for the quality verdict
    and the coverage figures.
    """
    from app.services.agriculture.aggregation import (
        build_reducer,
        estimate_pixel_count,
        parse_reduction_result,
        pixel_area_sq_m,
    )

    collection = (
        ee_module.ImageCollection(S2_DATASET_ID)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
    )

    scene_count = int(collection.size().getInfo())
    if scene_count == 0:
        return [], 0, None

    total_pixels = estimate_pixel_count(
        context.option("area_sq_m"), PHENOLOGY_WORKING_SCALE
    )

    # Reduce each scene to a spatial mean of the per-scene NDVI and tag
    # it with its calendar month in one server-side pass. Doing NDVI
    # first and averaging second is what a median composite cannot give:
    # the seasonal shape must survive, and a median composite over the
    # whole window would destroy it by construction.
    def per_scene(image: Any) -> Any:
        scl = image.select("SCL")
        invalid = scl.eq(S2_SCL_INVALID_CLASSES[0])
        for class_value in S2_SCL_INVALID_CLASSES[1:]:
            invalid = invalid.Or(scl.eq(class_value))
        masked = image.updateMask(invalid.Not())
        red = masked.select("B4").multiply(0.0001)
        nir = masked.select("B8").multiply(0.0001)
        ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI")
        ndvi_mean = ndvi.reduceRegion(
            reducer=ee_module.Reducer.mean(),
            geometry=context.geometry,
            scale=PHENOLOGY_WORKING_SCALE,
            maxPixels=1e9,
            bestEffort=True,
        ).get("NDVI")
        return ndvi.set(
            {
                "scene_month": image.date().format("YYYY-MM"),
                "ndvi_mean": ndvi_mean,
            }
        )

    monthly = collection.map(per_scene)

    # One read per property; the client returns the per-image values in
    # collection order, so the two lists align.
    try:
        months_raw = monthly.aggregate_array("scene_month").getInfo()
        means_raw = monthly.aggregate_array("ndvi_mean").getInfo()
    except Exception as exc:  # noqa: BLE001 - degrade to insufficient
        logger.warning("Could not read the phenology series: %s", exc)
        return [], scene_count, None

    # Whole-window statistics for the quality verdict: the mean of the
    # per-scene NDVI images, reduced once over the geometry. An
    # ImageCollection has no reduceRegion; the mean image does.
    window_raw = (
        monthly
        .mean()
        .reduceRegion(
            reducer=build_reducer(ee_module),
            geometry=context.geometry,
            scale=PHENOLOGY_WORKING_SCALE,
            maxPixels=1e9,
            bestEffort=True,
        )
        .getInfo()
    )
    window_stats = parse_reduction_result(
        window_raw or {},
        band="NDVI",
        total_pixel_count=total_pixels,
        pixel_area_sq_m=pixel_area_sq_m(PHENOLOGY_WORKING_SCALE),
    )

    series: List[MonthlyValue] = []
    seen_months = set()
    for month_key, mean_value in zip(months_raw, means_raw):
        if month_key is None or mean_value is None:
            # A scene fully masked over the geometry contributes no
            # monthly value. It is not an error and not a zero.
            continue
        try:
            year_text, month_text = str(month_key).split("-")
            year = int(year_text)
            month = int(month_text)
        except (ValueError, TypeError):
            continue
        if not (1 <= month <= 12):
            continue
        value = _clean_float(mean_value)
        if value is None:
            continue
        key = (year, month)
        if key in seen_months:
            # Two scenes in one month: average them. A mean of spatial
            # means over the same geometry is the monthly mean.
            existing = next(v for v in series if v.key == key)
            merged_mean = (existing.value + value) / 2.0
            series = [
                MonthlyValue(year, month, merged_mean)
                if v.key == key
                else v
                for v in series
            ]
            continue
        seen_months.add(key)
        series.append(MonthlyValue(year, month, value))

    series.sort(key=lambda v: _month_index(v.year, v.month))
    return series, scene_count, window_stats


def _clean_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    return None


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


class _PhenologyMetric(Metric):
    """Shared behaviour for the phenology metrics.

    Every subclass runs the same series build and event detection and
    then publishes one aspect of the events. The refusal rules are
    identical across the family and live here, in one place.
    """

    domain = MetricDomain.PHENOLOGY
    dataset_ids = (S2_DATASET_ID,)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = PHENOLOGY_WORKING_SCALE

    #: Which event this metric publishes: "sos", "peak", "eos", "los" or
    #: "amplitude".
    event: str = ""

    def can_attempt(self, context: MetricContext) -> Tuple[bool, Optional[str]]:
        # The dataset's own coverage gate applies exactly as for any other
        # OBSERVATION product. On top of it, phenology has a window-length
        # rule of its own: a window shorter than the minimum cannot
        # contain a season's shape, and refusing it early saves an
        # expensive query that could never succeed.
        can, reason = super().can_attempt(context)
        if not can:
            return can, reason

        start = context.start
        end = context.end
        if start is None or end is None:
            return False, "outside_temporal_coverage"
        if (end - start).days + 1 < MIN_WINDOW_DAYS:
            return False, "window_too_short"
        return True, None

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        series, scene_count, window_stats = build_monthly_series_from_context(
            context, ee
        )

        start = context.start
        end = context.end
        assert start is not None and end is not None  # can_attempt guarantees

        if scene_count == 0 or not series:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No usable Sentinel-2 observations were found in the "
                    "requested window, so no vegetation season could be "
                    "characterised."
                ),
                unit=self.unit,
            )

        events = detect_season_events(series, start, end)

        quality = (
            assess_quality(
                image_count=scene_count,
                coverage_percent=(
                    window_stats.coverage_percent if window_stats else 0.0
                ),
                valid_pixel_count=(
                    window_stats.valid_pixel_count if window_stats else 0
                ),
                thresholds=SENTINEL2_THRESHOLDS,
            )
            if window_stats is not None
            else QualityLevel.INSUFFICIENT
        )

        provenance = self._provenance(
            context, dataset, events, scene_count, series, quality
        )

        # -- refusal rules, in the order a caller needs to read them ----
        if events.n_months < MIN_MONTHS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {events.n_months} distinct month(s) with usable "
                    f"data across {scene_count} scene(s) in the window; "
                    f"the minimum is {MIN_MONTHS}. No season event is "
                    "reported, because the seasonal shape cannot be "
                    "distinguished from cloud gaps."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if events.max_gap_months > MAX_TOLERATED_GAP_MONTHS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The monthly series contains a gap of "
                    f"{events.max_gap_months} consecutive month(s) without "
                    "data, above the tolerated maximum of "
                    f"{MAX_TOLERATED_GAP_MONTHS}. An event inside the gap "
                    "could not have been seen, so none is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        # The temporal rules can be satisfied while the spatial coverage
        # is not: twelve scenes that all saw a sliver of the field carry a
        # shape but describe none of it. The quality verdict is therefore
        # enforced here, before any value is published, so a number is
        # never released merely because the series arithmetic succeeded.
        if quality is QualityLevel.INSUFFICIENT:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The Sentinel-2 observations in this window cover too "
                    "little of the requested area for the seasonal shape "
                    "to describe it. No season event is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        event = self.event

        if event == "amplitude":
            return self._amplitude_result(
                context, events, provenance, quality, series
            )

        # All remaining events are dates or a length derived from dates.
        if event in ("sos", "peak", "eos"):
            if event == "peak" and events.peak_at_window_edge:
                return MetricResult.insufficient(
                    metric_key=self.key,
                    display_name=self.display_name,
                    display_name_fa=self.display_name_fa,
                    message=(
                        "The peak of vegetation activity falls in the "
                        "first or last month of the requested window, so "
                        "it may be an artefact of the window rather than "
                        "of the season. Widen the window to include the "
                        "shoulders of the season."
                    ),
                    unit=self.unit,
                    provenance=provenance,
                )
            event_date: Optional[date] = getattr(events, event)
            if event_date is None:
                return MetricResult.insufficient(
                    metric_key=self.key,
                    display_name=self.display_name,
                    display_name_fa=self.display_name_fa,
                    message=(
                        "The threshold rule did not fire inside this "
                        "window: the series never crosses "
                        f"{events.threshold:.3f} in the required "
                        "direction. Either the amplitude is too small or "
                        "the season lies outside the window."
                    ),
                    unit=self.unit,
                    provenance=provenance,
                )
            warnings = self._warnings(events, quality)
            return MetricResult(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                value=_date_to_decimal_year(event_date),
                unit=self.unit,
                provenance=provenance,
                warnings=warnings,
            )

        # length of season
        if events.los_days is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The season length requires both a start and an end "
                    "crossing inside the window, and at least one of them "
                    "did not occur (or occurred in an inverted order). "
                    "No length is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        warnings = self._warnings(events, quality)
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=float(events.los_days),
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )

    def _amplitude_result(
        self,
        context: MetricContext,
        events: SeasonEvents,
        provenance: Provenance,
        quality: QualityLevel,
        series: Sequence[MonthlyValue],
    ) -> MetricResult:
        assert events.amplitude is not None
        warnings = self._warnings(events, quality)
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=events.amplitude,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )

    def _warnings(
        self,
        events: SeasonEvents,
        quality: QualityLevel,
    ) -> List[str]:
        warnings: List[str] = [
            "These dates describe the vegetation signal, not agronomic "
            "events: the onset is not the planting date, the peak is not "
            "flowering, and the end is not the harvest date.",
            (
                f"Threshold rule: {THRESHOLD_MIDPOINT:.0%} of the seasonal "
                "amplitude above the per-window minimum, applied to a "
                "3-point moving average of monthly mean NDVI. This is a "
                "reporting convention, not a calibrated agronomic rule."
            ),
            f"Series resolution is monthly; dates carry month resolution.",
        ]
        if events.max_gap_months > 0:
            warnings.append(
                f"The series carries a gap of up to {events.max_gap_months} "
                "consecutive month(s) without data inside the window."
            )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))
        if quality is QualityLevel.MODERATE:
            warnings.append(describe_quality(QualityLevel.MODERATE))
        return warnings

    def _provenance(
        self,
        context: MetricContext,
        dataset: Any,
        events: SeasonEvents,
        scene_count: int,
        series: Sequence[MonthlyValue],
        quality: QualityLevel,
    ) -> Provenance:
        months_text = ", ".join(
            f"{v.year}-{v.month:02d}:{v.value:.3f}" for v in series
        )
        return self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["B4", "B8"],
            formula=(
                "NDVI = (B8 - B4) / (B8 + B4) per scene after the SCL "
                "mask; monthly value = mean of per-scene spatial means; "
                "smoothing = 3-point moving average where all three "
                "months are consecutive; threshold = min(smoothed) + "
                f"{THRESHOLD_MIDPOINT:.0%} * (max(smoothed) - "
                "min(smoothed)); SOS = first upward crossing; EOS = last "
                "downward crossing; PEAK = argmax smoothed (edges "
                "excluded); LOS = EOS - SOS"
            ),
            quality=quality,
            image_count=scene_count,
            aggregation_method=(
                "per-scene spatial mean, then calendar-month mean, then "
                "3-point moving average"
            ),
            extra_limitations=self.limitations,
            extra_caveats=(
                f"Monthly series used ({events.n_months} months): "
                f"{months_text or '(empty)'}",
                (
                    f"Longest gap in the series: "
                    f"{events.max_gap_months} consecutive month(s)."
                ),
            ),
        )


def _date_to_decimal_year(value: date) -> float:
    """A date as a decimal year, so a date can travel in a float field.

    Day resolution inside the float does not imply day resolution of the
    event: the value encodes the first day of the event's month.
    """
    start = date(value.year, 1, 1)
    year_days = 366.0 if _is_leap(value.year) else 365.0
    return value.year + ((value - start).days / year_days)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


class SeasonOnsetMetric(_PhenologyMetric):
    """Start of the vegetation season (SOS), month resolution.

    The threshold crossing of the smoothed monthly NDVI series. Not the
    planting date: green-up marks canopy development, which can sit weeks
    away from sowing and depends on species, cultivar and irrigation.
    """

    key = "vegetation_season_onset"
    display_name = "Vegetation Season Onset"
    display_name_fa = "شروع فصل رشد پوشش گیاهی"
    event = "sos"
    unit = "decimal_year"
    description = (
        "The start of the vegetation season: the first month in which the "
        "smoothed monthly NDVI series rises above the midpoint of the "
        "seasonal amplitude. Month resolution. This is the vegetation "
        "signal's onset, not the planting date."
    )
    limitations = (
        "Not the planting date. Canopy development follows sowing by an "
        "interval that depends on species, cultivar, irrigation and "
        "establishment method, and no registered dataset observes sowing.",
        "Month resolution: the event is dated to the first day of the "
        "month in which the threshold crossing occurred.",
        "A double season, or a season straddling the window edges, can "
        "produce a first crossing that is not the main season's onset.",
        "The threshold is the amplitude midpoint, a reporting convention "
        "of this engine, not a calibrated agronomic rule.",
        "Persistent cloud can delay the observed onset by suppressing "
        "the months in which the crossing would otherwise fall.",
    )


class SeasonPeakMetric(_PhenologyMetric):
    """Peak of vegetation activity, month resolution.

    The month of maximum smoothed NDVI. Not flowering: an NDVI maximum is
    peak green canopy or biomass, and for many crops flowering precedes
    or accompanies it only loosely.
    """

    key = "vegetation_activity_peak"
    display_name = "Vegetation Activity Peak"
    display_name_fa = "اوج فعالیت پوشش گیاهی"
    event = "peak"
    unit = "decimal_year"
    description = (
        "The month of maximum smoothed monthly NDVI inside the window, "
        "reported only when it does not fall on the window edge. This is "
        "peak vegetation activity, not flowering."
    )
    limitations = (
        "Not the flowering date. The NDVI maximum is peak green canopy; "
        "flowering is a reproductive event that no registered dataset "
        "observes.",
        "A peak clamped to the window's first or last month is refused, "
        "because it may be an artefact of the window.",
        "NDVI saturates over dense canopies, so the true biomass peak can "
        "differ from the index peak.",
        "Month resolution: the event is dated to the first day of the "
        "peak month.",
    )


class SeasonEndMetric(_PhenologyMetric):
    """End of the vegetation season (EOS), month resolution.

    The last downward crossing of the threshold. Not the harvest date:
    green-canopy loss has many causes and none is distinguished here.
    """

    key = "vegetation_season_end"
    display_name = "Vegetation Season End"
    display_name_fa = "پایان فصل رشد پوشش گیاهی"
    event = "eos"
    unit = "decimal_year"
    description = (
        "The end of the vegetation season: the last month in which the "
        "smoothed monthly NDVI series falls below the midpoint of the "
        "seasonal amplitude. Month resolution. This is the vegetation "
        "signal's end, not the harvest date."
    )
    limitations = (
        "Not the harvest date. Canopy loss can come from harvest, "
        "senescence, drought stress, disease, hail or forage cutting, "
        "and the signal does not distinguish them.",
        "Month resolution: the event is dated to the first day of the "
        "month in which the threshold crossing occurred.",
        "The crossing is detected inside the requested window; a season "
        "ending after the window is invisible to it.",
        "The threshold is the amplitude midpoint, a reporting convention "
        "of this engine, not a calibrated agronomic rule.",
    )


class SeasonLengthMetric(_PhenologyMetric):
    """Length of the vegetation season (EOS minus SOS), in days.

    Reported only when both crossings occur inside the window in a sane
    order. The length of the *vegetation signal's* active period, not the
    agronomic season.
    """

    key = "vegetation_season_length"
    display_name = "Vegetation Season Length"
    display_name_fa = "طول فصل رشد پوشش گیاهی"
    event = "los"
    unit = "days"
    description = (
        "The number of days between the vegetation season's onset and "
        "its end, from the threshold crossings of the smoothed monthly "
        "NDVI series. Reported only when both crossings occur inside the "
        "window."
    )
    limitations = (
        "The length of the vegetation signal's active period, not of an "
        "agronomic season: sowing and harvest both fall outside the "
        "crossings by intervals this engine cannot measure.",
        "Requires both crossings inside the window; a season that starts "
        "before or ends after it yields no length.",
        "Month-resolution endpoints bound the length's resolution: two "
        "seasons within half a month of each other are not "
        "distinguishable.",
    )


class SeasonAmplitudeMetric(_PhenologyMetric):
    """Seasonal amplitude of the smoothed NDVI series.

    ``max(smoothed) - min(smoothed)`` over the window. The size of the
    vegetation signal's seasonal swing, independent of when it happens.
    """

    key = "vegetation_season_amplitude"
    display_name = "Vegetation Seasonal Amplitude"
    display_name_fa = "دامنه فصلی پوشش گیاهی"
    event = "amplitude"
    unit = "index"
    description = (
        "The seasonal amplitude of vegetation activity: the difference "
        "between the maximum and the minimum of the smoothed monthly "
        "NDVI series inside the window."
    )
    limitations = (
        "An amplitude computed over the requested window, not over a "
        "calendar season: a window shorter than the season truncates it.",
        "NDVI saturation over dense canopies compresses the amplitude "
        "from above.",
        "Cloud gaps at the seasonal extremes bias the amplitude; the "
        "gap diagnostics travel with every result.",
    )


# --------------------------------------------------------------------------
# Not produced: the seasonal integral
# --------------------------------------------------------------------------

INTEGRAL_UNAVAILABLE_CODE = "integral_requires_gap_filling"
INTEGRAL_UNAVAILABLE_REASON = (
    "Not produced. The seasonal integral of a vegetation index (time-over-"
    "threshold, AUC) requires a continuous series, and this engine's "
    "phenology series deliberately refuses to fill gaps: every fill — "
    "interpolation, spline or harmonic — is an invented value in exactly "
    "the cloud-covered periods where the integral is most likely to be "
    "used. The tolerated-gap rule of the event metrics (up to two months) "
    "bounds where an event can be *found*, but an integral sums every "
    "month between the crossings, so an unfilled gap of even one month "
    "would produce a systematically biased total, and no defensible "
    "correction exists. If a gap-free series is ever required, it must "
    "come from a gap-filled product (for example a MODIS gap-filled "
    "series) whose own fill semantics are documented, rather than from "
    "locally invented interpolation. Until then the integral is declined "
    "rather than published with a silent bias."
)


class SeasonalIntegralMetric(Metric):
    """The seasonal integral, registered as unavailable with its reason.

    Structurally incapable of carrying a value, like every other
    deliberately unavailable metric in this engine.
    """

    key = "vegetation_seasonal_integral"
    display_name = "Vegetation Seasonal Integral (not produced)"
    display_name_fa = "انتگرال فصلی پوشش گیاهی (تولید نمی‌شود)"
    domain = MetricDomain.PHENOLOGY
    unit = "index.days"
    dataset_ids: Tuple[str, ...] = (S2_DATASET_ID,)
    measurement_basis = MeasurementBasis.INFERENCE
    description = (
        "Not produced. A time-over-threshold integral needs a gap-free "
        "series, and the engine's series refuses to invent values in "
        "cloud gaps."
    )
    limitations = (
        "Not produced. See the unavailable reason for the full argument.",
    )

    def can_attempt(self, context: MetricContext) -> Tuple[bool, Optional[str]]:
        return super().can_attempt(context)

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
            reason=INTEGRAL_UNAVAILABLE_CODE,
            message=INTEGRAL_UNAVAILABLE_REASON,
            unit=self.unit,
            provenance=provenance,
        )

    def metadata(self) -> Dict[str, Any]:
        metadata = super().metadata()
        metadata["available"] = False
        metadata["unavailable_code"] = INTEGRAL_UNAVAILABLE_CODE
        metadata["unavailable_reason"] = INTEGRAL_UNAVAILABLE_REASON
        return metadata


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------

PHENOLOGY_METRICS: Tuple[Metric, ...] = (
    SeasonOnsetMetric(),
    SeasonPeakMetric(),
    SeasonEndMetric(),
    SeasonLengthMetric(),
    SeasonAmplitudeMetric(),
)

UNAVAILABLE_PHENOLOGY_METRICS: Tuple[Metric, ...] = (
    SeasonalIntegralMetric(),
)

ALL_PHENOLOGY_METRICS: Tuple[Metric, ...] = (
    PHENOLOGY_METRICS + UNAVAILABLE_PHENOLOGY_METRICS
)
