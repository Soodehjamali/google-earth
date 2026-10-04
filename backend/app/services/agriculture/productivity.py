"""Crop productivity indicators (Phase M).

This module sits at the top of the derived layers. It consumes only
quantities other modules already publish -- the phenology engine's
season events, the vegetation module's NDVI composite, the water module's
MOD16 evapotranspiration, the crop module's WorldCereal share -- and it
introduces no new Earth Engine band of its own.

The scientific boundary that governs everything here
----------------------------------------------------
Phase M distinguishes six concepts and never collapses two of them:

A. **Vegetation condition** -- an index snapshot (NDVI today). Published
   by ``vegetation.py``.
B. **Vegetation productivity** -- how much vegetation activity a season
   carried. *Partially* observable; this module publishes only the
   explicitly-defined pieces of it below, each named an indicator or a
   proxy.
C. **Biomass** -- mass of plant material per unit area. NOT produced
   anywhere in this engine; see ``yield_model.py``.
D. **Crop productivity estimate** -- productivity of the crop, as
   distinct from whatever green vegetation happens to share the pixel.
   Only the explicitly-defined, bounded areal combination below is
   offered, and it is named for what it is.
E. **Yield** -- harvested mass per unit area. NOT produced. See
   ``yield_model.py``.
F. **Observed yield** -- a harvest record. Does not exist in this
   project and nothing fabricates one.

Consequently: NDVI is never called yield; a seasonal NDVI integral is
never expressed in tons per hectare (and remains deliberately
unavailable as a raw integral -- see ``phenology.py``); and no
LAI/FAPAR/ET quantity is converted into yield.

Temporal alignment
------------------
The seasonal indicators reuse the phenology engine's season detection
verbatim: the same monthly NDVI series, the same 3-point moving average,
the same amplitude-midpoint threshold, the same minimum-months,
minimum-window and maximum-gap rules, and the same refusal to
interpolate. A season the phenology engine will not certify is a season
these indicators will not summarise: if the events refuse, the
indicators refuse with the phenology engine's own reason. The requested
window bounds what can be summarised; the indicators never widen it.

Spatial alignment
-----------------
Every metric runs at the scale of its coarsest contributing input and
says so. The areal combination in particular is bounded by the crop
mask's validity (2021 reference year) and by the fact that the
vegetation composite is a field-scale median: it cannot resolve which
pixels within the field carry the crop, and the metric is documented as
a field-level, not crop-pixel-level, quantity.

Provenance carries the detected season boundaries and the monthly series
whenever a season is involved, so a reader can audit exactly which
months a number rests on.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.aggregation import (
    build_reducer,
    estimate_pixel_count,
    parse_reduction_result,
    pixel_area_sq_m,
)
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.crop import (
    CROP_AREA_MIN_VALID_FRACTION,
    WORLDCEREAL_ID,
    reduce_worldcereal_mask,
    _crop_share,
)
from app.services.agriculture.phenology import (
    MAX_TOLERATED_GAP_MONTHS,
    MIN_MONTHS,
    MIN_WINDOW_DAYS,
    PHENOLOGY_WORKING_SCALE,
    S2_DATASET_ID,
    SeasonEvents,
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
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    SpatialStats,
)
from app.services.agriculture.vegetation import (
    S2_DATASET_ID as VEGETATION_S2_DATASET_ID,
    _mask_sentinel2,
)
from app.services.agriculture.water import (
    MOD16_GAPFILLED,
    MOD16_NRT,
    MOD16_SCALE,
    _resolve_mod16_dataset,
)

logger = get_logger(__name__)

__all__ = [
    "PRODUCTIVITY_DISCLAIMER",
    "SeasonalVegetationProductivityIndicator",
    "SeasonalETProductivityContextMetric",
    "CropAreaNormalisedProductivityIndicator",
    "PRODUCTIVITY_METRICS",
    "ALL_PRODUCTIVITY_METRICS",
    "PRODUCTIVITY_AVAILABLE",
]


#: The boundary statement carried in the limitations of every metric in
#: this module. It is deliberately a *denial*, worded so that a reader
#: cannot mistake any number here for a yield or a biomass.
PRODUCTIVITY_DISCLAIMER = (
    "This is a vegetation-productivity indicator. It describes the "
    "strength of the vegetation signal, not the mass of any crop, and it "
    "is not a yield estimate of any kind: it carries no units of mass "
    "and cannot be converted into one without a validated model that "
    "this engine does not have."
)


# ==========================================================================
# Seasonal machinery shared by the seasonal metrics
# ==========================================================================


def summarise_season(
    series: Sequence,
    events: SeasonEvents,
) -> Dict[str, Optional[float]]:
    """Summarise the monthly NDVI series inside the detected season.

    The season is the span from the detected onset to the detected end
    (both first-of-month dates, the resolution the phenology series
    supports). Months strictly inside that span, as the series reports
    them, contribute their values; months the series does not carry
    contribute nothing -- they are never filled and never zero.

    Returns a dict with ``mean``, ``peak``, ``min``, ``count`` (months
    contributing), ``months_in_span`` (calendar months the span covers)
    and ``missing_in_span``. ``mean`` is ``None`` when no month inside
    the span carried data.
    """
    if events.sos is None or events.eos is None:
        return {
            "mean": None,
            "peak": None,
            "min": None,
            "count": 0,
            "months_in_span": 0,
            "missing_in_span": 0,
        }

    def month_index(year: int, month: int) -> int:
        return year * 12 + (month - 1)

    span_start = month_index(events.sos.year, events.sos.month)
    span_end = month_index(events.eos.year, events.eos.month)
    months_in_span = max(0, span_end - span_start + 1)

    inside: List[float] = []
    peak: Optional[float] = None
    minimum: Optional[float] = None
    for value in series:
        key = month_index(value.year, value.month)
        if span_start <= key <= span_end:
            inside.append(value.value)
            if peak is None or value.value > peak:
                peak = value.value
            if minimum is None or value.value < minimum:
                minimum = value.value

    count = len(inside)
    mean = (sum(inside) / count) if count else None
    return {
        "mean": mean,
        "peak": peak,
        "min": minimum,
        "count": count,
        "months_in_span": months_in_span,
        "missing_in_span": months_in_span - count,
    }


# ==========================================================================
# 1. Seasonal vegetation productivity indicator
# ==========================================================================


class SeasonalVegetationProductivityIndicator(Metric):
    """Mean NDVI over the detected vegetation season.

    Definition, stated in full so the number is reproducible:

    * **Input index.** NDVI = (B8 - B4) / (B8 + B4) from Sentinel-2 L2A,
      per scene, after the engine's standard SCL mask. The input index is
      fixed: the indicator does not accept EVI or any other index,
      because the season detection is itself defined on NDVI and
      summarising a different series inside NDVI's season would pair a
      shape with a boundary that was not derived from it.
    * **Temporal compositing.** Per-scene spatial means, then calendar-
      month means -- exactly the phenology engine's compositing.
    * **Season boundaries.** The SOS and EOS the phenology engine
      detects on the smoothed monthly series, at the amplitude-midpoint
      threshold. No independent boundary is derived here.
    * **Missing observations.** A month with no usable scene is missing.
      It is never filled and never zero. The gap rules of the phenology
      engine apply unchanged: a gap above ``MAX_TOLERATED_GAP_MONTHS``
      months refuses the season, and therefore the indicator.
    * **Minimum observations.** At least ``MIN_MONTHS`` distinct months
      in the window and a window of at least ``MIN_WINDOW_DAYS`` days,
      inherited from the phenology engine's gates.
    * **Minimum season coverage.** At least
      ``MIN_SEASON_MONTH_COVERAGE`` of the calendar months inside the
      detected span must carry data, or the indicator is refused: a mean
      resting on a fraction of the season is not a seasonal mean.

    The value is the arithmetic mean of the monthly NDVI values inside
    the detected span. It is dimensionless (unit ``index``). It is a
    vegetation-productivity proxy: the mean greenness the season
    carried, not the mass the season produced.
    """

    key = "seasonal_vegetation_productivity_indicator"
    display_name = "Seasonal Vegetation Productivity Indicator"
    display_name_fa = "شاخص بهره‌وری فصلی پوشش گیاهی"
    unit = "index"
    domain = MetricDomain.PRODUCTIVITY
    dataset_ids = (S2_DATASET_ID,)
    measurement_basis = MeasurementBasis.PROXY
    default_scale = PHENOLOGY_WORKING_SCALE

    #: Share of the calendar months inside the detected season span that
    #: must carry data for the seasonal mean to be published. A season
    #: with a third of its months missing is not summarised.
    MIN_SEASON_MONTH_COVERAGE = 0.75

    description = (
        "Mean NDVI across the calendar months of the vegetation season "
        "detected by the phenology engine, on the same smoothed monthly "
        "series and the same threshold rule. A vegetation-productivity "
        "proxy: dimensionless, not a mass, not a yield."
    )
    limitations = (
        PRODUCTIVITY_DISCLAIMER,
        "The season is the *vegetation signal's* season, bounded by the "
        "amplitude-midpoint threshold on a smoothed monthly NDVI series. "
        "It is not an agronomic season and the span is not sowing to "
        "harvest.",
        "The mean covers the calendar months of the detected span at "
        "month resolution; a month the satellite never saw is missing, "
        "never filled, and months below the coverage floor refuse the "
        "mean entirely.",
        "NDVI saturates over dense canopies, so the indicator "
        "understates differences between very productive seasons.",
        "Cloud gaps at the seasonal peak bias the mean downward in "
        "exactly the seasons where the question matters most; the gap "
        "diagnostics travel with every result.",
        "The indicator is comparable only with other results computed "
        "with the same window and the same threshold convention, not "
        "with published seasonal NDVI values from other engines.",
    )

    def can_attempt(self, context: MetricContext) -> Tuple[bool, Optional[str]]:
        # The phenology engine's window gate is this metric's gate too:
        # a window too short to contain a season cannot contain a
        # seasonal mean.
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
                    "detected and no seasonal productivity indicator is "
                    "reported."
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

        # -- the season gates, inherited from the phenology engine ------
        if events.n_months < MIN_MONTHS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {events.n_months} distinct month(s) with usable "
                    f"data across {scene_count} scene(s); the phenology "
                    f"engine requires {MIN_MONTHS} to certify a season, so "
                    "no seasonal productivity indicator is reported."
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
                    f"{MAX_TOLERATED_GAP_MONTHS}. The season inside the gap "
                    "cannot be certified, so no seasonal mean is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if quality is QualityLevel.INSUFFICIENT:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The Sentinel-2 observations in this window cover too "
                    "little of the requested area for the seasonal shape "
                    "to describe it. No productivity indicator is "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if events.sos is None or events.eos is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The phenology engine could not bound a season inside "
                    "this window: the smoothed series never crosses the "
                    f"amplitude midpoint ({events.threshold:.3f}) in both "
                    "directions. Without a bounded season there is no "
                    "seasonal mean to report."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        summary = summarise_season(series, events)
        mean = summary["mean"]
        if mean is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No month inside the detected season's span carried "
                    "usable data, so the seasonal mean is undefined. The "
                    "span is reported in the provenance for audit."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        coverage = (
            summary["count"] / summary["months_in_span"]
            if summary["months_in_span"]
            else 0.0
        )
        if coverage < self.MIN_SEASON_MONTH_COVERAGE:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {summary['count']} of the "
                    f"{summary['months_in_span']} calendar month(s) inside "
                    "the detected season carried data "
                    f"({coverage:.0%}); the floor is "
                    f"{self.MIN_SEASON_MONTH_COVERAGE:.0%}. A mean resting "
                    "on the remainder would not be a seasonal mean, so it "
                    "is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            (
                f"Season span (month resolution): {events.sos.isoformat()} "
                f"to {events.eos.isoformat()}; "
                f"{summary['count']} of {summary['months_in_span']} months "
                "in the span carried data."
            ),
            (
                "Threshold rule inherited from the phenology engine: "
                f"{0.5:.0%} of the seasonal amplitude above the per-window "
                "minimum, on a 3-point moving average of monthly mean NDVI."
            ),
        ]
        if summary["missing_in_span"] > 0:
            warnings.append(
                f"{summary['missing_in_span']} month(s) inside the season "
                "span carried no usable observation. They are excluded, "
                "not filled."
            )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))
        elif quality is QualityLevel.MODERATE:
            warnings.append(describe_quality(QualityLevel.MODERATE))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=mean,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )

    def _provenance(
        self,
        context: MetricContext,
        dataset: Any,
        events: SeasonEvents,
        scene_count: int,
        series: Sequence,
        quality: QualityLevel,
    ) -> Provenance:
        months_text = ", ".join(
            f"{v.year}-{v.month:02d}:{v.value:.3f}" for v in series
        )
        season_text = (
            f"{events.sos.isoformat()} to {events.eos.isoformat()}"
            if events.sos and events.eos
            else "not bounded in this window"
        )
        return self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["B4", "B8"],
            formula=(
                "mean of the monthly NDVI values (per-scene spatial means, "
                "then calendar-month means) whose months fall inside the "
                "detected season span; season from the phenology engine's "
                "amplitude-midpoint threshold crossings on the 3-point "
                "moving average"
            ),
            quality=quality,
            image_count=scene_count,
            aggregation_method=(
                "per-scene spatial mean, then calendar-month mean, then an "
                "unweighted mean over the in-span months carrying data"
            ),
            extra_limitations=self.limitations,
            extra_caveats=(
                f"Detected season span: {season_text}.",
                (
                    f"Monthly series used ({events.n_months} months): "
                    f"{months_text or '(empty)'}"
                ),
                (
                    f"Longest gap in the series: "
                    f"{events.max_gap_months} consecutive month(s)."
                ),
                (
                    "Season boundaries are month resolution (first day of "
                    "the month)."
                ),
            ),
        )


# ==========================================================================
# 2. Seasonal evapotranspiration context
# ==========================================================================


class SeasonalETProductivityContextMetric(Metric):
    """Total MOD16 actual ET over the detected vegetation season.

    The window is the detected season span, in month resolution: the
    first day of the onset month to the last day of the end month. MOD16
    composites that fall inside that window are summed, each composite's
    own stored total scaled by its declared factor exactly once.

    The value is millimetres of water over the season -- a water-use
    *context* for the season's vegetation activity, not a biomass
    conversion. No water-use-efficiency factor is applied anywhere in
    this engine, because every published factor is crop- and
    cultivar-specific and none is verified for the areas this engine
    serves.

    Temporal alignment: the ET window and the vegetation season come
    from different satellites, and the alignment is stated rather than
    implied. The season is defined by Sentinel-2 NDVI at month
    resolution; the ET window is that same calendar span widened to full
    months. The two series are never mixed at a sub-month scale, and the
    metric carries the season's own refusal behaviour: no certified
    season, no ET context.
    """

    key = "seasonal_evapotranspiration_context"
    display_name = "Seasonal Evapotranspiration Context"
    display_name_fa = "زمینه تبخیر-تعرق فصلی"
    unit = "mm"
    domain = MetricDomain.PRODUCTIVITY
    dataset_ids = (MOD16_GAPFILLED, MOD16_NRT)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = MOD16_SCALE

    description = (
        "Sum of MOD16 actual ET composite totals inside the vegetation "
        "season detected by the phenology engine. Millimetres of water "
        "over the season; a water-use context, not a biomass or yield "
        "conversion."
    )
    limitations = (
        PRODUCTIVITY_DISCLAIMER,
        "The ET window is the vegetation signal's season, not an "
        "agronomic season: it opens and closes at the phenology engine's "
        "threshold crossings, widened to full months.",
        "Sentinel-2 defines the season and MOD16 supplies the ET; the "
        "two are aligned only at calendar-month resolution, and no "
        "sub-month pairing is claimed.",
        "MOD16 is a modelled product that performs poorly over sparse "
        "vegetation and arid surfaces, and it is published at 500 m, so "
        "the total describes a district rather than a field.",
        "No water-use-efficiency factor is applied and none may be "
        "derived from this number: converting millimetres of ET into "
        "mass of biomass requires a crop-specific, verified coefficient "
        "this engine does not have.",
        "Composites overlapping the window boundary are included in "
        "full, so the total can slightly exceed the window's own ET.",
    )

    def can_attempt(self, context: MetricContext) -> Tuple[bool, Optional[str]]:
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

        dataset_id, fallback_from = _resolve_mod16_dataset(context)
        dataset = get_dataset(dataset_id)

        # -- 1. the season, from the same machinery the indicator uses --
        series, scene_count, _window_stats = build_monthly_series_from_context(
            context, ee
        )
        start = context.start
        end = context.end
        assert start is not None and end is not None

        if scene_count == 0 or not series:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No usable Sentinel-2 observations were found in the "
                    "requested window, so no vegetation season could be "
                    "detected and no seasonal ET context is reported."
                ),
                unit=self.unit,
            )

        events = detect_season_events(series, start, end)

        # -- 2. the season gates, inherited verbatim ---------------------
        if events.n_months < MIN_MONTHS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {events.n_months} distinct month(s) with usable "
                    f"data across {scene_count} scene(s); the phenology "
                    f"engine requires {MIN_MONTHS} to certify a season, so "
                    "no seasonal ET context is reported."
                ),
                unit=self.unit,
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
                    f"{MAX_TOLERATED_GAP_MONTHS}. The season inside the gap "
                    "cannot be certified, so no ET context is reported."
                ),
                unit=self.unit,
            )
        if events.sos is None or events.eos is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The phenology engine could not bound a season inside "
                    "this window, so there is no season over which to "
                    "accumulate ET. No seasonal ET context is reported."
                ),
                unit=self.unit,
            )

        # -- 3. the ET window: the season span widened to full months ----
        et_start = events.sos.isoformat()
        et_end = _last_day_of_month(events.eos).isoformat()

        try:
            collection = (
                ee.ImageCollection(dataset_id)
                .filterDate(et_start, _exclusive_end(et_end))
                .filterBounds(context.geometry)
                .select(["ET"])
            )
            image_count = int(collection.size().getInfo())
        except Exception as exc:  # noqa: BLE001 - degrade to insufficient
            logger.warning(
                "Could not read MOD16 over the detected season: %s", exc
            )
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The MOD16 product could not be read over the detected "
                    f"season ({et_start} to {et_end}), so no seasonal ET "
                    "total is reported. The season is bounded; the water "
                    "product is not available over it."
                ),
                unit=self.unit,
            )

        band_spec = dataset.band("ET")

        def to_total(image: Any) -> Any:
            total = image.select("ET").reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=context.geometry,
                scale=MOD16_SCALE,
                maxPixels=1e9,
                bestEffort=True,
            ).get("ET")
            return image.set("period_mean", total)

        annotated = collection.map(to_total)
        try:
            raw_totals = annotated.aggregate_array("period_mean").getInfo()
        except Exception as exc:  # noqa: BLE001 - degrade to insufficient
            logger.warning(
                "Could not read per-composite ET means for the seasonal "
                "window: %s",
                exc,
            )
            raw_totals = None

        composite_totals: List[float] = []
        for record in raw_totals or []:
            physical = band_spec.to_physical(record)
            if physical is not None:
                composite_totals.append(physical)

        if image_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"No {dataset.name} composites fell inside the "
                    f"detected season ({et_start} to {et_end}), so no "
                    "seasonal ET total is reported. The season is bounded; "
                    "the water product is not available over it."
                ),
                unit=self.unit,
            )

        if not composite_totals:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Every MOD16 composite inside the detected season "
                    "carried no usable pixels over this area, so no "
                    "seasonal ET total is reported."
                ),
                unit=self.unit,
            )

        total_mm = float(sum(composite_totals))
        season_day_span = (
            _last_day_of_month(events.eos) - events.sos
        ).days + 1

        quality = assess_quality(
            image_count=max(image_count, 1),
            coverage_percent=100.0,
            valid_pixel_count=len(composite_totals),
            thresholds=MODIS_THRESHOLDS,
        )

        provenance = self._provenance(
            context,
            dataset,
            events,
            dataset_id,
            image_count,
            composite_totals,
            total_mm,
            quality,
            fallback_from,
        )

        warnings: List[str] = [
            (
                f"ET window: {et_start} to {et_end} "
                f"({season_day_span} days), the detected vegetation season "
                "widened to full months."
            ),
            (
                f"{image_count} MOD16 composite(s) contributed "
                f"{len(composite_totals)} usable spatial mean(s); totals "
                "of boundary-spanning composites are included in full."
            ),
            (
                "Sentinel-2 defines the season; MOD16 supplies the ET. "
                "The alignment is calendar-month only."
            ),
            (
                "No water-use-efficiency factor is applied: this total is "
                "not convertible to biomass or yield by this engine."
            ),
        ]
        if fallback_from is not None:
            warnings.append(
                "The gap-filled MOD16 product was unavailable for this "
                "period, so the near real-time product was used instead."
            )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))
        elif quality is QualityLevel.MODERATE:
            warnings.append(describe_quality(QualityLevel.MODERATE))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=total_mm,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )

    def _provenance(
        self,
        context: MetricContext,
        dataset: Any,
        events: SeasonEvents,
        dataset_id: str,
        image_count: int,
        composite_totals: Sequence[float],
        total_mm: float,
        quality: QualityLevel,
        fallback_from: Optional[str],
    ) -> Provenance:
        per_composite = ", ".join(
            f"{value:.2f}" for value in composite_totals
        )
        return self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["ET"],
            formula=(
                "sum over the MOD16 ET composites inside the detected "
                "season window of each composite's spatial-mean total "
                "scaled by the band's declared 0.1 factor (applied once, "
                "by the band spec)"
            ),
            quality=quality,
            image_count=image_count,
            aggregation_method=(
                "per-composite spatial mean inside the season window, then "
                "a sum across composites"
            ),
            fallback_from=fallback_from,
            extra_limitations=self.limitations,
            extra_caveats=(
                f"Detected season span (month resolution): "
                f"{events.sos.isoformat()} to {events.eos.isoformat()}.",
                f"ET window used: {events.sos.isoformat()} to "
                f"{_last_day_of_month(events.eos).isoformat()}.",
                (
                    f"Per-composite totals (mm): "
                    f"{per_composite or '(none usable)'}; sum = "
                    f"{total_mm:.2f} mm."
                ),
                (
                    "The season was detected from Sentinel-2 NDVI; the ET "
                    "product is MOD16. The two sources are aligned at "
                    "calendar-month resolution only."
                ),
            ),
        )


# ==========================================================================
# 3. Crop-area-normalised productivity indicator
# ==========================================================================


class CropAreaNormalisedProductivityIndicator(Metric):
    """Mean NDVI weighted by the WorldCereal temporary-crop share.

    Definition, stated so nothing can be read into it:

    .. math::

        value = \\overline{NDVI}_{field} \\times share

    where ``share`` is the fraction of valid pixels the ESA WorldCereal
    2021 ``temporarycrops`` mask carries, and ``NDVI_bar`` is the
    field-level median-composite NDVI over the requested window.

    What the product is **not**:

    * It is **not crop production**. Multiplying a dimensionless index by
      an area fraction yields a dimensionless number, not a mass.
    * It is **not the NDVI of the crop pixels**. The vegetation
      composite is a field-level median; it cannot resolve which pixels
      carry the crop, so the multiplication weights the *field's* mean
      signal by the crop share rather than extracting the crop's own
      signal. A field that is 10 percent crop and 90 percent luminous
      bare soil scores the same as one that is 10 percent crop and 90
      percent dark vegetation.
    * It carries **no units of area or mass**. Its unit is
      ``index.fraction`` and it is dimensionless.

    The crop share is the 2021 reference year. A window in any other
    year is refused rather than answered from a neighbouring season --
    the crop module's own coverage gate, inherited unchanged.
    """

    key = "crop_area_normalised_productivity_indicator"
    display_name = "Crop Area-Normalised Productivity Indicator"
    display_name_fa = "شاخص بهره‌وری نرمال‌شده با سطح محصول"
    unit = "index.fraction"
    domain = MetricDomain.PRODUCTIVITY
    dataset_ids = (S2_DATASET_ID, WORLDCEREAL_ID)
    measurement_basis = MeasurementBasis.PROXY
    default_scale = 10

    description = (
        "The field-mean NDVI multiplied by the ESA WorldCereal 2021 "
        "temporary-crop share. Dimensionless and deliberately so: this "
        "weights a field-level vegetation signal by crop area context. "
        "It is not crop production, not crop-only NDVI, and not a mass "
        "of any kind."
    )
    limitations = (
        PRODUCTIVITY_DISCLAIMER,
        "The crop share is the 2021 reference-year product. A request "
        "outside 2021 cannot carry a crop-area normalisation and is "
        "refused, never answered from another year.",
        "This is not the NDVI of the crop pixels: the vegetation signal "
        "is a field-level median composite and cannot resolve which "
        "pixels carry the crop. Non-crop vegetation inside the field "
        "contributes to the signal.",
        "The multiplication is a weighting, not a production estimate. "
        "The result is dimensionless and carries no units of area or "
        "mass.",
        "The WorldCereal mask's own validation errors (user's accuracy "
        "88.5 percent, producer's 92.1 percent for temporary crops) "
        "propagate into the share.",
        "Perennial crops and pastures are excluded by the mask's "
        "definition; orchards are invisible to it.",
        "Minimum mapping unit around 0.5 hectares; smaller plots are "
        "unreliable.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        # -- 1. the crop share, through the crop module's own reduction --
        # reduce_worldcereal_mask applies the product filter, the binary
        # domain check and the valid-pixel accounting; the share it
        # returns is the same figure temporary_crop_context publishes.
        # A collection that cannot be read at all is a missing crop
        # context, never a zero share.
        try:
            crop_stats, _image_count, _total_pixels, reason = (
                reduce_worldcereal_mask(
                    context, ee, "temporarycrops", "tc-annual"
                )
            )
        except Exception as exc:  # noqa: BLE001 - degrade to insufficient
            logger.warning(
                "Could not read the WorldCereal product for the areal "
                "productivity indicator: %s",
                exc,
            )
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The WorldCereal temporary-crops product could not be "
                    "read for this area, so no crop share exists to "
                    "normalise by. No areal indicator is reported."
                ),
                unit=self.unit,
            )

        if crop_stats is None:
            if reason == "no_matching_image":
                return MetricResult.insufficient(
                    metric_key=self.key,
                    display_name=self.display_name,
                    display_name_fa=self.display_name_fa,
                    message=(
                        "No temporary-crops image for the tc-annual season "
                        "covers this area. WorldCereal processed each "
                        "agro-ecological zone independently, and zones "
                        "without a product were not processed, so no crop "
                        "share exists to normalise by."
                    ),
                    unit=self.unit,
                )
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=reason or "unavailable",
                message="The WorldCereal image could not be resolved.",
                unit=self.unit,
            )

        share = _crop_share(crop_stats)
        if share is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The classification band carried values outside the "
                    "documented binary domain (0 or 100), so no crop "
                    "share can be derived."
                ),
                unit=self.unit,
            )

        crop_dataset = get_dataset(WORLDCEREAL_ID)
        crop_quality = assess_quality(
            image_count=max(_image_count, 1),
            coverage_percent=(
                crop_stats.valid_pixel_count / _total_pixels * 100.0
                if _total_pixels
                else 0.0
            ),
            valid_pixel_count=crop_stats.valid_pixel_count,
            thresholds=SENTINEL2_THRESHOLDS,
        )
        total_pixels = _total_pixels
        valid_fraction = (
            crop_stats.valid_pixel_count / total_pixels
            if total_pixels > 0
            else None
        )

        # -- 2. the field NDVI, through the vegetation module's path ----
        composite, ndvi_image_count = build_sentinel2_ndvi_composite(
            context, ee
        )
        ndvi_stats = _reduce_ndvi(composite, context, ee, 10)

        ndvi_quality = assess_quality(
            image_count=ndvi_image_count,
            coverage_percent=ndvi_stats.coverage_percent,
            valid_pixel_count=ndvi_stats.valid_pixel_count,
            thresholds=SENTINEL2_THRESHOLDS,
        )

        quality = combine_quality([crop_quality, ndvi_quality])

        provenance = self._provenance(
            context,
            crop_dataset,
            share,
            ndvi_image_count,
            ndvi_stats,
            crop_stats,
            total_pixels,
            valid_fraction,
            quality,
        )

        if ndvi_image_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No Sentinel-2 scenes matched the requested period and "
                    "cloud filter, so no field NDVI exists to normalise."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if valid_fraction is None or valid_fraction < CROP_AREA_MIN_VALID_FRACTION:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {crop_stats.valid_pixel_count} pixel(s) of the "
                    f"estimated {total_pixels} the geometry covers carry "
                    "the temporary-crops product. Below the "
                    f"{CROP_AREA_MIN_VALID_FRACTION:.0%} valid-pixel floor "
                    "no crop share is published, and without a share there "
                    "is no normalisation."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if (
            quality is QualityLevel.INSUFFICIENT
            or not ndvi_stats.has_values
            or ndvi_stats.mean is None
        ):
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The Sentinel-2 NDVI reduction covers too little of "
                    "the area, or returned no valid pixels, so there is no "
                    "field signal to weight."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        value = ndvi_stats.mean * share

        warnings: List[str] = [
            (
                f"Construction: field-mean NDVI ({ndvi_stats.mean:.3f}) "
                f"x temporary-crop share ({share:.3f}) = {value:.4f}, a "
                "dimensionless weighting. It is not production and not a "
                "mass."
            ),
            (
                "The vegetation signal is a field-level median; the crop "
                "share weights it but cannot extract the crop's own "
                "pixels."
            ),
            (
                "The crop share is the 2021 reference year; the NDVI "
                "window is the requested period. The two describe "
                "different years by construction."
            ),
        ]
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))
        elif quality is QualityLevel.MODERATE:
            warnings.append(describe_quality(QualityLevel.MODERATE))

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
        crop_dataset: Any,
        share: float,
        ndvi_image_count: int,
        ndvi_stats: SpatialStatsLike,
        crop_stats: Any,
        total_pixels: int,
        valid_fraction: Optional[float],
        quality: QualityLevel,
    ) -> Provenance:
        return self.build_provenance(
            context=context,
            dataset=crop_dataset,
            bands=["classification", "B4", "B8"],
            formula=(
                "value = mean(NDVI over the geometry, Sentinel-2 median "
                "composite) * (mean(classification) / 100 of the ESA "
                "WorldCereal 2021 temporarycrops tc-annual mask); both "
                "factors reduced before the multiplication"
            ),
            quality=quality,
            image_count=ndvi_image_count,
            aggregation_method=(
                "field-level median-composite NDVI mean, multiplied by the "
                "crop share derived from the binary mask's mean over valid "
                "pixels"
            ),
            extra_limitations=self.limitations,
            extra_caveats=(
                f"Crop share = {share:.4f} of valid pixels "
                f"({crop_stats.valid_pixel_count} of {total_pixels}; "
                f"{(valid_fraction or 0.0):.1%} valid coverage).",
                (
                    "Temporal note: the crop mask is the 2021 reference "
                    "year regardless of the requested NDVI window."
                ),
                (
                    "Spatial note: the reduction runs at 10 m for both "
                    "inputs; the crop mask's own validity is bounded by "
                    "its 2021 zones."
                ),
            ),
        )


# Type alias kept out of the public surface: the areal metric's provenance
# helper accepts the SpatialStats it is given without importing the type
# at module top level twice.
SpatialStatsLike = SpatialStats


# ==========================================================================
# Shared helpers
# ==========================================================================


def build_sentinel2_ndvi_composite(
    context: MetricContext,
    ee_module: Any,
    max_cloud_percent: Optional[float] = None,
) -> Tuple[Any, int]:
    """Build the cloud-masked NDVI median composite over the window.

    Mirrors the vegetation module's compositing path (same collection
    filter, same SCL mask, same 0.0001 scale) and computes NDVI before
    the median, because a median of per-scene NDVI preserves the index's
    distribution where a median of reflectances would not compose
    cleanly into an index. The implementation reads the vegetation
    module's mask directly so the two cannot drift.
    """
    cloud_limit = (
        max_cloud_percent
        if max_cloud_percent is not None
        else context.cloud_max_percent
    )
    collection = (
        ee_module.ImageCollection(VEGETATION_S2_DATASET_ID)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
    )
    if cloud_limit is not None and cloud_limit < 100:
        collection = collection.filter(
            ee_module.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud_limit)
        )
    image_count = int(collection.size().getInfo())

    def prepare(image: Any) -> Any:
        masked = _mask_sentinel2(image, ee_module)
        red = masked.select("B4").multiply(0.0001)
        nir = masked.select("B8").multiply(0.0001)
        ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI")
        return ndvi

    composite = collection.map(prepare).median()
    return composite, image_count


def _reduce_ndvi(
    image: Any,
    context: MetricContext,
    ee_module: Any,
    scale: int,
):
    """Reduce the NDVI composite over the geometry (vegetation parity)."""
    raw = image.select("NDVI").reduceRegion(
        reducer=build_reducer(ee_module),
        geometry=context.geometry,
        scale=scale,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()
    area_sq_m = context.option("area_sq_m")
    return parse_reduction_result(
        raw or {},
        band="NDVI",
        total_pixel_count=estimate_pixel_count(area_sq_m, scale),
        pixel_area_sq_m=pixel_area_sq_m(scale),
    )


def _last_day_of_month(day: date) -> date:
    """The last calendar day of the month containing ``day``."""
    import calendar

    last = calendar.monthrange(day.year, day.month)[1]
    return date(day.year, day.month, last)


# ==========================================================================
# Collection
# ==========================================================================


PRODUCTIVITY_METRICS: Tuple[Metric, ...] = (
    SeasonalVegetationProductivityIndicator(),
    SeasonalETProductivityContextMetric(),
    CropAreaNormalisedProductivityIndicator(),
)

ALL_PRODUCTIVITY_METRICS: Tuple[Metric, ...] = PRODUCTIVITY_METRICS

#: Every key this module registers, checked against the registry so no
#: name here can silently collide with an existing quantity or drift
#: into publishing one under a productivity label.
PRODUCTIVITY_AVAILABLE: Dict[str, str] = {
    metric.key: metric.unit for metric in PRODUCTIVITY_METRICS
}
