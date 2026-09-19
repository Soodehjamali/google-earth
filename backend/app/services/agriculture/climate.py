"""Climate and meteorology metrics.

All of these read from ERA5-Land daily aggregated reanalysis. That is a
modelled product at roughly 11 km resolution, so every metric here
declares itself as modelled and carries a caveat that it describes a
region rather than a field.

The ERA5 sign convention is the main hazard. The ECMWF convention treats
downward fluxes as positive, which means evaporation is stored as a
negative number. Presenting that directly would report negative
evaporation, which is physically meaningless.
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
    REANALYSIS_THRESHOLDS,
    assess_quality,
    describe_quality,
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
    "PrecipitationMetric",
    "TemperatureMaxMetric",
    "TemperatureMinMetric",
    "TemperatureMeanMetric",
    "VPDMetric",
    "RelativeHumidityMetric",
    "SolarRadiationMetric",
    "PARMetric",
    "WindSpeedMetric",
    "GDDMetric",
    "CLIMATE_METRICS",
]

ERA5_DAILY = "ECMWF/ERA5_LAND/DAILY_AGGR"

#: ERA5-Land is published on a 0.1 degree grid, approximately 11.1 km.
#: Reductions use a coarser working scale than the native grid to keep
#: request sizes sane; the provenance reports the native resolution.
ERA5_WORKING_SCALE = 11132


# --------------------------------------------------------------------------
# Shared reduction helper
# --------------------------------------------------------------------------


def _reduce_era5_band(
    context: MetricContext,
    ee_module: Any,
    band_name: str,
    scale: int = ERA5_WORKING_SCALE,
) -> Tuple[SpatialStats, int, List[float]]:
    """Reduce one ERA5 band over the geometry.

    Returns the aggregated statistics, the number of days in the
    collection, and the per-day spatial means.

    The per-day means matter for derived metrics: vapour pressure deficit
    and relative humidity must be computed from temperature and dewpoint
    *on the same day*, then averaged. Computing them from period-average
    temperatures would pair a warm day's temperature with a cool day's
    dewpoint and produce a value that describes no actual day.
    """
    collection = (
        ee_module.ImageCollection(ERA5_DAILY)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
        .select([band_name])
    )

    day_count = int(collection.size().getInfo())

    # Per-day spatial means, used by the derived metrics.
    #
    # The period statistics and the daily series are both derived from
    # this one collection, so they cannot disagree about which days were
    # used. Reducing each day to a single number also keeps the derived
    # maths in pure Python, where it can be unit tested.
    #
    # The day index is carried as a property so that the returned order
    # is the collection's own order rather than an artefact of mapping.
    daily_means = collection.map(
        lambda image: image.set(
            "day_mean",
            image.select([band_name]).reduceRegion(
                reducer=ee_module.Reducer.mean(),
                geometry=context.geometry,
                scale=scale,
                maxPixels=1e9,
                bestEffort=True,
            ).get(band_name),
        )
    )

    daily_values: List[float] = []
    try:
        records = daily_means.aggregate_array("day_mean").getInfo()
        for record in records or []:
            if record is None:
                continue
            try:
                numeric = float(record)
            except (TypeError, ValueError):
                continue
            if numeric == numeric:  # filters NaN
                daily_values.append(numeric)
    except Exception as exc:  # noqa: BLE001 - per-day values are optional
        logger.warning(
            "Could not read per-day values for %s: %s", band_name, exc
        )

    # Spatial statistics over the period, as a single reduction.
    period_mean_image = collection.mean()
    raw = period_mean_image.reduceRegion(
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
        # Applies the band's declared scale factor and offset so the
        # statistics are physical. ERA5 bands here are already in their
        # declared unit, so the conversion is the identity, but routing
        # through the spec means a band with a scale factor cannot be
        # silently read as raw counts.
        band_spec=get_dataset(ERA5_DAILY).band(band_name),
    )

    return stats, day_count, daily_values


class _ERA5Metric(Metric):
    """Common behaviour for metrics read directly from a single ERA5 band."""

    domain = MetricDomain.CLIMATE
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.MODELLED
    default_scale = ERA5_WORKING_SCALE

    #: ERA5 band to read.
    source_band: str = ""

    #: Unit before conversion, for the provenance record.
    source_unit: str = ""

    #: Conversion applied to the raw ERA5 values.
    conversion = "none"

    def convert(self, value: Optional[float]) -> Optional[float]:
        """Convert raw ERA5 units to the reported unit."""
        return value

    @property
    def source_bands(self) -> Tuple[str, ...]:
        """The single ERA5 band this metric reads."""
        return (self.source_band,)

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        stats, day_count, _ = _reduce_era5_band(
            context, ee, self.source_band
        )

        converted = self._convert_stats(stats)

        quality = assess_quality(
            image_count=max(day_count, 1),
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=REANALYSIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=[self.source_band],
            formula=self.formula,
            quality=quality,
            image_count=day_count,
            aggregation_method="time mean, then spatial mean",
            extra_limitations=self.extra_limitations,
        )

        if day_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No ERA5-Land days were available for the requested "
                    "period, so no value is reported."
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
                    "No valid pixels were returned for this area, so no "
                    "value is reported."
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

    def _convert_stats(self, stats: SpatialStats) -> SpatialStats:
        """Apply the unit conversion to every statistic."""
        converted = SpatialStats(
            mean=self.convert(stats.mean),
            median=self.convert(stats.median),
            min=self.convert(stats.min),
            max=self.convert(stats.max),
            std_dev=(
                None
                if stats.std_dev is None or self.conversion != "none"
                else stats.std_dev
            ),
            p10=self.convert(stats.p10),
            p25=self.convert(stats.p25),
            p75=self.convert(stats.p75),
            p90=self.convert(stats.p90),
            valid_pixel_count=stats.valid_pixel_count,
            total_pixel_count=stats.total_pixel_count,
            valid_area_sq_m=stats.valid_area_sq_m,
        )
        return converted

    @property
    def formula(self) -> str:
        return self.conversion

    @property
    def extra_limitations(self) -> Tuple[str, ...]:
        return ()


# --------------------------------------------------------------------------
# Direct ERA5 metrics
# --------------------------------------------------------------------------


class PrecipitationMetric(_ERA5Metric):
    key = "precipitation"
    display_name = "Precipitation"
    display_name_fa = "بارش"
    unit = "mm"
    source_band = "total_precipitation_sum"
    source_unit = "m"
    conversion = "millimetres = metres x 1000"
    description = (
        "Total precipitation accumulated over the requested period, from "
        "ERA5-Land reanalysis."
    )
    limitations = (
        "This is a modelled reanalysis value at roughly 11 km, not a rain "
        "gauge reading at the field.",
        "Convective rainfall is spatially uneven at scales far below the "
        "model grid, so a field total may differ substantially.",
        "The value is a period total, not a daily series. Request a shorter "
        "period for finer time resolution.",
    )

    def convert(self, value: Optional[float]) -> Optional[float]:
        return u.metres_to_millimetres(value)


class TemperatureMaxMetric(_ERA5Metric):
    key = "temperature_max"
    display_name = "Maximum Air Temperature"
    display_name_fa = "بیشینه دمای هوا"
    unit = "degC"
    source_band = "temperature_2m_max"
    source_unit = "K"
    conversion = "celsius = kelvin - 273.15"
    description = "Mean of daily maximum air temperature, from ERA5-Land."
    limitations = (
        "Modelled at roughly 11 km, not measured at the field.",
        "This is the mean of the daily maxima over the period, not the "
        "highest temperature recorded.",
        "Air temperature is measured in shade at 2 m; it is not canopy "
        "or leaf temperature.",
    )

    def convert(self, value: Optional[float]) -> Optional[float]:
        return u.kelvin_to_celsius(value)


class TemperatureMinMetric(_ERA5Metric):
    key = "temperature_min"
    display_name = "Minimum Air Temperature"
    display_name_fa = "کمینه دمای هوا"
    unit = "degC"
    source_band = "temperature_2m_min"
    source_unit = "K"
    conversion = "celsius = kelvin - 273.15"
    description = "Mean of daily minimum air temperature, from ERA5-Land."
    limitations = (
        "Modelled at roughly 11 km, not measured at the field.",
        "This is the mean of the daily minima over the period, not the "
        "lowest temperature recorded.",
        "Frost risk assessment requires the absolute minimum, which this "
        "does not provide.",
    )

    def convert(self, value: Optional[float]) -> Optional[float]:
        return u.kelvin_to_celsius(value)


class TemperatureMeanMetric(_ERA5Metric):
    key = "temperature_mean"
    display_name = "Mean Air Temperature"
    display_name_fa = "میانگین دمای هوا"
    unit = "degC"
    source_band = "temperature_2m"
    source_unit = "K"
    conversion = "celsius = kelvin - 273.15"
    description = "Mean air temperature at 2 m over the period."
    limitations = (
        "Modelled at roughly 11 km, not measured at the field.",
        "Air temperature at 2 m differs from temperature within the crop "
        "canopy, which can be several degrees warmer or cooler.",
    )

    def convert(self, value: Optional[float]) -> Optional[float]:
        return u.kelvin_to_celsius(value)


class WindSpeedMetric(Metric):
    key = "wind_speed"
    display_name = "Wind Speed"
    display_name_fa = "سرعت باد"
    unit = "m/s"
    domain = MetricDomain.CLIMATE
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = ERA5_WORKING_SCALE
    description = (
        "Wind speed at 10 m, derived as the magnitude of the eastward and "
        "northward wind components reported by ERA5-Land."
    )
    limitations = (
        "Modelled at roughly 11 km, and known to underestimate wind in "
        "complex terrain and over sheltered valleys.",
        "Wind at 10 m is not the wind experienced within a crop canopy, "
        "which is typically much lower and governs spray drift and "
        "pollination.",
        "A vector magnitude cannot be negative, so it carries no direction "
        "information.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("u_component_of_wind_10m", "v_component_of_wind_10m")

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        _, day_count, u_daily = _reduce_era5_band(
            context, ee, "u_component_of_wind_10m"
        )
        _, _, v_daily = _reduce_era5_band(
            context, ee, "v_component_of_wind_10m"
        )

        # Combine the two components on the same day. Reducing a single
        # component and calling it wind speed would understate the speed
        # whenever the flow is not purely eastward.
        daily_speed: List[float] = []
        paired = min(len(u_daily), len(v_daily))
        for index in range(paired):
            speed = u.wind_speed_from_components(
                u_daily[index], v_daily[index]
            )
            if speed is not None:
                daily_speed.append(speed)

        quality = assess_quality(
            image_count=max(day_count, 1),
            coverage_percent=100.0 if daily_speed else 0.0,
            valid_pixel_count=len(daily_speed),
            thresholds=REANALYSIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=[
                "u_component_of_wind_10m",
                "v_component_of_wind_10m",
            ],
            formula="speed = sqrt(u^2 + v^2)",
            quality=quality,
            image_count=day_count,
            aggregation_method="computed per day, then averaged over days",
            extra_limitations=(
                "Direction is not reported, because that would require a "
                "meteorological convention choice to be stated explicitly.",
            ),
        )

        if not daily_speed:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The wind components could not be paired for any day "
                    "in the requested period, so wind speed was not "
                    "computed. Reporting zero would falsely indicate "
                    "still air."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        mean_speed = sum(daily_speed) / len(daily_speed)
        stats = SpatialStats(
            mean=mean_speed,
            min=min(daily_speed),
            max=max(daily_speed),
            valid_pixel_count=len(daily_speed),
            total_pixel_count=max(day_count, len(daily_speed)),
        )

        warnings: List[str] = []
        missing_days = max(day_count, len(daily_speed)) - len(daily_speed)
        if missing_days > 0:
            warnings.append(
                f"{missing_days} of {max(day_count, len(daily_speed))} days "
                "could not be paired and were excluded, which may bias the "
                "mean."
            )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=mean_speed,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )


class SolarRadiationMetric(_ERA5Metric):
    key = "solar_radiation"
    display_name = "Solar Radiation"
    display_name_fa = "تابش خورشیدی"
    unit = "MJ/m2"
    source_band = "surface_solar_radiation_downwards_sum"
    source_unit = "J/m2"
    conversion = "megajoules = joules / 1e6"
    description = (
        "Downward shortwave solar radiation reaching the surface, "
        "accumulated over the period."
    )
    limitations = (
        "Modelled at roughly 11 km, with no account of local shading, "
        "slope aspect or terrain.",
        "This is a period accumulation, not a daily or hourly value.",
        "Cloud effects are represented at the model grid, not at the field.",
    )

    def convert(self, value: Optional[float]) -> Optional[float]:
        return u.joules_per_m2_to_megajoules(value)


# --------------------------------------------------------------------------
# Derived metrics
# --------------------------------------------------------------------------


class VPDMetric(Metric):
    key = "vpd"
    display_name = "Vapour Pressure Deficit"
    display_name_fa = "کمبود فشار بخار (VPD)"
    unit = "kPa"
    domain = MetricDomain.CLIMATE
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = ERA5_WORKING_SCALE
    description = (
        "Vapour pressure deficit in kilopascals. The atmospheric water "
        "demand, computed from temperature and dewpoint."
    )
    limitations = (
        "Derived from modelled temperature and dewpoint, so it inherits "
        "the reanalysis resolution of roughly 11 km.",
        "The Magnus approximation is accurate to about 0.1 percent over "
        "the range minus 40 to plus 50 degrees Celsius.",
        "VPD describes atmospheric demand, not soil water availability. "
        "A high VPD does not by itself indicate a water-stressed crop.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("temperature_2m", "dewpoint_temperature_2m")

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        _, day_count, temperature_daily = _reduce_era5_band(
            context, ee, "temperature_2m"
        )
        _, _, dewpoint_daily = _reduce_era5_band(
            context, ee, "dewpoint_temperature_2m"
        )

        # Pair temperature and dewpoint by day. Averaging them separately
        # first would pair one day's temperature with another day's
        # dewpoint and describe no real day.
        daily_vpd: List[float] = []
        paired = min(len(temperature_daily), len(dewpoint_daily))
        for index in range(paired):
            t_kelvin = temperature_daily[index]
            td_kelvin = dewpoint_daily[index]
            vpd = u.vapour_pressure_deficit(
                u.kelvin_to_celsius(t_kelvin),
                u.kelvin_to_celsius(td_kelvin),
            )
            if vpd is not None:
                daily_vpd.append(vpd)

        quality = assess_quality(
            image_count=max(day_count, 1),
            coverage_percent=100.0 if daily_vpd else 0.0,
            valid_pixel_count=len(daily_vpd),
            thresholds=REANALYSIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["temperature_2m", "dewpoint_temperature_2m"],
            formula=(
                "VPD = es(T) - ea(Td), where es = 0.6108 * "
                "exp(17.27 * T / (T + 237.3)) kPa"
            ),
            quality=quality,
            image_count=day_count,
            aggregation_method="computed per day, then averaged over days",
            extra_limitations=(
                "Computed per day before averaging. Averaging temperature "
                "and dewpoint separately first and then combining them "
                "would produce a value describing no actual day.",
            ),
        )

        if not daily_vpd:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Temperature and dewpoint could not be paired for any "
                    "day in the requested period, so VPD was not computed. "
                    "Reporting zero would falsely indicate no atmospheric "
                    "demand."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        mean_vpd = sum(daily_vpd) / len(daily_vpd)
        stats = SpatialStats(
            mean=mean_vpd,
            min=min(daily_vpd),
            max=max(daily_vpd),
            valid_pixel_count=len(daily_vpd),
            total_pixel_count=max(day_count, len(daily_vpd)),
        )

        warnings: List[str] = []
        missing_days = max(day_count, len(daily_vpd)) - len(daily_vpd)
        if missing_days > 0:
            warnings.append(
                f"{missing_days} of {max(day_count, len(daily_vpd))} days "
                "could not be paired and were excluded, which may bias the "
                "mean."
            )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=mean_vpd,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )


class RelativeHumidityMetric(Metric):
    key = "relative_humidity"
    display_name = "Relative Humidity"
    display_name_fa = "رطوبت نسبی"
    unit = "percent"
    domain = MetricDomain.CLIMATE
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = ERA5_WORKING_SCALE
    description = (
        "Relative humidity as a percentage, derived from modelled "
        "temperature and dewpoint."
    )
    limitations = (
        "ERA5-Land does not publish relative humidity directly, so this is "
        "derived rather than read from the source.",
        "Derived from modelled values at roughly 11 km, not measured at "
        "the field.",
        "Relative humidity rises as air cools even when the water content "
        "is unchanged, so it is a poor indicator of atmospheric demand. "
        "Vapour pressure deficit is the better measure for that purpose.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("temperature_2m", "dewpoint_temperature_2m")

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        _, day_count, temperature_daily = _reduce_era5_band(
            context, ee, "temperature_2m"
        )
        _, _, dewpoint_daily = _reduce_era5_band(
            context, ee, "dewpoint_temperature_2m"
        )

        daily_rh: List[float] = []
        paired = min(len(temperature_daily), len(dewpoint_daily))
        for index in range(paired):
            rh = u.relative_humidity_from_dewpoint(
                u.kelvin_to_celsius(temperature_daily[index]),
                u.kelvin_to_celsius(dewpoint_daily[index]),
            )
            if rh is not None:
                daily_rh.append(rh)

        quality = assess_quality(
            image_count=max(day_count, 1),
            coverage_percent=100.0 if daily_rh else 0.0,
            valid_pixel_count=len(daily_rh),
            thresholds=REANALYSIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["temperature_2m", "dewpoint_temperature_2m"],
            formula="RH = 100 * ea(Td) / es(T), Magnus with 0.6108 kPa",
            quality=quality,
            image_count=day_count,
            aggregation_method="computed per day, then averaged over days",
        )

        if not daily_rh:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Temperature and dewpoint could not be paired for any "
                    "day in the requested period, so relative humidity was "
                    "not computed."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        mean_rh = sum(daily_rh) / len(daily_rh)
        stats = SpatialStats(
            mean=mean_rh,
            min=min(daily_rh),
            max=max(daily_rh),
            valid_pixel_count=len(daily_rh),
            total_pixel_count=max(day_count, len(daily_rh)),
        )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=mean_rh,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
        )


class PARMetric(Metric):
    key = "par"
    display_name = "Photosynthetically Active Radiation (proxy)"
    display_name_fa = "تابش فعال فتوسنتزی (تقریبی)"
    unit = "MJ/m2"
    domain = MetricDomain.CLIMATE
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.PROXY
    default_scale = ERA5_WORKING_SCALE
    description = (
        "Photosynthetically active radiation, estimated as 45 percent of "
        "downward shortwave radiation."
    )
    limitations = (
        "This is a fixed-coefficient estimate, not a measurement of the "
        "400 to 700 nanometre waveband.",
        "The true PAR fraction varies with cloud cover, atmospheric "
        "composition, solar elevation and surface albedo. A single "
        "constant cannot represent all of those.",
        "Derived from modelled radiation at roughly 11 km.",
        "Named with a proxy suffix because it is an approximation, and it "
        "must not be presented as an observation of PAR.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("surface_solar_radiation_downwards_sum",)

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        stats, day_count, _ = _reduce_era5_band(
            context, ee, "surface_solar_radiation_downwards_sum"
        )

        converted = SpatialStats(
            mean=u.solar_radiation_to_par(
                u.joules_per_m2_to_megajoules(stats.mean)
            ),
            min=u.solar_radiation_to_par(
                u.joules_per_m2_to_megajoules(stats.min)
            ),
            max=u.solar_radiation_to_par(
                u.joules_per_m2_to_megajoules(stats.max)
            ),
            p10=u.solar_radiation_to_par(
                u.joules_per_m2_to_megajoules(stats.p10)
            ),
            p90=u.solar_radiation_to_par(
                u.joules_per_m2_to_megajoules(stats.p90)
            ),
            valid_pixel_count=stats.valid_pixel_count,
            total_pixel_count=stats.total_pixel_count,
            valid_area_sq_m=stats.valid_area_sq_m,
        )

        quality = assess_quality(
            image_count=max(day_count, 1),
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=REANALYSIS_THRESHOLDS,
        )
        if quality is QualityLevel.EXCELLENT:
            # An approximation can never be better than moderate. The
            # coefficient itself, not the data, is the limiting factor.
            quality = QualityLevel.MODERATE

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["surface_solar_radiation_downwards_sum"],
            formula=(
                "PAR = 0.45 * shortwave, where shortwave is converted from "
                "joules per square metre to megajoules"
            ),
            quality=quality,
            image_count=day_count,
            aggregation_method="time sum, spatial mean, then 0.45 coefficient",
        )

        if day_count == 0 or not converted.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No radiation data was available for the requested "
                    "period, so no proxy value is reported."
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
            warnings=[
                "This value is an approximation derived from a fixed "
                "coefficient, not a measurement of PAR.",
            ],
        )


class GDDMetric(Metric):
    key = "gdd"
    display_name = "Growing Degree Days"
    display_name_fa = "درجه-روز رشد (GDD)"
    unit = "degC-day"
    domain = MetricDomain.CLIMATE
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = ERA5_WORKING_SCALE
    description = (
        "Accumulated growing degree days over the requested period, from "
        "daily minimum and maximum temperature."
    )
    limitations = (
        "Uses the simple averaging method, which is what most published "
        "crop coefficient tables assume. Other methods exist and give "
        "different totals for the same weather.",
        "The base temperature is a parameter of the crop and its growth "
        "stage, not a universal constant. The value used is reported in "
        "the provenance; a default of 10 degrees Celsius is applied when "
        "none is supplied.",
        "Derived from modelled temperature at roughly 11 km, which smooths "
        "the extremes that drive accumulation.",
        "GDD describes heat accumulation. It does not predict a "
        "development stage without a crop-specific model.",
    )

    #: Default base temperature in degrees Celsius. Suited to warm-season
    #: crops. Callers should override it for the crop in question.
    base_temperature: float = 10.0

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("temperature_2m_min", "temperature_2m_max")

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        base = float(context.option("base_temperature", self.base_temperature))
        upper = context.option("upper_temperature")

        _, day_count, t_min_daily = _reduce_era5_band(
            context, ee, "temperature_2m_min"
        )
        _, _, t_max_daily = _reduce_era5_band(
            context, ee, "temperature_2m_max"
        )

        daily_gdd: List[float] = []
        paired = min(len(t_min_daily), len(t_max_daily))
        for index in range(paired):
            value = u.growing_degree_days(
                u.kelvin_to_celsius(t_min_daily[index]),
                u.kelvin_to_celsius(t_max_daily[index]),
                base_temperature_c=base,
                upper_temperature_c=(
                    float(upper) if upper is not None else None
                ),
            )
            if value is not None:
                daily_gdd.append(value)

        quality = assess_quality(
            image_count=max(day_count, 1),
            coverage_percent=100.0 if daily_gdd else 0.0,
            valid_pixel_count=len(daily_gdd),
            thresholds=REANALYSIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["temperature_2m_min", "temperature_2m_max"],
            formula=(
                f"GDD = max(0, ((Tmin + Tmax) / 2) - {base}), "
                "with temperatures in degrees Celsius"
            ),
            quality=quality,
            image_count=day_count,
            aggregation_method="computed per day, then summed over the period",
            extra_limitations=(
                f"Base temperature used: {base} degrees Celsius.",
                (
                    f"Upper temperature cap used: {float(upper)} degrees "
                    "Celsius, applied to both Tmin and Tmax."
                    if upper is not None
                    else "No upper temperature cap was applied, so hot days "
                    "accumulate without limit."
                ),
            ),
        )

        if not daily_gdd:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Temperature could not be paired for any day in the "
                    "requested period, so no accumulation is reported. "
                    "Reporting zero would falsely indicate no heat "
                    "accumulation."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        total = sum(daily_gdd)
        stats = SpatialStats(
            mean=total,
            min=min(daily_gdd),
            max=max(daily_gdd),
            valid_pixel_count=len(daily_gdd),
            total_pixel_count=max(day_count, len(daily_gdd)),
        )

        warnings: List[str] = []
        if len(daily_gdd) < max(day_count, len(daily_gdd)):
            missing = max(day_count, len(daily_gdd)) - len(daily_gdd)
            warnings.append(
                f"{missing} day(s) could not be computed and were excluded. "
                "The accumulation is therefore biased low."
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


#: Every climate metric, in catalog order.
CLIMATE_METRICS: Tuple[Metric, ...] = (
    PrecipitationMetric(),
    TemperatureMaxMetric(),
    TemperatureMinMetric(),
    TemperatureMeanMetric(),
    VPDMetric(),
    RelativeHumidityMetric(),
    SolarRadiationMetric(),
    PARMetric(),
    WindSpeedMetric(),
    GDDMetric(),
)
