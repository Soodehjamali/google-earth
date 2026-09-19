"""Water metrics: spectral water indices and evapotranspiration.

This module covers four groups:

1. **Spectral water indices** — NDWI, NDMI and MNDWI. The formulas already
   exist as pure functions in :mod:`app.services.agriculture.indices`;
   this module only wires them to Earth Engine. No formula is restated
   here, so there is no possibility of the two drifting apart.

2. **Evapotranspiration** — actual and potential, from the MODIS MOD16
   product, plus a cumulative total over the requested period.

3. **ERA5-Land evaporation** — the reanalysis water-balance residual, with
   an explicitly handled sign convention.

4. **Indices that are NOT produced** — CWSI and WDI are registered as
   unavailable, with the scientific reason recorded. See the module-level
   note at the end of this file.

Two sign and unit hazards dominate this module, and both are handled
explicitly rather than by convention:

* ERA5 stores evaporation as **negative** when water is leaving the
  surface. Reporting the stored value directly would report negative
  evaporation; taking the absolute value would turn condensation into
  evaporation. The only correct operation is negation.
* MOD16 ``ET`` and ``PET`` are **8-day sums**, not daily rates, and the
  final composite period of each year spans only five or six days.
  Dividing a sum by a nominal eight would understate the rate for that
  period, so the divisor is read from the image rather than assumed.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture import indices as pure
from app.services.agriculture.aggregation import (
    build_reducer,
    estimate_pixel_count,
    parse_reduction_result,
    pixel_area_sq_m,
)
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.quality import (
    MODIS_THRESHOLDS,
    REANALYSIS_THRESHOLDS,
    SENTINEL2_THRESHOLDS,
    assess_quality,
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
    S2_DATASET_ID,
    _SpectralIndexMetric,
    _mask_sentinel2,
    _reduce_index,
    build_sentinel2_composite,
)

logger = get_logger(__name__)

__all__ = [
    "NDWIMetric",
    "NDMIMetric",
    "MNDWIMetric",
    "EvapotranspirationMetric",
    "PotentialEvapotranspirationMetric",
    "CumulativeEvapotranspirationMetric",
    "ERA5EvaporationMetric",
    "WATER_METRICS",
    "UNAVAILABLE_WATER_METRICS",
    "CWSI_UNAVAILABLE_REASON",
    "WDI_UNAVAILABLE_REASON",
]


# ==========================================================================
# Dataset IDs
# ==========================================================================

MOD16_GAPFILLED = "MODIS/061/MOD16A2GF"
MOD16_NRT = "MODIS/061/MOD16A2"
ERA5_DAILY = "ECMWF/ERA5_LAND/DAILY_AGGR"

#: MOD16 is published on a 500 m grid.
MOD16_SCALE = 500

#: ERA5-Land is published on a 0.1 degree grid, approximately 11.1 km.
ERA5_WORKING_SCALE = 11132

#: The nominal length of a MOD16 composite period. The real length is read
#: from each image's own start and end, because the last period of each
#: year is shorter.
MOD16_NOMINAL_PERIOD_DAYS = 8


# ==========================================================================
# 1. Spectral water indices — thin wrappers over the existing formulas
# ==========================================================================
#
# These deliberately reuse ``_SpectralIndexMetric`` from the vegetation
# module rather than reimplementing the Sentinel-2 compositing, masking and
# reduction path. The only thing that differs is the domain and, for NDMI
# and MNDWI, the bands.
#
# A warning that is easy to miss: NDWI and NDMI are NOT the same index.
#
#   NDWI  = (GREEN - NIR)   / (GREEN + NIR)     bands B3, B8
#   NDMI  = (NIR   - SWIR1) / (NIR   + SWIR1)   bands B8, B11
#
# They answer different questions. NDWI finds open water; NDMI describes
# vegetation water content. Feeding the same band pair to both would
# produce a numerically valid but physically meaningless number, so the
# required_bands tuples below are asserted against the pure registry by
# tests.


class _WaterIndexMetric(_SpectralIndexMetric):
    """A Sentinel-2 water index, in the water domain."""

    domain = MetricDomain.WATER
    unit = "index"
    measurement_basis = MeasurementBasis.DERIVED

    @property
    def domain_note(self) -> str:
        return ""


class NDWIMetric(_WaterIndexMetric):
    key = "ndwi"
    display_name = "NDWI (open water)"
    display_name_fa = "شاخص آب (NDWI)"
    index_name = "NDWI"
    # McFeeters NDWI: green and near-infrared.
    required_bands = ("B3", "B8")
    band_scale = 10
    description = (
        "Normalized Difference Water Index after McFeeters. Uses green and "
        "near-infrared to delineate open water surfaces."
    )
    limitations = (
        "Targets open water, including irrigation canals and flooded "
        "fields. It is not an indicator of crop water status.",
        "Confused by built-up surfaces and by cloud shadow, both of which "
        "can appear dark in the near-infrared and score like water.",
        "Sensitive to the threshold chosen; there is no single accepted "
        "cut-off for separating water from land.",
        "A negative value here means only that the pixel is not open "
        "water. It carries no information about whether a crop is "
        "water-stressed.",
    )

    @property
    def domain_note(self) -> str:
        return (
            "For crop water status use NDMI, which reads the shortwave "
            "infrared. NDWI is an open-water index and will not serve that "
            "purpose."
        )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.normalizedDifference(["B3", "B8"])


class NDMIMetric(_WaterIndexMetric):
    key = "ndmi"
    display_name = "NDMI (vegetation water)"
    display_name_fa = "شاخص رطوبت گیاه (NDMI)"
    index_name = "NDMI"
    # Gao NDMI: near-infrared and shortwave infrared 1.
    required_bands = ("B8", "B11")
    band_scale = 20
    description = (
        "Normalized Difference Moisture Index after Gao. Uses near-infrared "
        "and shortwave infrared to describe vegetation water content."
    )
    limitations = (
        "The shortwave infrared band is acquired at 20 m, so within-field "
        "detail is coarser than for NDVI.",
        "This is a canopy water status signal, not a soil moisture "
        "measurement. A high NDMI does not mean the soil is wet.",
        "Affected by canopy structure as well as by water content: a "
        "change in leaf area changes NDMI without any change in leaf water.",
        "Cannot distinguish a genuinely water-stressed canopy from one "
        "that is senescing, diseased, or damaged by pests.",
    )

    @property
    def domain_note(self) -> str:
        return (
            "This is the index to use for crop water status. It must not be "
            "confused with NDWI, which uses green and near-infrared."
        )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.normalizedDifference(["B8", "B11"])


class MNDWIMetric(_WaterIndexMetric):
    key = "mndwi"
    display_name = "MNDWI (modified water)"
    display_name_fa = "شاخص آب اصلاح‌شده (MNDWI)"
    index_name = "MNDWI"
    # Xu MNDWI: green and shortwave infrared 1.
    required_bands = ("B3", "B11")
    band_scale = 20
    description = (
        "Modified Normalized Difference Water Index after Xu. Uses green "
        "and shortwave infrared, which suppresses vegetation and shadow "
        "better than near-infrared."
    )
    limitations = (
        "The shortwave infrared band is acquired at 20 m, so within-field "
        "detail is coarser than for NDVI.",
        "Like NDWI this is an open-water index and says nothing about crop "
        "water status.",
        "Performance degrades for turbid or shallow water and for narrow "
        "channels thinner than the pixel.",
        "Sensitive to the threshold chosen.",
    )

    @property
    def domain_note(self) -> str:
        return (
            "Prefer this over NDWI where water bodies adjoin built-up land "
            "or dense vegetation."
        )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.normalizedDifference(["B3", "B11"])


# ==========================================================================
# 2. Evapotranspiration — MOD16
# ==========================================================================


def _reduce_mod16(
    context: MetricContext,
    ee_module: Any,
    dataset_id: str,
    band_name: str,
) -> Tuple[SpatialStats, int, List[float]]:
    """Reduce one MOD16 band over the geometry.

    Returns ``(stats, image_count, period_lengths)`` where
    ``period_lengths`` is the length in days of each composite that
    contributed, in the collection's own order.

    The period length is read from each image rather than assumed to be
    eight days. The final composite period of each year spans five or six
    days; dividing its sum by eight would understate the daily rate by up
    to 37 percent for that period.
    """
    collection = (
        ee_module.ImageCollection(dataset_id)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
        .select([band_name])
    )

    image_count = int(collection.size().getInfo())

    # Carry each composite's own length forward as a property so the
    # daily-rate conversion can use the true value.
    def annotate(image: Any) -> Any:
        return image.set("period_days", _composite_length_days(image))

    annotated = collection.map(annotate)
    try:
        raw_lengths = annotated.aggregate_array("period_days").getInfo()
    except Exception as exc:  # noqa: BLE001 - falls back to the nominal value
        logger.warning(
            "Could not read MOD16 composite lengths from %s: %s",
            dataset_id,
            exc,
        )
        raw_lengths = None

    period_lengths: List[float] = []
    for record in raw_lengths or []:
        try:
            numeric = float(record)
        except (TypeError, ValueError):
            continue
        if numeric != numeric:  # filters NaN
            continue
        period_lengths.append(numeric)

    if not period_lengths:
        period_lengths = [float(MOD16_NOMINAL_PERIOD_DAYS)] * image_count

    # Mean over the period, then one reduction. A mean rather than a sum
    # because the composites are already sums over their own windows.
    period_mean = collection.mean()
    raw = period_mean.reduceRegion(
        reducer=build_reducer(ee_module),
        geometry=context.geometry,
        scale=MOD16_SCALE,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()

    area_sq_m = context.option("area_sq_m")
    stats = parse_reduction_result(
        raw or {},
        band=band_name,
        total_pixel_count=estimate_pixel_count(area_sq_m, MOD16_SCALE),
        pixel_area_sq_m=pixel_area_sq_m(MOD16_SCALE),
        # The band declares a scale factor of 0.1, so without this the
        # statistics would be raw stored integers, ten times too large.
        band_spec=get_dataset(dataset_id).band(band_name),
    )

    return stats, image_count, period_lengths


def _composite_length_days(image: Any) -> Any:
    """Length of a MOD16 composite in days, read from the image itself.

    MOD16 images carry the ``period_days`` property in Earth Engine, and
    MOD16A2GF's assets are annotated with it. Where the property is absent
    the value is ``None`` and the caller substitutes the nominal 8 days.

    The property is read rather than assumed because the final composite
    period of each year spans only 5 or 6 days. Dividing that period's sum
    by 8 would understate its daily rate by up to 37 percent.
    """
    return image.get("period_days")


class _MOD16Metric(Metric):
    """Common behaviour for the MOD16 evapotranspiration bands."""

    domain = MetricDomain.WATER
    dataset_ids = (MOD16_GAPFILLED, MOD16_NRT)
    measurement_basis = MeasurementBasis.PRODUCT
    default_scale = MOD16_SCALE

    #: MOD16 band to read.
    source_band: str = ""

    #: The reported unit after conversion.
    unit = "mm/period"

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset_id, fallback_from = _resolve_mod16_dataset(context)
        dataset = get_dataset(dataset_id)
        band_spec = dataset.band(self.source_band)

        stats, image_count, period_lengths = _reduce_mod16(
            context, ee, dataset_id, self.source_band
        )

        # Convert from the product's own storage unit to millimetres.
        # MOD16 reports kg/m2, which for water is numerically identical to
        # millimetres of water depth. The declared scale factor of 0.1 has
        # already been applied by the reduction.
        converted = self._convert_stats(stats)

        quality = assess_quality(
            image_count=max(image_count, 1),
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=MODIS_THRESHOLDS,
        )

        mean_period_days = (
            sum(period_lengths) / len(period_lengths)
            if period_lengths
            else float(MOD16_NOMINAL_PERIOD_DAYS)
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=[self.source_band],
            formula=self.formula,
            quality=quality,
            image_count=image_count,
            aggregation_method=(
                "mean of composite periods, then spatial mean"
            ),
            fallback_from=fallback_from,
            extra_limitations=self.extra_limitations,
            extra_caveats=(
                (
                    f"The mean composite period in this request was "
                    f"{mean_period_days:.1f} days. The final composite "
                    "period of each year is shorter than 8 days."
                ),
                (
                    "The value describes an 8-day composite window, not a "
                    "single day. It must not be read as a daily "
                    "observation."
                ),
            ),
        )

        if image_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"No {dataset.name} scenes were available for the "
                    "requested period, so no value is reported. Reporting "
                    "zero would falsely indicate no water use."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not converted.has_values or quality is QualityLevel.INSUFFICIENT:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"{image_count} composite period(s) were found but only "
                    f"{converted.valid_pixel_count} valid pixel(s) "
                    f"({converted.coverage_percent:.1f} percent coverage) "
                    "remained after the product's own quality masking. No "
                    "value is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))
        if fallback_from is not None:
            warnings.append(
                f"The gap-filled product was unavailable for this period, "
                f"so the near real-time product was used instead. It is not "
                "gap-filled and has lower effective coverage."
            )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=converted.mean,
            unit=self.unit,
            stats=converted,
            provenance=provenance,
            warnings=warnings,
        )

    def _convert_stats(self, stats: SpatialStats) -> SpatialStats:
        """MOD16 stores kg/m2, which equals millimetres of water depth.

        No arithmetic is needed for ET and PET because 1 kg of water
        spread over 1 m2 is exactly 1 mm deep. The conversion is recorded
        as an identity rather than omitted, so the provenance states the
        reasoning instead of leaving it to be rediscovered.
        """
        return stats

    @property
    def formula(self) -> str:
        return (
            f"MOD16 {self.source_band} raw x 0.1 = kg/m2 per composite "
            "period; kg/m2 of water is numerically equal to mm of water "
            "depth"
        )

    @property
    def extra_limitations(self) -> Tuple[str, ...]:
        return ()

    def metadata(self) -> dict:
        metadata = super().metadata()
        metadata["band"] = self.source_band
        metadata["native_temporal_resolution"] = "8 days"
        return metadata


def _resolve_mod16_dataset(
    context: MetricContext,
) -> Tuple[str, Optional[str]]:
    """Choose between the gap-filled and near real-time MOD16 products.

    ``MOD16A2GF`` is the recommended product for historical records and is
    gap-filled. ``MOD16A2`` begins only on 2021-01-01 and is not
    gap-filled, but the gap-filled product lags roughly a year, so the
    near real-time product is the only option for the most recent months.

    The choice is a caller preference, not a date inference. Defaulting to
    the gap-filled product for a recent period would silently return an
    empty collection, which is indistinguishable from a cloud problem.
    A caller who wants the near real-time product asks for it by ID.

    Returns ``(dataset_id, fallback_from)`` where ``fallback_from`` names
    the dataset that was preferred but could not be used, or ``None``.
    """
    requested = context.option("mod16_dataset")
    if requested == MOD16_GAPFILLED:
        return MOD16_GAPFILLED, None
    if requested == MOD16_NRT:
        # Recorded as a fallback so the provenance shows that the
        # gap-filled product was superseded for this request.
        return MOD16_NRT, MOD16_GAPFILLED
    return MOD16_GAPFILLED, None


class EvapotranspirationMetric(_MOD16Metric):
    key = "evapotranspiration"
    display_name = "Evapotranspiration (actual)"
    display_name_fa = "تبخیر-تعرق واقعی"
    unit = "mm/period"
    source_band = "ET"
    description = (
        "Actual evapotranspiration from the MODIS MOD16 product: the mean "
        "8-day composite total over the requested period, expressed as "
        "millimetres of water."
    )
    limitations = (
        "The MOD16 algorithm is driven by a Penman-Monteith model with a "
        "biome look-up table, not by a direct measurement of vapour flux "
        "over this field.",
        "It performs poorly over sparse vegetation and arid bare surfaces, "
        "which describes a large part of Iran.",
        "The value is the mean of 8-day composite totals. It is not a "
        "daily rate and not an instantaneous flux.",
        "ET aggregates soil evaporation and plant transpiration. It cannot "
        "separate them, so a high value does not prove that the crop "
        "itself is transpiring well.",
        "At 500 m a single pixel covers many fields, so the value cannot "
        "be attributed to one plot.",
        "The gap-filled product lags roughly one year; recent months fall "
        "back to the near real-time product, which is not gap-filled.",
    )
    extra_limitations = (
        "Do not divide this value by 8 to obtain a daily rate without "
        "accounting for the true length of each composite period. The "
        "final period of each year is only 5 or 6 days.",
    )


class PotentialEvapotranspirationMetric(_MOD16Metric):
    key = "potential_evapotranspiration"
    display_name = "Potential Evapotranspiration"
    display_name_fa = "تبخیر-تعرق پتانسیل"
    unit = "mm/period"
    source_band = "PET"
    description = (
        "Potential evapotranspiration from the MODIS MOD16 product: the "
        "mean 8-day composite total over the requested period."
    )
    limitations = (
        "This is MOD16 potential evapotranspiration, which the algorithm "
        "computes under the assumption of unlimited soil water. It is NOT "
        "reference evapotranspiration (ET0) as defined by FAO-56 or the "
        "ASCE standard, and the two are not interchangeable.",
        "Derived from the same Penman-Monteith model as MOD16 actual ET, "
        "so it shares the same look-up table limitations.",
        "The value is the mean of 8-day composite totals, not a daily rate.",
        "Because PET assumes no water limitation, the difference between "
        "PET and actual ET is only suggestive of a water deficit. It is "
        "not a measurement of crop water stress.",
    )
    extra_limitations = (
        "Do not substitute this for reference evapotranspiration in an "
        "irrigation scheduling calculation. Use a locally calibrated ET0 "
        "for that purpose.",
    )


class CumulativeEvapotranspirationMetric(_MOD16Metric):
    """Total evapotranspiration over the requested period.

    This is not simply ``EvapotranspirationMetric`` multiplied by the
    number of days. The per-period metric reports the mean composite
    total, while this one sums the composites. Both are useful and they
    answer different questions, so both are registered.
    """

    key = "evapotranspiration_cumulative"
    display_name = "Cumulative Evapotranspiration"
    display_name_fa = "تبخیر-تعرق تجمعی"
    unit = "mm"
    source_band = "ET"
    description = (
        "Total evapotranspiration accumulated over the requested period, "
        "summed across the MOD16 composite periods that fall inside it."
    )
    limitations = (
        "An accumulation is only as reliable as its weakest composite. A "
        "single corrupted period distorts the total.",
        "Because the composites are 8-day windows, a period boundary "
        "rarely aligns with the requested date range. Composites that "
        "overlap the boundary are included in full, so the total describes "
        "slightly more than the requested window.",
        "It inherits every limitation of the underlying MOD16 actual "
        "evapotranspiration product, including its poor performance over "
        "sparse vegetation and arid surfaces.",
        "A cumulative total cannot be compared between periods of "
        "different length without dividing by the number of days.",
    )
    extra_limitations = (
        "Overlapping composites are counted once. The engine sums each "
        "composite in the collection exactly once, so a composite that "
        "spans a period boundary is not counted twice.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset_id, fallback_from = _resolve_mod16_dataset(context)
        dataset = get_dataset(dataset_id)

        collection = (
            ee.ImageCollection(dataset_id)
            .filterDate(context.start_date, context.end_date)
            .filterBounds(context.geometry)
            .select([self.source_band])
        )

        image_count = int(collection.size().getInfo())

        # Two reductions from one collection: the per-composite spatial
        # mean, and the spatial statistics of the collection sum.
        def to_mean(image: Any) -> Any:
            mean_value = image.select([self.source_band]).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=context.geometry,
                scale=MOD16_SCALE,
                maxPixels=1e9,
                bestEffort=True,
            ).get(self.source_band)
            return image.set("period_mean", mean_value)

        annotated = collection.map(to_mean)
        try:
            raw_means = annotated.aggregate_array("period_mean").getInfo()
        except Exception as exc:  # noqa: BLE001 - the sum path still works
            logger.warning(
                "Could not read per-composite means for %s: %s",
                self.source_band,
                exc,
            )
            raw_means = None

        band_spec = dataset.band(self.source_band)
        composite_means: List[float] = []
        for record in raw_means or []:
            physical = band_spec.to_physical(record)
            if physical is not None:
                composite_means.append(physical)

        # The spatial statistics of the raster sum, for the spread across
        # the field rather than across time.
        summed = collection.sum()
        raw = summed.reduceRegion(
            reducer=build_reducer(ee),
            geometry=context.geometry,
            scale=MOD16_SCALE,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()

        area_sq_m = context.option("area_sq_m")
        stats = parse_reduction_result(
            raw or {},
            band=self.source_band,
            total_pixel_count=estimate_pixel_count(area_sq_m, MOD16_SCALE),
            pixel_area_sq_m=pixel_area_sq_m(MOD16_SCALE),
            band_spec=band_spec,
        )

        quality = assess_quality(
            image_count=max(image_count, 1),
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=MODIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=[self.source_band],
            formula=(
                "sum of MOD16 ET composite totals over the period, each "
                "raw value multiplied by 0.1"
            ),
            quality=quality,
            image_count=image_count,
            aggregation_method=(
                "temporal sum of composite totals, then spatial mean"
            ),
            fallback_from=fallback_from,
            extra_limitations=self.extra_limitations,
            extra_caveats=(
                (
                    "Each composite is summed exactly once, so a composite "
                    "that straddles a period boundary is not double "
                    "counted."
                ),
            ),
        )

        if image_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No MOD16 composite periods fell inside the requested "
                    "date range, so no accumulation is reported. Reporting "
                    "zero would falsely indicate no water use."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not composite_means:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"{image_count} composite period(s) were found but none "
                    "returned a usable spatial mean, so no accumulation can "
                    "be reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        total = sum(composite_means)
        warnings: List[str] = []
        missing = image_count - len(composite_means)
        if missing > 0:
            warnings.append(
                f"{missing} of {image_count} composite period(s) returned no "
                "usable mean and were excluded. The accumulation is "
                "therefore biased low."
            )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        accumulated = SpatialStats(
            mean=total,
            min=min(composite_means),
            max=max(composite_means),
            valid_pixel_count=len(composite_means),
            total_pixel_count=max(image_count, len(composite_means)),
        )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=total,
            unit=self.unit,
            stats=accumulated,
            provenance=provenance,
            warnings=warnings,
        )


# ==========================================================================
# 3. ERA5-Land evaporation
# ==========================================================================

#: The ERA5 band carrying the water-balance evaporation residual.
ERA5_EVAPORATION_BAND = "total_evaporation_sum"

#: ECMWF's integrated forecasting system convention, quoted from the Earth
#: Engine catalogue entry for this band: "downward fluxes are positive.
#: Therefore, negative values indicate evaporation and positive values
#: indicate condensation."
ERA5_EVAPORATION_SIGN_NOTE = (
    "ECMWF convention: downward fluxes are positive, so a negative stored "
    "value means evaporation and a positive stored value means condensation"
)


def era5_evaporation_from_stored(stored_value: Optional[float]) -> Optional[float]:
    """Convert ERA5's stored water-balance flux to a positive evaporation.

    ERA5 stores this band with the ECMWF sign convention, in which
    downward fluxes are positive. Water leaving the surface is therefore
    stored as a **negative** number, and condensation is stored as a
    positive one.

    The correct conversion is a plain negation:

        evaporation = -stored_value

    Two tempting alternatives are both wrong, and both are dangerous
    precisely because they look harmless:

    * ``abs(stored_value)`` destroys the distinction between evaporation
      and condensation. A night of dew formation would be reported as a
      night of evaporation, and the sign error would be invisible in the
      output.
    * Clamping negatives to zero would silently discard every real
      evaporation event and leave only condensation, which is close to
      its opposite.

    The result is returned in millimetres, because ERA5 reports this band
    in metres of water equivalent.

    A positive return value is evaporation. A negative return value is
    condensation, and is reported as such rather than hidden.
    """
    if stored_value is None:
        return None
    if isinstance(stored_value, bool):
        return None
    if not isinstance(stored_value, (int, float)):
        return None
    # NaN fails its own comparison.
    if stored_value != stored_value:
        return None
    if stored_value in (float("inf"), float("-inf")):
        return None
    return -float(stored_value) * 1000.0


class ERA5EvaporationMetric(Metric):
    """Water-balance evaporation from ERA5-Land.

    This is the residual of the ECMWF land surface water balance. It is a
    modelled quantity, and it must not be presented as a measurement.

    The component breakdown of this quantity is deliberately not exposed.
    The Earth Engine catalogue documents that three of the ECMWF component
    bands carry swapped values:

        evaporation_from_bare_soil_sum                     holds the
            vegetation transpiration values
        evaporation_from_open_water_surfaces_excluding_oceans_sum
            holds the bare soil values
        evaporation_from_vegetation_transpiration_sum      holds the open
            water values

    Any decomposition of ET from this dataset would therefore be wrong.
    Reading the total is safe; splitting it is not.
    """

    key = "era5_evaporation"
    display_name = "Evaporation (ERA5-Land water balance)"
    display_name_fa = "تبخیر (ERA5-Land)"
    unit = "mm"
    domain = MetricDomain.WATER
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.MODELLED
    default_scale = ERA5_WORKING_SCALE
    description = (
        "Evaporation from the ERA5-Land reanalysis land surface water "
        "balance, accumulated over the requested period and reported as "
        "millimetres of water. Positive values indicate evaporation; "
        "negative values indicate condensation."
    )
    limitations = (
        "This is a reanalysis model field at roughly 11 km, constrained by "
        "observations but not measured at the field. It is not a "
        "measurement of evaporation from this plot.",
        "The total is a water-balance residual. It aggregates soil "
        "evaporation, plant transpiration, interception loss and snow "
        "sublimation, and it cannot be decomposed into them.",
        "The component bands in this dataset carry swapped values in the "
        "source data, so any attempt to break the total down would be "
        "wrong. Use MOD16 for a component-aware evapotranspiration "
        "estimate.",
        "A negative value is condensation, most commonly dew or frost "
        "formation overnight. It is reported rather than removed, because "
        "hiding it would bias a subsequent water balance.",
        "The value is a period total. Dividing by the number of days gives "
        "a daily mean, which hides the strong day-to-day variability of "
        "evaporation.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return (ERA5_EVAPORATION_BAND,)

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        collection = (
            ee.ImageCollection(ERA5_DAILY)
            .filterDate(context.start_date, context.end_date)
            .filterBounds(context.geometry)
            .select([ERA5_EVAPORATION_BAND])
        )

        day_count = int(collection.size().getInfo())

        # Per-day spatial means, so the period total is a sum of real days
        # rather than a product of two averages that describe no day.
        def to_mean(image: Any) -> Any:
            day_mean = image.select([ERA5_EVAPORATION_BAND]).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=context.geometry,
                scale=ERA5_WORKING_SCALE,
                maxPixels=1e9,
                bestEffort=True,
            ).get(ERA5_EVAPORATION_BAND)
            return image.set("day_mean", day_mean)

        annotated = collection.map(to_mean)
        try:
            raw_days = annotated.aggregate_array("day_mean").getInfo()
        except Exception as exc:  # noqa: BLE001 - reported as insufficient
            logger.warning(
                "Could not read per-day ERA5 evaporation values: %s", exc
            )
            raw_days = None

        band_spec = dataset.band(ERA5_EVAPORATION_BAND)
        daily_mm: List[float] = []
        condensation_days = 0
        for record in raw_days or []:
            stored = band_spec.to_physical(record)
            converted = era5_evaporation_from_stored(stored)
            if converted is None:
                continue
            if converted < 0:
                condensation_days += 1
            daily_mm.append(converted)

        # Spatial statistics over the period, as a single reduction. This
        # gives the spread across the field rather than across time.
        period_mean = collection.mean()
        raw = period_mean.reduceRegion(
            reducer=build_reducer(ee),
            geometry=context.geometry,
            scale=ERA5_WORKING_SCALE,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()

        area_sq_m = context.option("area_sq_m")
        raw_stats = parse_reduction_result(
            raw or {},
            band=ERA5_EVAPORATION_BAND,
            total_pixel_count=estimate_pixel_count(
                area_sq_m, ERA5_WORKING_SCALE
            ),
            pixel_area_sq_m=pixel_area_sq_m(ERA5_WORKING_SCALE),
            band_spec=band_spec,
        )

        # Every statistic is negated, including min and max. Negation is
        # monotonic, so min becomes -max and max becomes -min. The spread
        # is unchanged and keeps its sign.
        def flip(value: Optional[float]) -> Optional[float]:
            return None if value is None else -value * 1000.0

        converted_stats = SpatialStats(
            mean=flip(raw_stats.mean),
            median=flip(raw_stats.median),
            min=flip(raw_stats.max),
            max=flip(raw_stats.min),
            std_dev=(
                None
                if raw_stats.std_dev is None
                else raw_stats.std_dev * 1000.0
            ),
            p10=flip(raw_stats.p90),
            p25=flip(raw_stats.p75),
            p75=flip(raw_stats.p25),
            p90=flip(raw_stats.p10),
            valid_pixel_count=raw_stats.valid_pixel_count,
            total_pixel_count=raw_stats.total_pixel_count,
            valid_area_sq_m=raw_stats.valid_area_sq_m,
        )

        quality = assess_quality(
            image_count=max(day_count, 1),
            coverage_percent=raw_stats.coverage_percent,
            valid_pixel_count=raw_stats.valid_pixel_count,
            thresholds=REANALYSIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=[ERA5_EVAPORATION_BAND],
            formula=(
                f"evaporation_mm = {ERA5_EVAPORATION_BAND} x (-1) x 1000. "
                f"{ERA5_EVAPORATION_SIGN_NOTE}"
            ),
            quality=quality,
            image_count=day_count,
            aggregation_method=(
                "negated per day, converted to millimetres, then summed "
                "over the period"
            ),
            extra_limitations=(
                "The stored value is negated, never made absolute and "
                "never clamped. Taking the absolute value would turn "
                "condensation into evaporation; clamping would delete "
                "every real evaporation event.",
                "The component bands of this quantity carry swapped values "
                "in the source data and are deliberately not read.",
            ),
            extra_caveats=(
                ERA5_EVAPORATION_SIGN_NOTE,
                (
                    "A positive result is evaporation from the surface. A "
                    "negative result is condensation onto it, typically "
                    "dew or frost."
                ),
            ),
        )

        if day_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No ERA5-Land days were available for the requested "
                    "period, so no evaporation total is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not daily_mm:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No valid per-day evaporation values could be read, so "
                    "no total is reported. Reporting zero would falsely "
                    "indicate a completely dry period."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        total = sum(daily_mm)
        warnings: List[str] = []
        if condensation_days:
            warnings.append(
                f"{condensation_days} of {len(daily_mm)} day(s) had net "
                "condensation rather than evaporation, which reduces the "
                "period total."
            )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        stats = SpatialStats(
            mean=total,
            min=min(daily_mm),
            max=max(daily_mm),
            valid_pixel_count=len(daily_mm),
            total_pixel_count=max(day_count, len(daily_mm)),
        )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=total,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )


class ERA5PotentialEvaporationMetric(Metric):
    """Deliberately not implemented. See the class docstring.

    The ERA5-Land band ``potential_evaporation_sum`` has no documented sign
    convention. The Earth Engine catalogue entry states the downward-
    positive convention explicitly for ``total_evaporation_sum`` and for
    the radiation bands, but is silent for this one. The band description
    says only that it is computed with vegetation set to crops/mixed
    farming and with no soil moisture stress assumed.

    An earlier version of the registry recorded the sign as *inferred*.
    Inferred is not good enough for a value that a user will read as a
    water deficit: if the convention were opposite, the sign of the
    reported deficit would be wrong and nothing in the output would reveal
    it.

    The metric is therefore registered as unavailable, and callers are
    directed to MOD16 potential evapotranspiration, whose sign convention
    is documented and whose units are unambiguous.
    """

    key = "era5_potential_evaporation"
    display_name = "Potential Evaporation (ERA5-Land)"
    display_name_fa = "تبخیر پتانسیل (ERA5-Land)"
    unit = "mm"
    domain = MetricDomain.WATER
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.MODELLED
    default_scale = ERA5_WORKING_SCALE
    description = (
        "Not produced. The ERA5-Land potential evaporation band has no "
        "documented sign convention, so the sign of any derived water "
        "deficit would be unverifiable."
    )
    limitations = (
        "The Earth Engine catalogue documents the downward-positive "
        "convention explicitly for total_evaporation_sum but not for "
        "potential_evaporation_sum.",
        "Without a documented convention, a derived water deficit could "
        "carry the wrong sign with no way to detect it from the output.",
        "Use the MOD16 potential evapotranspiration metric instead, whose "
        "units and sign are documented, while remembering that MOD16 PET "
        "is not reference evapotranspiration.",
    )

    unavailable_code = "no_documented_sign_convention"

    unavailable_reason = (
        "The ERA5-Land band potential_evaporation_sum has no documented "
        "sign convention. The catalogue states the downward-positive "
        "convention for total_evaporation_sum but is silent for this band, "
        "and an inferred convention is not a sufficient basis for a water "
        "deficit whose sign would be silently wrong if the inference were "
        "incorrect. No value is reported. Use the MOD16 potential "
        "evapotranspiration metric, whose sign and units are documented."
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("potential_evaporation_sum",)

    def compute(self, context: MetricContext) -> MetricResult:
        dataset = self.primary_dataset()

        # Quality is reported as unavailable rather than insufficient,
        # because no amount of additional data would resolve this. It is a
        # documentation gap, not a data gap.
        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["potential_evaporation_sum"],
            formula="not computed: sign convention undocumented",
            quality=QualityLevel.UNAVAILABLE,
            image_count=0,
            aggregation_method="not applicable",
        )

        return MetricResult.unavailable(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            # The specific code, not the generic default: a client
            # filtering on 'why is this missing?' needs the distinction
            # between 'unsupported' and the actual documented gap.
            reason=self.unavailable_code,
            message=self.unavailable_reason,
            unit=self.unit,
            provenance=provenance,
        )


# ==========================================================================
# 4. Indices that are NOT produced
# ==========================================================================

#: Why CWSI is not computed. This text is surfaced verbatim to users, so it
#: states the missing input precisely rather than saying "not available".
CWSI_UNAVAILABLE_REASON = (
    "The Crop Water Stress Index requires a crop water stress baseline: "
    "the canopy temperature of a well-watered, non-transpiring reference "
    "crop under the same atmospheric conditions as the field being "
    "assessed. That baseline is not supplied by any dataset this engine "
    "uses. Satellite thermal data provide a single land surface "
    "temperature per pixel, which mixes soil and canopy and cannot "
    "establish the lower and upper temperature bounds CWSI is defined "
    "against. Constructing those bounds from air temperature instead "
    "requires empirical, site-specific coefficients that have not been "
    "validated for this region, and would produce a number with the "
    "appearance of rigour that the inputs do not support. No value is "
    "reported."
)

#: Why WDI is not computed.
WDI_UNAVAILABLE_REASON = (
    "The Water Deficit Index requires the same temperature trapezoid as "
    "CWSI: a well-watered baseline and a fully stressed, non-transpiring "
    "baseline, together with a vegetation cover fraction to position the "
    "pixel within the trapezoid. The baselines require reference surfaces "
    "that are not present in the satellite record for a given field, and "
    "the cover fraction available from MODIS or Sentinel-2 is a different "
    "quantity from the fractional vegetation cover the trapezoid is "
    "defined against. Without validated baselines the index is "
    "unidentifiable for a specific field, so no value is reported."
)

#: Machine-readable reason codes, used by the API layer.
CWSI_UNAVAILABLE_CODE = "no_well_watered_baseline"
WDI_UNAVAILABLE_CODE = "no_temperature_trapezoid_baseline"


class _UnavailableMetric(Metric):
    """A metric that exists in the catalog but can never carry a value.

    Registering these is not padding. The catalog exists so that a user
    asking "can this system tell me about crop water stress?" receives an
    answer that says no and explains why, rather than receiving silence
    that could be mistaken for an oversight.

    The class makes the unavailability structural. ``compute`` cannot
    return a value, so no future change can accidentally turn one of these
    into a fabricated indicator without deleting this class.
    """

    domain = MetricDomain.WATER
    measurement_basis = MeasurementBasis.INFERENCE
    dataset_ids: Tuple[str, ...] = ()

    #: Text explaining precisely what input is missing.
    unavailable_reason: str = ""

    #: Machine-readable reason code.
    unavailable_code: str = "not_supported"

    def compute(self, context: MetricContext) -> MetricResult:
        provenance = None
        if self.dataset_ids:
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
            # The specific code, not the generic default: a client
            # filtering on 'why is this missing?' needs the distinction
            # between 'unsupported' and the actual documented gap.
            reason=self.unavailable_code,
            message=self.unavailable_reason,
            unit=self.unit,
            provenance=provenance,
        )

    def metadata(self) -> dict:
        metadata = super().metadata()
        metadata["available"] = False
        metadata["unavailable_code"] = self.unavailable_code
        metadata["unavailable_reason"] = self.unavailable_reason
        return metadata


class CWSIMetric(_UnavailableMetric):
    key = "cwsi"
    display_name = "Crop Water Stress Index (not produced)"
    display_name_fa = "شاخص تنش آبی گیاه (تولید نمی‌شود)"
    unit = "dimensionless"
    description = (
        "Not produced. CWSI requires a well-watered, non-transpiring "
        "canopy temperature baseline that the datasets in this engine "
        "cannot supply."
    )
    limitations = (
        "CWSI is defined between a lower bound (a well-watered crop at "
        "full transpiration) and an upper bound (a non-transpiring crop, "
        "usually taken as air temperature plus an aerodynamic offset).",
        "Neither bound is observable from a satellite. Both require "
        "reference surfaces at the field, or locally validated empirical "
        "coefficients.",
        "MODIS and Landsat thermal data give one land surface temperature "
        "per pixel, mixing soil and canopy. Over a partly vegetated field "
        "this is not a canopy temperature at all.",
        "Producing a proxy value here would create an agricultural "
        "indicator whose sign and magnitude are unverifiable, which is "
        "worse than reporting nothing.",
    )
    unavailable_reason = CWSI_UNAVAILABLE_REASON
    unavailable_code = CWSI_UNAVAILABLE_CODE


class WDIMetric(_UnavailableMetric):
    key = "wdi"
    display_name = "Water Deficit Index (not produced)"
    display_name_fa = "شاخص کمبود آب (تولید نمی‌شود)"
    unit = "dimensionless"
    description = (
        "Not produced. WDI requires the same temperature trapezoid as "
        "CWSI: a well-watered and a fully stressed baseline, plus a "
        "compatible vegetation cover fraction."
    )
    limitations = (
        "The WDI temperature trapezoid is anchored by a well-watered edge "
        "and a non-transpiring edge, neither of which is observable from "
        "the satellite record for a specific field.",
        "Positioning a pixel inside the trapezoid needs a fractional "
        "vegetation cover that matches the definition used to construct "
        "the trapezoid. The cover fractions available from MODIS or "
        "Sentinel-2 are different quantities.",
        "Without validated baselines the index is unidentifiable for a "
        "given field, so any number would be an artefact of the assumed "
        "baselines rather than a property of the field.",
    )
    unavailable_reason = WDI_UNAVAILABLE_REASON
    unavailable_code = WDI_UNAVAILABLE_CODE


# ==========================================================================
# Registration
# ==========================================================================

#: Water metrics that can produce a value.
#:
#: Note that ``evapotranspiration_cumulative`` is listed as well as the
#: per-period metrics. It reads the same band but answers a different
#: question, and the two are not redundant: the per-period value is a mean
#: composite and the cumulative value is a period total.
WATER_METRICS: Tuple[Metric, ...] = (
    NDWIMetric(),
    NDMIMetric(),
    MNDWIMetric(),
    EvapotranspirationMetric(),
    PotentialEvapotranspirationMetric(),
    CumulativeEvapotranspirationMetric(),
    ERA5EvaporationMetric(),
    ERA5PotentialEvaporationMetric(),
)

#: Metrics that are registered so the catalog can answer questions about
#: them, but that never carry a value.
UNAVAILABLE_WATER_METRICS: Tuple[Metric, ...] = (
    CWSIMetric(),
    WDIMetric(),
)

#: Everything this module contributes to the registry.
ALL_WATER_METRICS: Tuple[Metric, ...] = (
    WATER_METRICS + UNAVAILABLE_WATER_METRICS
)
