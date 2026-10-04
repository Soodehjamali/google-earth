"""Seasonal canopy-moisture anomalies (Phase CD-2).

Interannual anomalies of the Sentinel-2 vegetation/moisture indices
against same-calendar baseline windows:

* ``ndmi_anomaly`` — NDMI (Gao) vegetation-moisture anomaly (water domain)
* ``msi_anomaly`` — MSI moisture-stress anomaly (water domain)
* ``ndre_anomaly`` — NDRE red-edge condition anomaly (vegetation domain)

Each metric reuses the Phase K baseline framework through
:class:`~app.services.agriculture.irrigation._BaselineAnomalyMetric`:
the same calendar window in preceding years, whole-year offsets with
leap-day folding, ``anomaly = current - mean(baseline years)``, and a
refusal whenever fewer than ``min_years`` baseline years contribute.
No second baseline framework is introduced here.

Each window's value is produced by the already verified sibling index
metric (``NDMIMetric``, ``MSIMetric``, ``NDREMetric``), so the requested
and baseline values are the identical computation — same product,
bands, SCL cloud masking, median compositing and spatial reduction —
at whole-year offsets. Nothing is re-read and no formula is restated.

Scientific boundary: these are temporal anomalies of remotely sensed
optical indices — a vegetation moisture anomaly, a canopy moisture
anomaly, an optical stress anomaly, a seasonal moisture departure.
They are not measurements of leaf drying, not layer-specific drying,
not percentages of dry leaves, not diagnoses and not causal
attribution. The middle-canopy proxy belongs to a later phase.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple, Type

from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.irrigation import _BaselineAnomalyMetric
from app.services.agriculture.types import MeasurementBasis, QualityLevel
from app.services.agriculture.vegetation import (
    NDREMetric,
    S2_DATASET_ID,
    _SpectralIndexMetric,
)
from app.services.agriculture.water import MSIMetric, NDMIMetric

__all__ = [
    "NDMIAnomalyMetric",
    "MSIAnomalyMetric",
    "NDREAnomalyMetric",
    "CANOPY_MOISTURE_METRICS",
    "CANOPY_ANOMALY_BASELINE_YEARS",
    "CANOPY_ANOMALY_MIN_YEARS",
]


#: How many preceding same-calendar windows form the seasonal baseline.
#: Ten windows is the established policy for the long-record anomaly
#: metrics in this engine (LST, precipitation, evapotranspiration).
#: Sentinel-2 surface reflectance begins in March 2017, so for a recent
#: request the effective reference is the S2-era subset of those ten
#: windows; pre-launch years contribute nothing rather than a partial
#: value.
CANOPY_ANOMALY_BASELINE_YEARS = 10

#: Fewer contributing baseline years than this and the anomaly is not
#: published: two reference years cannot separate a genuine seasonal
#: departure from ordinary interannual variability. This minimum is the
#: same threshold every anomaly metric in this engine already uses.
CANOPY_ANOMALY_MIN_YEARS = 3


class _S2IndexAnomalyMetric(_BaselineAnomalyMetric):
    """Anomaly of a Sentinel-2 spectral index against prior-year windows.

    Subclasses name the sibling index metric that produces each
    window's value. The sibling's own ``compute`` runs the full
    Sentinel-2 pipeline — SCL masking, median composite, index
    expression, spatial reduction, quality assessment — so this class
    adds only the temporal comparison, exactly as the irrigation
    anomaly metrics reuse their own sibling computations.
    """

    measurement_basis = MeasurementBasis.DERIVED
    default_scale = 20
    dataset_ids = (S2_DATASET_ID,)
    baseline_years = CANOPY_ANOMALY_BASELINE_YEARS
    min_years = CANOPY_ANOMALY_MIN_YEARS

    #: The sibling index metric class producing each window's value.
    source_metric_cls: Type[_SpectralIndexMetric]

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return tuple(self.source_metric_cls.required_bands)

    def _window_value(
        self, context: MetricContext, ee_module: Any
    ) -> Tuple[Optional[float], int, QualityLevel]:
        result = self.source_metric_cls().compute(context)
        provenance = result.provenance
        count = provenance.image_count if provenance is not None else 0
        quality = (
            provenance.quality_level
            if provenance is not None
            else QualityLevel.UNAVAILABLE
        )
        return result.value, count, quality


class NDMIAnomalyMetric(_S2IndexAnomalyMetric):
    """NDMI (Gao) seasonal moisture anomaly.

    .. math::

        anomaly = NDMI_{request}
                  - \\overline{NDMI_{baseline}}

    The requested value and every baseline value are the median
    composite spatial mean of ``(B8 - B11) / (B8 + B11)`` over the
    identical month-day window, from Sentinel-2. A negative anomaly
    means canopy moisture was below the local interannual reference
    for that seasonal window. This is a temporal anomaly of an
    optical index, not a measurement of leaf drying.
    """

    key = "ndmi_anomaly"
    display_name = "NDMI Seasonal Anomaly"
    display_name_fa = "آنومالی فصلی NDMI"
    domain = MetricDomain.WATER
    unit = "index"
    source_metric_cls = NDMIMetric
    formula_text = (
        "anomaly = (B8 - B11) / (B8 + B11) median-composite spatial mean "
        "over the requested window minus the mean of the same quantity "
        "over the same calendar window in each preceding year"
    )
    aggregation_text = (
        "median composite per window, then spatial mean; the baseline is "
        "the mean of one such window mean per preceding year"
    )
    description = (
        "Mean NDMI vegetation moisture for the requested period minus "
        "the mean of the same quantity over the same calendar window in "
        "each preceding year, from Sentinel-2. A negative anomaly means "
        "canopy moisture was below the local interannual reference for "
        "that seasonal window. This is a temporal anomaly of a remotely "
        "sensed index, not a measurement of leaf drying and not a "
        "diagnosis of its cause."
    )
    limitations = (
        "Sentinel-2 observes the canopy top-down and cannot separate "
        "upper, middle or lower leaves; no layer-specific drying is "
        "measured here.",
        "This is an anomaly of a derived moisture index, not a direct "
        "measurement of leaf water, and there is no validated conversion "
        "to a percentage of dry leaves.",
        "The shortwave infrared band is acquired at 20 m, and cloud gaps "
        "can leave a window with few usable scenes.",
        "Sentinel-2 surface reflectance begins in March 2017, so early "
        "requests have thin baselines and pre-launch baseline years "
        "contribute nothing.",
        "Cannot distinguish a water-stressed canopy from one that is "
        "senescing, diseased, or damaged by pests, and it does not "
        "attribute a cause.",
    )


class MSIAnomalyMetric(_S2IndexAnomalyMetric):
    """MSI seasonal moisture-stress anomaly.

    .. math::

        anomaly = MSI_{request}
                  - \\overline{MSI_{baseline}}

    The requested value and every baseline value are the median
    composite spatial mean of ``B11 / B8`` over the identical
    month-day window, from Sentinel-2. A positive anomaly means
    moisture stress was above the local interannual reference for
    that seasonal window. This is a temporal anomaly of an optical
    index, not a measurement of leaf drying.
    """

    key = "msi_anomaly"
    display_name = "MSI Seasonal Anomaly"
    display_name_fa = "آنومالی فصلی MSI"
    domain = MetricDomain.WATER
    unit = "index"
    source_metric_cls = MSIMetric
    formula_text = (
        "anomaly = B11 / B8 median-composite spatial mean over the "
        "requested window minus the mean of the same quantity over the "
        "same calendar window in each preceding year"
    )
    aggregation_text = (
        "median composite per window, then spatial mean; the baseline is "
        "the mean of one such window mean per preceding year"
    )
    description = (
        "Mean MSI moisture stress for the requested period minus the "
        "mean of the same quantity over the same calendar window in "
        "each preceding year, from Sentinel-2. A positive anomaly means "
        "moisture stress was above the local interannual reference for "
        "that seasonal window. This is a temporal anomaly of a remotely "
        "sensed index, not a measurement of leaf drying and not a "
        "diagnosis of its cause."
    )
    limitations = (
        "Sentinel-2 observes the canopy top-down and cannot separate "
        "upper, middle or lower leaves; no layer-specific drying is "
        "measured here.",
        "This is an anomaly of a derived stress index, not a direct "
        "measurement of leaf water, and there is no validated conversion "
        "to a percentage of dry leaves.",
        "The shortwave infrared band is acquired at 20 m, and cloud gaps "
        "can leave a window with few usable scenes.",
        "Sentinel-2 surface reflectance begins in March 2017, so early "
        "requests have thin baselines and pre-launch baseline years "
        "contribute nothing.",
        "Cannot distinguish a water-stressed canopy from one that is "
        "senescing, diseased, or damaged by pests, and it does not "
        "attribute a cause.",
    )


class NDREAnomalyMetric(_S2IndexAnomalyMetric):
    """NDRE seasonal red-edge anomaly.

    .. math::

        anomaly = NDRE_{request}
                  - \\overline{NDRE_{baseline}}

    The requested value and every baseline value are the median
    composite spatial mean of ``(B8 - B5) / (B8 + B5)`` over the
    identical month-day window, from Sentinel-2. A negative anomaly
    means red-edge condition was below the local interannual reference
    for that seasonal window, which may indicate vegetation stress but
    must not be read as direct leaf drying.
    """

    key = "ndre_anomaly"
    display_name = "NDRE Seasonal Anomaly"
    display_name_fa = "آنومالی فصلی NDRE"
    domain = MetricDomain.VEGETATION
    unit = "index"
    source_metric_cls = NDREMetric
    formula_text = (
        "anomaly = (B8 - B5) / (B8 + B5) median-composite spatial mean "
        "over the requested window minus the mean of the same quantity "
        "over the same calendar window in each preceding year"
    )
    aggregation_text = (
        "median composite per window, then spatial mean; the baseline is "
        "the mean of one such window mean per preceding year"
    )
    description = (
        "Mean NDRE red-edge condition for the requested period minus "
        "the mean of the same quantity over the same calendar window in "
        "each preceding year, from Sentinel-2. A negative anomaly means "
        "red-edge condition was below the local interannual reference "
        "for that seasonal window. This is a temporal anomaly of a "
        "remotely sensed index, not a measurement of leaf drying and "
        "not a diagnosis of its cause."
    )
    limitations = (
        "Sentinel-2 observes the canopy top-down and cannot separate "
        "upper, middle or lower leaves; no layer-specific drying is "
        "measured here.",
        "NDRE is a chlorophyll-related signal, not a measurement of leaf "
        "chlorophyll, nitrogen or water, and there is no validated "
        "conversion to a percentage of dry leaves.",
        "The red edge band is acquired at 20 m, and cloud gaps can "
        "leave a window with few usable scenes.",
        "Sentinel-2 surface reflectance begins in March 2017, so early "
        "requests have thin baselines and pre-launch baseline years "
        "contribute nothing.",
        "Cannot distinguish stress from senescence, disease or pest "
        "damage, and it does not attribute a cause.",
    )


#: Canopy-moisture anomaly metrics registered with the catalog.
CANOPY_MOISTURE_METRICS: Tuple[Metric, ...] = (
    NDMIAnomalyMetric(),
    MSIAnomalyMetric(),
    NDREAnomalyMetric(),
)
