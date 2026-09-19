"""Vegetation metrics.

Each vegetation index is an independent :class:`Metric`. They share a
composition step (build a cloud-masked median composite) but compute and
report independently, so one index failing cannot suppress the others.

The formula for every index lives in
:mod:`app.services.agriculture.indices` as a pure function. This module
builds the equivalent Earth Engine expression. The two are kept in step
by tests that evaluate both against identical synthetic reflectances.
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
    SENTINEL2_THRESHOLDS,
    assess_quality,
    describe_quality,
)
from app.services.agriculture.registry import S2_SCL_INVALID_CLASSES
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    SpatialStats,
)

logger = get_logger(__name__)

__all__ = [
    "NDVIMetric",
    "EVIMetric",
    "SAVIMetric",
    "MSAVIMetric",
    "NDREMetric",
    "LAIMetric",
    "FPARMetric",
    "FCOVERMetric",
    "VEGETATION_METRICS",
]

S2_DATASET_ID = "COPERNICUS/S2_SR_HARMONIZED"
LAI_DATASET_ID = "MODIS/061/MCD15A3H"


# --------------------------------------------------------------------------
# Shared Earth Engine helpers
# --------------------------------------------------------------------------


def _mask_sentinel2(image: Any, ee_module: Any) -> Any:
    """Mask a Sentinel-2 image using its Scene Classification Layer.

    Classes 0, 1, 3, 8, 9 and 10 are removed. Class 7, cloud with low
    probability, is retained: masking it discards a great deal of usable
    data over humid regions, and it is the caller's quality assessment
    rather than a blanket mask that should decide trust.
    """
    scl = image.select("SCL")
    invalid = ee_module.Image.constant(0)
    for class_value in S2_SCL_INVALID_CLASSES:
        invalid = invalid.Or(scl.eq(class_value))
    return image.updateMask(invalid.Not())


def build_sentinel2_composite(
    context: MetricContext,
    ee_module: Any,
    bands: Sequence[str],
    max_cloud_percent: Optional[float] = None,
) -> Tuple[Any, int]:
    """Build a cloud-masked median composite over the context's period.

    A median composite is used rather than a mean because a single
    undetected thin-cloud pixel drags a mean far more than a median, and
    over agricultural fields the median better represents the modal
    surface condition.

    Returns a ``(composite, image_count)`` pair. The image count is the
    number of scenes that survived filtering, which the quality
    assessment needs.

    Note: this deliberately performs one collection filter and one
    reduction. The pre-existing implementation loaded the collection a
    second time purely to obtain a count, which doubles the cost of every
    analysis.
    """
    collection = (
        ee_module.ImageCollection(S2_DATASET_ID)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
    )

    cloud_limit = (
        max_cloud_percent
        if max_cloud_percent is not None
        else context.cloud_max_percent
    )
    if cloud_limit is not None and cloud_limit < 100:
        collection = collection.filter(
            ee_module.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud_limit)
        )

    # Count once, from the same collection we composite.
    image_count = int(collection.size().getInfo())

    def prepare(image: Any) -> Any:
        masked = _mask_sentinel2(image, ee_module)
        # L2A reflectance is stored as integers scaled by 10000.
        return masked.select(list(bands)).multiply(0.0001)

    composite = collection.map(prepare).median()
    return composite, image_count


def _reduce_index(
    image: Any,
    index_name: str,
    context: MetricContext,
    ee_module: Any,
    scale: int,
) -> SpatialStats:
    """Reduce a single-band index image over the geometry."""
    index_image = image.select([index_name])
    reducer = build_reducer(ee_module)
    raw = index_image.reduceRegion(
        reducer=reducer,
        geometry=context.geometry,
        scale=scale,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()

    # Estimate the geometry's pixel count so coverage is a real fraction
    # rather than an unstated number.
    area_sq_m = context.option("area_sq_m")
    total_pixels = estimate_pixel_count(area_sq_m, scale)

    return parse_reduction_result(
        raw or {},
        band=index_name,
        total_pixel_count=total_pixels,
        pixel_area_sq_m=pixel_area_sq_m(scale),
    )


# --------------------------------------------------------------------------
# Base class for the spectral indices
# --------------------------------------------------------------------------


class _SpectralIndexMetric(Metric):
    """Common behaviour for a Sentinel-2 derived spectral index."""

    domain = MetricDomain.VEGETATION
    unit = "index"
    dataset_ids = (S2_DATASET_ID,)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = 10

    #: Which pure formula to use from the indices module.
    index_name: str = ""

    #: Bands required from Sentinel-2.
    required_bands: Tuple[str, ...] = ()

    #: Closest scale actually suitable for the required bands. Bands at
    #: 20 m must not be reduced at 10 m, because Earth Engine would
    #: resample them and the reported resolution would be a lie.
    band_scale: int = 10

    def effective_scale(self, context: MetricContext) -> int:
        """Use the band scale, ignoring any context-supplied scale.

        This override is the reason the attribute cannot simply be named
        ``default_scale``: for a spectral index the working resolution is
        fixed by the bands being read, not by a caller preference. Letting
        a context scale of 10 govern NDRE would resample the 20 m red edge
        band and then report 10 m resolution in the provenance.
        """
        return self.band_scale

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        scale = self.band_scale

        composite, image_count = build_sentinel2_composite(
            context, ee, self.required_bands
        )

        expression = self.build_expression(composite, ee)
        index_image = expression.rename(self.index_name)

        stats = _reduce_index(
            index_image, self.index_name, context, ee, scale
        )

        # Guard against the composite having produced nothing at all.
        if image_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No Sentinel-2 scenes matched the requested period and "
                    "cloud filter, so this index was not computed."
                ),
                unit=self.unit,
            )

        quality = assess_quality(
            image_count=image_count,
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=SENTINEL2_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=list(self.required_bands),
            formula=pure.FORMULA_TEXT.get(self.index_name, ""),
            quality=quality,
            image_count=image_count,
            aggregation_method="median composite, then spatial mean",
            extra_limitations=(
                "This index indicates vegetation condition. It does not "
                "identify a cause such as disease, a pest, or a nutrient "
                "deficiency.",
            ),
        )

        if quality is QualityLevel.INSUFFICIENT or not stats.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=self._insufficient_message(image_count, stats),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))
        value = stats.mean

        # A value outside the physically plausible range means something
        # upstream is wrong. Report it, but do not hide the number.
        low, high = pure.EXPECTED_RANGE.get(self.index_name, (-2.0, 2.0))
        if value is not None and not (low <= value <= high):
            warnings.append(
                f"Mean value {value:.3f} falls outside the expected range "
                f"{low} to {high}. This usually indicates a compositing or "
                "masking problem rather than a real surface condition."
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
        self, image_count: int, stats: SpatialStats
    ) -> str:
        """Explain precisely why the index could not be reported."""
        if image_count == 0:
            return (
                "No usable scenes were found for this period, so no value "
                "is reported. Reporting zero would misrepresent an "
                "unobserved field as a failing one."
            )
        if stats.valid_pixel_count == 0:
            return (
                f"{image_count} scene(s) were found but every pixel in the "
                "requested area was masked, most likely by cloud or by the "
                "scene classification layer. No value is reported."
            )
        return (
            f"Only {stats.valid_pixel_count} valid pixel(s) across "
            f"{image_count} scene(s), covering "
            f"{stats.coverage_percent:.1f} percent of the requested area. "
            "This is too little to report a trustworthy value."
        )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        """Build the Earth Engine expression for this index.

        Overridden by each index. Kept explicit per index rather than
        generated from a string, so the arithmetic is readable and cannot
        be broken by a typo in a band name.
        """
        raise NotImplementedError


class NDVIMetric(_SpectralIndexMetric):
    key = "ndvi"
    display_name = "NDVI"
    display_name_fa = "شاخص سبزینگی (NDVI)"
    index_name = "NDVI"
    required_bands = ("B4", "B8")
    band_scale = 10
    description = (
        "Normalized Difference Vegetation Index. A measure of greenness "
        "and canopy density."
    )
    limitations = (
        "Saturates over dense canopies, where it stops responding to "
        "further leaf area.",
        "Sensitive to soil background in sparse or early-season canopies.",
        "Affected by undetected thin cloud, which lowers the value.",
        "Cannot identify the cause of an anomaly. A low value does not "
        "distinguish drought, waterlogging, nutrient shortage, disease, "
        "pest damage or a management effect.",
    )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.normalizedDifference(["B8", "B4"])


class EVIMetric(_SpectralIndexMetric):
    key = "evi"
    display_name = "EVI"
    display_name_fa = "شاخص گیاهی بهبودیافته (EVI)"
    index_name = "EVI"
    required_bands = ("B2", "B4", "B8")
    band_scale = 10
    description = (
        "Enhanced Vegetation Index. Greenness with reduced atmospheric "
        "and soil background influence."
    )
    limitations = (
        "Noisier than NDVI over sparse vegetation, where the blue band "
        "carries little signal and much noise.",
        "More sensitive to errors in the blue band, including incomplete "
        "aerosol correction.",
        "Not comparable in absolute terms with NDVI or SAVI values.",
        "Cannot identify the cause of an anomaly. A low value does not "
        "distinguish drought, waterlogging, nutrient shortage, disease, "
        "pest damage or a management effect.",
    )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.expression(
            "2.5 * (NIR - RED) / (NIR + 6.0 * RED - 7.5 * BLUE + 1.0)",
            {
                "NIR": composite.select("B8"),
                "RED": composite.select("B4"),
                "BLUE": composite.select("B2"),
            },
        )


class SAVIMetric(_SpectralIndexMetric):
    key = "savi"
    display_name = "SAVI"
    display_name_fa = "شاخص گیاهی تعدیل‌شده با خاک (SAVI)"
    index_name = "SAVI"
    required_bands = ("B4", "B8")
    band_scale = 10
    soil_factor = 0.5
    description = (
        "Soil-Adjusted Vegetation Index. Greenness with soil background "
        "partially suppressed, for sparse canopies."
    )
    limitations = (
        "Requires an L value chosen for the canopy density; the default "
        "0.5 assumes intermediate cover and is reported in the provenance.",
        "Values are not directly comparable with NDVI or EVI.",
        "Cannot identify the cause of an anomaly. A low value does not "
        "distinguish drought, waterlogging, nutrient shortage, disease, "
        "pest damage or a management effect.",
    )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.expression(
            "((NIR - RED) / (NIR + RED + L)) * (1.0 + L)",
            {
                "NIR": composite.select("B8"),
                "RED": composite.select("B4"),
                "L": float(self.soil_factor),
            },
        )

    def build_provenance(self, **kwargs: Any) -> Provenance:
        provenance = super().build_provenance(**kwargs)
        provenance.formula = pure.FORMULA_TEXT["savi"].replace(
            "0.5", str(self.soil_factor)
        )
        return provenance


class MSAVIMetric(_SpectralIndexMetric):
    key = "msavi"
    display_name = "MSAVI"
    display_name_fa = "شاخص گیاهی تعدیل‌شده اصلاح‌شده (MSAVI)"
    index_name = "MSAVI"
    required_bands = ("B4", "B8")
    band_scale = 10
    description = (
        "Modified Soil-Adjusted Vegetation Index. Self-adjusting for soil "
        "background without an L parameter."
    )
    limitations = (
        "The square root term is undefined for some reflectance "
        "combinations, which yields no value for those pixels.",
        "Noisier than NDVI over dense canopies.",
        "Cannot identify the cause of an anomaly. A low value does not "
        "distinguish drought, waterlogging, nutrient shortage, disease, "
        "pest damage or a management effect.",
    )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.expression(
            "(2.0 * NIR + 1.0 - sqrt((2.0 * NIR + 1.0) * "
            "(2.0 * NIR + 1.0) - 8.0 * (NIR - RED))) / 2.0",
            {
                "NIR": composite.select("B8"),
                "RED": composite.select("B4"),
            },
        )


class NDREMetric(_SpectralIndexMetric):
    key = "ndre"
    display_name = "NDRE"
    display_name_fa = "شاخص لبه قرمز (NDRE)"
    index_name = "NDRE"
    required_bands = ("B5", "B8")
    band_scale = 20
    description = (
        "Normalized Difference Red Edge. A chlorophyll-related signal "
        "that saturates later than NDVI."
    )
    limitations = (
        "Acquired at 20 m, so within-field detail is coarser than NDVI.",
        "This is a chlorophyll-related signal, not a measurement of leaf "
        "chlorophyll content or of plant nitrogen.",
        "Requires the red edge band, which is unavailable before "
        "Sentinel-2 and therefore has a shorter history than NDVI.",
        "Cannot identify the cause of an anomaly. A low value does not "
        "distinguish drought, waterlogging, nutrient shortage, disease, "
        "pest damage or a management effect.",
    )

    def build_expression(self, composite: Any, ee_module: Any) -> Any:
        return composite.normalizedDifference(["B8", "B5"])


# --------------------------------------------------------------------------
# MODIS structural metrics
# --------------------------------------------------------------------------


class _MODISStructuralMetric(Metric):
    """Common behaviour for LAI, FPAR and FCOVER from MCD15A3H."""

    domain = MetricDomain.VEGETATION
    dataset_ids = (LAI_DATASET_ID,)
    measurement_basis = MeasurementBasis.PRODUCT
    default_scale = 500

    #: Band in MCD15A3H.
    source_band: str = ""

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        band_spec = dataset.band(self.source_band)
        scale = self.default_scale

        collection = (
            ee.ImageCollection(LAI_DATASET_ID)
            .filterDate(context.start_date, context.end_date)
            .filterBounds(context.geometry)
        )

        image_count = int(collection.size().getInfo())

        # Apply the documented fill sentinels, then the scale factor, so
        # a fill value can never enter the statistics as a real reading.
        def prepare(image: Any) -> Any:
            raw = image.select(self.source_band)
            masked = raw.updateMask(raw.lt(249))
            return masked.multiply(band_spec.scale_factor).rename(self.key)

        composite = collection.map(prepare).median()

        raw = composite.select([self.key]).reduceRegion(
            reducer=build_reducer(ee),
            geometry=context.geometry,
            scale=scale,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()

        area_sq_m = context.option("area_sq_m")
        stats = parse_reduction_result(
            raw or {},
            band=self.key,
            total_pixel_count=estimate_pixel_count(area_sq_m, scale),
            pixel_area_sq_m=pixel_area_sq_m(scale),
        )

        quality = assess_quality(
            image_count=image_count,
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
            aggregation_method="median composite, then spatial mean",
            extra_limitations=(
                "At 500 m this cannot describe within-field variability "
                "and is suitable only as a regional or block-scale layer.",
                "The MODIS retrieval assumes a biome look-up table, which "
                "is a poor fit over managed agricultural land.",
            ),
        )

        if image_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No scenes were available for the requested period, so "
                    "no value is reported."
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
                    f"Insufficient valid coverage: "
                    f"{stats.coverage_percent:.1f} percent of the area "
                    f"across {image_count} scene(s). No value is reported."
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
            value=stats.mean,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )

    @property
    def formula(self) -> str:
        return f"MCD15A3H {self.source_band} scaled by 0.1"


class LAIMetric(_MODISStructuralMetric):
    key = "lai"
    display_name = "Leaf Area Index"
    display_name_fa = "شاخص سطح برگ (LAI)"
    unit = "m2/m2"
    source_band = "Lai"
    description = (
        "One-sided green leaf area per unit ground area, from MODIS."
    )
    limitations = (
        "A model retrieval that assumes a biome look-up table, not a "
        "direct measurement of this field.",
        "Satellite LAI estimates are known to be biased low for row crops.",
        "Cannot distinguish leaf area of the crop from that of weeds.",
    )


class FPARMetric(_MODISStructuralMetric):
    key = "fapar"
    display_name = "Fraction of Absorbed PAR"
    display_name_fa = "کسر تابش جذب‌شده (FPAR)"
    unit = "fraction"
    source_band = "Fpar"
    description = (
        "Fraction of incoming photosynthetically active radiation "
        "absorbed by the canopy."
    )
    limitations = (
        "Retrieved jointly with LAI, so it inherits the same look-up "
        "table assumptions.",
        "Does not account for radiation absorbed by non-photosynthetic "
        "material such as stems and senescent leaves.",
    )


class FCOVERMetric(_MODISStructuralMetric):
    key = "fcover"
    display_name = "Fraction of Vegetation Cover"
    display_name_fa = "کسر پوشش گیاهی (FCOVER)"
    unit = "fraction"
    source_band = "Fcov"
    description = (
        "Fraction of ground covered by green vegetation, from MODIS."
    )
    limitations = (
        "Reports the fraction of ground covered, not crop vigour or health.",
        "At 500 m it cannot separate a crop from adjacent natural "
        "vegetation.",
    )


#: Every vegetation metric, in catalog order.
VEGETATION_METRICS: Tuple[Metric, ...] = (
    NDVIMetric(),
    EVIMetric(),
    SAVIMetric(),
    MSAVIMetric(),
    NDREMetric(),
    LAIMetric(),
    FPARMetric(),
    FCOVERMetric(),
)
