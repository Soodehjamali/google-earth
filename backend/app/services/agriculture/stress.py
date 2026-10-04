"""Crop water and environmental stress indicators (Phase K).

This module is a **derived layer**. It computes stress indicators by
combining inputs that earlier phases already verified against their
sources, and it does not recompute any of them:

* vegetation indices and NDMI are published by ``vegetation.py`` and
  ``water.py`` (Phase C / Phase F),
* ET and PET are published by ``water.py`` from MOD16 (Phase F),
* root-zone soil moisture is published by ``soil.py`` from SMAP L4
  (Phase F),
* field capacity, wilting point and available water capacity are
  published by ``soil_properties.py`` from SoilGrids (Phase J),
* land surface temperature is published by ``thermal.py`` from MOD11A2
  (Phase E),
* VPD is published by ``climate.py`` from ERA5-Land (Phase D).

Every stress metric here reaches those products through the *same*
reduction helpers the publishing metrics use, so the numbers cannot
drift from the ones the engine already publishes under their own keys.
No input is recomputed and no input's unit conversion is reapplied.

Scientific boundary
-------------------
These metrics **describe** environmental or vegetation conditions. They
do not identify a cause:

* low NDVI does not prove disease,
* high LST does not prove water stress,
* low soil moisture does not prove irrigation failure,
* high VPD does not prove crop damage.

An indicator is therefore labelled a vegetation-stress indicator, a
water-stress indicator, a thermal-stress indicator, an
atmospheric-demand indicator or an environmental-stress context. The
module never converts an indicator into a diagnosis, and it introduces
no threshold whose crop applicability cannot be verified.

Temporal alignment
------------------
Combining measurements from different dates silently is the main way a
derived layer manufactures results. Every metric here therefore states
its alignment rule, and each rule is one of two defensible kinds:

1. **Same composites by construction.** ET and PET come from one MOD16
   collection filtered once, so the two series describe the same
   composite periods. Nothing needs to be matched.
2. **Dynamic measurement against a static container, or against the same
   product's own history.** Soil moisture moves and field capacity does
   not; the SMAP observation defines the analysis time and SoilGrids
   supplies the static reference. The LST and VPD anomalies compare a
   requested window with the *same product, same geometry, same calendar
   window* in preceding years, so no cross-dataset assumption enters the
   comparison at all.

Where no defensible alignment exists the metric is not published.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

from app.core.logging import get_logger
from app.services.agriculture.aggregation import (
    build_reducer,
    estimate_pixel_count,
    parse_reduction_result,
    pixel_area_sq_m,
)
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.climate import (
    ERA5_DAILY,
    ERA5_WORKING_SCALE,
    _reduce_era5_band,
)
from app.services.agriculture.quality import (
    MODIS_THRESHOLDS,
    REANALYSIS_THRESHOLDS,
    assess_quality,
    combine_quality,
    describe_quality,
)
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.soil import SMAP_L4
from app.services.agriculture.soil_properties import (
    ROOT_ZONE_INTERVALS,
    ROOT_ZONE_LAYER_THICKNESSES_CM,
    SOILGRIDS,
    SOILGRIDS_SCALE,
    SOILGRIDS_WV0033,
    SOILGRIDS_WV1500,
    SOIL_STATIC_THRESHOLDS,
    _layer_band,
    _profile_quality,
    _reduce_soilgrids_layers,
    combine_layer_stats,
)
from app.services.agriculture.thermal import (
    MODIS_LST_8DAY,
    MODIS_LST_WORKING_SCALE,
    _lst_stats_to_celsius,
    _reduce_modis_lst,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    SpatialStats,
)
from app.services.agriculture.units import (
    kelvin_to_celsius,
    vapour_pressure_deficit,
)
from app.services.agriculture.water import (
    MOD16_GAPFILLED,
    MOD16_NRT,
    MOD16_SCALE,
    _reduce_mod16,
    _resolve_mod16_dataset,
)

logger = get_logger(__name__)

__all__ = [
    # Anomaly framework
    "AnomalyRecord",
    "shift_window_years",
    "baseline_windows",
    "summarise_baseline",
    "compute_anomaly",
    "percentile_of_value",
    "percentile_value",
    # Metrics
    "EvaporativeFractionMetric",
    "SoilWaterContentRatioMetric",
    "PlantAvailableWaterFractionMetric",
    "VPDAnomalyMetric",
    "VPDHighDurationMetric",
    "LSTDayAnomalyMetric",
    "LSTDayPercentileMetric",
    "CompositeStressMetric",
    "STRESS_METRICS",
    "UNAVAILABLE_STRESS_METRICS",
    "ALL_STRESS_METRICS",
]


# ==========================================================================
# Constants
# ==========================================================================

#: SMAP L4 root-zone soil moisture is published at an 11 km pixel. The
#: derived soil-water metrics reduce at this scale because SMAP is always
#: the coarsest input; reducing at SoilGrids' 250 m would resample the
#: coarse grid and then report the finer figure as the result's
#: resolution, which would be false.
SMAP_L4_SCALE = 11000

#: How many preceding years the LST anomaly gathers as its baseline. The
#: window is long enough to span the El Nino / La Nina cycle's typical
#: two to seven years, so a single anomalous year does not become the
#: reference, and short enough that a long-run climate trend does not
#: make the oldest years unrepresentative of the current regime.
LST_ANOMALY_BASELINE_YEARS = 10

#: Fewer contributing baseline years than this and the anomaly is not
#: published: two reference years cannot separate a genuine anomaly from
#: ordinary interannual variability.
LST_ANOMALY_MIN_YEARS = 3

#: A percentile needs a population, and a population of fewer than this
#: many same-window values resolves the rank only in coarse steps. The
#: metric refuses rather than reporting a rank computed from too few
#: references to mean anything.
LST_PERCENTILE_MIN_SAMPLES = 8

#: The VPD baseline is shorter than the LST one because each baseline
#: year costs two ERA5-Land collections (temperature and dewpoint), and
#: five years already gives a defensible interannual reference.
VPD_ANOMALY_BASELINE_YEARS = 5
VPD_ANOMALY_MIN_YEARS = 3

#: The high-VPD duration threshold is the 90th percentile of the pooled
#: same-window daily VPD distribution from the baseline years. It is a
#: *relative* threshold drawn from the local climatological record, not
#: an absolute kPa value: an absolute threshold would need crop
#: applicability this engine cannot verify.
VPD_HIGH_DURATION_BASELINE_YEARS = 5
VPD_HIGH_DURATION_PERCENTILE = 90.0
VPD_HIGH_DURATION_MIN_SAMPLES = 30
VPD_HIGH_DURATION_MIN_YEARS = 3

#: A "same calendar window in preceding years" baseline is only defined
#: for a request shorter than a year. A longer request would overlap its
#: own baseline windows, and the anomaly would then partly measure the
#: period against itself.
MAX_ANOMALY_WINDOW_DAYS = 366

_STRESS_DISCLAIMER = (
    "This is an environmental indicator. It describes a condition, it does "
    "not identify its cause, and it is not a diagnosis of disease, pest, "
    "nutrient status or irrigation failure."
)


# ==========================================================================
# A reusable anomaly framework
# ==========================================================================


@dataclass(frozen=True)
class AnomalyRecord:
    """An anomaly and the baseline it was taken against.

    Every field is published because an anomaly without its baseline is
    an uninterpretable number: "+2.3 degC" means nothing unless the
    reader also knows which years, which statistic and how many
    observations defined the reference.
    """

    #: The value observed for the requested period.
    value: float

    #: The baseline the value is compared with.
    baseline: float

    #: ``value`` minus ``baseline``.
    anomaly: float

    #: The statistic used over the baseline population, e.g.
    #: "mean of per-year window means".
    baseline_statistic: str

    #: How many baseline years actually contributed. Fewer than the
    #: requested count means some years had no usable data.
    observation_count: int

    #: Human description of the reference period, e.g.
    #: "same calendar window in 2015-2024".
    baseline_period: str


def shift_window_years(
    start: date, end: date, years_back: int
) -> Tuple[date, date]:
    """Move a date window back by a whole number of years.

    The window is defined by month and day rather than by an offset in
    days, so it stays the same calendar window each year. A window whose
    start day does not exist in the target year — the 29th of February
    in a non-leap year — is folded onto the last valid day of that
    month, which shortens that one baseline window by a day rather than
    discarding the year. The rule is deterministic and is stated in the
    provenance of every metric that uses it.

    Raises :class:`ValueError` if ``years_back`` is not positive, because
    a non-positive shift would produce a window that is not in the past.
    """
    if years_back <= 0:
        raise ValueError(
            f"years_back must be a positive number of years, got {years_back}"
        )

    def shift_day(day: date, month: int, day_of_month: int) -> date:
        try:
            return date(day.year, month, day_of_month)
        except ValueError:
            # Only reachable for a day that does not exist in this month
            # of this year: the 29th of February in a non-leap year. The
            # last valid day of the month is the closest in-calendar date.
            if month == 2 and day_of_month == 29:
                return date(day.year, 2, 28)
            raise

    new_start = shift_day(
        date(start.year - years_back, 1, 1), start.month, start.day
    )
    new_end = shift_day(
        date(end.year - years_back, 1, 1), end.month, end.day
    )
    return new_start, new_end


def baseline_windows(
    start: date,
    end: date,
    n_years: int,
) -> List[Tuple[int, date, date]]:
    """The preceding same-calendar windows used as a historical baseline.

    Returns one ``(years_back, window_start, window_end)`` entry per
    preceding year, from the most recent backwards. Each entry is a real
    calendar window of the same month-day span as the request.
    """
    if start > end:
        return []
    return [
        (years_back, *shift_window_years(start, end, years_back))
        for years_back in range(1, n_years + 1)
    ]


def summarise_baseline(
    values: Sequence[Optional[float]],
    statistic: str = "mean",
) -> Optional[float]:
    """Reduce the per-baseline-year values to one reference number.

    ``None`` entries are excluded rather than treated as zero, so a year
    with no usable data lowers the population but cannot pull the
    baseline toward zero. Returns ``None`` when nothing contributed.
    """
    usable = [v for v in values if v is not None and math.isfinite(v)]
    if not usable:
        return None
    if statistic == "median":
        return float(np.median(usable))
    return float(sum(usable) / len(usable))


def compute_anomaly(
    value: Optional[float],
    baseline_values: Sequence[Optional[float]],
    statistic: str = "mean",
) -> Optional[AnomalyRecord]:
    """Subtract a baseline from a value, recording what the baseline is.

    Returns ``None`` when the value is missing or no baseline year
    contributed, which the caller reports as insufficient data rather
    than as a zero anomaly. A zero anomaly is a real statement
    ("indistinguishable from the reference") and must never be produced
    by the absence of a baseline.
    """
    if value is None or not math.isfinite(value):
        return None
    contributing = [v for v in baseline_values if v is not None]
    baseline = summarise_baseline(contributing, statistic)
    if baseline is None:
        return None
    return AnomalyRecord(
        value=float(value),
        baseline=float(baseline),
        anomaly=float(value) - float(baseline),
        baseline_statistic=(
            f"{statistic} of per-year window means"
        ),
        observation_count=len(contributing),
        baseline_period="",
    )


def _percentile_samples(
    values: Sequence[Optional[float]],
) -> List[float]:
    """The finite, non-null members of a candidate percentile population."""
    return [
        float(v)
        for v in values
        if v is not None and isinstance(v, (int, float)) and math.isfinite(v)
    ]


def percentile_of_value(
    value: Optional[float],
    population: Sequence[Optional[float]],
    min_samples: int,
) -> Optional[float]:
    """Where a value sits within a reference population, as a percentile.

    Uses the linear-interpolation method (numpy's default), the same
    convention as the rest of the engine's percentile reporting. The
    population is the reference only; the value itself is **not** a
    member of it, so the result ranks the observation against the
    reference rather than against itself.

    Returns ``None`` when the value is missing, the population has fewer
    than ``min_samples`` usable members, or the population is degenerate
    (all members identical). A degenerate population would report every
    value as either the 0th or the 100th percentile depending on the
    sign of an undefined difference, so it is refused instead.

    This is a percentile of a stated reference population, not a min-max
    normalisation and not a probability.
    """
    if value is None or not math.isfinite(value):
        return None
    samples = _percentile_samples(population)
    if len(samples) < max(min_samples, 1):
        return None
    if len(set(samples)) == 1:
        return None
    return float((np.array(samples) < value).mean() * 100.0)


def percentile_value(
    population: Sequence[Optional[float]],
    percentile: float,
    min_samples: int,
) -> Optional[float]:
    """The value at a given percentile of a reference population.

    Used to draw a *relative* threshold from the climatological record
    instead of asserting an absolute one. Returns ``None`` when the
    population is too small, so a caller can never receive a threshold
    computed from too few observations to support it.
    """
    samples = _percentile_samples(population)
    if len(samples) < max(min_samples, 1):
        return None
    if not 0.0 <= percentile <= 100.0:
        return None
    return float(np.percentile(samples, percentile))


# ==========================================================================
# Shared Earth Engine helpers
# ==========================================================================


def _shift_context(
    context: MetricContext, start: date, end: date
) -> MetricContext:
    """Re-issue a context over a different date window.

    Geometry, scale, cloud tolerance and options are carried across
    unchanged, so a baseline reduction uses exactly the same spatial
    treatment as the requested-period reduction. That equality is what
    makes the two comparable.
    """
    return replace(
        context,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )


def _reduce_smap_rootzone(
    context: MetricContext, ee_module: Any
) -> Tuple[SpatialStats, int]:
    """Reduce the SMAP L4 root-zone band over the geometry.

    This reads the same verified band as
    :class:`app.services.agriculture.soil.SoilMoistureRootZoneMetric`,
    through the same registry band spec, so the reduction applies the
    band's conversion exactly once and reports the same quantity that
    the soil module publishes under ``soil_moisture_rootzone``.
    """
    dataset = get_dataset(SMAP_L4)
    band_name = "sm_rootzone"

    collection = (
        ee_module.ImageCollection(SMAP_L4)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
        .select([band_name])
    )
    step_count = int(collection.size().getInfo())

    raw = collection.mean().reduceRegion(
        reducer=build_reducer(ee_module),
        geometry=context.geometry,
        scale=SMAP_L4_SCALE,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()

    stats = parse_reduction_result(
        raw or {},
        band=band_name,
        total_pixel_count=estimate_pixel_count(
            context.option("area_sq_m"), SMAP_L4_SCALE
        ),
        pixel_area_sq_m=pixel_area_sq_m(SMAP_L4_SCALE),
        band_spec=dataset.band(band_name),
    )
    return stats, step_count


def _missing_layer_name(exc: KeyError) -> Optional[str]:
    """Extract a SoilGrids depth interval from a band-select KeyError.

    The band-select error lists the missing bands first and the available
    ones after an ``it has`` separator; only the former may be named as
    the gap. The first such interval in
    :data:`ROOT_ZONE_INTERVALS` order is returned so the refusal message
    names the shallowest gap, matching what ``_profile_quality`` would
    report for an empty reduction.
    """
    text = " ".join(str(arg) for arg in exc.args)
    head = text.split("it has", 1)[0]
    found = re.findall(r"val_(\d+_\d+)cm_mean", head)
    if not found:
        found = re.findall(r"val_(\d+_\d+)cm_mean", text)
    if not found:
        return None
    for depth, _ in ROOT_ZONE_INTERVALS:
        if depth in found:
            return depth
    return found[0]


def _soilgrids_rootzone_mean(
    context: MetricContext,
    ee_module: Any,
    asset_id: str,
) -> Tuple[Optional[SpatialStats], Optional[str]]:
    """Reduce a SoilGrids retention asset to one 0-100 cm root-zone value.

    Uses the same layered reduction, thickness weights and profile
    completeness rule as the Phase J retention metrics, so the field
    capacity and wilting point used here are the same numbers
    ``soil_field_capacity`` and ``soil_wilting_point`` publish.

    Returns ``(combined_stats, missing_layer)``. A missing layer is
    reported by its interval name so the caller can name it in the
    refusal message; the caller refuses rather than re-weighting over
    the surviving layers, which would describe a shallower column than
    the result claims.
    """
    bands = [_layer_band(depth) for depth, _ in ROOT_ZONE_INTERVALS]
    try:
        layer_stats, _total_pixels = _reduce_soilgrids_layers(
            context, ee_module, asset_id, bands
        )
    except KeyError as exc:
        # A layer missing from the asset's band list cannot be re-weighted
        # over the survivors; that would describe a shallower column than
        # the result claims. Name the layer so the caller can refuse.
        missing = _missing_layer_name(exc)
        return None, missing
    quality, missing = _profile_quality(layer_stats, 0)
    if missing is not None or quality is QualityLevel.INSUFFICIENT:
        return None, missing
    combined = combine_layer_stats(
        [layer_stats[_layer_band(depth)] for depth, _ in ROOT_ZONE_INTERVALS],
        ROOT_ZONE_LAYER_THICKNESSES_CM,
    )
    if not combined.has_values:
        return None, None
    return combined, None


def _daily_vpd_series(
    context: MetricContext, ee_module: Any
) -> Tuple[List[float], int]:
    """Per-day spatial-mean VPD over the context's window.

    Temperature and dewpoint are paired **on the same day** before the
    deficit is formed, exactly as the climate module's VPD metric does.
    Averaging the two series separately first would pair one day's
    temperature with another day's dewpoint and produce a deficit
    describing no real day.
    """
    _, day_count, temperature_daily = _reduce_era5_band(
        context, ee_module, "temperature_2m"
    )
    _, _, dewpoint_daily = _reduce_era5_band(
        context, ee_module, "dewpoint_temperature_2m"
    )

    daily_vpd: List[float] = []
    paired = min(len(temperature_daily), len(dewpoint_daily))
    for index in range(paired):
        vpd = vapour_pressure_deficit(
            kelvin_to_celsius(temperature_daily[index]),
            kelvin_to_celsius(dewpoint_daily[index]),
        )
        if vpd is not None:
            daily_vpd.append(vpd)
    return daily_vpd, day_count


def _vpd_quality(
    daily_vpd: Sequence[float], day_count: int
) -> QualityLevel:
    """Quality verdict for one VPD reduction."""
    return assess_quality(
        image_count=max(day_count, 1),
        coverage_percent=100.0 if daily_vpd else 0.0,
        valid_pixel_count=len(daily_vpd),
        thresholds=REANALYSIS_THRESHOLDS,
    )


def _window_label(start: date, end: date) -> str:
    """A compact, unambiguous label for a baseline window."""
    if start.year == end.year:
        return f"{start.isoformat()} to {end.isoformat()}"
    return f"{start.isoformat()} to {end.isoformat()}"


def _baseline_label(
    windows: Sequence[Tuple[int, date, date]],
    contributed_years: int,
) -> str:
    """Describe the reference period in a provenance-readable way."""
    if not windows:
        return "no baseline window was defined"
    years = sorted({w[1].year for w in windows} | {w[2].year for w in windows})
    return (
        f"same calendar window in {years[0]}-{years[-1]} "
        f"({contributed_years} of {len(windows)} years contributed)"
    )


# ==========================================================================
# 1. Water-stress indicators
# ==========================================================================


class EvaporativeFractionMetric(Metric):
    """Evaporative fraction: the ratio of actual to potential ET.

    .. math::

        EF = \\frac{\\overline{ET}}{\\overline{PET}}

    Both inputs are the period mean of the same MOD16 8-day composite
    product, read from **one** collection filtered once, so ET and PET
    describe the same composite periods by construction and no
    cross-dataset alignment is involved. Both are already in
    millimetres per composite period after the single declared scale
    factor of 0.1 has been applied by the shared reduction helper, so
    the ratio is dimensionless and no unit conversion is reapplied here.

    Values near 1 indicate that evapotranspiration is close to the
    atmospheric demand, which is consistent with ample water supply;
    values near 0 indicate that actual ET falls well short of demand,
    which is consistent with a limited water supply. This is a
    water-balance indicator and not a diagnosis of what is limiting.
    """

    key = "evaporative_fraction"
    display_name = "Evaporative Fraction (ET/PET)"
    display_name_fa = "کسری تبخیر (ET/PET)"
    unit = "fraction"
    domain = MetricDomain.STRESS
    dataset_ids = (MOD16_GAPFILLED, MOD16_NRT)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = MOD16_SCALE
    description = (
        "Ratio of actual to potential evapotranspiration from the MODIS "
        "MOD16 product. Values close to 1 are consistent with ample water "
        "supply; values well below 1 are consistent with a limited supply. "
        "This is a water-balance indicator, not a diagnosis of cause."
    )
    limitations = (
        _STRESS_DISCLAIMER,
        "ET and PET are both means of 8-day composite sums, so the ratio "
        "describes a composite window rather than a single day. It must "
        "not be read as a daily observation.",
        "MOD16 is a model-derived product, not a measurement, and the "
        "algorithm performs poorly over sparse vegetation and arid "
        "surfaces, which includes much of Iran.",
        "At 500 m the value describes a district rather than a single "
        "field.",
        "The MOD16 product's own potential ET is not reference ET and "
        "must not be substituted for it.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("ET", "PET")

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset_id, fallback_from = _resolve_mod16_dataset(context)
        dataset = get_dataset(dataset_id)

        et_stats, et_count, _ = _reduce_mod16(context, ee, dataset_id, "ET")
        pet_stats, _, _ = _reduce_mod16(context, ee, dataset_id, "PET")

        quality = combine_quality(
            [
                assess_quality(
                    image_count=max(et_count, 1),
                    coverage_percent=et_stats.coverage_percent,
                    valid_pixel_count=et_stats.valid_pixel_count,
                    thresholds=MODIS_THRESHOLDS,
                ),
                assess_quality(
                    image_count=max(et_count, 1),
                    coverage_percent=pet_stats.coverage_percent,
                    valid_pixel_count=pet_stats.valid_pixel_count,
                    thresholds=MODIS_THRESHOLDS,
                ),
            ]
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["ET", "PET"],
            formula="EF = mean(ET) / mean(PET)",
            quality=quality,
            image_count=et_count,
            aggregation_method=(
                "mean of 8-day composite sums per band from one filtered "
                "MOD16 collection, then ratio of the two means"
            ),
            fallback_from=fallback_from,
            extra_limitations=(
                "ET and PET are read from the same collection filtered by "
                "the same dates, so the two series describe the same "
                "composite periods. No nearest-date matching is involved "
                "and none is needed.",
            ),
            extra_caveats=(
                "Both inputs are means of MOD16 8-day composite sums, so "
                "the ratio inherits the composite window rather than a "
                "daily timestep.",
                "The ratio is computed from period means. A per-composite "
                "ratio then averaged would weight short composites equally "
                "with full ones, which is a different and non-equivalent "
                "aggregation.",
                "A PET mean at or below zero is reported as insufficient "
                "rather than producing an undefined ratio.",
            ),
        )

        if et_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"No {dataset.name} composites were available for the "
                    "requested period, so the ratio is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not et_stats.has_values or not pet_stats.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "ET or PET returned no valid pixels for this area, so "
                    "the ratio is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        et_value = et_stats.mean
        pet_value = pet_stats.mean
        if et_value is None or pet_value is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "ET or PET has no mean value, so the ratio is not "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if pet_value <= 0.0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The potential ET mean is {pet_value:.3f} mm per "
                    "composite period, which is not a positive denominator, "
                    "so the ratio is undefined and is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        value = et_value / pet_value

        warnings: List[str] = []
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))
        if fallback_from is not None:
            warnings.append(
                "The gap-filled MOD16 product was unavailable for this "
                "period, so the near real-time product was used instead. It "
                "is not gap-filled and has lower effective coverage."
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


class SoilWaterContentRatioMetric(Metric):
    """Root-zone soil moisture as a fraction of field capacity.

    .. math::

        ratio = \\frac{SM_{rootzone}}{FC_{rootzone}}

    The numerator is the period mean of the SMAP L4 root-zone
    volumetric water content (0-100 cm). The denominator is the
    SoilGrids field capacity over the same 0-100 cm interval, reduced
    with the same layered, thickness-weighted computation as
    ``soil_field_capacity``, so the container and the level describe
    the same soil column.

    Temporal alignment: SMAP L4 is dynamic and SoilGrids is a static
    modelled surface, so the alignment rule is that the SMAP observation
    defines the analysis time and SoilGrids supplies a time-invariant
    reference. No nearest-date matching between the two is involved,
    and none would be meaningful for a static product.

    Values near 1 indicate that the root zone sits near field capacity;
    values well below 1 indicate it sits well below it. This is a
    soil-water-status indicator. A low value does not prove the crop is
    stressed, because root depth, extraction pattern and irrigation all
    intervene.
    """

    key = "soil_water_content_ratio"
    display_name = "Soil Water Content / Field Capacity Ratio"
    display_name_fa = "نسبت محتوای آب خاک به ظرفیت زراعی"
    unit = "fraction"
    domain = MetricDomain.STRESS
    dataset_ids = (SMAP_L4, SOILGRIDS)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = SMAP_L4_SCALE
    description = (
        "Root-zone soil moisture (SMAP L4, 0-100 cm) as a fraction of the "
        "SoilGrids field capacity over the same interval. A value near 1 "
        "means the root zone sits near field capacity. This is a "
        "soil-water-status indicator, not a plant-stress diagnosis."
    )
    limitations = (
        _STRESS_DISCLAIMER,
        "SMAP L4 is an assimilated model product at roughly 11 km, not a "
        "retrieval and not a field measurement.",
        "Field capacity is approximated by the SoilGrids water content at "
        "33 kPa, a static modelled prediction. The 33 kPa convention is a "
        "poorer approximation in coarse or structured soils.",
        "The metric is limited by its coarsest input: SMAP at roughly "
        "11 km versus SoilGrids at 250 m, so the reduction runs at the "
        "SMAP scale and no 250 m detail is claimed.",
        "This describes soil water status relative to a static container, "
        "not plant water stress, and it does not distinguish the cause of "
        "a dry root zone.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("sm_rootzone",) + tuple(
            _layer_band(depth) for depth, _ in ROOT_ZONE_INTERVALS
        )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        sm_dataset = get_dataset(SMAP_L4)

        sm_stats, step_count = _reduce_smap_rootzone(context, ee)
        fc_stats, fc_missing = _soilgrids_rootzone_mean(
            context, ee, SOILGRIDS_WV0033
        )

        quality = combine_quality(
            [
                assess_quality(
                    image_count=max(step_count, 1),
                    coverage_percent=sm_stats.coverage_percent,
                    valid_pixel_count=sm_stats.valid_pixel_count,
                    thresholds=REANALYSIS_THRESHOLDS,
                ),
                assess_quality(
                    image_count=1,
                    coverage_percent=(
                        fc_stats.coverage_percent if fc_stats else 0.0
                    ),
                    valid_pixel_count=(
                        fc_stats.valid_pixel_count if fc_stats else 0
                    ),
                    thresholds=SOIL_STATIC_THRESHOLDS,
                ),
            ]
        )

        provenance = self.build_provenance(
            context=context,
            dataset=sm_dataset,
            bands=list(self.source_bands),
            formula=(
                "ratio = mean(sm_rootzone, SMAP L4) / "
                "thickness-weighted mean(theta(33 kPa), SoilGrids)"
            ),
            quality=quality,
            image_count=step_count,
            aggregation_method=(
                "time mean of the SMAP L4 3-hourly steps; thickness-weighted "
                "spatial mean of the five SoilGrids 0-100 cm layers; the "
                "ratio is formed from the two reduced means"
            ),
            extra_limitations=(
                "Temporal alignment: the SMAP L4 observation defines the "
                "analysis time and SoilGrids supplies a time-invariant "
                "reference, so no cross-dataset date matching is involved.",
                "Spatial alignment: the ratio is computed at the SMAP L4 "
                "scale after Earth Engine resamples the 250 m SoilGrids "
                "grid to the coarser SMAP grid. The result's spatial detail "
                "is limited by SMAP.",
            ),
            extra_caveats=(
                "The ratio is formed from two already-reduced means in "
                "physical units (m3/m3 over cm3/cm3); no scale factor is "
                "reapplied at this layer.",
                f"Inputs: SMAP root-zone mean = "
                f"{sm_stats.mean if sm_stats.mean is not None else 'n/a'} "
                f"m3/m3; SoilGrids field capacity = "
                f"{fc_stats.mean if fc_stats and fc_stats.mean is not None else 'n/a'} "
                f"cm3/cm3.",
            ),
        )

        if step_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No SMAP L4 timesteps were available for the requested "
                    "period, so the ratio is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if fc_missing is not None or fc_stats is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The {fc_missing.replace('_', '-')} cm SoilGrids layer "
                    "returned no usable prediction for this area, so a "
                    "0-100 cm field capacity cannot be computed and the "
                    "ratio is refused rather than computed against a "
                    "shallower column."
                )
                if fc_missing is not None
                else (
                    "The SoilGrids field capacity reduction returned no "
                    "usable prediction for this area, so the ratio is not "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not sm_stats.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The SMAP L4 root-zone reduction returned no valid "
                    "pixels for this area, so the ratio is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        sm_value = sm_stats.mean
        fc_value = fc_stats.mean
        if sm_value is None or fc_value is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Soil moisture or field capacity has no mean value, so "
                    "the ratio is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if fc_value <= 0.0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The field capacity mean is {fc_value:.4f} cm3/cm3, "
                    "which is not a positive denominator, so the ratio is "
                    "undefined and is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        value = sm_value / fc_value

        warnings: List[str] = [
            "The two inputs have different native resolutions (SMAP L4 "
            "roughly 11 km, SoilGrids 250 m). The ratio is computed at the "
            "SMAP scale and is limited by it."
        ]
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=value,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )


class PlantAvailableWaterFractionMetric(Metric):
    """Plant-available water fraction of the root zone.

    .. math::

        PAF = \\frac{SM - WP}{FC - WP}

    All three terms are root-zone (0-100 cm) quantities. ``SM`` is the
    SMAP L4 period mean in m3/m3; ``FC`` and ``WP`` are the
    thickness-weighted SoilGrids predictions at 33 kPa and 1500 kPa in
    cm3/cm3, reduced exactly as ``soil_field_capacity`` and
    ``soil_wilting_point`` reduce them.

    A value of 0 means the root zone sits at the wilting-point
    prediction and a value of 1 means it sits at field capacity. Values
    outside ``[0, 1]`` are reported, not clipped: they mean the SMAP
    state sits outside the SoilGrids retention range for this soil,
    which is information about the two products' disagreement rather
    than an impossible measurement.

    The denominator is the available water capacity, so a soil whose
    predicted field capacity does not exceed its wilting point has no
    defined available-water range and the metric is refused.
    """

    key = "plant_available_water_fraction"
    display_name = "Plant Available Water Fraction"
    display_name_fa = "کسری آب قابل‌دسترس گیاه"
    unit = "fraction"
    domain = MetricDomain.STRESS
    dataset_ids = (SMAP_L4, SOILGRIDS)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = SMAP_L4_SCALE
    description = (
        "Root-zone soil moisture normalised by the plant-available water "
        "range (wilting point to field capacity), all over the 0-100 cm "
        "interval. 0 means the soil sits at the wilting-point prediction, 1 "
        "means it sits at field capacity. This is a soil-water-status "
        "indicator, not a plant-stress diagnosis."
    )
    limitations = (
        _STRESS_DISCLAIMER,
        "Field capacity and wilting point are the SoilGrids predictions at "
        "33 kPa and 1500 kPa. Both suctions are conventional surrogates "
        "rather than exact properties, and the approximation is poorer in "
        "coarse or structured soils.",
        "SMAP L4 is an assimilated model product at roughly 11 km and does "
        "not represent irrigation at field scale.",
        "Different crops have different rooting depths and extraction "
        "patterns, so a single available-water fraction says nothing about "
        "a specific crop's water status.",
        "All three inputs are required. If any one is missing the metric is "
        "refused rather than computed from the remaining two.",
        "The metric is limited by its coarsest input (SMAP, roughly 11 km); "
        "no SoilGrids 250 m detail is claimed.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("sm_rootzone",) + tuple(
            _layer_band(depth) for depth, _ in ROOT_ZONE_INTERVALS
        )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        sm_dataset = get_dataset(SMAP_L4)

        sm_stats, step_count = _reduce_smap_rootzone(context, ee)
        fc_stats, fc_missing = _soilgrids_rootzone_mean(
            context, ee, SOILGRIDS_WV0033
        )
        wp_stats, wp_missing = _soilgrids_rootzone_mean(
            context, ee, SOILGRIDS_WV1500
        )

        sm_quality = assess_quality(
            image_count=max(step_count, 1),
            coverage_percent=sm_stats.coverage_percent,
            valid_pixel_count=sm_stats.valid_pixel_count,
            thresholds=REANALYSIS_THRESHOLDS,
        )
        fc_quality = assess_quality(
            image_count=1,
            coverage_percent=(fc_stats.coverage_percent if fc_stats else 0.0),
            valid_pixel_count=(fc_stats.valid_pixel_count if fc_stats else 0),
            thresholds=SOIL_STATIC_THRESHOLDS,
        )
        wp_quality = assess_quality(
            image_count=1,
            coverage_percent=(wp_stats.coverage_percent if wp_stats else 0.0),
            valid_pixel_count=(wp_stats.valid_pixel_count if wp_stats else 0),
            thresholds=SOIL_STATIC_THRESHOLDS,
        )
        quality = combine_quality([sm_quality, fc_quality, wp_quality])

        provenance = self.build_provenance(
            context=context,
            dataset=sm_dataset,
            bands=list(self.source_bands),
            formula=(
                "PAF = (mean(sm_rootzone) - thickness-weighted "
                "theta(1500 kPa)) / (thickness-weighted theta(33 kPa) "
                "- thickness-weighted theta(1500 kPa))"
            ),
            quality=quality,
            image_count=step_count,
            aggregation_method=(
                "time mean of the SMAP L4 3-hourly steps; thickness-weighted "
                "spatial means of the five SoilGrids 0-100 cm layers at 33 "
                "and 1500 kPa; the fraction is formed from the three "
                "reduced means"
            ),
            extra_limitations=(
                "Temporal alignment: the SMAP L4 observation defines the "
                "analysis time and both SoilGrids predictions are "
                "time-invariant, so no cross-dataset date matching is "
                "involved.",
                "Spatial alignment: the fraction is computed at the SMAP L4 "
                "scale after Earth Engine resamples the 250 m SoilGrids "
                "grid to the coarser SMAP grid. The result's spatial detail "
                "is limited by SMAP.",
                "Values outside [0, 1] are reported rather than clipped. "
                "They indicate that the SMAP state sits outside the "
                "SoilGrids retention range, which is a property of the two "
                "products, not an impossible measurement.",
            ),
            extra_caveats=(
                "The fraction is formed from three already-reduced means in "
                "physical units; no scale factor is reapplied at this "
                "layer.",
                f"Inputs: SMAP root-zone mean = "
                f"{sm_stats.mean if sm_stats.mean is not None else 'n/a'} "
                f"m3/m3; field capacity = "
                f"{fc_stats.mean if fc_stats and fc_stats.mean is not None else 'n/a'} "
                f"cm3/cm3; wilting point = "
                f"{wp_stats.mean if wp_stats and wp_stats.mean is not None else 'n/a'} "
                f"cm3/cm3.",
            ),
        )

        if step_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No SMAP L4 timesteps were available for the requested "
                    "period, so the fraction is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        missing = fc_missing if fc_missing is not None else wp_missing
        if missing is not None or fc_stats is None or wp_stats is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The {missing.replace('_', '-')} cm SoilGrids layer "
                    "returned no usable prediction for this area, so a "
                    "0-100 cm retention range cannot be computed and the "
                    "fraction is refused rather than computed against a "
                    "shallower column."
                )
                if missing is not None
                else (
                    "A SoilGrids retention reduction returned no usable "
                    "prediction for this area, so the fraction is not "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if not sm_stats.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The SMAP L4 root-zone reduction returned no valid "
                    "pixels for this area, so the fraction is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        sm_value = sm_stats.mean
        fc_value = fc_stats.mean
        wp_value = wp_stats.mean
        if sm_value is None or fc_value is None or wp_value is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "At least one of soil moisture, field capacity and "
                    "wilting point has no mean value, so the fraction is "
                    "not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        awc = fc_value - wp_value
        if awc <= 0.0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The predicted available water capacity is "
                    f"{awc:.4f} cm3/cm3 (field capacity {fc_value:.4f} "
                    f"minus wilting point {wp_value:.4f}), which is not a "
                    "positive available-water range, so the fraction is "
                    "undefined and is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        value = (sm_value - wp_value) / awc

        warnings: List[str] = [
            "Field capacity and wilting point are the 33 kPa and 1500 kPa "
            "SoilGrids predictions, both conventional surrogates for the "
            "true retention properties of this soil."
        ]
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

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
# 2. Atmospheric-demand indicators
# ==========================================================================


class _VPDBaselineMetric(Metric):
    """Common machinery for the baseline-relative VPD metrics."""

    domain = MetricDomain.STRESS
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = ERA5_WORKING_SCALE
    unit = "kPa"

    #: Number of preceding years to gather.
    baseline_years: int = VPD_ANOMALY_BASELINE_YEARS

    #: Minimum contributing years below which the metric is refused.
    min_years: int = VPD_ANOMALY_MIN_YEARS

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("temperature_2m", "dewpoint_temperature_2m")

    def _collect_baseline(
        self, context: MetricContext, ee_module: Any
    ) -> Tuple[List[Tuple[int, date, date]], List[List[float]], List[int]]:
        """Per-year daily VPD series for the preceding same-calendar windows.

        Returns ``(windows, per_year_series, per_year_day_counts)``. A year
        whose window produced no paired days contributes an empty series,
        which the caller treats as a non-contributing year rather than as
        a zero-demand year.
        """
        start = context.start
        end = context.end
        if start is None or end is None:
            return [], [], []

        windows = baseline_windows(start, end, self.baseline_years)
        series: List[List[float]] = []
        counts: List[int] = []
        for _years_back, win_start, win_end in windows:
            shifted = _shift_context(context, win_start, win_end)
            daily_vpd, day_count = _daily_vpd_series(shifted, ee_module)
            series.append(daily_vpd)
            counts.append(day_count)
        return windows, series, counts

    def _baseline_provenance(
        self,
        context: MetricContext,
        record: Optional[AnomalyRecord],
    ) -> Tuple[List[str], List[str]]:
        """Caveats and warnings describing the reference period."""
        caveats: List[str] = []
        warnings: List[str] = []
        if record is not None:
            caveats.append(
                f"Baseline: {record.baseline_statistic} over the "
                f"{record.observation_count} contributing baseline year(s); "
                f"reference period {record.baseline_period or 'n/a'}."
            )
        else:
            caveats.append(
                "No baseline year contributed usable data, so no "
                "reference period could be established."
            )
        return caveats, warnings


class VPDAnomalyMetric(_VPDBaselineMetric):
    """Anomaly of mean VPD against the same calendar window in prior years.

    .. math::

        anomaly = \\overline{VPD}_{request} - \\overline{VPD}_{baseline}

    The requested value is the mean of the per-day VPD series over the
    requested window, with temperature and dewpoint paired on the same
    day. The baseline is the mean of the same statistic computed over
    the **same calendar window in each of the preceding years**, from
    the same product, the same bands and the same geometry, so the
    comparison involves no cross-dataset assumption at all.

    A positive anomaly means atmospheric demand was higher than the
    local interannual reference for that window; a negative anomaly
    means it was lower. This is an atmospheric-demand indicator. A high
    anomaly does not by itself indicate a stressed crop, because wind,
    soil water and stomatal behaviour all intervene.
    """

    key = "vpd_anomaly"
    display_name = "Vapour Pressure Deficit Anomaly"
    display_name_fa = "آنومالی کمبود فشار بخار"
    baseline_years = VPD_ANOMALY_BASELINE_YEARS
    min_years = VPD_ANOMALY_MIN_YEARS
    description = (
        "Mean daily vapour pressure deficit for the requested period, minus "
        "the mean of the same statistic over the same calendar window in "
        "each of the preceding years from the same ERA5-Land product. A "
        "positive anomaly means atmospheric demand exceeded the local "
        "interannual reference. This is an atmospheric-demand indicator, "
        "not a crop-stress diagnosis."
    )
    limitations = (
        _STRESS_DISCLAIMER,
        "VPD is derived from modelled temperature and dewpoint at roughly "
        "11 km, so the value describes a region rather than a field.",
        "The Magnus approximation is accurate to about 0.1 percent over "
        "the range minus 40 to plus 50 degrees Celsius.",
        "The anomaly measures atmospheric demand, not soil water "
        "availability and not crop water status.",
        "A baseline of a few years separates an anomaly from ordinary "
        "interannual variability only coarsely.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        start = context.start
        end = context.end

        if start is None or end is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The requested period cannot be parsed, so no anomaly "
                    "window is defined."
                ),
                unit=self.unit,
            )

        if (end - start).days > MAX_ANOMALY_WINDOW_DAYS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The requested period spans {(end - start).days} days, "
                    f"which is longer than one year. A same-calendar-window "
                    f"baseline is not defined for a request that long "
                    f"because the baseline windows would overlap the "
                    f"requested period."
                ),
                unit=self.unit,
            )

        requested_vpd, requested_days = _daily_vpd_series(context, ee)
        windows, baseline_series, _ = self._collect_baseline(context, ee)

        per_year_means: List[Optional[float]] = [
            (sum(series) / len(series)) if series else None
            for series in baseline_series
        ]
        contributed = sum(1 for value in per_year_means if value is not None)

        requested_quality = _vpd_quality(requested_vpd, requested_days)
        baseline_quality = assess_quality(
            image_count=contributed,
            coverage_percent=100.0 if contributed else 0.0,
            valid_pixel_count=contributed,
            thresholds=REANALYSIS_THRESHOLDS,
        )
        quality = combine_quality([requested_quality, baseline_quality])

        record = None
        if requested_vpd:
            requested_mean = sum(requested_vpd) / len(requested_vpd)
            record = compute_anomaly(requested_mean, per_year_means, "mean")
            if record is not None:
                record = AnomalyRecord(
                    value=record.value,
                    baseline=record.baseline,
                    anomaly=record.anomaly,
                    baseline_statistic=record.baseline_statistic,
                    observation_count=record.observation_count,
                    baseline_period=_baseline_label(windows, contributed),
                )

        caveats, _ = self._baseline_provenance(context, record)
        caveats.append(
            f"Requested window: {_window_label(start, end)} "
            f"({len(requested_vpd)} of {max(requested_days, len(requested_vpd))} "
            f"days paired)."
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=list(self.source_bands),
            formula=(
                "VPD_day = es(T_day) - ea(Td_day), es = 0.6108 * "
                "exp(17.27 * T / (T + 237.3)) kPa; anomaly = "
                "mean(VPD_day over the requested window) - mean over the "
                "same calendar window in each preceding year"
            ),
            quality=quality,
            image_count=requested_days,
            aggregation_method=(
                "per-day pairing of temperature and dewpoint, then a window "
                "mean; the baseline is the mean of one such window mean per "
                "preceding year"
            ),
            extra_limitations=(
                "Temporal alignment: the requested window and every "
                "baseline window use the same product, bands, geometry and "
                "month-day span, offset only by whole years. No "
                "cross-dataset alignment is involved.",
                "A baseline year with no paired days is excluded from the "
                "reference rather than counted as a zero-demand year.",
            ),
            extra_caveats=caveats,
        )

        if not requested_vpd:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Temperature and dewpoint could not be paired for any "
                    "day in the requested period, so no anomaly is "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if record is None or contributed < self.min_years:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributed} of the {self.baseline_years} "
                    "preceding-year baseline windows contributed usable VPD "
                    f"data, which is fewer than the {self.min_years} "
                    "required, so no interannual anomaly is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if contributed < self.baseline_years:
            warnings.append(
                f"{self.baseline_years - contributed} baseline year(s) "
                "contributed no usable data and were excluded from the "
                "reference, which weakens the baseline."
            )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=record.anomaly,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )


class VPDHighDurationMetric(_VPDBaselineMetric):
    """Number of days whose VPD exceeds the local climatological reference.

    .. math::

        n = |\\{ d \\in request : VPD_d > P_{90}(VPD_{baseline}) \\}|

    The threshold is the 90th percentile of the **pooled per-day VPD
    distribution over the same calendar window in the preceding years**,
    drawn from the local climatological record rather than asserted as
    an absolute value in kPa. An absolute VPD threshold would need
    verified crop applicability that no registered dataset can supply,
    so none is introduced.

    The result is a count of days of above-reference atmospheric demand.
    It is not a crop-stress duration: whether elevated demand stresses a
    crop depends on soil water, rooting, stomatal behaviour and growth
    stage, none of which this metric observes.
    """

    key = "vpd_high_duration"
    display_name = "Duration of Above-Reference VPD"
    display_name_fa = "مدت زمان VPD بالاتر از مرجع"
    unit = "count_days"
    baseline_years = VPD_HIGH_DURATION_BASELINE_YEARS
    min_years = VPD_HIGH_DURATION_MIN_YEARS
    description = (
        "Number of days in the requested period whose daily vapour pressure "
        "deficit exceeds the 90th percentile of the pooled daily VPD "
        "distribution over the same calendar window in the preceding years. "
        "The reference is drawn from the local climatological record, not "
        "from an absolute kPa threshold. This is an atmospheric-demand "
        "indicator, not a crop-stress diagnosis."
    )
    limitations = (
        _STRESS_DISCLAIMER,
        "The count is not a crop-stress duration: whether elevated demand "
        "stresses a crop depends on soil water, rooting, stomatal behaviour "
        "and growth stage, none of which this metric observes.",
        "The 90th percentile reference is relative to the local "
        "interannual distribution of this window, so the count is a "
        "statement about unusual demand for this place and season, not "
        "about any crop's tolerance.",
        "VPD is derived from modelled temperature and dewpoint at roughly "
        "11 km, so a day-level count describes a region rather than a "
        "field.",
        "A short requested window yields a small count by construction; a "
        "count of 3 out of 10 days is not comparable to 3 out of 90.",
        "The pooled reference distribution is coarse when few baseline "
        "years contribute, which is why a minimum sample count is enforced.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        start = context.start
        end = context.end

        if start is None or end is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The requested period cannot be parsed, so no "
                    "comparison window is defined."
                ),
                unit=self.unit,
            )

        if (end - start).days > MAX_ANOMALY_WINDOW_DAYS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The requested period spans {(end - start).days} days, "
                    "which is longer than one year. A same-calendar-window "
                    "reference is not defined for a request that long "
                    "because the reference windows would overlap the "
                    "requested period."
                ),
                unit=self.unit,
            )

        requested_vpd, requested_days = _daily_vpd_series(context, ee)
        windows, baseline_series, _ = self._collect_baseline(context, ee)

        pooled_baseline: List[float] = []
        contributed = 0
        for series in baseline_series:
            if series:
                contributed += 1
                pooled_baseline.extend(series)

        threshold = percentile_value(
            pooled_baseline,
            VPD_HIGH_DURATION_PERCENTILE,
            VPD_HIGH_DURATION_MIN_SAMPLES,
        )

        requested_quality = _vpd_quality(requested_vpd, requested_days)
        baseline_quality = assess_quality(
            image_count=contributed,
            coverage_percent=100.0 if contributed else 0.0,
            valid_pixel_count=len(pooled_baseline),
            thresholds=REANALYSIS_THRESHOLDS,
        )
        quality = combine_quality([requested_quality, baseline_quality])

        caveats = [
            "The exceedance reference is the "
            f"{VPD_HIGH_DURATION_PERCENTILE:.0f}th percentile of the pooled "
            "daily VPD distribution over the same calendar window in the "
            f"preceding {self.baseline_years} years, not an absolute kPa "
            "threshold.",
            f"Reference population: {len(pooled_baseline)} daily values from "
            f"{contributed} of {self.baseline_years} baseline year(s); "
            f"reference period {_baseline_label(windows, contributed)}.",
            f"Requested window: {_window_label(start, end)} "
            f"({len(requested_vpd)} of {max(requested_days, len(requested_vpd))} "
            f"days paired).",
        ]

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=list(self.source_bands),
            formula=(
                "VPD_day = es(T_day) - ea(Td_day); threshold = "
                f"P{VPD_HIGH_DURATION_PERCENTILE:.0f} of the pooled daily "
                "VPD over the same calendar window in the preceding years; "
                "count = number of requested days above the threshold"
            ),
            quality=quality,
            image_count=requested_days,
            aggregation_method=(
                "per-day pairing of temperature and dewpoint; the "
                "per-day series of every baseline year is pooled into one "
                "reference distribution; the count is over the requested "
                "days only"
            ),
            extra_limitations=(
                "Temporal alignment: the requested window and every "
                "reference window use the same product, bands, geometry and "
                "month-day span, offset only by whole years.",
                "A baseline year with no paired days contributes nothing to "
                "the pooled reference distribution.",
            ),
            extra_caveats=caveats,
        )

        if not requested_vpd:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Temperature and dewpoint could not be paired for any "
                    "day in the requested period, so no count is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if threshold is None or contributed < self.min_years:
            reason = (
                f"Only {contributed} of the {self.baseline_years} "
                "preceding-year windows contributed usable VPD data"
                if contributed < self.min_years
                else (
                    f"The pooled reference distribution has "
                    f"{len(pooled_baseline)} daily values, which is fewer "
                    f"than the {VPD_HIGH_DURATION_MIN_SAMPLES} required to "
                    "define a percentile reference"
                )
            )
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"{reason}, so no above-reference duration is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        count = sum(1 for value in requested_vpd if value > threshold)

        warnings: List[str] = [
            f"The exceedance reference is {threshold:.3f} kPa, the "
            f"{VPD_HIGH_DURATION_PERCENTILE:.0f}th percentile of this "
            "window's local interannual distribution. It is not an "
            "absolute stress threshold."
        ]
        if contributed < self.baseline_years:
            warnings.append(
                f"{self.baseline_years - contributed} baseline year(s) "
                "contributed no usable data and were excluded from the "
                "reference distribution."
            )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=float(count),
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )


# ==========================================================================
# 3. Thermal-stress indicators
# ==========================================================================


class _LSTBaselineMetric(Metric):
    """Common machinery for the baseline-relative LST metrics."""

    domain = MetricDomain.STRESS
    dataset_ids = (MODIS_LST_8DAY,)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = MODIS_LST_WORKING_SCALE
    unit = "degC"

    source_band = "LST_Day_1km"

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return (self.source_band,)

    def _window_mean(
        self, context: MetricContext, ee_module: Any, start: date, end: date
    ) -> Tuple[Optional[float], int, QualityLevel]:
        """The mean daytime LST over one window, in degrees Celsius.

        The reduction goes through the thermal module's shared helper, so
        the band's scale factor is applied exactly once and the
        Kelvin-to-Celsius shift happens once, in the same helper the
        thermal metrics use.
        """
        shifted = _shift_context(context, start, end)
        stats, image_count = _reduce_modis_lst(
            shifted, ee_module, MODIS_LST_8DAY, self.source_band
        )
        celsius = _lst_stats_to_celsius(stats)
        quality = assess_quality(
            image_count=max(image_count, 1),
            coverage_percent=celsius.coverage_percent,
            valid_pixel_count=celsius.valid_pixel_count,
            thresholds=MODIS_THRESHOLDS,
        )
        if image_count == 0 or not celsius.has_values:
            return None, image_count, quality
        return celsius.mean, image_count, quality

    def _collect_baseline(
        self, context: MetricContext, ee_module: Any
    ) -> Tuple[List[Tuple[int, date, date]], List[Optional[float]], List[int]]:
        """Per-year window means for the preceding same-calendar windows."""
        start = context.start
        end = context.end
        if start is None or end is None:
            return [], [], []

        windows = baseline_windows(start, end, LST_ANOMALY_BASELINE_YEARS)
        means: List[Optional[float]] = []
        counts: List[int] = []
        for _years_back, win_start, win_end in windows:
            mean, count, _ = self._window_mean(
                context, ee_module, win_start, win_end
            )
            means.append(mean)
            counts.append(count)
        return windows, means, counts

    def _can_use_window(
        self, context: MetricContext
    ) -> Optional[MetricResult]:
        """Reject a window for which no baseline is defined, up front."""
        start = context.start
        end = context.end
        if start is None or end is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The requested period cannot be parsed, so no anomaly "
                    "window is defined."
                ),
                unit=self.unit,
            )
        if (end - start).days > MAX_ANOMALY_WINDOW_DAYS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The requested period spans {(end - start).days} days, "
                    "which is longer than one year. A same-calendar-window "
                    "baseline is not defined for a request that long "
                    "because the baseline windows would overlap the "
                    "requested period."
                ),
                unit=self.unit,
            )
        return None


class LSTDayAnomalyMetric(_LSTBaselineMetric):
    """Daytime LST anomaly against the same window in prior years.

    .. math::

        anomaly = \\overline{LST}_{request} - \\overline{LST}_{baseline}

    The requested value is the mean daytime land surface temperature
    over the requested window. The baseline is the mean of the same
    statistic over the **same calendar window in each of the preceding
    years**, from the same MODIS product and the same geometry, so the
    comparison is a like-for-like departure from the local
    interannual reference rather than a comparison against an absolute
    temperature.

    Land surface temperature is the radiometric skin temperature of
    everything in the pixel. It is not canopy temperature, and the
    anomaly inherits that limitation: a positive anomaly over a partly
    vegetated pixel may reflect exposed soil rather than leaf
    temperature.
    """

    key = "lst_day_anomaly"
    display_name = "Daytime Land Surface Temperature Anomaly"
    display_name_fa = "آنومالی دمای سطح زمین در روز"
    description = (
        "Mean daytime land surface temperature for the requested period, "
        "minus the mean of the same statistic over the same calendar window "
        "in each of the preceding years from the same MODIS product. A "
        "positive anomaly means the surface was warmer than the local "
        "interannual reference for that window. This is an environmental "
        "thermal indicator, not a crop-stress diagnosis."
    )
    limitations = (
        _STRESS_DISCLAIMER,
        "This is land surface temperature, the radiometric skin temperature "
        "of everything in the pixel. It is NOT canopy temperature and NOT "
        "leaf temperature.",
        "At 1 km the value describes a district rather than a field, and "
        "within-field variability is not resolved.",
        "A thermal anomaly does not by itself indicate water stress. Over a "
        "partly vegetated pixel a positive anomaly may reflect exposed "
        "soil, a change in cover, or a genuine canopy effect, and the "
        "signal does not distinguish them.",
        "The retrieval assumes a surface emissivity that varies with land "
        "cover, contributing roughly 1 K of uncertainty on top of the "
        "quoted retrieval error.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        rejected = self._can_use_window(context)
        if rejected is not None:
            return rejected

        start = context.start
        end = context.end
        assert start is not None and end is not None  # for the type checker

        requested_mean, requested_count, requested_quality = (
            self._window_mean(context, ee, start, end)
        )
        windows, baseline_means, baseline_counts = self._collect_baseline(
            context, ee
        )

        contributed = sum(
            1 for value in baseline_means if value is not None
        )
        baseline_quality = assess_quality(
            image_count=max(sum(1 for c in baseline_counts if c > 0), 1),
            coverage_percent=100.0 if contributed else 0.0,
            valid_pixel_count=contributed,
            thresholds=MODIS_THRESHOLDS,
        )
        quality = combine_quality(
            [requested_quality, baseline_quality]
        )

        record = compute_anomaly(requested_mean, baseline_means, "mean")
        if record is not None:
            record = AnomalyRecord(
                value=record.value,
                baseline=record.baseline,
                anomaly=record.anomaly,
                baseline_statistic=record.baseline_statistic,
                observation_count=record.observation_count,
                baseline_period=_baseline_label(windows, contributed),
            )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=list(self.source_bands),
            formula=(
                "anomaly = mean(LST_Day_1km over the requested window, in "
                "degC) - mean of one such window mean per preceding year"
            ),
            quality=quality,
            image_count=requested_count,
            aggregation_method=(
                "time mean then spatial mean per window, in degrees Celsius "
                "after the single band scale factor and the "
                "Kelvin-to-Celsius shift; the baseline is the mean of one "
                "window mean per preceding year"
            ),
            extra_limitations=(
                "Temporal alignment: the requested window and every "
                "baseline window use the same product, band, geometry and "
                "month-day span, offset only by whole years. No "
                "cross-dataset alignment is involved and no value from "
                "another date is substituted for a missing one.",
                "A baseline year whose window returned no valid pixels is "
                "excluded from the reference rather than counted as a "
                "zero-temperature year.",
            ),
            extra_caveats=(
                f"Baseline: mean of per-year window means over "
                f"{contributed} contributing year(s); reference period "
                f"{_baseline_label(windows, contributed)}.",
                f"Requested window: {_window_label(start, end)}.",
                "Spatial alignment: both the requested and the baseline "
                "reductions run at the MODIS 1 km scale, so the anomaly is "
                "limited by that resolution.",
            ),
        )

        if requested_mean is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No MODIS scenes or no valid pixels were returned for "
                    "the requested window, so no anomaly is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if record is None or contributed < LST_ANOMALY_MIN_YEARS:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributed} of the {LST_ANOMALY_BASELINE_YEARS} "
                    "preceding-year baseline windows contributed usable "
                    f"land surface temperature, which is fewer than the "
                    f"{LST_ANOMALY_MIN_YEARS} required, so no interannual "
                    "anomaly is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if contributed < LST_ANOMALY_BASELINE_YEARS:
            warnings.append(
                f"{LST_ANOMALY_BASELINE_YEARS - contributed} baseline "
                "year(s) contributed no usable data and were excluded from "
                "the reference, which weakens the baseline."
            )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=record.anomaly,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )


class LSTDayPercentileMetric(_LSTBaselineMetric):
    """Where this window's daytime LST sits in the historical distribution.

    .. math::

        p = 100 \\cdot \\frac{|\\{b \\in baseline : b < v\\}|}{|baseline|}

    where ``v`` is the requested window's mean daytime LST and the
    baseline population is the set of per-year window means over the
    same calendar window in the preceding years, from the same product
    and geometry. The requested value is ranked against the reference
    and is not itself a member of the population.

    This is a percentile of a stated reference population: it is not a
    min-max normalisation and not a stress probability. With ``N``
    contributing years the rank resolves only in steps of ``100 / N``,
    which is stated in the result.
    """

    key = "lst_day_percentile"
    display_name = "Daytime LST Percentile of Historical Window"
    display_name_fa = "صدک دمای سطح زمین نسبت به سال‌های گذشته"
    unit = "percent"
    description = (
        "Percentile rank of the requested window's mean daytime land "
        "surface temperature within the distribution of the same statistic "
        "over the same calendar window in the preceding years, from the "
        "same MODIS product. A value near 100 means the window was warmer "
        "than the local interannual reference. This is an environmental "
        "thermal indicator, not a crop-stress diagnosis."
    )
    limitations = (
        _STRESS_DISCLAIMER,
        "This is a percentile of a stated reference population; it is not "
        "a min-max normalisation and not a stress probability.",
        "This is land surface temperature, not canopy temperature and not "
        "leaf temperature.",
        "A percentile of a small population resolves only in coarse steps, "
        "so the rank is an approximate position within the reference "
        "distribution, not a precise quantile.",
        "At 1 km the value describes a district rather than a field.",
        "A high percentile does not by itself indicate water stress and "
        "says nothing about cause.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        rejected = self._can_use_window(context)
        if rejected is not None:
            return rejected

        start = context.start
        end = context.end
        assert start is not None and end is not None  # for the type checker

        requested_mean, requested_count, requested_quality = (
            self._window_mean(context, ee, start, end)
        )
        windows, baseline_means, _ = self._collect_baseline(context, ee)

        population = [v for v in baseline_means if v is not None]
        contributed = len(population)

        rank = percentile_of_value(
            requested_mean,
            population,
            LST_PERCENTILE_MIN_SAMPLES,
        )

        baseline_quality = assess_quality(
            image_count=max(contributed, 1),
            coverage_percent=100.0 if contributed else 0.0,
            valid_pixel_count=contributed,
            thresholds=MODIS_THRESHOLDS,
        )
        quality = combine_quality([requested_quality, baseline_quality])

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=list(self.source_bands),
            formula=(
                "percentile = 100 * (number of baseline window means below "
                "the requested window mean) / (number of contributing "
                "baseline years)"
            ),
            quality=quality,
            image_count=requested_count,
            aggregation_method=(
                "time mean then spatial mean per window, in degrees Celsius; "
                "the requested window mean is ranked against the per-year "
                "window means of the preceding years"
            ),
            extra_limitations=(
                "The reference population is the set of per-year window "
                "means over the same calendar window in the preceding "
                "years. The requested value is ranked against it and is not "
                "a member of it.",
                "Temporal alignment: the requested window and every "
                "reference window use the same product, band, geometry and "
                "month-day span, offset only by whole years.",
            ),
            extra_caveats=(
                f"Reference population: {contributed} contributing year(s); "
                f"reference period {_baseline_label(windows, contributed)}.",
                f"Requested window: {_window_label(start, end)}.",
                "With N contributing years the rank resolves in steps of "
                "100/N, so the percentile is an approximate position, not a "
                "precise quantile.",
            ),
        )

        if requested_mean is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No MODIS scenes or no valid pixels were returned for "
                    "the requested window, so no percentile is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if rank is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {contributed} of the "
                    f"{LST_ANOMALY_BASELINE_YEARS} preceding-year windows "
                    "contributed usable land surface temperature, which is "
                    f"fewer than the {LST_PERCENTILE_MIN_SAMPLES} samples "
                    "required to define a percentile, so no rank is "
                    "reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            "This is a percentile of a historical reference population, not "
            "a stress probability and not a min-max normalised index."
        ]
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=rank,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )


# ==========================================================================
# 4. Deliberately unavailable stress metrics
# ==========================================================================


COMPOSITE_UNAVAILABLE_CODE = "no_scientific_weighting"
COMPOSITE_UNAVAILABLE_REASON = (
    "A composite stress index would combine vegetation, moisture, thermal, "
    "atmospheric and soil signals into one number. That combination is only "
    "defensible with a stated weighting scheme whose weights are validated "
    "for a named crop and climate. No registered dataset supplies such "
    "weights, no weighting scheme has been validated against field data in "
    "this engine, and normalising each indicator onto a common scale would "
    "require a reference distribution that has not been established for "
    "most of the inputs. Publishing a single number with unverified weights "
    "would present an arbitrary aggregate as a measurement, so the metric "
    "is not produced. The individual indicators it would combine are each "
    "published under their own keys with their own provenance."
)


class _UnavailableStressMetric(Metric):
    """A stress metric this engine deliberately does not compute.

    The metric is registered so the catalog can answer the question it
    represents with the specific reason it cannot be answered, rather
    than with silence that could be mistaken for an oversight. It is
    structurally incapable of carrying a value: ``compute`` has no path
    that returns anything but an unavailable result.
    """

    domain = MetricDomain.STRESS
    measurement_basis = MeasurementBasis.INFERENCE
    dataset_ids: Tuple[str, ...] = ()
    unit = "index"
    unavailable_code: str = COMPOSITE_UNAVAILABLE_CODE
    unavailable_reason: str = COMPOSITE_UNAVAILABLE_REASON

    def compute(self, context: MetricContext) -> MetricResult:
        return MetricResult.unavailable(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            reason=self.unavailable_code,
            message=self.unavailable_reason,
            unit=self.unit,
        )

    def metadata(self) -> dict:
        metadata = super().metadata()
        metadata["available"] = False
        metadata["unavailable_code"] = self.unavailable_code
        metadata["unavailable_reason"] = self.unavailable_reason
        return metadata


class CompositeStressMetric(_UnavailableStressMetric):
    key = "composite_stress"
    display_name = "Composite Stress Index"
    display_name_fa = "شاخص تنش ترکیبی"
    description = (
        "Not produced. Combining vegetation, moisture, thermal, atmospheric "
        "and soil indicators into one index requires a validated weighting "
        "scheme that no registered dataset supplies. The indicators are "
        "published individually instead."
    )
    limitations = (
        "Requires a weighting scheme and a validation record that are not "
        "available in this engine, and no scientific weighting of "
        "indicators may be invented to fill that gap.",
        "The individual indicators it would combine are each published "
        "under their own keys with their own provenance.",
    )


# ==========================================================================
# Metric collections
# ==========================================================================


STRESS_METRICS: Tuple[Metric, ...] = (
    EvaporativeFractionMetric(),
    SoilWaterContentRatioMetric(),
    PlantAvailableWaterFractionMetric(),
    VPDAnomalyMetric(),
    VPDHighDurationMetric(),
    LSTDayAnomalyMetric(),
    LSTDayPercentileMetric(),
)

UNAVAILABLE_STRESS_METRICS: Tuple[Metric, ...] = (CompositeStressMetric(),)

ALL_STRESS_METRICS: Tuple[Metric, ...] = (
    STRESS_METRICS + UNAVAILABLE_STRESS_METRICS
)
