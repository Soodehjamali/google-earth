"""Sentinel-1 radar canopy signals (Phase CD-3).

Complementary C-band backscatter observations for canopy
structure/moisture analysis, from ``COPERNICUS/S1_GRD``:

* ``vv`` — VV co-polarized backscatter mean (dB)
* ``vh`` — VH cross-polarized backscatter mean (dB)
* ``vh_vv`` — cross-polarization ratio as a dB difference (``VH - VV``)
* ``rvi`` — Radar Vegetation Index, dual-polarization form

Every window uses one homogeneous acquisition subset — IW mode,
dual-polarization VV+VH, descending pass — so scenes with incompatible
geometry are never mixed. The metrics share a composition step (build
a filtered temporal-mean composite) but compute and report
independently, like the optical indices.

Temporal aggregation is a deliberate choice, not a copy of the
optical median composite: a temporal MEAN in the collection's native
decibels. Averaging successive acquisitions suppresses speckle, the
dominant noise in SAR, while a median would preserve it. The dB-domain
mean approximates the power-domain mean closely enough for a
monitoring signal, and staying in decibels keeps the whole path in
the units the collection publishes.

There is deliberately no radar baseline/anomaly here. A decadal
same-calendar baseline would span the Sentinel-1B outage (December
2021 to December 2024, single-satellite 12-day revisit), the arrival
of Sentinel-1C, and early-archive sparsity, while pass-level
filtering alone cannot guarantee identical incidence geometry
(different relative orbits share a pass). Forcing the optical
ten-year policy onto that record would produce comparisons the
inputs do not support, so the radar metric comes first and the
anomaly is deferred until the path is validated against real data.

Scientific boundary: C-band backscatter mixes canopy structure,
biomass, soil and roughness contributions. It is
moisture-sensitive but is not a measurement of leaf water, does not
penetrate to any specific leaf layer, and says nothing about upper,
middle or lower leaves. These metrics are complementary canopy
structural/moisture-sensitive radar signals — never middle-leaf
moisture, never a percentage of dry leaves, never a diagnosis.
"""

from __future__ import annotations

import math
from typing import Any, List, Tuple

from app.core.logging import get_logger
from app.services.agriculture import indices as pure
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.quality import (
    SAR_THRESHOLDS,
    assess_quality,
    describe_quality,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    QualityLevel,
    SpatialStats,
)
from app.services.agriculture.vegetation import _reduce_index

logger = get_logger(__name__)

__all__ = [
    "VVBackscatterMetric",
    "VHBackscatterMetric",
    "VHVVRatioMetric",
    "RVIMetric",
    "RADAR_METRICS",
    "build_s1_composite",
    "S1_DATASET_ID",
    "S1_MODE",
    "S1_PASS",
    "S1_SCALE",
]

S1_DATASET_ID = "COPERNICUS/S1_GRD"

#: Interferometric Wide Swath: the mode routinely acquired over land,
#: 10 m ground range detected product, dual-polarization VV+VH.
S1_MODE = "IW"

#: Fixed orbit-pass policy. Ascending and descending passes view the
#: field from opposite sides with different incidence geometry, so
#: mixing them would fold acquisition geometry into every temporal
#: comparison. Descending (morning) acquisitions are used throughout:
#: pre-dawn equilibration and calmer morning conditions make them the
#: steadier choice for vegetation time series.
S1_PASS = "DESCENDING"

#: Native IW GRD resolution. Reductions run at this scale so the
#: reported resolution is the true one.
S1_SCALE = 10

#: Natural logarithm of ten, for the decibel-to-linear conversion in
#: the RVI image algebra below.
_LN10 = math.log(10.0)


# --------------------------------------------------------------------------
# Shared Earth Engine helpers
# --------------------------------------------------------------------------


def build_s1_composite(
    context: MetricContext,
    ee_module: Any,
) -> Tuple[Any, int]:
    """Build a homogeneous filtered temporal-mean composite.

    The filter admits only IW-mode dual-polarization VV+VH
    descending-pass acquisitions over the context's period, so every
    scene in the composite shares instrument mode, polarizations and
    orbit direction. Scenes failing any criterion are excluded
    server-side, never averaged in.

    Returns a ``(composite, acquisition_count)`` pair. The count is
    the number of acquisitions that survived filtering, which the
    quality assessment needs. There is no cloud masking for SAR and
    none is invented: C-band largely penetrates cloud.
    """
    collection = (
        ee_module.ImageCollection(S1_DATASET_ID)
        .filterBounds(context.geometry)
        .filterDate(context.start_date, context.end_date)
        .filter(ee_module.Filter.eq("instrumentMode", S1_MODE))
        .filter(
            ee_module.Filter.listContains(
                "transmitterReceiverPolarisation", "VV"
            )
        )
        .filter(
            ee_module.Filter.listContains(
                "transmitterReceiverPolarisation", "VH"
            )
        )
        .filter(ee_module.Filter.eq("orbitProperties_pass", S1_PASS))
        .select(["VV", "VH"])
    )

    acquisition_count = int(collection.size().getInfo())
    composite = collection.mean()
    return composite, acquisition_count


# --------------------------------------------------------------------------
# Base class for the radar signals
# --------------------------------------------------------------------------


class _RadarMetric(Metric):
    """Common behaviour for a Sentinel-1 derived radar signal."""

    domain = MetricDomain.VEGETATION
    dataset_ids = (S1_DATASET_ID,)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = S1_SCALE

    #: Key into the RADAR_* registries in the pure indices module.
    radar_name: str = ""

    #: Polarizations read from Sentinel-1.
    required_polarizations: Tuple[str, ...] = ()

    def effective_scale(self, context: MetricContext) -> int:
        """The working resolution is fixed by the IW GRD product."""
        return S1_SCALE

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        scale = S1_SCALE

        composite, acquisition_count = build_s1_composite(context, ee)

        expression = self.build_expression(composite, ee)
        signal_image = expression.rename(self.radar_name)

        stats = _reduce_index(
            signal_image, self.radar_name, context, ee, scale
        )

        if acquisition_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No Sentinel-1 acquisitions matched the requested "
                    "period and the IW / VV+VH / descending-pass filter, "
                    "so this signal was not computed."
                ),
                unit=self.unit,
            )

        quality = assess_quality(
            image_count=acquisition_count,
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=SAR_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=list(self.required_polarizations),
            formula=pure.RADAR_FORMULA_TEXT.get(
                self.radar_name.lower(), ""
            ),
            quality=quality,
            image_count=acquisition_count,
            aggregation_method=(
                "temporal mean composite (IW mode, VV+VH, descending "
                "pass), then spatial mean"
            ),
            extra_limitations=(
                "This is a complementary canopy structural and "
                "moisture-sensitive radar signal. It does not measure "
                "leaf water content and says nothing about upper, "
                "middle or lower leaves.",
            ),
            extra_caveats=(
                f"Acquisition subset: {S1_MODE} mode, VV+VH "
                f"dual-polarization, {S1_PASS} pass; "
                f"{acquisition_count} acquisition(s) in the window.",
            ),
        )

        if quality is QualityLevel.INSUFFICIENT or not stats.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=self._insufficient_message(
                    acquisition_count, stats
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))
        value = stats.mean

        low, high = pure.RADAR_EXPECTED_RANGE.get(
            self.radar_name.lower(), (-100.0, 100.0)
        )
        if value is not None and not (low <= value <= high):
            warnings.append(
                f"Mean value {value:.3f} falls outside the expected range "
                f"{low} to {high}. This usually indicates a compositing "
                "problem rather than a real surface condition."
            )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=value,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )

    def _insufficient_message(
        self, acquisition_count: int, stats: SpatialStats
    ) -> str:
        """Explain precisely why the signal could not be reported."""
        if acquisition_count == 0:
            return (
                "No usable acquisitions were found for this period, so no "
                "value is reported. Reporting zero would misrepresent an "
                "unobserved field as a measured one."
            )
        if stats.valid_pixel_count == 0:
            return (
                f"{acquisition_count} acquisition(s) were found but every "
                "pixel in the requested area was invalid. No value is "
                "reported."
            )
        return (
            f"Only {stats.valid_pixel_count} valid pixel(s) across "
            f"{acquisition_count} acquisition(s), covering "
            f"{stats.coverage_percent:.1f} percent of the requested area. "
            "This is too little to report a trustworthy value."
        )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        """Build the Earth Engine image for this signal."""
        raise NotImplementedError


class VVBackscatterMetric(_RadarMetric):
    key = "vv"
    display_name = "VV Backscatter"
    display_name_fa = "پس‌پراکنش VV"
    unit = "dB"
    radar_name = "VV"
    required_polarizations = ("VV",)
    description = (
        "Sentinel-1 VV co-polarized backscatter, temporal mean over the "
        "requested window in decibels. Sensitive to surface roughness, "
        "soil moisture and canopy structure together."
    )
    limitations = (
        "A single backscatter value mixes canopy, soil and roughness "
        "contributions; it is not a vegetation-only signal and not a "
        "measurement of leaf water.",
        "Affected by incidence angle, which varies between satellite "
        "tracks even within the same orbit pass.",
        "Subject to speckle; the temporal mean suppresses it but a "
        "window with few acquisitions remains noisy.",
        "Says nothing about upper, middle or lower leaves.",
    )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.select("VV")


class VHBackscatterMetric(_RadarMetric):
    key = "vh"
    display_name = "VH Backscatter"
    display_name_fa = "پس‌پراکنش VH"
    unit = "dB"
    radar_name = "VH"
    required_polarizations = ("VH",)
    description = (
        "Sentinel-1 VH cross-polarized backscatter, temporal mean over "
        "the requested window in decibels. Cross-polarization responds "
        "more strongly to volume scattering within vegetation than VV."
    )
    limitations = (
        "A single backscatter value mixes canopy, soil and roughness "
        "contributions; it is not a vegetation-only signal and not a "
        "measurement of leaf water.",
        "Affected by incidence angle, which varies between satellite "
        "tracks even within the same orbit pass.",
        "Subject to speckle; the temporal mean suppresses it but a "
        "window with few acquisitions remains noisy.",
        "Says nothing about upper, middle or lower leaves.",
    )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.select("VH")


class VHVVRatioMetric(_RadarMetric):
    key = "vh_vv"
    display_name = "VH/VV (dB difference)"
    display_name_fa = "نسبت VH/VV (تفاضل دسی‌بل)"
    unit = "dB"
    radar_name = "VHVV"
    required_polarizations = ("VV", "VH")
    description = (
        "Cross-polarization ratio in the log domain: VH minus VV in "
        "decibels, the exact equivalent of the linear power ratio "
        "VH / VV. Higher values indicate relatively more volume "
        "scattering from vegetation."
    )
    limitations = (
        "A log-domain difference, reported in dB: it must not be read "
        "as a linear ratio and never combined with linear quantities.",
        "Responds to canopy structure and biomass as well as moisture; "
        "it is not a measurement of leaf water.",
        "Affected by incidence angle, which varies between satellite "
        "tracks even within the same orbit pass.",
        "Says nothing about upper, middle or lower leaves.",
    )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.expression(
            "VH - VV",
            {
                "VH": composite.select("VH"),
                "VV": composite.select("VV"),
            },
        )


class RVIMetric(_RadarMetric):
    key = "rvi"
    display_name = "RVI (dual-pol)"
    display_name_fa = "شاخص پوشش گیاهی راداری (RVI)"
    unit = "ratio"
    radar_name = "RVI"
    required_polarizations = ("VV", "VH")
    description = (
        "Radar Vegetation Index in the dual-polarization form for "
        "Sentinel-1: 4*VH/(VV+VH) in linear power, 0 for a bare "
        "surface and rising with volume scattering (crops typically "
        "0.3 to 1.0). A structure-sensitive indicator of vegetation "
        "density, not of leaf water."
    )
    limitations = (
        "The dual-pol form assumes the ECO-SAR convention for "
        "Sentinel-1 VV/VH; it is an indicator of vegetation density, "
        "not a measurement of leaf water or biomass.",
        "Requires conversion from decibels to linear power; the "
        "conversion is exact but amplifies noise in very dark pixels.",
        "Affected by incidence angle, soil moisture and roughness, "
        "which all enter the two backscatter terms.",
        "Says nothing about upper, middle or lower leaves.",
    )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        # Converted with image algebra rather than a single
        # expression string so the computation uses only verified
        # image methods (divide, multiply, exp, add).
        vv_linear = (
            composite.select("VV").divide(10.0).multiply(_LN10).exp()
        )
        vh_linear = (
            composite.select("VH").divide(10.0).multiply(_LN10).exp()
        )
        return vh_linear.multiply(4.0).divide(vv_linear.add(vh_linear))


#: Every radar signal, in catalog order.
RADAR_METRICS: Tuple[Metric, ...] = (
    VVBackscatterMetric(),
    VHBackscatterMetric(),
    VHVVRatioMetric(),
    RVIMetric(),
)
