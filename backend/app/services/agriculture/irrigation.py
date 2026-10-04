"""Irrigation and water-management analytics (Phase L).

A derived layer on top of the already verified water, soil, climate and
stress metrics. Nothing here re-reads a raw band that a lower layer
already publishes: period integrals reuse
:class:`~app.services.agriculture.water.CumulativeEvapotranspirationMetric`
and a cumulative precipitation built on the climate module's shared
reduction helper, and the anomaly metrics reuse the Phase K baseline
framework (same calendar window in preceding years, whole-year offsets,
leap-day folding).

Scientific boundary: this module quantifies water demand, water supply
and the difference between them over a stated period. It does not issue
irrigation instructions. A water deficit is not a soil water deficit
(runoff, drainage, irrigation and storage change are not observed), and
no metric here decides that a field needs irrigation.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.climate import (
    ERA5_DAILY,
    ERA5_WORKING_SCALE,
    _reduce_era5_band,
)
from app.services.agriculture.quality import (
    REANALYSIS_THRESHOLDS,
    assess_quality,
    combine_quality,
    describe_quality,
)
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.stress import (
    MAX_ANOMALY_WINDOW_DAYS,
    SMAP_L4_SCALE,
    AnomalyRecord,
    _baseline_label,
    _reduce_smap_rootzone,
    _shift_context,
    _window_label,
    baseline_windows,
    compute_anomaly,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    QualityLevel,
)
from app.services.agriculture.units import metres_to_millimetres
from app.services.agriculture.water import (
    MOD16_GAPFILLED,
    MOD16_NRT,
    CumulativeEvapotranspirationMetric,
)

__all__ = [
    "PrecipitationCumulativeMetric",
    "ETPrecipitationDeficitMetric",
    "PrecipitationAnomalyMetric",
    "EvapotranspirationAnomalyMetric",
    "SoilMoistureRootZoneAnomalyMetric",
    "IrrigationWaterRequirementMetric",
    "GrossIrrigationRequirementMetric",
    "CropEvapotranspirationMetric",
    "IRRIGATION_METRICS",
    "UNAVAILABLE_IRRIGATION_METRICS",
    "ALL_IRRIGATION_METRICS",
]


#: The ERA5-Land band carrying the daily precipitation total.
ERA5_PRECIPITATION_BAND = "total_precipitation_sum"

#: Baseline geometry for the anomaly metrics. ERA5-Land reaches back to
#: 1950, so a ten-year same-calendar baseline is available for any recent
#: request. MOD16 reaches back to 2000 with a roughly one-year latency,
#: which still leaves a decade of candidate years for a recent request.
PRECIP_ANOMALY_BASELINE_YEARS = 10
PRECIP_ANOMALY_MIN_YEARS = 3
ET_ANOMALY_BASELINE_YEARS = 10
ET_ANOMALY_MIN_YEARS = 3

#: SMAP L4 begins in March 2015, so a shorter baseline is the most a
#: recent request can honestly gather.
SM_ANOMALY_BASELINE_YEARS = 5
SM_ANOMALY_MIN_YEARS = 3

_IRRIGATION_DISCLAIMER = (
    "This is a water-balance indicator. It quantifies the relationship "
    "between atmospheric water demand and rainfall supply over a stated "
    "period; it is not an irrigation instruction, and a positive value "
    "does not by itself determine that a field needs irrigation."
)

#: The term accounting demanded by the water-balance spec: every term of
#: the conceptual balance is labelled observed/modelled/user-provided or
#: unavailable, and the excluded ones are named rather than silently set
#: to zero.
_WATER_BALANCE_TERMS_CAVEAT = (
    "Water-balance terms: evapotranspiration (modelled, MOD16), "
    "precipitation (modelled, ERA5-Land reanalysis), runoff (unavailable, "
    "excluded), drainage (unavailable, excluded), irrigation input "
    "(unavailable, excluded), soil-water storage change (not estimated)."
)


def _era5_precipitation_total_mm(
    context: MetricContext, ee_module: Any
) -> Tuple[Optional[float], int, int, QualityLevel]:
    """Sum of daily ERA5-Land precipitation totals over the window, in mm.

    Returns ``(total_mm, day_count, contributing_days, quality)``. The
    metres-to-millimetres conversion is applied exactly once, here, to
    each daily total that the shared reduction helper returns in the
    band's declared unit (metres). A window with no usable daily total
    yields ``total_mm=None`` so the caller reports missing data rather
    than a rainless period.
    """
    stats, day_count, daily_values = _reduce_era5_band(
        context, ee_module, ERA5_PRECIPITATION_BAND
    )
    daily_mm = [
        converted
        for converted in (
            metres_to_millimetres(value) for value in daily_values
        )
        if converted is not None
    ]
    total = float(sum(daily_mm)) if daily_mm else None
    quality = assess_quality(
        image_count=max(day_count, 1),
        coverage_percent=stats.coverage_percent,
        valid_pixel_count=stats.valid_pixel_count,
        thresholds=REANALYSIS_THRESHOLDS,
    )
    return total, day_count, len(daily_mm), quality


# ==========================================================================
# 1. Period integrals of the water-balance supply and demand terms
# ==========================================================================


class PrecipitationCumulativeMetric(Metric):
    """Cumulative precipitation over the requested period.

    .. math::

        P_{cumulative} = \\sum_{days} P_{day}

    The sum is over the daily ERA5-Land ``total_precipitation_sum``
    values inside the requested window, converted from metres to
    millimetres exactly once. Unlike the climate module's
    ``precipitation`` metric (the *mean* of daily totals), this is a true
    period total, which is the form the water-balance terms require.

    This is rainfall only. Irrigation, runoff and drainage are not part
    of the accumulation, so the result is the precipitation term of a
    simplified water balance, not a complete water-input record.
    """

    key = "precipitation_cumulative"
    display_name = "Cumulative Precipitation"
    display_name_fa = "بارش تجمعی"
    domain = MetricDomain.IRRIGATION
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.MODELLED
    default_scale = ERA5_WORKING_SCALE
    unit = "mm"
    description = (
        "Total precipitation accumulated over the requested period: the "
        "sum of the daily ERA5-Land totals inside the window, in "
        "millimetres."
    )
    limitations = (
        "This is a modelled reanalysis value at roughly 11 km, not a rain "
        "gauge reading at the field.",
        "Convective rainfall is spatially uneven at scales far below the "
        "model grid, so a field total may differ substantially.",
        "This is rainfall only; irrigation, runoff and drainage are not "
        "part of the accumulation.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return (ERA5_PRECIPITATION_BAND,)

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        total, day_count, contributing, quality = _era5_precipitation_total_mm(
            context, ee
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=[ERA5_PRECIPITATION_BAND],
            formula=(
                "cumulative_precipitation = sum over the requested period "
                "of daily total_precipitation_sum; metres converted to "
                "millimetres once (x1000)"
            ),
            quality=quality,
            image_count=day_count,
            aggregation_method="temporal sum of daily spatial means",
            extra_limitations=(
                "Temporal alignment: the accumulation covers exactly the "
                "requested start to end window; days outside it contribute "
                "nothing and no nearest-day substitution is made.",
            ),
            extra_caveats=(
                f"{contributing} of {day_count} day(s) in the window "
                "contributed a usable daily total.",
            ),
        )

        if total is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No daily precipitation totals were available inside "
                    "the requested period, so no accumulation is reported. "
                    "Reporting zero would falsely indicate a rainless "
                    "period."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=total,
            unit=self.unit,
            provenance=provenance,
        )


class ETPrecipitationDeficitMetric(Metric):
    """ET minus precipitation over the identical requested period.

    .. math::

        deficit = ET_{cumulative} - P_{cumulative}

    Both terms are integrals over the same requested window: ET is the
    sum of the MOD16 8-day composite totals published by
    ``evapotranspiration_cumulative``, and precipitation is the sum of
    the daily ERA5-Land totals from ``precipitation_cumulative``. The
    deficit inherits each term's native timestep (8-day composites versus
    daily) but both sums span the identical calendar interval, so no
    cross-period comparison is involved.

    This is deliberately named an ET-minus-precipitation deficit, not a
    soil water deficit: runoff, drainage, irrigation and the change in
    soil water storage are not observed and are excluded. A positive
    value means atmospheric water demand exceeded rainfall supply over
    the window; the missing term must be made up from soil storage or an
    external supply, but this metric does not observe either and does not
    conclude that irrigation is required. A negative value (rainfall
    surplus) is reported unclipped.
    """

    key = "et_precipitation_deficit"
    display_name = "ET minus Precipitation Water Deficit"
    display_name_fa = "کسری آب: تبخیر-تعرق منهای بارش"
    domain = MetricDomain.IRRIGATION
    dataset_ids = (MOD16_GAPFILLED, MOD16_NRT, ERA5_DAILY)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = ERA5_WORKING_SCALE
    unit = "mm"
    description = (
        "Cumulative evapotranspiration minus cumulative precipitation "
        "over the same requested period, in millimetres. A positive value "
        "means atmospheric water demand exceeded rainfall supply over the "
        "window. This is not a soil water deficit and not an irrigation "
        "instruction."
    )
    limitations = (
        _IRRIGATION_DISCLAIMER,
        "This is an ET-minus-precipitation deficit, not a soil water "
        "deficit: runoff, drainage, irrigation and the change in soil "
        "water storage are not observed and are excluded, so this is not "
        "a complete field water balance.",
        "MOD16 contributes whole 8-day composites that fall inside the "
        "window while precipitation contributes exactly the days inside "
        "it; the two sums span the same calendar interval at different "
        "native timesteps.",
        "The result is limited by its coarsest input, ERA5-Land at "
        "roughly 11 km; no field-scale precision is implied.",
        "A negative value means rainfall exceeded ET over the window and "
        "is reported unclipped.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("ET", ERA5_PRECIPITATION_BAND)

    def compute(self, context: MetricContext) -> MetricResult:
        et_result = CumulativeEvapotranspirationMetric().compute(context)
        p_result = PrecipitationCumulativeMetric().compute(context)

        et_quality = (
            et_result.provenance.quality_level
            if et_result.provenance is not None
            else QualityLevel.INSUFFICIENT
        )
        p_quality = (
            p_result.provenance.quality_level
            if p_result.provenance is not None
            else QualityLevel.INSUFFICIENT
        )
        quality = combine_quality([et_quality, p_quality])

        caveats = [
            (
                "Inputs: cumulative ET = "
                f"{et_result.value if et_result.value is not None else 'n/a'} "
                "mm (MOD16); cumulative precipitation = "
                f"{p_result.value if p_result.value is not None else 'n/a'} "
                "mm (ERA5-Land)."
            ),
            _WATER_BALANCE_TERMS_CAVEAT,
        ]
        provenance = self.build_provenance(
            context=context,
            dataset=get_dataset(ERA5_DAILY),
            bands=list(self.source_bands),
            formula=(
                "deficit = ET_cumulative - precipitation_cumulative over "
                "the identical requested window; ET_cumulative is the "
                "evapotranspiration_cumulative metric (MOD16) and "
                "precipitation_cumulative is the precipitation_cumulative "
                "metric (ERA5-Land)"
            ),
            quality=quality,
            aggregation_method=(
                "difference of two period integrals computed over the "
                "same requested start to end window"
            ),
            extra_limitations=(
                "Temporal alignment: both inputs are integrals over the "
                "identical requested window, so no cross-period alignment "
                "is involved; the deficit inherits the 8-day composite "
                "timestep of its ET term and the daily timestep of its "
                "precipitation term.",
                "Spatial alignment: the result is limited by its coarsest "
                "input, ERA5-Land at roughly 11 km.",
            ),
            extra_caveats=tuple(caveats),
        )

        if et_result.value is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The cumulative evapotranspiration input could not be "
                    f"computed for this period ({et_result.message}), so "
                    "the deficit is not reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        if p_result.value is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The cumulative precipitation input could not be "
                    f"computed for this period ({p_result.message}), so "
                    "the deficit is not reported."
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
            value=et_result.value - p_result.value,
            unit=self.unit,
            provenance=provenance,
            warnings=warnings,
        )


# ==========================================================================
# 2. Interannual anomalies of the water-balance terms
# ==========================================================================


class _BaselineAnomalyMetric(Metric):
    """Anomaly of a window statistic against same-calendar baseline years.

    Subclasses reduce one context window to ``(value, observation_count,
    quality)`` through :meth:`_window_value`. The base class gathers the
    same statistic over the same calendar window in each of the
    preceding ``baseline_years`` years (whole-year offsets, leap-day
    folding, via the Phase K framework), and reports ``value - mean``
    with the full baseline record in the provenance.
    """

    domain = MetricDomain.IRRIGATION
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = ERA5_WORKING_SCALE

    #: Number of preceding same-calendar windows to gather.
    baseline_years: int = 10

    #: Minimum contributing baseline years below which the metric refuses.
    min_years: int = 3

    #: Subclass-provided provenance text.
    formula_text = ""
    aggregation_text = ""

    def _window_value(
        self, context: MetricContext, ee_module: Any
    ) -> Tuple[Optional[float], int, QualityLevel]:
        raise NotImplementedError

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

        requested_value, requested_count, requested_quality = (
            self._window_value(context, ee)
        )

        windows = baseline_windows(start, end, self.baseline_years)
        per_year_values: List[Optional[float]] = []
        for _years_back, win_start, win_end in windows:
            shifted = _shift_context(context, win_start, win_end)
            value, _count, _quality = self._window_value(shifted, ee)
            per_year_values.append(value)

        contributed = sum(1 for value in per_year_values if value is not None)
        baseline_quality = assess_quality(
            image_count=contributed,
            coverage_percent=100.0 if contributed else 0.0,
            valid_pixel_count=contributed,
            thresholds=REANALYSIS_THRESHOLDS,
        )
        quality = combine_quality([requested_quality, baseline_quality])

        record = None
        if requested_value is not None:
            record = compute_anomaly(requested_value, per_year_values, "mean")
            if record is not None:
                record = AnomalyRecord(
                    value=record.value,
                    baseline=record.baseline,
                    anomaly=record.anomaly,
                    baseline_statistic=record.baseline_statistic,
                    observation_count=record.observation_count,
                    baseline_period=_baseline_label(windows, contributed),
                )

        caveats: List[str] = []
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
        caveats.append(
            f"Requested window: {_window_label(start, end)} "
            f"({requested_count} contributing observation(s))."
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=list(self.source_bands),
            formula=self.formula_text,
            quality=quality,
            image_count=requested_count,
            aggregation_method=self.aggregation_text,
            extra_limitations=(
                "Temporal alignment: the requested window and every "
                "baseline window use the same product, bands, geometry and "
                "month-day span, offset only by whole years. No "
                "cross-dataset alignment is involved.",
                "A baseline year with no usable data is excluded from the "
                "reference rather than counted as a zero year.",
            ),
            extra_caveats=tuple(caveats),
        )

        if requested_value is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The requested window produced no usable value, so no "
                    "interannual anomaly is reported."
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
                    "preceding-year baseline windows contributed usable "
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


class PrecipitationAnomalyMetric(_BaselineAnomalyMetric):
    """Precipitation anomaly against the same calendar window in prior years.

    .. math::

        anomaly = P_{cumulative,request}
                  - \\overline{P_{cumulative,baseline}}

    The requested value and every baseline value are cumulative
    precipitation over the identical month-day window, from the same
    ERA5-Land product, so the comparison involves no cross-dataset
    assumption. A negative anomaly means the period was drier than the
    local interannual reference.

    A precipitation anomaly is a meteorological signal. It does not by
    itself establish a soil water deficit, crop water stress or an
    irrigation deficit; those are separate concepts with their own
    metrics in this engine.
    """

    key = "precipitation_anomaly"
    display_name = "Precipitation Anomaly"
    display_name_fa = "آنومالی بارش"
    dataset_ids = (ERA5_DAILY,)
    default_scale = ERA5_WORKING_SCALE
    unit = "mm"
    baseline_years = PRECIP_ANOMALY_BASELINE_YEARS
    min_years = PRECIP_ANOMALY_MIN_YEARS
    formula_text = (
        "anomaly = cumulative precipitation over the requested window "
        "minus the mean of the same cumulative over the same calendar "
        "window in each preceding year; cumulative = sum of daily "
        "total_precipitation_sum with metres converted to millimetres "
        "once (x1000)"
    )
    aggregation_text = (
        "temporal sum of daily spatial means per window; the baseline is "
        "the mean of one such window total per preceding year"
    )
    description = (
        "Cumulative precipitation for the requested period minus the "
        "mean of the same cumulative over the same calendar window in "
        "each preceding year, from ERA5-Land. A negative anomaly means "
        "the period was drier than the local interannual reference. This "
        "is a meteorological indicator, not evidence of irrigation "
        "failure."
    )
    limitations = (
        "This is a modelled reanalysis value at roughly 11 km, not a rain "
        "gauge reading at the field.",
        "A precipitation anomaly is a meteorological drought signal; it "
        "does not by itself establish a soil water deficit, crop water "
        "stress or an irrigation deficit, which are separate concepts "
        "with separate metrics.",
        "A baseline of a few years separates an anomaly from ordinary "
        "interannual variability only coarsely.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return (ERA5_PRECIPITATION_BAND,)

    def _window_value(
        self, context: MetricContext, ee_module: Any
    ) -> Tuple[Optional[float], int, QualityLevel]:
        total, day_count, contributing, quality = _era5_precipitation_total_mm(
            context, ee_module
        )
        return total, contributing, quality


class EvapotranspirationAnomalyMetric(_BaselineAnomalyMetric):
    """Cumulative ET anomaly against the same calendar window in prior years.

    .. math::

        anomaly = ET_{cumulative,request}
                  - \\overline{ET_{cumulative,baseline}}

    Each window's value is the cumulative MOD16 ET published by
    ``evapotranspiration_cumulative`` for that window, so the requested
    and baseline values are produced by the identical computation at
    whole-year offsets. A positive anomaly means evaporative demand or
    consumption was higher than the local interannual reference.

    An ET anomaly describes the demand side of the water balance. It is
    not a crop stress diagnosis: high ET over a well supplied field is
    healthy growth, not stress.
    """

    key = "evapotranspiration_anomaly"
    display_name = "Evapotranspiration Anomaly"
    display_name_fa = "آنومالی تبخیر-تعرق"
    dataset_ids = (MOD16_GAPFILLED, MOD16_NRT)
    unit = "mm"
    baseline_years = ET_ANOMALY_BASELINE_YEARS
    min_years = ET_ANOMALY_MIN_YEARS
    formula_text = (
        "anomaly = cumulative ET over the requested window minus the "
        "mean of the same cumulative over the same calendar window in "
        "each preceding year; cumulative ET is the "
        "evapotranspiration_cumulative metric (sum of MOD16 8-day "
        "composite totals, raw values multiplied by 0.1)"
    )
    aggregation_text = (
        "sum of per-composite spatial means per window; the baseline is "
        "the mean of one such window total per preceding year"
    )
    description = (
        "Cumulative evapotranspiration for the requested period minus "
        "the mean of the same cumulative over the same calendar window "
        "in each preceding year, from MOD16. A positive anomaly means "
        "evaporative demand or consumption exceeded the local "
        "interannual reference. This is a demand-side indicator, not a "
        "crop stress diagnosis."
    )
    limitations = (
        "MOD16 is a modelled product at 500 m with 8-day composites and "
        "a roughly one-year gap-filled latency; a baseline year inside "
        "that latency contributes nothing rather than a partial value.",
        "An ET anomaly describes the demand side of the water balance; "
        "high ET over a well supplied field is healthy growth, not "
        "stress, so this is not a crop water stress diagnosis.",
        "A baseline of a few years separates an anomaly from ordinary "
        "interannual variability only coarsely.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("ET",)

    def _window_value(
        self, context: MetricContext, ee_module: Any
    ) -> Tuple[Optional[float], int, QualityLevel]:
        result = CumulativeEvapotranspirationMetric().compute(context)
        provenance = result.provenance
        count = provenance.image_count if provenance is not None else 0
        quality = (
            provenance.quality_level
            if provenance is not None
            else QualityLevel.UNAVAILABLE
        )
        return result.value, count, quality


class SoilMoistureRootZoneAnomalyMetric(_BaselineAnomalyMetric):
    """Root-zone soil-moisture anomaly against prior years.

    .. math::

        anomaly = \\overline{SM}_{request}
                  - \\overline{\\overline{SM}_{baseline}}

    The value in each window is the mean of the SMAP L4 ``sm_rootzone``
    band over that window — the same reduction the soil module publishes
    under ``soil_moisture_rootzone`` — so requested and baseline values
    are the same quantity at whole-year offsets. A negative anomaly means
    the root zone was drier than the local interannual reference.

    A soil-moisture anomaly describes soil water status relative to the
    local reference. Low soil moisture does not by itself prove lack of
    irrigation, and it does not distinguish rainfall deficit from
    irrigation deficit.
    """

    key = "soil_moisture_rootzone_anomaly"
    display_name = "Root-Zone Soil Moisture Anomaly"
    display_name_fa = "آنومالی رطوبت خاک ناحیه ریشه"
    dataset_ids = ("NASA/SMAP/SPL4SMGP/008",)
    default_scale = SMAP_L4_SCALE
    unit = "m3/m3"
    baseline_years = SM_ANOMALY_BASELINE_YEARS
    min_years = SM_ANOMALY_MIN_YEARS
    formula_text = (
        "anomaly = mean(sm_rootzone, SMAP L4) over the requested window "
        "minus the mean of the same quantity over the same calendar "
        "window in each preceding year"
    )
    aggregation_text = (
        "time mean of the SMAP L4 3-hourly steps per window, then "
        "spatial mean; the baseline is the mean of one such window mean "
        "per preceding year"
    )
    description = (
        "Mean root-zone soil moisture for the requested period minus "
        "the mean of the same quantity over the same calendar window in "
        "each preceding year, from SMAP L4. A negative anomaly means the "
        "root zone was drier than the local interannual reference. This "
        "describes soil water status; it does not distinguish rainfall "
        "deficit from irrigation deficit."
    )
    limitations = (
        "SMAP L4 is a modelled product at roughly 11 km; its root zone "
        "is the model's 0-100 cm layer, not a measured crop rooting "
        "depth.",
        "The SMAP L4 archive begins in March 2015, so the baseline is "
        "short and a recent request may have few contributing years.",
        "A soil-moisture anomaly describes soil water status relative to "
        "the local reference; low soil moisture does not by itself prove "
        "lack of irrigation, and it does not distinguish rainfall "
        "deficit from irrigation deficit.",
        "A baseline of a few years separates an anomaly from ordinary "
        "interannual variability only coarsely.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("sm_rootzone",)

    def _window_value(
        self, context: MetricContext, ee_module: Any
    ) -> Tuple[Optional[float], int, QualityLevel]:
        stats, step_count = _reduce_smap_rootzone(context, ee_module)
        quality = assess_quality(
            image_count=max(step_count, 1),
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=REANALYSIS_THRESHOLDS,
        )
        return stats.mean, step_count, quality


# ==========================================================================
# 3. Deliberately unavailable irrigation metrics
# ==========================================================================


class _UnavailableIrrigationMetric(Metric):
    """An irrigation metric this engine deliberately does not compute.

    Registered so the catalog can answer the question the metric
    represents with the specific reason it cannot be answered, rather
    than with silence that could be mistaken for an oversight. It is
    structurally incapable of carrying a value: ``compute`` has no path
    that returns anything but an unavailable result.
    """

    domain = MetricDomain.IRRIGATION
    measurement_basis = MeasurementBasis.INFERENCE
    dataset_ids: Tuple[str, ...] = ()
    unavailable_code: str = "unsupported_water_balance_terms"
    unavailable_reason: str = ""

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


class IrrigationWaterRequirementMetric(_UnavailableIrrigationMetric):
    """Estimated irrigation water requirement: not produced.

    A defensible irrigation requirement needs every term of
    ``requirement = demand - effective rainfall - usable soil water``
    explicitly defined. The engine observes ET demand and rainfall, but
    runoff, drainage and any irrigation already applied are unobserved,
    and assuming them to be zero cannot be scientifically justified for
    an uninstrumented field. No verified crop coefficient, crop rooting
    depth or irrigation record exists in any registered dataset either.
    The ET-minus-precipitation deficit is published under its own key as
    the demand-minus-supply context this metric would build on.
    """

    key = "irrigation_water_requirement"
    display_name = "Estimated Irrigation Water Requirement"
    display_name_fa = "نیاز آبی آبیاری (برآوردی)"
    unit = "mm"
    unavailable_code = "unsupported_water_balance_terms"
    unavailable_reason = (
        "An estimated irrigation water requirement would subtract "
        "effective rainfall and usable soil-water contribution from "
        "water demand. The engine observes demand (MOD16 ET) and "
        "rainfall (ERA5-Land), but runoff, drainage and irrigation "
        "already applied are unobserved, and assuming them to be zero "
        "cannot be scientifically justified for an uninstrumented "
        "field. No verified crop coefficient, crop rooting depth or "
        "irrigation record exists in any registered dataset to "
        "constrain the remaining terms, so any number this metric "
        "produced would rest on invented assumptions. The ET minus "
        "precipitation deficit is published under its own key as the "
        "demand-minus-supply context."
    )
    description = (
        "Not produced. A defensible estimate requires runoff, drainage "
        "and irrigation terms that no registered dataset observes, plus "
        "crop parameters that do not exist in this engine. The "
        "ET-minus-precipitation deficit is published instead."
    )
    limitations = (
        "Requires water-balance terms (runoff, drainage, applied "
        "irrigation) that are unobserved and must not be assumed zero, "
        "and crop parameters (coefficient, rooting depth) that no "
        "registered dataset supplies.",
        "The ET-minus-precipitation deficit published under "
        "et_precipitation_deficit is the demand-minus-supply context, "
        "not an irrigation instruction.",
    )


class GrossIrrigationRequirementMetric(_UnavailableIrrigationMetric):
    """Gross applied irrigation requirement: not produced.

    Gross requirement divides a net requirement by an irrigation
    efficiency. The net requirement is itself unavailable (see
    ``irrigation_water_requirement``), and no efficiency parameter is
    supplied by any registered dataset. The architecture can carry an
    explicitly provided efficiency through the context options for a
    future decision-support layer, but no default efficiency may be
    invented.
    """

    key = "gross_irrigation_requirement"
    display_name = "Gross Irrigation Requirement"
    display_name_fa = "نیاز آبی آبیاری ناخالص"
    unit = "mm"
    unavailable_code = "no_efficiency_parameter"
    unavailable_reason = (
        "A gross irrigation requirement divides a net requirement by an "
        "irrigation-system efficiency. The net requirement is not "
        "produced (see irrigation_water_requirement), and no efficiency "
        "parameter is supplied by any registered dataset. No default "
        "efficiency — 100 percent or any other number — may be assumed, "
        "so the gross figure cannot be computed. The engine can carry an "
        "explicitly user-provided efficiency through the request options "
        "for a future decision-support layer."
    )
    description = (
        "Not produced. Gross requirement needs a net requirement and an "
        "explicitly supplied irrigation efficiency; neither is available "
        "and no default efficiency may be assumed."
    )
    limitations = (
        "Requires the net irrigation requirement, which is itself "
        "unavailable, and an irrigation efficiency that must be supplied "
        "explicitly rather than defaulted.",
    )


class CropEvapotranspirationMetric(_UnavailableIrrigationMetric):
    """Crop-specific evapotranspiration: not produced.

    Crop ET in the FAO-56 sense multiplies reference ET by a crop
    coefficient that depends on the crop and its growth stage. No
    registered dataset identifies the crop or supplies a verified Kc,
    and the MODIS PET band is potential evapotranspiration, not FAO-56
    reference ET0, so it cannot stand in for the reference term.
    """

    key = "crop_evapotranspiration"
    display_name = "Crop Evapotranspiration"
    display_name_fa = "تبخیر-تعرق محصول"
    unit = "mm"
    unavailable_code = "no_verified_crop_coefficient"
    unavailable_reason = (
        "Crop evapotranspiration in the FAO-56 sense is reference ET "
        "multiplied by a crop coefficient, and the coefficient depends "
        "on the crop and its growth stage. No registered dataset "
        "identifies which crop is growing, no verified coefficient table "
        "exists in this engine, and the MODIS PET band is potential "
        "evapotranspiration, not FAO-56 reference ET0, so it cannot "
        "stand in for the reference term. Actual ET published under "
        "evapotranspiration describes what the land surface did "
        "evaporate and transpire, which is the observable quantity."
    )
    description = (
        "Not produced. Crop ET needs a verified crop coefficient and "
        "FAO-56 reference ET; neither exists here, and MODIS PET is not "
        "ET0. Actual ET is published instead."
    )
    limitations = (
        "This metric is not produced: the engine does not identify the "
        "crop, does not hold a verified crop coefficient, and the MODIS "
        "PET band is not FAO-56 reference ET0.",
        "Actual ET published under evapotranspiration is the observable "
        "quantity and is not crop-specific.",
    )


# ==========================================================================
# Metric collections
# ==========================================================================


IRRIGATION_METRICS: Tuple[Metric, ...] = (
    PrecipitationCumulativeMetric(),
    ETPrecipitationDeficitMetric(),
    PrecipitationAnomalyMetric(),
    EvapotranspirationAnomalyMetric(),
    SoilMoistureRootZoneAnomalyMetric(),
)

UNAVAILABLE_IRRIGATION_METRICS: Tuple[Metric, ...] = (
    IrrigationWaterRequirementMetric(),
    GrossIrrigationRequirementMetric(),
    CropEvapotranspirationMetric(),
)

ALL_IRRIGATION_METRICS: Tuple[Metric, ...] = (
    IRRIGATION_METRICS + UNAVAILABLE_IRRIGATION_METRICS
)
