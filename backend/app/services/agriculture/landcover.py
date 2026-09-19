"""Land cover metrics: the categorical description of what is on the ground.

Phase I addition: Dynamic World per-class probabilities
(``land_cover_probability``) joined this module as a separate metric
collection. It reads only the nine probability bands, never the argmax
``label`` band, and derives no area from a probability. See the section
heading below for the full reasoning.

The rule that governs this module
---------------------------------
**A land-cover class code is a label, not a number.**

Every other module in this engine reduces a continuous field and reports
a mean, a median and a set of percentiles. None of that works here.
Class 4 (Deciduous Broadleaf Forests) is not "twice" class 2 (Evergreen
Broadleaf Forests), the difference between class 12 and class 13 is not a
distance, and the mean of a field that is half water (17) and half
cropland (12) is 14.5 — a number that describes neither and happens to
collide with a real class, Cropland/Natural Vegetation Mosaics. A
downstream reader would act on it.

So this module never touches ``SpatialStats``. Categorical results are
carried in a :class:`~app.services.agriculture.types.ClassHistogram`,
which counts pixels per class, and ``MetricResult`` enforces at
construction that a result carries either a histogram or a numeric value
but never both.

What this module will not claim
-------------------------------
* **No crop species.** ``LC_Type1`` offers one generic *Croplands* class
  (12) and one *Cropland/Natural Vegetation Mosaics* class (14). It
  cannot distinguish wheat from maize from rice from pistachio, and a
  metric that named one would be inventing it.
* **No combined cropland fraction.** Classes 12 and 14 are kept apart.
  Class 12 is over 60% cultivated; class 14 is 40-60% cultivation mixed
  with natural vegetation. Adding them would overstate cultivated extent
  by an amount the product does not let us correct, so the two are
  reported separately and a caller who wants a total does the addition
  knowing what it means.
* **No confidence score from QC.** The ``QC`` band's ten values are
  post-processing event codes, not a ranking. See
  :class:`LandCoverQualityMetric`.
* **No interpolation between years.** The product is annual. A mid-year
  request is mapped to its containing product year, and a request that
  spans several years is reported per year rather than averaged into a
  fiction of a single "period" classification.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.aggregation import (
    build_class_reducer,
    estimate_pixel_count,
    parse_class_histogram,
    pixel_area_sq_m,
)
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.quality import (
    MODIS_THRESHOLDS,
    assess_quality,
)
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.registry.datasets import (
    MCD12Q1_CROPLAND_CLASSES,
    MCD12Q1_CROPLAND_MOSAIC_CLASS,
    MCD12Q1_IGBP_CLASSES,
    MCD12Q1_QC_CLASSES,
    MCD12Q1_QC_PRIMARY_VALUES,
    MCD12Q1_STRICT_CROPLAND_CLASS,
)
from app.services.agriculture.types import (
    ClassHistogram,
    MeasurementBasis,
    MetricResult,
    QualityLevel,
    SpatialStats,
)

logger = get_logger(__name__)

__all__ = [
    "LandCoverClassMetric",
    "LandCoverQualityMetric",
    "LandCoverProbabilityMetric",
    "CropTypeMetric",
    "IrrigationMetric",
    "MCD12Q1",
    "DYNAMIC_WORLD",
    "DYNAMIC_WORLD_WORKING_SCALE",
    "DYNAMIC_WORLD_PROBABILITY_BANDS",
    "LANDCOVER_WORKING_SCALE",
    "LANDCOVER_METRICS",
    "UNAVAILABLE_LANDCOVER_METRICS",
    "ALL_LANDCOVER_METRICS",
    "DYNAMIC_WORLD_METRICS",
    "CROP_TYPE_UNAVAILABLE_REASON",
    "IRRIGATION_UNAVAILABLE_REASON",
    "resolve_product_year",
    "reduce_dynamic_world_probabilities",
]


#: The one land-cover dataset this module reads.
MCD12Q1 = "MODIS/061/MCD12Q1"

#: The product's own grid. Reducing at anything finer would resample a
#: 500 m classification and then report the finer number as the result's
#: resolution, which would be false precision about a product that cannot
#: resolve it.
LANDCOVER_WORKING_SCALE = 500


#: The IGBP class code for Water Bodies. Named so the value 17 has a
#: meaning at every call site, and so the frontend's class-0 mismatch is
#: visible in code rather than buried in a comment.
IGBP_WATER_BODIES = 17


def resolve_product_year(
    start_date: str,
    end_date: str,
    available_from: str = "2001-01-01",
    available_to: str = "2024-01-01",
) -> Tuple[Optional[int], List[int], Optional[str]]:
    """Map a requested date range onto the annual product's years.

    MCD12Q1 publishes one classification image per calendar year. A
    request therefore does not describe a period in the way a daily or
    eight-day product does; it names one or more product years, and the
    honest answer states which year each image belongs to.

    The mapping is deliberately literal:

    * every product year that the request *overlaps at all* is included,
      because dropping a year the user asked about would silently narrow
      the answer;
    * a request entirely before ``available_from`` or after
      ``available_to`` yields no years and a reason, never a substitute
      year.

    Returns:
        ``(single_year, all_years, reason)``. ``single_year`` is the
        product year when the request resolves to exactly one, which is
        the common case and the one the API reports directly.
        ``all_years`` is every overlapping product year in ascending
        order, so a multi-year request reports each year separately
        instead of averaging them. ``reason`` is set only when no year
        is available.
    """
    from app.services.agriculture.base import _parse_date  # local: private helper

    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start is None or end is None:
        return None, [], "invalid_dates"
    if start > end:
        return None, [], "invalid_dates"

    first = _parse_date(available_from)
    last = _parse_date(available_to)
    if first is None or last is None:
        return None, [], "invalid_dates"

    overlap_start = max(start, first)
    overlap_end = min(end, last)
    if overlap_start > overlap_end:
        # No product year covers any part of the request. Report that
        # explicitly; do not clamp to the nearest available year.
        return None, [], "outside_product_coverage"

    years = list(range(overlap_start.year, overlap_end.year + 1))
    if not years:
        return None, [], "outside_product_coverage"
    if len(years) == 1:
        return years[0], years, None
    return None, years, None


def _collect_class_histogram(
    context: MetricContext,
    ee_module: Any,
    band_name: str,
    class_names: Dict[int, str],
    scale: int = LANDCOVER_WORKING_SCALE,
    drop_codes: Sequence[int] = (),
) -> Tuple[ClassHistogram, int, Optional[int]]:
    """Reduce one categorical band to a class histogram.

    The image is the *first* classification in the resolved product year,
    not a mean over the year. Averaging annual classifications would
    interpolate between labels, which is exactly the arithmetic this
    module exists to avoid.

    Returns ``(histogram, image_count, product_year)``.
    """
    collection = (
        ee_module.ImageCollection(MCD12Q1)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
        .select([band_name])
    )

    image_count = int(collection.size().getInfo())
    if image_count <= 0:
        return ClassHistogram(), 0, None

    # The yearly classification is a single image, so first() is the
    # product for the year rather than an arbitrary pick from a stack.
    classification = collection.first()

    raw = classification.reduceRegion(
        reducer=build_class_reducer(ee_module),
        geometry=context.geometry,
        scale=scale,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()

    area_sq_m = context.option("area_sq_m")
    total_pixels = estimate_pixel_count(area_sq_m, scale)

    # The payload's shape is resolved inside the parser, which knows both
    # the flat and the band-nested form. Unwrapping here as well would be a
    # second, competing implementation of the same decision.
    histogram = parse_class_histogram(
        raw,
        class_names=class_names,
        total_pixel_count=total_pixels,
        drop_codes=drop_codes,
        band=band_name,
    )
    return histogram, image_count, None


class LandCoverClassMetric(Metric):
    """The IGBP land-cover class distribution of the analysis area.

    Answers "what is here, and how much of it?" as a set of class extents,
    never as a single number.
    """

    key = "land_cover_class"
    display_name = "Land Cover Class Distribution"
    display_name_fa = "توزیع کلاس پوشش زمین"
    unit = "class"
    domain = MetricDomain.LANDCOVER
    dataset_ids = (MCD12Q1,)
    measurement_basis = MeasurementBasis.PRODUCT
    default_scale = LANDCOVER_WORKING_SCALE
    description = (
        "The distribution of IGBP land-cover classes over the analysis "
        "area for the requested year, from the MODIS yearly land cover "
        "product. Reports every class present with its pixel count and "
        "share of the classified area, and identifies the dominant class."
    )
    limitations = (
        "This is a generic land-cover classification, not a crop type. "
        "It cannot distinguish wheat from maize from rice; class 12 "
        "covers all croplands regardless of species.",
        "Classes 12 (Croplands) and 14 (Cropland/Natural Vegetation "
        "Mosaics) are reported separately and are never merged. Class 12 "
        "is over 60% cultivated while class 14 is 40-60% cultivation "
        "mixed with natural vegetation.",
        "The product is annual. A single image describes the whole "
        "calendar year and cannot show within-year change such as "
        "planting, harvest or a mid-season shift.",
        "At 500 m a pixel covers 25 hectares, so a field smaller than "
        "that may contain no pixel centred on it at all, and a class "
        "present in the field may be absent from the result entirely.",
        "Class boundaries are not precise at the pixel level: a pixel "
        "lying on the edge of two land covers is assigned to one of them, "
        "so the reported extents carry an unquantified classification "
        "error.",
        "The product lags roughly a year behind the present, so the most "
        "recent calendar year is often not yet published.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("LC_Type1",)

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        product_year, years, reason = resolve_product_year(
            context.start_date, context.end_date
        )
        if reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=reason,
                message=(
                    "MODIS land cover is an annual product published from "
                    f"{dataset.available_from} to {dataset.available_to}. "
                    "The requested period is outside that range, and no "
                    "other year is substituted for it."
                ),
                unit=self.unit,
            )

        histogram, image_count, _ = _collect_class_histogram(
            context=context,
            ee_module=ee,
            band_name="LC_Type1",
            class_names=MCD12Q1_IGBP_CLASSES,
        )

        quality = assess_quality(
            image_count=image_count,
            coverage_percent=_coverage_percent(histogram),
            valid_pixel_count=histogram.valid_pixel_count,
            thresholds=MODIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["LC_Type1"],
            formula=(
                "frequencyHistogram(LC_Type1); "
                "percent = class_pixels / classified_pixels * 100; "
                "percent_of_geometry = class_pixels / geometry_pixels * 100"
            ),
            quality=quality,
            image_count=image_count,
            aggregation_method="class histogram (pixel counts per class)",
            extra_limitations=(
                "No mean, median or percentile is reported for this "
                "metric. A land-cover class code is a label, so the "
                "average of two classes is not a class and the median "
                "would pick an arbitrary midpoint of an unordered set.",
                (
                    f"Resolved to product year {product_year}."
                    if product_year is not None
                    else "Resolved to product years "
                    + ", ".join(str(y) for y in years)
                    + ", reported per year rather than averaged."
                ),
            ),
        )

        if not histogram.entries:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No classified land-cover pixels were found over the "
                    "requested area. This is reported as insufficient data "
                    "rather than as an absence of land cover, because a "
                    "geometry smaller than one 500 m pixel may fall "
                    "between pixel centres."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if quality is QualityLevel.POOR:
            warnings.append(
                "Low valid-pixel coverage: the class percentages describe "
                "only the classified part of the area, not the whole of it."
            )
        if histogram.total_pixel_count > histogram.valid_pixel_count:
            warnings.append(
                f"{histogram.total_pixel_count - histogram.valid_pixel_count} "
                "of the covered pixels carried no class label and are "
                "excluded from the percentages."
            )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            unit=self.unit,
            class_histogram=histogram,
            provenance=provenance,
            warnings=warnings,
        )


class LandCoverQualityMetric(Metric):
    """The distribution of MCD12Q1 product quality flags.

    This metric exists to *prevent* a mistake rather than to offer a
    convenience. The ``QC`` band looks like a confidence score and is not
    one. Its ten values are specific post-processing outcomes:

    * 0 and 2 are straightforward: the pixel was classified and agreed
      with the MOD44W water mask.
    * 1 and 3 are missing data.
    * 5 and 7 are pixels the algorithm got wrong and then corrected.
    * 8 is a label borrowed from a different processing stage.

    There is no ordering. A pixel with QC 8 is not "twice as uncertain" as
    one with QC 4, and ``1 - QC/9`` would be a fabricated score with no
    meaning in the product's documentation. So this metric reports the
    flag distribution, exactly as published, and never a derived index.
    """

    key = "land_cover_quality"
    display_name = "Land Cover Product Quality Flags"
    display_name_fa = "پرچم‌های کیفیت محصول پوشش زمین"
    unit = "class"
    domain = MetricDomain.LANDCOVER
    dataset_ids = (MCD12Q1,)
    measurement_basis = MeasurementBasis.PRODUCT
    default_scale = LANDCOVER_WORKING_SCALE
    description = (
        "The distribution of MCD12Q1 QC flag values over the analysis "
        "area, reported as a class histogram. QC values are product "
        "processing-event codes, not a confidence score."
    )
    limitations = (
        "QC is not a confidence score and must not be converted into one. "
        "Its values are unordered event codes describing what "
        "post-processing did to a pixel, so no arithmetic on them is "
        "meaningful.",
        "A higher QC value is not worse than a lower one. Value 1 is "
        "unclassified land while value 2 is successfully classified "
        "water, which is not a monotonic relationship in any direction.",
        "QC describes the processing history of a pixel, not the "
        "accuracy of its label. A backfilled label (8) may be perfectly "
        "correct, and a first-pass label (0) may be wrong.",
        "The product publishes no confidence percentage, so none is "
        "reported here.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return ("QC",)

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        product_year, years, reason = resolve_product_year(
            context.start_date, context.end_date
        )
        if reason is not None:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=reason,
                message=(
                    "MODIS land cover quality flags are published "
                    "annually. The requested period is outside the "
                    "product's coverage and no other year is substituted."
                ),
                unit=self.unit,
            )

        histogram, image_count, _ = _collect_class_histogram(
            context=context,
            ee_module=ee,
            band_name="QC",
            class_names=MCD12Q1_QC_CLASSES,
        )

        quality = assess_quality(
            image_count=image_count,
            coverage_percent=_coverage_percent(histogram),
            valid_pixel_count=histogram.valid_pixel_count,
            thresholds=MODIS_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["QC"],
            formula="frequencyHistogram(QC); percent = flag_pixels / flagged_pixels * 100",
            quality=quality,
            image_count=image_count,
            aggregation_method="class histogram (pixel counts per QC flag)",
            extra_limitations=(
                "No aggregate quality score is derived from this band. "
                "Any single number computed from QC values would be an "
                "invention, because the product defines the values as "
                "unordered outcomes.",
                (
                    f"Resolved to product year {product_year}."
                    if product_year is not None
                    else "Resolved to product years "
                    + ", ".join(str(y) for y in years)
                    + "."
                ),
            ),
        )

        if not histogram.entries:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No QC flag pixels were found over the requested area."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        # Report how much of the area was classified cleanly, as a count
        # derived from the histogram rather than as a score over the
        # codes. This is arithmetic on extents, which is legitimate.
        primary_pixels = sum(
            entry.pixel_count
            for entry in histogram.entries
            if entry.code in MCD12Q1_QC_PRIMARY_VALUES
        )
        warnings: List[str] = []
        if histogram.valid_pixel_count > 0:
            primary_percent = (
                primary_pixels / histogram.valid_pixel_count * 100.0
            )
            warnings.append(
                "QC flags indicating a direct classification "
                f"(values {sorted(MCD12Q1_QC_PRIMARY_VALUES)}) account for "
                f"{primary_percent:.1f}% of the classified pixels; the "
                "remainder were altered by post-processing."
            )

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            unit=self.unit,
            class_histogram=histogram,
            provenance=provenance,
            warnings=warnings,
        )


def _coverage_percent(histogram: ClassHistogram) -> float:
    """Share of the covered geometry that carried a class label, 0-100."""
    if histogram.total_pixel_count <= 0:
        return 0.0
    return histogram.valid_pixel_count / histogram.total_pixel_count * 100.0


# --------------------------------------------------------------------------
# Metrics this engine deliberately does not produce
# --------------------------------------------------------------------------

CROP_TYPE_UNAVAILABLE_REASON = (
    "MCD12Q1 provides one generic Croplands class and one "
    "Cropland/Natural Vegetation Mosaics class. It does not identify crop "
    "species, so no metric can report wheat, maize, rice, or any other "
    "specific crop from it. The only product in the catalogue that "
    "addresses crop type is ESA WorldCereal, and it is not a crop-type "
    "classifier either: each of its images is a separate binary mask "
    "(values 0 or 100) for one product and one season, covering the single "
    "reference year 2021, and its images must be filtered by "
    "agro-ecological zone before use. Producing a crop-type metric would "
    "therefore require either inventing species from a generic class, or "
    "presenting a 2021 binary mask for one product as a present-day "
    "multi-class crop map. Neither is defensible, so no crop-type metric "
    "is produced."
)

CROP_TYPE_UNAVAILABLE_CODE = "no_crop_species_product"

IRRIGATION_UNAVAILABLE_REASON = (
    "The ESA WorldCereal suite does publish an irrigation product, but it "
    "cannot support a general irrigation metric here. It is a binary mask "
    "for one specific product rather than an irrigation classification of "
    "the landscape; it is published for the single reference year 2021 and "
    "so cannot describe any other season; it is stratified into up to 106 "
    "agro-ecological zones whose images must be filtered by aez_id, "
    "product and season and are independent of one another; and the "
    "catalogue records that zones without a product were not processed "
    "because thermal Landsat data was unavailable there, so coverage is "
    "incomplete. Irrigating status is also not derivable from MCD12Q1, "
    "which contains no irrigation information at all. No irrigation proxy "
    "is produced from either dataset."
)

IRRIGATION_UNAVAILABLE_CODE = "no_general_irrigation_product"


class _UnavailableLandCoverMetric(Metric):
    """A land-cover metric that exists in the catalog but cannot carry a value.

    Registered so that the catalog can answer "does this system know
    which crop is growing here?" with a reasoned no, instead of silence
    that a caller could mistake for an oversight.

    As in the water domain, the unavailability is structural: ``compute``
    has no path that returns a value, so a later change cannot turn one of
    these into a fabricated indicator without deliberately deleting this
    class.
    """

    domain = MetricDomain.LANDCOVER
    measurement_basis = MeasurementBasis.INFERENCE
    dataset_ids: Tuple[str, ...] = ()

    #: Text explaining precisely which input is missing.
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
            # The specific code, not the generic default.
            reason=self.unavailable_code,
            message=self.unavailable_reason,
            unit=self.unit,
            provenance=provenance,
        )

    def metadata(self) -> Dict[str, Any]:
        metadata = super().metadata()
        metadata["available"] = False
        metadata["unavailable_code"] = self.unavailable_code
        metadata["unavailable_reason"] = self.unavailable_reason
        return metadata


class CropTypeMetric(_UnavailableLandCoverMetric):
    key = "crop_type"
    display_name = "Crop Type Identification (not produced)"
    display_name_fa = "شناسایی نوع محصول (تولید نمی‌شود)"
    unit = "class"
    dataset_ids = (MCD12Q1,)
    unavailable_reason = CROP_TYPE_UNAVAILABLE_REASON
    unavailable_code = CROP_TYPE_UNAVAILABLE_CODE
    description = (
        "Crop species identification. Not produced: no dataset available "
        "to this engine identifies crop species."
    )
    limitations = (
        "Not produced. MCD12Q1 has a single generic Croplands class and "
        "the WorldCereal product suite is a set of binary per-product "
        "masks for one reference year, not a crop-type classifier.",
    )


class IrrigationMetric(_UnavailableLandCoverMetric):
    key = "irrigation"
    display_name = "Irrigation Status (not produced)"
    display_name_fa = "وضعیت آبیاری (تولید نمی‌شود)"
    unit = "class"
    unavailable_reason = IRRIGATION_UNAVAILABLE_REASON
    unavailable_code = IRRIGATION_UNAVAILABLE_CODE
    description = (
        "Irrigation status. Not produced: the one available irrigation "
        "product is a reference-year-constrained binary mask, and no "
        "irrigation signal exists in the land cover product."
    )
    limitations = (
        "Not produced. No proxy is derived from MCD12Q1 or from any "
        "other dataset.",
    )


# --------------------------------------------------------------------------
# Dynamic World — per-class probabilities (added in the Phase I audit)
# --------------------------------------------------------------------------
#
# Phase G deliberately excluded this dataset; Phase I implements it, as a
# *probabilistic* land-cover context metric rather than a hard
# classification. The design decisions Phase G deferred are made here
# explicitly:
#
# * **The argmax ``label`` band is never read.** The catalogue warns that
#   the argmax label can be confidently wrong when the top probability is
#   low, and recommends thresholding on the probability bands. This metric
#   therefore summarises the nine probability bands directly.
# * **The dominant class comes from the mean probabilities**, not from a
#   histogram of argmax labels, and is reported as a *candidate* dominant
#   class whose strength is the mean probability itself.
# * **No area is derived from a probability.** A mean crop probability of
#   0.42 does not mean 42 percent of the area is crop: the probabilities
#   are per-pixel posteriors, not sub-pixel cover fractions. No crop-area
#   metric is built from Dynamic World; the crop-area metric lives in
#   ``crop.py`` and reads the WorldCereal binary mask instead.
# * **No mapping onto IGBP codes.** The nine-class vocabulary stays as
#   published.
#
# Verified against the Dynamic World publication (Brown et al. 2022,
# Scientific Data 9:251): collection ID, band order, probabilities summing
# to 1, the 35 percent CLOUDY_PIXEL_PERCENTAGE production filter, and the
# validation confusion matrix in which the crops class reaches 88.9 percent
# user's accuracy but only about 60 percent producer's accuracy against
# expert consensus — a recall figure that is quoted in the metric's
# limitations because it bounds how much cropland this product can be
# trusted to find.

#: The one Dynamic World dataset this module reads.
DYNAMIC_WORLD = "GOOGLE/DYNAMICWORLD/V1"

#: The product's own grid. Reducing at anything finer would resample a
#: 10 m product and then report the finer number as the result's
#: resolution.
DYNAMIC_WORLD_WORKING_SCALE = 10

#: The nine probability bands, in the documented order. The ``label`` band
#: is deliberately absent: this engine never reads the argmax band.
DYNAMIC_WORLD_PROBABILITY_BANDS: Tuple[str, ...] = (
    "water",
    "trees",
    "grass",
    "flooded_vegetation",
    "crops",
    "shrub_and_scrub",
    "built",
    "bare",
    "snow_and_ice",
)

#: Below this mean probability, no class can be called a dominant context
#: even in the weak "candidate" sense. This is a reporting convention of
#: this engine, stated here and in every result, not a property of the
#: product.
DYNAMIC_WORLD_DOMINANT_MIN_PROBABILITY = 0.4


def reduce_dynamic_world_probabilities(
    context: MetricContext,
    ee_module: Any,
    bands: Sequence[str] = DYNAMIC_WORLD_PROBABILITY_BANDS,
    scale: int = DYNAMIC_WORLD_WORKING_SCALE,
) -> Tuple[Dict[str, "SpatialStats"], int]:
    """Reduce Dynamic World probability bands to per-band statistics.

    The collection is filtered by the requested period and geometry only —
    no cloud filter is applied, because the product itself exists only for
    Sentinel-2 scenes with ``CLOUDY_PIXEL_PERCENTAGE <= 35`` and ships
    pre-masked; re-filtering on a property the prediction images do not
    carry would silently drop everything.

    The temporal mean of a probability is a mean of posteriors. That is a
    defensible summary of the period and is labelled as exactly that; it
    is not a classification and never becomes one.

    Returns ``(per_band_stats, image_count)`` where ``per_band_stats`` maps
    each band name to its :class:`SpatialStats` over the geometry.
    """
    from app.services.agriculture.aggregation import (
        build_reducer,
        estimate_pixel_count,
        parse_reduction_result,
        pixel_area_sq_m,
    )

    collection = (
        ee_module.ImageCollection(DYNAMIC_WORLD)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
    )

    image_count = int(collection.size().getInfo())
    composite = collection.select(list(bands)).mean()

    raw = composite.reduceRegion(
        reducer=build_reducer(ee_module),
        geometry=context.geometry,
        scale=scale,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()

    area_sq_m = context.option("area_sq_m")
    total_pixels = estimate_pixel_count(area_sq_m, scale)

    per_band: Dict[str, SpatialStats] = {}
    for band in bands:
        per_band[band] = parse_reduction_result(
            raw or {},
            band=band,
            total_pixel_count=total_pixels,
            pixel_area_sq_m=pixel_area_sq_m(scale),
        )
    return per_band, image_count


class LandCoverProbabilityMetric(Metric):
    """Per-class probabilities from Dynamic World, as land-cover context.

    Reports the temporal mean of each of the nine published probability
    bands over the analysis area, and names the class with the highest mean
    probability as the *candidate* dominant context class. The value is
    that candidate's mean probability — a confidence for the context claim,
    not an extent, and not a classification.
    """

    key = "land_cover_probability"
    display_name = "Dynamic World Class Probabilities"
    display_name_fa = "احتمال کلاس‌های پوشش زمین (دنیای پویا)"
    unit = "probability"
    domain = MetricDomain.LANDCOVER
    dataset_ids = (DYNAMIC_WORLD,)
    measurement_basis = MeasurementBasis.PRODUCT
    default_scale = DYNAMIC_WORLD_WORKING_SCALE
    description = (
        "The mean per-class probability from the Dynamic World 10 m "
        "land-cover product over the requested period, with the class of "
        "highest mean probability reported as the candidate dominant "
        "land-cover context. The argmax label band is deliberately not "
        "used."
    )
    limitations = (
        "These are per-pixel class probabilities, not sub-pixel cover "
        "fractions: a mean crops probability of 0.42 does not mean 42 "
        "percent of the area is crop, and no area is derived from them.",
        "The dominant class is the class with the highest mean probability, "
        "reported as a candidate context. It is not a classification of "
        "the area and must not be mapped onto IGBP classes.",
        "The product is a per-scene neural network prediction. In its own "
        "validation the crops class reached about 89 percent user's "
        "accuracy but only about 60 percent producer's accuracy against "
        "expert consensus, so cropland is missed substantially more often "
        "than it is falsely reported.",
        "The argmax label band is not read, because the catalogue warns "
        "the argmax can be confidently wrong when the top probability is "
        "low.",
        "Predictions exist only where Sentinel-2 scenes met the product's "
        "own 35 percent cloud filter; masked periods leave no data rather "
        "than a zero probability.",
        "A temporal mean of per-scene probabilities describes the period "
        "as a whole and cannot show within-period land-cover change.",
        "This is generic land-cover context. It cannot identify a crop "
        "species: the crops class covers all cultivated land.",
    )

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return DYNAMIC_WORLD_PROBABILITY_BANDS

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        from app.services.agriculture.quality import (
            SENTINEL2_THRESHOLDS,
            assess_quality,
            describe_quality,
        )
        from app.services.agriculture.registry.datasets import (
            DYNAMIC_WORLD_CLASSES,
        )

        dataset = self.primary_dataset()

        per_band, image_count = reduce_dynamic_world_probabilities(
            context, ee, DYNAMIC_WORLD_PROBABILITY_BANDS
        )

        if image_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No Dynamic World predictions were available for the "
                    "requested period and area. Predictions exist only "
                    "where Sentinel-2 scenes met the product's own cloud "
                    "filter."
                ),
                unit=self.unit,
            )

        # The candidate dominant class is the class with the highest mean
        # probability — never the argmax label band. Ties resolve to the
        # lower class code so the result is deterministic.
        means = {
            band: stats.mean for band, stats in per_band.items()
        }
        scored = [
            (band, mean) for band, mean in means.items() if mean is not None
        ]
        if not scored:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Dynamic World predictions were found but every pixel "
                    "in the requested area was masked. No probability is "
                    "reported."
                ),
                unit=self.unit,
            )

        top_band, top_mean = max(scored, key=lambda pair: (pair[1], -DYNAMIC_WORLD_PROBABILITY_BANDS.index(pair[0])))
        top_stats = per_band[top_band]

        quality = assess_quality(
            image_count=image_count,
            coverage_percent=top_stats.coverage_percent,
            valid_pixel_count=top_stats.valid_pixel_count,
            thresholds=SENTINEL2_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=list(DYNAMIC_WORLD_PROBABILITY_BANDS),
            formula=(
                "per class p: mean over the period of the published "
                "probability band, spatially averaged; dominant = "
                "argmax over class mean probabilities (the argmax label "
                "band is not read)"
            ),
            quality=quality,
            image_count=image_count,
            aggregation_method=(
                "temporal mean composite, then spatial mean per "
                "probability band"
            ),
            extra_limitations=(
                "The reported value is the mean probability of the "
                "candidate dominant class, not an area and not a share of "
                "the geometry.",
            ),
        )

        if quality is QualityLevel.INSUFFICIENT:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"Only {top_stats.valid_pixel_count} valid pixel(s) "
                    f"across {image_count} prediction(s), covering "
                    f"{top_stats.coverage_percent:.1f} percent of the "
                    "area. No probability is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            "Mean class probabilities over the period: "
            + ", ".join(
                f"{DYNAMIC_WORLD_CLASSES.get(band, band)} {means[band]:.2f}"
                for band in DYNAMIC_WORLD_PROBABILITY_BANDS
                if means.get(band) is not None
            ),
            (
                f"Candidate dominant land-cover context: "
                f"{DYNAMIC_WORLD_CLASSES.get(top_band, top_band)} "
                f"(mean probability {top_mean:.2f}). This is a context "
                "statement, not a classification."
            ),
        ]
        if top_mean < DYNAMIC_WORLD_DOMINANT_MIN_PROBABILITY:
            warnings.append(
                f"The highest mean probability is only {top_mean:.2f}, "
                "below the reporting floor of "
                f"{DYNAMIC_WORLD_DOMINANT_MIN_PROBABILITY:.2f}, so no "
                "class can be called a dominant context even in the "
                "candidate sense."
            )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=top_mean,
            unit=self.unit,
            stats=top_stats,
            provenance=provenance,
            warnings=warnings,
        )


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------

LANDCOVER_METRICS: Tuple[Metric, ...] = (
    LandCoverClassMetric(),
    LandCoverQualityMetric(),
)

#: Dynamic World lives in its own collection, deliberately outside
#: ``LANDCOVER_METRICS``: the ``landcover`` analysis type and its serialised
#: payload are pinned to the MCD12Q1 categorical contract, and this metric
#: must not silently change what that analysis computes. Registration is
#: shared through ``register_all_metrics``.
DYNAMIC_WORLD_METRICS: Tuple[Metric, ...] = (
    LandCoverProbabilityMetric(),
)

UNAVAILABLE_LANDCOVER_METRICS: Tuple[Metric, ...] = (
    CropTypeMetric(),
    IrrigationMetric(),
)

ALL_LANDCOVER_METRICS: Tuple[Metric, ...] = (
    LANDCOVER_METRICS + UNAVAILABLE_LANDCOVER_METRICS
)
