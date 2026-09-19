"""Soil moisture metrics.

This module is about water in the soil, and the single most important
thing it does is keep three incompatible quantities apart:

======================  ==============  ===========================
Quantity                Unit            What it is
======================  ==============  ===========================
SMAP L3 soil moisture   m3/m3           Radiometer retrieval
SMAP L4 soil moisture   m3/m3           Assimilated land model
ERA5 soil water         m3/m3           Reanalysis land model
GLDAS soil moisture     kg/m2           Water mass per unit area
TerraClimate soil       mm              Depth-integrated water
SoilGrids retention     cm3/cm3         Static soil property
======================  ==============  ===========================

Those are not interchangeable. ``m3/m3`` is a volume fraction,
independent of how thick the layer is. ``kg/m2`` is a mass per unit area,
which depends on layer thickness, and converting it to a volume fraction
requires dividing by the layer depth and the water density. ``mm`` is a
depth of water, which is the mass per unit area expressed as a length.
Dividing one by the other without stating the layer thickness produces a
number with no physical meaning, so this module never does it.

What is measured and what is modelled
-------------------------------------
This distinction is not cosmetic and the code enforces it:

* :class:`SoilMoistureSurfaceMetric` reads the SMAP L3 **retrieval**. It
  is declared ``MeasurementBasis.PRODUCT`` because it is an agency science
  product, but its limitations state plainly that it is a radiometer
  retrieval at 9 km and not an in-situ measurement.
* :class:`SoilMoistureRootZoneERA5Metric` reads the ERA5-Land **land
  surface model**. It is declared ``MeasurementBasis.MODELLED`` and says
  so in the most direct words available.

A caller who puts the two side by side is comparing a satellite retrieval
with a model field, and the provenance of each says so.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
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
    assess_quality,
    describe_quality,
    decode_smap_retrieval_quality,
)
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    SpatialStats,
)

logger = get_logger(__name__)

__all__ = [
    "SoilMoistureSurfaceMetric",
    "SoilMoistureSurfaceEveningMetric",
    "SoilMoistureRootZoneMetric",
    "SoilMoistureRootZoneERA5Metric",
    "SoilMoistureWetnessMetric",
    "SOIL_METRICS",
    "SMAP_L3_CURRENT",
    "SMAP_L3_PREVIOUS",
    "SMAP_L4",
    "ERA5_DAILY",
    "SMAP_NATIVE_SCALE",
]


# ==========================================================================
# Dataset IDs and scales
# ==========================================================================

SMAP_L3_CURRENT = "NASA/SMAP/SPL3SMP_E/006"
SMAP_L3_PREVIOUS = "NASA/SMAP/SPL3SMP_E/005"
SMAP_L4 = "NASA/SMAP/SPL4SMGP/008"
ERA5_DAILY = "ECMWF/ERA5_LAND/DAILY_AGGR"

#: SMAP L3 is posted on a 9 km EASE-Grid; Earth Engine serves it on a
#: 9000 m pixel. Reducing at a finer scale would resample the grid and the
#: reported resolution would be a lie.
SMAP_NATIVE_SCALE = 9000

#: ERA5-Land is 0.1 degree, approximately 11.1 km.
ERA5_WORKING_SCALE = 11132

#: The ERA5-Land layer boundaries in centimetres, from the catalogue band
#: descriptions. Layer 3 (28-100 cm) is the deeper half of the 0-100 cm
#: root zone.
ERA5_LAYER_DEPTHS_CM = {
    1: (0.0, 7.0),
    2: (7.0, 28.0),
    3: (28.0, 100.0),
    4: (100.0, 289.0),
}


def _smap_dataset_id(start_date: str) -> Tuple[str, Optional[str]]:
    """Pick the SMAP L3 collection that actually covers a start date.

    The SMAP L3 product was split across two Earth Engine collections at
    2023-12-04. Requesting the v006 collection for an earlier date returns
    an empty collection rather than an error, which would be
    indistinguishable from a cloud-cover problem. Selecting the collection
    from the date avoids that.

    Returns ``(dataset_id, fallback_from)`` so the provenance can record
    that a fallback collection was used.
    """
    if start_date >= "2023-12-04":
        return SMAP_L3_CURRENT, None
    return SMAP_L3_PREVIOUS, None


# ==========================================================================
# SMAP L3 surface soil moisture — a satellite retrieval
# ==========================================================================


def _reduce_smap_l3(
    context: MetricContext,
    ee_module: Any,
    band_name: str,
    quality_band: str,
    dataset_id: str,
) -> Tuple[SpatialStats, int, dict]:
    """Reduce one SMAP L3 retrieval band, masked on its quality flag.

    The retrieval is masked to pixels where the quality flag says the
    retrieval was actually attempted. Pixels where it was skipped are
    removed rather than included, because those pixels hold a fill value
    that would otherwise enter the statistics as a very dry reading.

    Returns ``(stats, image_count, quality_counts)``.
    """
    collection = (
        ee_module.ImageCollection(dataset_id)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
    )

    image_count = int(collection.size().getInfo())

    def prepare(image: Any) -> Any:
        soil = image.select([band_name])
        flag = image.select([quality_band])
        # A retrieval exists only when bit 1 is clear. Bit 0 distinguishes
        # recommended from uncertain quality, which is handled through the
        # quality assessment rather than through masking, because an
        # uncertain retrieval is still a real observation.
        skipped = flag.bitwiseAnd(0b10).neq(0)
        return soil.updateMask(skipped.Not()).rename(band_name)

    prepared = collection.map(prepare)
    # Median across days for the same reason the vegetation metrics use
    # one: a single bad day should not drag the result.
    composite = prepared.median()

    raw = composite.reduceRegion(
        reducer=build_reducer(ee_module),
        geometry=context.geometry,
        scale=SMAP_NATIVE_SCALE,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()

    area_sq_m = context.option("area_sq_m")
    stats = parse_reduction_result(
        raw or {},
        band=band_name,
        total_pixel_count=estimate_pixel_count(area_sq_m, SMAP_NATIVE_SCALE),
        pixel_area_sq_m=pixel_area_sq_m(SMAP_NATIVE_SCALE),
        # SMAP stores volume fraction directly; the scale factor is 1.0.
        # Routing through the spec still matters, because it rejects the
        # product's fill values and any value it declares out of range.
        band_spec=get_dataset(dataset_id).band(band_name),
    )
    return stats, image_count, {}


class _SmapSurfaceMetric(Metric):
    """Surface soil moisture from the SMAP L3 radiometer retrieval."""

    domain = MetricDomain.SOIL
    unit = "m3/m3"
    dataset_ids = (SMAP_L3_CURRENT, SMAP_L3_PREVIOUS)
    measurement_basis = MeasurementBasis.PRODUCT
    default_scale = SMAP_NATIVE_SCALE

    #: Which overpass band to read.
    source_band: str = "soil_moisture_am"

    #: Which quality flag band pairs with it.
    quality_band: str = "retrieval_qual_flag_am"

    #: Whether this metric aggregates the recommended-quality pixels only.
    recommended_only: bool = False

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset_id, _ = _smap_dataset_id(context.start_date)
        dataset = get_dataset(dataset_id)

        stats, image_count, _ = _reduce_smap_l3(
            context, ee, self.source_band, self.quality_band, dataset_id
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
            bands=[self.source_band, self.quality_band],
            formula=(
                f"{self.source_band} volume fraction, masked to pixels where "
                f"{self.quality_band} indicates the retrieval was attempted"
            ),
            quality=quality,
            image_count=image_count,
            aggregation_method=(
                "per-pixel median across days, then spatial mean"
            ),
            extra_limitations=self.extra_limitations,
        )

        if image_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No SMAP retrieval scenes were available for the "
                    "requested period, so no soil moisture value is "
                    "reported. Reporting zero would falsely indicate a "
                    "completely dry soil."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not stats.has_values or quality is QualityLevel.INSUFFICIENT:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"{image_count} SMAP scene(s) were found, but after "
                    "removing pixels where the retrieval was skipped only "
                    f"{stats.valid_pixel_count} valid pixel(s) remained "
                    f"({stats.coverage_percent:.1f} percent coverage). This "
                    "commonly happens over frozen ground or over surfaces "
                    "the retrieval cannot handle. No value is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        # A volume fraction above about 0.6 is above the porosity of any
        # mineral soil, so it cannot be real. Report it rather than hide
        # it, because it signals a problem upstream.
        if stats.mean is not None and stats.mean > 0.6:
            warnings.append(
                f"Mean soil moisture {stats.mean:.3f} m3/m3 exceeds the "
                "porosity of mineral soil. This usually indicates a "
                "quality-flag or masking problem rather than a real "
                "surface condition."
            )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=stats.mean,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )

    @property
    def extra_limitations(self) -> Tuple[str, ...]:
        return ()


class SoilMoistureSurfaceMetric(_SmapSurfaceMetric):
    key = "soil_moisture_surface"
    display_name = "Surface Soil Moisture (morning overpass)"
    display_name_fa = "رطوبت خاک سطحی (گذر صبح)"
    source_band = "soil_moisture_am"
    quality_band = "retrieval_qual_flag_am"
    description = (
        "Volumetric soil moisture in the top 0 to 5 cm, retrieved by the "
        "SMAP L-band radiometer from the descending, morning overpass at "
        "approximately 06:00 local solar time."
    )
    limitations = (
        "This is a radiometer retrieval at 9 km per pixel. A single pixel "
        "covers thousands of hectares, so the value describes a district, "
        "not a field.",
        "It is a satellite retrieval, not an in-situ measurement. It is "
        "not interchangeable with a soil moisture probe reading.",
        "The retrieval only works over thawed, unfrozen ground. Frozen "
        "pixels are removed, which means the metric returns insufficient "
        "data for winter periods rather than a number.",
        "The L-band signal penetrates only the top few centimetres, so "
        "this describes the surface skin of the soil and not the root "
        "zone where a crop actually draws water.",
        "A morning retrieval describes the soil after overnight drainage. "
        "It does not represent the midday condition that drives "
        "evaporation.",
        "The value is a volume fraction, which is not comparable with a "
        "soil moisture product reported in kg/m2 or in millimetres without "
        "a documented conversion.",
    )
    extra_limitations = (
        "The retrieval quality flag is applied as a mask: pixels where the "
        "retrieval was skipped are removed. Flag bit 0 records whether the "
        "retained pixels were of recommended or merely uncertain quality; "
        "an uncertain retrieval is still a real observation and is kept.",
    )


class SoilMoistureSurfaceEveningMetric(_SmapSurfaceMetric):
    key = "soil_moisture_surface_evening"
    display_name = "Surface Soil Moisture (evening overpass)"
    display_name_fa = "رطوبت خاک سطحی (گذر عصر)"
    source_band = "soil_moisture_pm"
    quality_band = "retrieval_qual_flag_pm"
    description = (
        "Volumetric soil moisture in the top 0 to 5 cm, retrieved by the "
        "SMAP L-band radiometer from the ascending, evening overpass at "
        "approximately 18:00 local solar time."
    )
    limitations = (
        "This is a radiometer retrieval at 9 km per pixel, not a "
        "within-field measurement.",
        "It is a satellite retrieval, not an in-situ measurement.",
        "The retrieval only works over thawed, unfrozen ground.",
        "The L-band signal penetrates only the top few centimetres, so "
        "this is a surface value and not a root zone value.",
        "The evening retrieval is reported separately from the morning "
        "retrieval rather than averaged with it, because surface soil "
        "moisture has a strong diurnal cycle. Averaging the two would "
        "produce a value describing no actual time of day.",
    )
    extra_limitations = (
        "Compare this with the morning metric only with the diurnal cycle "
        "in mind. A difference between the two is a real drying signal, "
        "not noise.",
    )


# ==========================================================================
# Root zone — ERA5-Land, explicitly modelled
# ==========================================================================


class SoilMoistureRootZoneERA5Metric(Metric):
    """Root zone soil water from the ERA5-Land land surface model.

    This is a **model field**, not a measurement. The ECMWF land surface
    model integrates its own water balance, constrained by assimilated
    observations at scales far larger than a field, and reports the
    resulting soil water content for each of four soil layers.

    The metric is deliberately named and declared so that this cannot be
    overlooked: ``MeasurementBasis.MODELLED``, the display name carries
    "ERA5-Land", and the limitations open by stating that it is a model.
    """

    key = "soil_moisture_rootzone_era5"
    display_name = "Root Zone Soil Water (ERA5-Land model)"
    display_name_fa = "آب خاک ناحیه ریشه (مدل ERA5-Land)"
    unit = "m3/m3"
    domain = MetricDomain.SOIL
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.MODELLED
    default_scale = ERA5_WORKING_SCALE
    description = (
        "Volumetric soil water content of the 0 to 100 cm root zone, from "
        "the ERA5-Land reanalysis land surface model. Computed as the "
        "thickness-weighted mean of the model's layer 1, 2 and 3 values."
    )
    limitations = (
        "THIS IS A MODEL FIELD, NOT A MEASUREMENT. ERA5-Land is a "
        "reanalysis: a land surface model constrained by observations at "
        "a scale far coarser than a field. No instrument measured the "
        "soil water at this location.",
        "At roughly 11 km the model grid cell is far larger than an "
        "agricultural field. The value describes a region and cannot be "
        "attributed to one plot.",
        "The model's soil column has fixed hydraulic properties per grid "
        "cell. It does not know the actual soil texture, rooting depth or "
        "irrigation of the field being assessed.",
        "Irrigation is not represented. A model cell cannot know that a "
        "field was irrigated yesterday, so it will systematically "
        "understate soil water in irrigated areas and overstate drying.",
        "The value is a volume fraction for the whole 0 to 100 cm profile, "
        "which is a different quantity from the SMAP surface value for the "
        "top 5 cm. The two must not be compared as though they measured "
        "the same thing.",
        "It is aggregated across three layers of differing thickness. The "
        "provenance records the weights, because the result depends on "
        "them.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return (
            "volumetric_soil_water_layer_1",
            "volumetric_soil_water_layer_2",
            "volumetric_soil_water_layer_3",
        )

    @property
    def layer_weights(self) -> Tuple[float, float, float]:
        """Thickness of layers 1, 2 and 3 in centimetres.

        Layer 1 spans 0 to 7 cm, layer 2 spans 7 to 28 cm, and layer 3
        spans 28 to 100 cm. Together they are the 0 to 100 cm root zone
        the SMAP L4 product also reports.
        """
        depths = ERA5_LAYER_DEPTHS_CM
        return (
            depths[1][1] - depths[1][0],
            depths[2][1] - depths[2][0],
            depths[3][1] - depths[3][0],
        )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        layer_stats: List[Optional[SpatialStats]] = []
        day_count = 0

        for band_name in self.source_bands:
            collection = (
                ee.ImageCollection(ERA5_DAILY)
                .filterDate(context.start_date, context.end_date)
                .filterBounds(context.geometry)
                .select([band_name])
            )
            count = int(collection.size().getInfo())
            day_count = max(day_count, count)

            raw = collection.mean().reduceRegion(
                reducer=build_reducer(ee),
                geometry=context.geometry,
                scale=ERA5_WORKING_SCALE,
                maxPixels=1e9,
                bestEffort=True,
            ).getInfo()

            area_sq_m = context.option("area_sq_m")
            stats = parse_reduction_result(
                raw or {},
                band=band_name,
                total_pixel_count=estimate_pixel_count(
                    area_sq_m, ERA5_WORKING_SCALE
                ),
                pixel_area_sq_m=pixel_area_sq_m(ERA5_WORKING_SCALE),
                band_spec=dataset.band(band_name),
            )
            layer_stats.append(stats if stats.has_values else None)

        weights = self.layer_weights
        weight_total = sum(weights)

        def weighted_mean(attribute: str) -> Optional[float]:
            """Thickness-weighted mean of one statistic across layers."""
            numerator = 0.0
            denominator = 0.0
            for weight, stats in zip(weights, layer_stats):
                if stats is None:
                    continue
                value = getattr(stats, attribute, None)
                if value is None:
                    continue
                numerator += weight * value
                denominator += weight
            if denominator <= 0.0:
                return None
            return numerator / denominator

        combined = SpatialStats(
            mean=weighted_mean("mean"),
            median=weighted_mean("median"),
            min=weighted_mean("min"),
            max=weighted_mean("max"),
            p10=weighted_mean("p10"),
            p25=weighted_mean("p25"),
            p75=weighted_mean("p75"),
            p90=weighted_mean("p90"),
            valid_pixel_count=(
                layer_stats[0].valid_pixel_count
                if layer_stats and layer_stats[0] is not None
                else 0
            ),
            total_pixel_count=(
                layer_stats[0].total_pixel_count
                if layer_stats and layer_stats[0] is not None
                else 0
            ),
        )

        quality = assess_quality(
            image_count=max(day_count, 1),
            coverage_percent=combined.coverage_percent,
            valid_pixel_count=combined.valid_pixel_count,
            thresholds=REANALYSIS_THRESHOLDS,
        )

        weight_text = ", ".join(
            f"layer {index + 1} ({weights[index]:.0f} cm)"
            for index in range(len(weights))
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=list(self.source_bands),
            formula=(
                "root zone volumetric water = "
                "(7 * layer_1 + 21 * layer_2 + 72 * layer_3) / 100, "
                "weighted by layer thickness in centimetres"
            ),
            quality=quality,
            image_count=day_count,
            aggregation_method=(
                "thickness-weighted mean of the three ERA5-Land soil "
                "layers covering 0 to 100 cm, then spatial mean"
            ),
            extra_limitations=(
                f"Layer thickness weights used: {weight_text}. A different "
                "rooting depth would give a different answer.",
                "No ERA5 layer below 100 cm is included, because a root "
                "zone deeper than that is not a crop root zone.",
            ),
        )

        if day_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No ERA5-Land days were available for the requested "
                    "period, so no soil water value is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if combined.mean is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "None of the three ERA5-Land soil layers returned a "
                    "usable value for this area, so no root zone average "
                    "can be reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            "This value comes from a land surface model, not from an "
            "instrument. It cannot know about irrigation or local soil "
            "conditions at this field.",
        ]
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=combined.mean,
            unit=self.unit,
            stats=combined,
            provenance=provenance,
            warnings=warnings,
        )


class SoilMoistureRootZoneMetric(Metric):
    """Root zone soil moisture from the SMAP L4 assimilated model.

    This is distinct from both the SMAP L3 retrieval and the ERA5-Land
    model. SMAP L4 assimilates SMAP brightness temperature observations
    into a land surface model, so it is neither a pure retrieval nor a
    pure model field. That is recorded as its own measurement basis rather
    than being described as one or the other.

    **Important:** the L3 retrieval reads the top 0 to 5 cm only. It does
    not provide a root zone value, and this metric does not pretend that
    it does. The root zone product is a different SMAP dataset.
    """

    key = "soil_moisture_rootzone"
    display_name = "Root Zone Soil Moisture (SMAP L4 assimilated model)"
    display_name_fa = "رطوبت خاک ناحیه ریشه (SMAP L4)"
    unit = "m3/m3"
    domain = MetricDomain.SOIL
    dataset_ids = (SMAP_L4,)
    measurement_basis = MeasurementBasis.MODELLED
    default_scale = 11000
    description = (
        "Volumetric soil moisture of the 0 to 100 cm root zone, from the "
        "SMAP Level-4 product, which assimilates SMAP brightness "
        "temperature observations into a land surface model."
    )
    limitations = (
        "This is an ASSIMILATED MODEL product, not a retrieval. It blends "
        "satellite observations with a land surface model, so it is "
        "neither a measurement nor a pure simulation and must not be "
        "presented as either.",
        "It is NOT the same quantity as the SMAP L3 retrieval. The L3 "
        "retrieval covers only the top 0 to 5 cm; this covers 0 to 100 cm. "
        "The two are not comparable and are not expected to agree.",
        "At roughly 9 to 11 km the value describes a district, not a "
        "field.",
        "During SMAP instrument outages the product continues using land "
        "model output alone, with no assimilation. Documented outages "
        "include 2019-06-19 to 2019-07-23 and 2022-08-06 to 2022-09-20.",
        "The background model does not represent irrigation at field "
        "scale.",
        "The catalogue marks the additional geophysical fields of this "
        "product as research products that have not been validated. The "
        "soil moisture bands are the validated primary product, but the "
        "distinction is worth remembering.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("sm_rootzone",)

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        band_name = "sm_rootzone"

        collection = (
            ee.ImageCollection(SMAP_L4)
            .filterDate(context.start_date, context.end_date)
            .filterBounds(context.geometry)
            .select([band_name])
        )

        # The L4 product is 3-hourly. Averaging all steps within the
        # period gives a period mean, which is what a water balance needs.
        step_count = int(collection.size().getInfo())

        raw = collection.mean().reduceRegion(
            reducer=build_reducer(ee),
            geometry=context.geometry,
            scale=self.default_scale,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()

        area_sq_m = context.option("area_sq_m")
        stats = parse_reduction_result(
            raw or {},
            band=band_name,
            total_pixel_count=estimate_pixel_count(area_sq_m, self.default_scale),
            pixel_area_sq_m=pixel_area_sq_m(self.default_scale),
            band_spec=dataset.band(band_name),
        )

        quality = assess_quality(
            image_count=max(step_count, 1),
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=REANALYSIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=[band_name],
            formula=f"{band_name} volume fraction, mean over the period",
            quality=quality,
            image_count=step_count,
            aggregation_method=(
                "time mean of 3-hourly steps, then spatial mean"
            ),
            extra_limitations=(
                "This is an assimilated model product and cannot be "
                "compared with the SMAP L3 surface retrieval as though the "
                "two measured the same depth.",
            ),
        )

        if step_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No SMAP L4 timesteps were available for the requested "
                    "period, so no root zone value is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not stats.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"{step_count} SMAP L4 timestep(s) were found but no "
                    "valid pixels were returned for this area, so no value "
                    "is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            "This is an assimilated model estimate, not a measurement.",
        ]
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=stats.mean,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )


class SoilMoistureWetnessMetric(Metric):
    """Root zone relative saturation (wetness) from SMAP L4.

    This is **relative saturation**, not volumetric soil moisture. The
    two are different quantities and the distinction is the whole point
    of this metric:

    * volumetric soil moisture is a volume fraction, 0 to about 0.6 for
      mineral soil, and its ceiling depends on the soil's porosity;
    * relative saturation is dimensionless, runs 0 to 1, and is defined
      against the range between the driest and the fully saturated state
      *of that particular soil*.

    A wetness of 0.5 therefore means "halfway between air-dry and
    saturated" for this soil, not "0.5 m3/m3".

    Why this band rather than a SoilGrids normalisation
    ---------------------------------------------------
    A defensible wetness *could* be derived as
    ``(theta - wilting_point) / (field_capacity - wilting_point)`` using
    the SoilGrids retention assets. That derivation is not implemented
    here, because the two sides are not compatible as they stand:

    * ``theta`` from SMAP L4 is a 0 to 100 cm vertical average;
    * the SoilGrids retention bands are per depth interval (0-5, 5-15,
      15-30, 30-60, 60-100, 100-200 cm) and would have to be aggregated
      to 0-100 cm by thickness weighting before use;
    * SoilGrids is a static 250 m map, while theta is a 3-hourly 11 km
      model field, so the normalisation would divide a district-scale
      instantaneous value by a within-field static prediction;
    * the SoilGrids 33 kPa and 1500 kPa suctions are approximations to
      field capacity and wilting point, not measurements of them.

    Forcing that formula would produce a number that looks like a
    wetness but is not one. SMAP L4 publishes a wetness field computed
    by the product's own land surface model, so that is used instead and
    the derivation above is documented as declined.
    """

    key = "soil_moisture_wetness"
    display_name = "Root Zone Relative Saturation (SMAP L4 wetness)"
    display_name_fa = "اشباع نسبی ناحیه ریشه (SMAP L4)"
    unit = "fraction"
    domain = MetricDomain.SOIL
    dataset_ids = (SMAP_L4,)
    measurement_basis = MeasurementBasis.MODELLED
    default_scale = 11000
    description = (
        "Relative saturation of the 0 to 100 cm root zone, on a "
        "dimensionless 0 to 1 scale, from the SMAP Level-4 product. This "
        "is NOT volumetric soil moisture: 0 means air-dry and 1 means "
        "fully saturated for this soil."
    )
    limitations = (
        "This is RELATIVE SATURATION, not volumetric water content. A "
        "value of 0.5 means halfway between air-dry and saturated for "
        "this soil; it does not mean 0.5 m3/m3. The two must never be "
        "presented as the same quantity.",
        "The 0 to 1 scale is defined per soil by the underlying land "
        "surface model's own porosity and residual water content "
        "parameters. It is therefore comparable across time at one "
        "location, and only cautiously comparable between locations.",
        "This is an ASSIMILATED MODEL product, not a measurement. During "
        "SMAP instrument outages it continues on land model output alone. "
        "Documented outages include 2019-06-19 to 2019-07-23 and "
        "2022-08-06 to 2022-09-20.",
        "At roughly 9 to 11 km the value describes a district, not a "
        "field, and the model does not represent field-scale irrigation.",
        "It is a vertical average over 0 to 100 cm, so a dry surface over "
        "wet subsoil and a wet surface over dry subsoil can produce the "
        "same value.",
        "A SoilGrids-derived normalisation was considered and deliberately "
        "not implemented, because the depth support, the spatial scale "
        "and the static-versus-dynamic nature of the two inputs are not "
        "compatible without assumptions this engine will not make "
        "silently.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("sm_rootzone_wetness",)

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        band_name = "sm_rootzone_wetness"

        collection = (
            ee.ImageCollection(SMAP_L4)
            .filterDate(context.start_date, context.end_date)
            .filterBounds(context.geometry)
            .select([band_name])
        )

        step_count = int(collection.size().getInfo())

        raw = collection.mean().reduceRegion(
            reducer=build_reducer(ee),
            geometry=context.geometry,
            scale=self.default_scale,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()

        area_sq_m = context.option("area_sq_m")
        stats = parse_reduction_result(
            raw or {},
            band=band_name,
            total_pixel_count=estimate_pixel_count(area_sq_m, self.default_scale),
            pixel_area_sq_m=pixel_area_sq_m(self.default_scale),
            band_spec=dataset.band(band_name),
        )

        quality = assess_quality(
            image_count=max(step_count, 1),
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=REANALYSIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=[band_name],
            formula=(
                f"{band_name} relative saturation (dimensionless, 0 = "
                "air-dry to 1 = fully saturated), mean over the period"
            ),
            quality=quality,
            image_count=step_count,
            aggregation_method=(
                "time mean of 3-hourly steps, then spatial mean"
            ),
            extra_limitations=(
                "No conversion is applied. The band is already a "
                "dimensionless 0 to 1 relative saturation, so scaling it "
                "would be meaningless.",
                "A SoilGrids (theta - wilting point) / (field capacity - "
                "wilting point) derivation was evaluated and declined: the "
                "depth support, spatial scale and static-versus-dynamic "
                "nature of the inputs are not compatible.",
            ),
        )

        if step_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No SMAP L4 timesteps were available for the requested "
                    "period, so no relative saturation value is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not stats.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"{step_count} SMAP L4 timestep(s) were found but no "
                    "valid pixels were returned for this area, so no "
                    "relative saturation value is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            "This is RELATIVE SATURATION, not volumetric soil moisture. "
            "Do not read it as an m3/m3 value.",
            "This is an assimilated model estimate, not a measurement.",
        ]
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=stats.mean,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )


#: Every soil metric, in catalog order.
SOIL_METRICS: Tuple[Metric, ...] = (
    SoilMoistureSurfaceMetric(),
    SoilMoistureSurfaceEveningMetric(),
    SoilMoistureRootZoneMetric(),
    SoilMoistureRootZoneERA5Metric(),
    SoilMoistureWetnessMetric(),
)
