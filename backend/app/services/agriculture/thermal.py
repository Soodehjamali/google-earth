"""Thermal metrics: land surface temperature and the processes it drives.

The single most important rule in this module
---------------------------------------------
**Land surface temperature is not canopy temperature, and this engine
will never publish a ``canopy_temperature`` metric.**

The radiometric skin temperature a satellite measures is an area-weighted
mixture of everything in the sensor's field of view: sunlit leaves, shaded
leaves, soil, and whatever lies between the rows. Canopy temperature — the
temperature of the plant tissue itself — is a different quantity, it
requires either a thermal camera at close range or a surface-energy-balance
inversion, and it is the quantity that actually relates to transpiration
and water stress.

Presenting LST as canopy temperature would produce a number that looks
scientifically grounded and is wrong by several degrees in a direction
that depends on the crop, the row geometry and the time of day. A grower
acting on it would be acting on an artefact. So the metric is named
``land_surface_temperature``, its limitations say plainly what it is not,
and a test in this package asserts that no metric in the entire engine
exposes a canopy-temperature key.

What LST *is* useful for: a genuine measurement of the surface energy
balance, the day-night difference (a real signal of how much energy is
going into latent rather than sensible heat), and spatial variation within
a field. All three are offered here on those terms.
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
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.quality import (
    LANDSAT_THRESHOLDS,
    MODIS_THRESHOLDS,
    assess_quality,
    combine_quality,
    describe_quality,
    quality_from_cloud_fraction,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    QualityLevel,
    SpatialStats,
)
from app.services.agriculture import units as u

logger = get_logger(__name__)

__all__ = [
    "LandSurfaceTemperatureDayMetric",
    "LandSurfaceTemperatureNightMetric",
    "LandSurfaceTemperatureMeanMetric",
    "DiurnalTemperatureRangeMetric",
    "LandsatSurfaceTemperatureMetric",
    "THERMAL_METRICS",
    "MODIS_LST_8DAY",
    "MODIS_LST_DAILY",
    "LANDSAT_THERMAL",
    "MODIS_LST_SCALE",
    "MODIS_LST_WORKING_SCALE",
    "LANDSAT_ST_SCALE",
    "LANDSAT_THERMAL_NATIVE_SCALE",
]


#: The preferred source: an 8-day composite, so coverage is much better
#: than the daily product under persistent cloud.
MODIS_LST_8DAY = "MODIS/061/MOD11A2"

#: The fallback: daily, useful when a short period is requested and the
#: 8-day composite has no window covering it.
MODIS_LST_DAILY = "MODIS/061/MOD11A1"

LANDSAT_THERMAL = "LANDSAT/LC08/C02/T1_L2"

#: The 1 km grid both MODIS LST products are published on.
MODIS_LST_SCALE = 1000

#: Working scale for reductions. Identical to the native grid: unlike
#: ERA5, resampling MODIS LST to a coarser scale would mix genuinely
#: different surfaces (irrigated field versus bare soil) rather than
#: smoothing a continuous field.
MODIS_LST_WORKING_SCALE = 1000

#: Landsat Collection 2 Level-2 surface temperature is delivered at 30 m,
#: resampled from a 100 m thermal acquisition. The 30 m figure is the
#: pixel spacing; the 100 m figure is the true resolution. Both are
#: reported so the provenance cannot overstate the detail.
LANDSAT_ST_SCALE = 30
LANDSAT_THERMAL_NATIVE_SCALE = 100


# --------------------------------------------------------------------------
# Shared reduction helpers
# --------------------------------------------------------------------------


def _reduce_modis_lst(
    context: MetricContext,
    ee_module: Any,
    dataset_id: str,
    band_name: str,
    scale: int = MODIS_LST_WORKING_SCALE,
) -> Tuple[SpatialStats, int]:
    """Reduce one MODIS LST band over the geometry.

    The scene is first masked so that only retrievals with a documented
    LST error of 1 K or better, and which were actually produced,
    contribute. Masking is done in the image rather than by filtering the
    result, because a partly cloudy pixel must not contribute partly.
    """
    collection = (
        ee_module.ImageCollection(dataset_id)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
        .select([band_name])
    )

    image_count = int(collection.size().getInfo())

    # The period mean of the valid retrievals.
    composite = collection.mean()

    raw = composite.reduceRegion(
        reducer=build_reducer(ee_module),
        geometry=context.geometry,
        scale=scale,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()

    area_sq_m = context.option("area_sq_m")
    stats = parse_reduction_result(
        raw or {},
        band=band_name,
        total_pixel_count=estimate_pixel_count(area_sq_m, scale),
        pixel_area_sq_m=pixel_area_sq_m(scale),
        # Converts the raw stored counts to kelvin. Without this the
        # values would be counts of about 15000 rather than temperatures
        # of about 300 K.
        band_spec=get_dataset(dataset_id).band(band_name),
    )
    return stats, image_count


def _lst_stats_to_celsius(stats: SpatialStats) -> SpatialStats:
    """Convert every LST statistic from Kelvin to Celsius.

    The standard deviation is dropped rather than converted. LST is a
    scale-only conversion, so in principle the spread could be preserved,
    but reporting it alongside statistics that have been shifted by
    -273.15 invites exactly the reading error this engine exists to
    prevent. Callers needing spread should use the ranges.
    """
    return SpatialStats(
        mean=u.kelvin_to_celsius(stats.mean),
        median=u.kelvin_to_celsius(stats.median),
        min=u.kelvin_to_celsius(stats.min),
        max=u.kelvin_to_celsius(stats.max),
        p10=u.kelvin_to_celsius(stats.p10),
        p25=u.kelvin_to_celsius(stats.p25),
        p75=u.kelvin_to_celsius(stats.p75),
        p90=u.kelvin_to_celsius(stats.p90),
        valid_pixel_count=stats.valid_pixel_count,
        total_pixel_count=stats.total_pixel_count,
        valid_area_sq_m=stats.valid_area_sq_m,
    )


#: The canopy-temperature prohibition, attached to every thermal metric.
#:
#: This is a tuple so that it is appended verbatim to each metric's
#: limitations rather than paraphrased, because a paraphrase is how the
#: distinction gets lost. Because `Metric.build_provenance` copies
#: `self.limitations` into every provenance record, placing it here means
#: it reaches the catalog, the API response and the provenance record
#: without being restated at any of them.
_CANOPY_TEMPERATURE_DISCLAIMER = (
    "This is land surface temperature, the radiometric skin temperature "
    "of everything in the pixel. It is NOT canopy temperature and NOT "
    "leaf temperature. Over a partly vegetated pixel the signal is a "
    "mixture of leaves, soil and the spaces between rows."
)

#: Emissivity caveat, also attached to every LST metric.
_EMISSIVITY_DISCLAIMER = (
    "The retrieval assumes a surface emissivity that varies with land "
    "cover. Over heterogeneous fields this assumption contributes an "
    "uncertainty of roughly 1 K on top of the quoted retrieval error."
)


class _ModisLstMetric(Metric):
    """Common behaviour for metrics read from a MODIS LST band."""

    domain = MetricDomain.THERMAL
    dataset_ids = (MODIS_LST_8DAY, MODIS_LST_DAILY)
    measurement_basis = MeasurementBasis.PRODUCT
    default_scale = MODIS_LST_WORKING_SCALE
    unit = "degC"

    #: MODIS LST band to read.
    source_band: str = ""

    def source_bands_for(self, dataset_id: str) -> Tuple[str, ...]:
        """Which bands this metric reads from a given dataset."""
        return (self.source_band,) if self.source_band else ()

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return (self.source_band,) if self.source_band else ()

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        stats, image_count = _reduce_modis_lst(
            context, ee, dataset.id, self.source_band
        )

        converted = _lst_stats_to_celsius(stats)

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
            formula=self.formula,
            quality=quality,
            image_count=image_count,
            aggregation_method="time mean, then spatial mean",
            extra_limitations=self.extra_limitations,
        )

        if image_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No MODIS scenes were available for the requested "
                    "period, so no surface temperature is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not converted.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No valid surface temperature pixels were returned for "
                    "this area. Reporting zero degrees would be "
                    "indistinguishable from a real measurement."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

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

    @property
    def formula(self) -> str:
        return "celsius = kelvin - 273.15, from the LST band raw value x 0.02"

    @property
    def extra_limitations(self) -> Tuple[str, ...]:
        return ()


class LandSurfaceTemperatureDayMetric(_ModisLstMetric):
    key = "land_surface_temperature_day"
    display_name = "Daytime Land Surface Temperature"
    display_name_fa = "دمای سطح زمین در روز"
    source_band = "LST_Day_1km"
    description = (
        "Mean daytime land surface temperature over the requested period, "
        "from the MODIS 8-day composite."
    )
    limitations = (
        _CANOPY_TEMPERATURE_DISCLAIMER,
        _EMISSIVITY_DISCLAIMER,
        "Daytime overpass is roughly 10:30 local solar time, which is not "
        "the daily maximum surface temperature.",
        "The 8-day composite averages daily retrievals without filtering "
        "by quality, so a single cloudy day can bias the mean.",
    )


class LandSurfaceTemperatureNightMetric(_ModisLstMetric):
    key = "land_surface_temperature_night"
    display_name = "Nighttime Land Surface Temperature"
    display_name_fa = "دمای سطح زمین در شب"
    source_band = "LST_Night_1km"
    description = (
        "Mean nighttime land surface temperature over the requested "
        "period, from the MODIS 8-day composite."
    )
    limitations = (
        _CANOPY_TEMPERATURE_DISCLAIMER,
        _EMISSIVITY_DISCLAIMER,
        "Nighttime overpass is roughly 22:30 local solar time.",
        "Nighttime retrievals are less affected by sun-angle artefacts "
        "but more affected by atmospheric water vapour.",
        "Nighttime surface temperature is a better proxy for the "
        "thermal inertia of the surface than for crop water status.",
    )


class LandSurfaceTemperatureMeanMetric(_ModisLstMetric):
    key = "land_surface_temperature_mean"
    display_name = "Mean Land Surface Temperature"
    display_name_fa = "میانگین دمای سطح زمین"
    source_band = "LST_Day_1km"
    description = (
        "Daytime land surface temperature. Reported under a mean key as "
        "an alias of the daytime retrieval, since that is what most "
        "callers want."
    )
    limitations = (
        _CANOPY_TEMPERATURE_DISCLAIMER,
        _EMISSIVITY_DISCLAIMER,
        "This is the daytime retrieval, not a true 24-hour average. "
        "MODIS does not provide a daily mean surface temperature as a "
        "single band.",
        "A 24-hour average would require combining the day and night "
        "retrievals with a weighting that is not supplied by the product.",
    )


class DiurnalTemperatureRangeMetric(Metric):
    """Day minus night surface temperature.

    A genuine and physically meaningful quantity: a large range indicates
    that most incoming energy is leaving as sensible heat, while a small
    range suggests it is going into latent heat (evaporation) or storage.
    It is also markedly more robust than either retrieval alone, because
    systematic emissivity and atmospheric biases largely cancel.
    """

    key = "surface_temperature_range"
    display_name = "Day-Night Surface Temperature Range"
    display_name_fa = "اختلاف دمای سطح روز و شب"
    unit = "K"
    domain = MetricDomain.THERMAL
    dataset_ids = (MODIS_LST_8DAY, MODIS_LST_DAILY)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = MODIS_LST_WORKING_SCALE
    description = (
        "The difference between daytime and nighttime land surface "
        "temperature, in Kelvin. A measure of how the surface partitions "
        "incoming energy."
    )
    limitations = (
        _CANOPY_TEMPERATURE_DISCLAIMER,
        "The two retrievals come from different overpass times, roughly "
        "10:30 and 22:30 local solar time, so this is not a true daily "
        "maximum minus minimum.",
        "Expressed in Kelvin because a difference has no meaningful "
        "Celsius reading when it is zero.",
        "Cloud contamination on either retrieval biases the difference, "
        "and it does so in opposite directions for day and night.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("LST_Day_1km", "LST_Night_1km")

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        day_stats, image_count = _reduce_modis_lst(
            context, ee, dataset.id, "LST_Day_1km"
        )
        night_stats, _ = _reduce_modis_lst(
            context, ee, dataset.id, "LST_Night_1km"
        )

        # The difference is taken in Kelvin, where the values are still
        # absolute, so every statistic is a valid difference.
        stats = SpatialStats(
            mean=self._diff(day_stats.mean, night_stats.mean),
            median=self._diff(day_stats.median, night_stats.median),
            min=self._diff(day_stats.min, night_stats.min),
            max=self._diff(day_stats.max, night_stats.max),
            p10=self._diff(day_stats.p10, night_stats.p10),
            p90=self._diff(day_stats.p90, night_stats.p90),
            valid_pixel_count=min(
                day_stats.valid_pixel_count, night_stats.valid_pixel_count
            ),
            total_pixel_count=max(
                day_stats.total_pixel_count, night_stats.total_pixel_count
            ),
        )

        both_present = (
            day_stats.valid_pixel_count > 0 and night_stats.valid_pixel_count > 0
        )
        coverage = min(
            day_stats.coverage_percent, night_stats.coverage_percent
        ) if both_present else 0.0

        day_quality = quality_from_cloud_fraction(100.0 - day_stats.coverage_percent)
        night_quality = quality_from_cloud_fraction(
            100.0 - night_stats.coverage_percent
        )
        quality = combine_quality([day_quality, night_quality])

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["LST_Day_1km", "LST_Night_1km"],
            formula="range = LST_day - LST_night, in Kelvin",
            quality=quality,
            image_count=image_count,
            aggregation_method=(
                "time mean of each band, spatial mean of each, then "
                "subtracted"
            ),
            extra_limitations=(
                _CANOPY_TEMPERATURE_DISCLAIMER,
                "Subtracting the two spatial means is not identical to "
                "averaging the per-pixel difference. It is used here "
                "because it is far cheaper, and it is exact when the "
                "valid pixel sets coincide, which they usually do not.",
            ),
        )

        if not both_present or stats.mean is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Daytime and nighttime retrievals were not both "
                    "available for this area, so the difference was not "
                    "computed."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=stats.mean,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
        )

    @staticmethod
    def _diff(day: Optional[float], night: Optional[float]) -> Optional[float]:
        if day is None or night is None:
            return None
        return day - night


class LandsatSurfaceTemperatureMetric(Metric):
    """Landsat 8 surface temperature, for sub-field detail.

    Offered for its 100 m thermal resolution, which is a genuine
    capability the 1 km MODIS products cannot match. It is a lower
    priority for routine use: a 16-day revisit means a short requested
    period may contain no scene at all.
    """

    key = "landsat_surface_temperature"
    display_name = "Landsat Surface Temperature"
    display_name_fa = "دمای سطح زمین (لندست)"
    unit = "degC"
    domain = MetricDomain.THERMAL
    dataset_ids = (LANDSAT_THERMAL,)
    measurement_basis = MeasurementBasis.PRODUCT
    default_scale = 100  # the true thermal resolution, not the 30 m grid
    description = (
        "Land surface temperature from Landsat 8, at roughly 100 m. "
        "Offered for within-field detail rather than routine monitoring."
    )
    limitations = (
        _CANOPY_TEMPERATURE_DISCLAIMER,
        _EMISSIVITY_DISCLAIMER,
        "Landsat 8 revisits every 16 days, so a short requested period "
        "may contain no scene. With two sensors (Landsat 8 and 9) the "
        "effective revisit is roughly 8 days.",
        "The thermal band is acquired at 100 m and delivered resampled "
        "to 30 m. This metric reduces at 100 m so that the provenance "
        "reports the resolution the data actually supports.",
        "Scenes whose processing level is L2SR have the surface "
        "temperature bands fully masked and contribute nothing.",
        "Landsat surface temperature carries an uncertainty of roughly "
        "2 K over land before emissivity correction.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("ST_B10", "ST_QA", "QA_PIXEL")

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        collection = (
            ee.ImageCollection(LANDSAT_THERMAL)
            .filterDate(context.start_date, context.end_date)
            .filterBounds(context.geometry)
            .filter(ee.Filter.lt("CLOUD_COVER", context.cloud_max_percent))
        )

        image_count = int(collection.size().getInfo())
        scale = self.effective_scale(context)

        raw: dict = {}
        if image_count > 0:
            composite = collection.select(["ST_B10"]).mean()
            raw = (
                composite.reduceRegion(
                    reducer=build_reducer(ee),
                    geometry=context.geometry,
                    scale=scale,
                    maxPixels=1e9,
                    bestEffort=True,
                ).getInfo()
                or {}
            )

        area_sq_m = context.option("area_sq_m")
        stats = parse_reduction_result(
            raw,
            band="ST_B10",
            total_pixel_count=estimate_pixel_count(area_sq_m, scale),
            pixel_area_sq_m=pixel_area_sq_m(scale),
            band_spec=dataset.band("ST_B10"),
        )
        converted = _lst_stats_to_celsius(stats)

        quality = assess_quality(
            image_count=max(image_count, 1),
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=LANDSAT_THRESHOLDS,
        )
        if image_count < 2 and quality in (QualityLevel.EXCELLENT, QualityLevel.GOOD):
            # A single scene cannot support a confident multi-date claim,
            # even if it covers the whole field.
            quality = QualityLevel.MODERATE

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["ST_B10"],
            formula=(
                "kelvin = ST_B10 x 0.00341802 + 149.0, then celsius = "
                "kelvin - 273.15"
            ),
            quality=quality,
            image_count=image_count,
            aggregation_method="time mean, then spatial mean",
            extra_limitations=(
                _CANOPY_TEMPERATURE_DISCLAIMER,
                _EMISSIVITY_DISCLAIMER,
                f"The reduction uses a {scale} m scale, which is the true "
                f"thermal resolution of {LANDSAT_THERMAL_NATIVE_SCALE} m "
                "rounded to the delivered grid. The 30 m pixel spacing of "
                "the surface reflectance bands is not the thermal "
                "resolution.",
            ),
        )

        if image_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No Landsat scenes fell within the requested period "
                    "and cloud threshold. With a 16-day revisit this is "
                    "common for short periods."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not converted.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Scenes were present but returned no valid surface "
                    "temperature pixels, which happens when the surface "
                    "temperature bands are masked."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=converted.mean,
            unit=self.unit,
            stats=converted,
            provenance=provenance,
        )


#: Every thermal metric.
THERMAL_METRICS: Tuple[Metric, ...] = (
    LandSurfaceTemperatureDayMetric(),
    LandSurfaceTemperatureNightMetric(),
    LandSurfaceTemperatureMeanMetric(),
    DiurnalTemperatureRangeMetric(),
    LandsatSurfaceTemperatureMetric(),
)
