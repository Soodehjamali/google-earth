"""Crop context and crop area from the ESA WorldCereal 2021 products.

The rule that governs this module
---------------------------------
**A crop-context claim is only as strong as the product's own definition,
and every number here is bounded by the 2021 reference year.**

ESA WorldCereal publishes, for the single reference year 2021, one binary
mask per product and per season: ``classification`` takes exactly the
values 0 and 100, and a ``confidence`` band in 0-100 accompanies it. The
products relevant to this module are:

* ``temporarycrops`` (season ``tc-annual``) — land under crops with a
  less-than-one-year growing cycle that must be re-sown after harvest.
  Perennial crops and pastures are *excluded by definition*, so a low
  crop-context figure here does not mean the land is not farmed.
* ``maize`` (``tc-maize-main``, optionally ``tc-maize-second``) — a
  commodity-crop mask.
* ``wintercereals`` / ``springcereals`` — cereals of the Triticeae tribe
  (wheat, barley, rye). They are grouped because their signatures and
  seasons are too similar to separate globally; no wheat-only map exists.

What this module will not claim
-------------------------------
* **No crop species beyond the product's own.** Maize and "cereals of the
  Triticeae tribe" are the only crop identities any registered product
  supports, and only for 2021. No wheat-from-Triticeae split, no
  pistachio, no orchard.
* **No present-day or multi-year claims.** The collection covers 2021.
  A request outside 2020-01-01..2021-12-31 is out of coverage, exactly as
  the registry's OBSERVATION window states, and is never answered from a
  neighbouring season.
* **No irrigation mapping.** The irrigation product's limitations
  (single-year, AEZ-stratified, incomplete coverage) were already
  documented in the land-cover module's unavailable ``irrigation`` metric;
  nothing here revisits that decision.

Crop area
---------
The crop-area metric is a pixel-counting estimate, deliberately labelled
as such. Total geometry area is reported separately from the estimated
crop-covered area, the valid-pixel fraction is computed and enforced, and
every result states the product, the season, the 10 m working scale and
the validation accuracies the ESA reports for the product (user's 88.5,
producer's 92.1 for temporary crops). It is a class-extent estimate, not
a survey-grade boundary measurement.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.aggregation import (
    build_reducer,
    estimate_pixel_count,
    parse_reduction_result,
    pixel_area_sq_m,
)
from app.services.agriculture.base import (
    Metric,
    MetricContext,
    MetricDomain,
    _parse_date,
)
from app.services.agriculture.quality import (
    SENTINEL2_THRESHOLDS,
    assess_quality,
    describe_quality,
)
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.registry.datasets import (
    WORLDCEREAL_BINARY_VALUES,
    WORLDCEREAL_PRODUCTS,
    WORLDCEREAL_SEASONS,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    QualityLevel,
    SpatialStats,
)

logger = get_logger(__name__)

__all__ = [
    "WORLDCEREAL_ID",
    "WORLDCEREAL_WORKING_SCALE",
    "CROP_AREA_MIN_VALID_FRACTION",
    "resolve_worldcereal_image",
    "reduce_worldcereal_mask",
    "TemporaryCropContextMetric",
    "MaizeCropContextMetric",
    "CerealCropContextMetric",
    "TemporaryCropAreaMetric",
    "CropPlantingDateMetric",
    "CropHarvestDateMetric",
    "FloweringDateMetric",
    "CROP_METRICS",
    "UNAVAILABLE_CROP_METRICS",
    "ALL_CROP_METRICS",
    "PLANTING_UNAVAILABLE_REASON",
    "HARVEST_UNAVAILABLE_REASON",
    "FLOWERING_UNAVAILABLE_REASON",
]


#: The one WorldCereal collection this module reads. Phase G corrected the
#: ID (the ``v100`` suffix is mandatory); this constant is spelled out here
#: rather than imported so a registry edit cannot silently retarget the
#: metric without a test failing on the provenance.
WORLDCEREAL_ID = "ESA/WorldCereal/2021/MODELS/v100"

#: The product's own grid.
WORLDCEREAL_WORKING_SCALE = 10

#: Below this share of valid pixels, a crop-context or crop-area result is
#: refused rather than published. WorldCereal is a 10 m product with
#: essentially complete coverage inside its zones, so a coverage shortfall
#: means the geometry fell between zone footprints or was otherwise
#: unprocessed — and an extrapolated figure would be invented.
CROP_AREA_MIN_VALID_FRACTION = 0.5

#: The product's own nodata-free mask semantics: the classification takes
#: exactly 0 (not the product) or 100 (the product). Asserted against the
#: registry constants so a registry edit fails this module's tests.
_MASK_VALUES = (0, 100)
assert tuple(WORLDCEREAL_BINARY_VALUES) == _MASK_VALUES


# --------------------------------------------------------------------------
# Collection resolution
# --------------------------------------------------------------------------


def resolve_worldcereal_image(
    context: MetricContext,
    ee_module: Any,
    product: str,
    season: str,
) -> Tuple[Optional[Any], int, Optional[str]]:
    """Resolve the one image matching a product and season over the area.

    The collection must be filtered by ``product`` and ``season`` — its
    images are independent products, one per (product, season, AEZ), and
    must never be mixed. ``filterBounds`` narrows to the AEZ images that
    overlap the geometry; if several AEZ images overlap, the first is used
    and the count of matching images is returned so the caller can report
    the multi-zone situation rather than hide it.

    Returns ``(image, image_count, reason)``. ``image`` is ``None`` when
    no image matched, with ``reason`` naming the situation.
    """
    if product not in WORLDCEREAL_PRODUCTS:
        raise ValueError(
            f"Unknown WorldCereal product {product!r}. "
            f"Known products: {sorted(WORLDCEREAL_PRODUCTS)}"
        )
    if season not in WORLDCEREAL_SEASONS:
        raise ValueError(
            f"Unknown WorldCereal season {season!r}. "
            f"Known seasons: {sorted(WORLDCEREAL_SEASONS)}"
        )

    collection = (
        ee_module.ImageCollection(WORLDCEREAL_ID)
        .filterDate(context.start_date, context.end_date)
        .filterBounds(context.geometry)
        .filterMetadata("product", "equals", product)
        .filterMetadata("season", "equals", season)
    )

    image_count = int(collection.size().getInfo())
    if image_count <= 0:
        return None, 0, "no_matching_image"

    return collection.first(), image_count, None


def reduce_worldcereal_mask(
    context: MetricContext,
    ee_module: Any,
    product: str,
    season: str,
    band: str = "classification",
) -> Tuple[Optional[SpatialStats], int, int, Optional[str]]:
    """Reduce one WorldCereal mask band to per-pixel statistics.

    The mean of a 0/100 mask over the geometry is exactly the share of
    valid pixels carrying the product, scaled to 0-1 — the arithmetic that
    makes a single reduction sufficient for both the context metric and
    the area metric. The count is kept so the valid-pixel fraction can be
    enforced.

    Returns ``(stats, image_count, total_pixels, reason)``.
    """
    image, image_count, reason = resolve_worldcereal_image(
        context, ee_module, product, season
    )
    if image is None:
        return None, image_count, 0, reason

    area_sq_m = context.option("area_sq_m")
    total_pixels = estimate_pixel_count(area_sq_m, WORLDCEREAL_WORKING_SCALE)

    raw = (
        image.select([band])
        .reduceRegion(
            reducer=build_reducer(ee_module),
            geometry=context.geometry,
            scale=WORLDCEREAL_WORKING_SCALE,
            maxPixels=1e9,
            bestEffort=True,
        )
        .getInfo()
    )

    stats = parse_reduction_result(
        raw or {},
        band=band,
        total_pixel_count=total_pixels,
        pixel_area_sq_m=pixel_area_sq_m(WORLDCEREAL_WORKING_SCALE),
    )
    return stats, image_count, total_pixels, None


def _crop_share(stats: SpatialStats) -> Optional[float]:
    """The fraction of valid pixels carrying the product, from a 0/100 mean.

    The reduction's mean of a 0/100 band is 100 * share; the registry's
    scale factor of 1.0 leaves it unconverted, so the division happens
    here, once, with the assertion that the mean lies in [0, 100].
    """
    if stats.mean is None:
        return None
    if not 0.0 <= stats.mean <= 100.0:
        return None
    return stats.mean / 100.0


# --------------------------------------------------------------------------
# Crop-context metrics
# --------------------------------------------------------------------------


class _WorldCerealContextMetric(Metric):
    """Shared behaviour for the WorldCereal crop-context metrics.

    Each subclass names one product and one season and reports the share
    of valid pixels the product's binary mask covers. The value is a
    fraction of the classified (valid) pixels — never of the geometry,
    which is reported separately as coverage so the two cannot be
    conflated.
    """

    domain = MetricDomain.CROP
    unit = "fraction"
    dataset_ids = (WORLDCEREAL_ID,)
    measurement_basis = MeasurementBasis.PRODUCT
    default_scale = WORLDCEREAL_WORKING_SCALE

    #: The WorldCereal product this metric reads.
    product: str = ""

    #: The season this metric reads.
    season: str = ""

    #: Product-accurate phrase for what the mask means, reused in messages.
    mask_meaning: str = ""

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        # A direct compute() call must obey the same coverage gate the
        # executor applies, so an out-of-window request is reported as
        # unavailable even when this method is called outside the
        # executor. This mirrors the land-cover metrics' internal
        # product-year check.
        can_attempt, reason = self.can_attempt(context)
        if not can_attempt:
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=reason or "outside_temporal_coverage",
                message=(
                    "The requested period is outside the WorldCereal "
                    "collection's coverage (the single 2021 reference "
                    "year), and no other year is substituted."
                ),
                unit=self.unit,
            )

        dataset = self.primary_dataset()

        stats, image_count, total_pixels, reason = reduce_worldcereal_mask(
            context, ee, self.product, self.season
        )

        if stats is None:
            if reason == "no_matching_image":
                return MetricResult.insufficient(
                    metric_key=self.key,
                    display_name=self.display_name,
                    display_name_fa=self.display_name_fa,
                    message=(
                        f"No {self.product} image for season {self.season} "
                        "covers this area. WorldCereal processed each "
                        "agro-ecological zone independently, and zones "
                        "without a product were not processed at all, so "
                        "an unprocessed zone is reported as missing data "
                        "rather than as zero crop."
                    ),
                    unit=self.unit,
                )
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                reason=reason or "unavailable",
                message="The WorldCereal image could not be resolved.",
                unit=self.unit,
            )

        valid_fraction = (
            stats.valid_pixel_count / total_pixels
            if total_pixels > 0
            else None
        )
        if valid_fraction is None or valid_fraction < CROP_AREA_MIN_VALID_FRACTION:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Only "
                    f"{stats.valid_pixel_count} pixel(s) of the estimated "
                    f"{total_pixels} the geometry covers carry the "
                    f"{self.product} product. Below the "
                    f"{CROP_AREA_MIN_VALID_FRACTION:.0%} valid-pixel floor "
                    "no crop-context figure is published, because the "
                    "missing part could be crop or not crop and the "
                    "product gives no way to tell."
                ),
                unit=self.unit,
            )

        share = _crop_share(stats)
        if share is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "The classification band carried values outside the "
                    "documented binary domain (0 or 100), so no crop "
                    "share can be derived."
                ),
                unit=self.unit,
            )

        coverage_percent = valid_fraction * 100.0
        quality = assess_quality(
            image_count=max(image_count, 1),
            coverage_percent=coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=SENTINEL2_THRESHOLDS,
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["classification"],
            formula=(
                f"share = mean(classification) / 100 over pixels where "
                f"the {self.product} product is defined; "
                f"product='{self.product}', season='{self.season}', "
                "reference year 2021"
            ),
            quality=quality,
            image_count=image_count,
            aggregation_method="spatial mean of the binary mask, reported as a fraction of valid pixels",
            extra_limitations=self.limitations,
        )

        if quality is QualityLevel.INSUFFICIENT:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Too few valid pixels carried the product for a "
                    "trustworthy crop-context figure."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            (
                f"This is the 2021 reference-year product for "
                f"{self.mask_meaning}. It cannot describe any other year."
            ),
            (
                f"{coverage_percent:.1f} percent of the geometry was "
                "classified; the share describes the classified part."
            ),
        ]
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))
        if quality is QualityLevel.MODERATE:
            warnings.append(describe_quality(QualityLevel.MODERATE))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=share,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )


class TemporaryCropContextMetric(_WorldCerealContextMetric):
    """Share of the classified area under temporary crops (2021).

    Temporary crops are crops with a less-than-one-year cycle that must be
    re-sown after harvest. Perennial crops and pastures are excluded by
    the product's own definition, which the limitations below state so a
    low figure is never read as "not farmed".
    """

    key = "temporary_crop_context"
    display_name = "Temporary Crop Context (2021)"
    display_name_fa = "بافت محصول موقت (۲۰۲۱)"
    product = "temporarycrops"
    season = "tc-annual"
    mask_meaning = "temporary crops (annual crops; perennials and pastures excluded)"
    description = (
        "The share of the area classified as temporary cropland by the "
        "ESA WorldCereal 2021 binary product, for the tc-annual season. "
        "Crop context, not crop type."
    )
    limitations = (
        "The product is a binary mask for the single reference year 2021. "
        "It cannot describe 2020, 2022 or any later season, and no "
        "multi-year claim can be based on it.",
        "Temporary crops exclude perennial crops and pastures by the "
        "product's own definition, so a low share does not mean the land "
        "is not farmed.",
        "This is crop *context*, not crop type: the mask says nothing "
        "about which species is grown.",
        "Each image covers one agro-ecological zone; areas without a "
        "product were not processed and are reported as missing data, "
        "never as zero crop.",
        "The ESA's own global validation reports user's accuracy 88.5 "
        "percent and producer's accuracy 92.1 percent for this product, "
        "so individual fields are misclassified at roughly those rates.",
        "Minimum mapping unit is around 0.5 hectares; smaller plots are "
        "unreliable.",
    )


class MaizeCropContextMetric(_WorldCerealContextMetric):
    """Share of the classified area under maize (2021 main season)."""

    key = "maize_context"
    display_name = "Maize Context (2021 main season)"
    display_name_fa = "بافت ذرت (فصل اصلی ۲۰۲۱)"
    product = "maize"
    season = "tc-maize-main"
    mask_meaning = "maize in its main season"
    description = (
        "The share of the area classified as maize by the ESA WorldCereal "
        "2021 binary product, for the tc-maize-main season. This is the "
        "one commodity-crop identity the product supports."
    )
    limitations = (
        "The product is a binary mask for the single reference year 2021 "
        "and the main maize season as defined per agro-ecological zone. "
        "It cannot describe other years or the second maize season.",
        "Maize is the only named species this engine's registered "
        "datasets support; no other crop identity is derivable.",
        "The mask is generated inside the temporary-crop mask, so it "
        "inherits that product's omissions.",
        "Areas without a product were not processed and are reported as "
        "missing data, never as zero maize.",
        "Minimum mapping unit is around 0.5 hectares; smaller plots are "
        "unreliable.",
    )


class CerealCropContextMetric(_WorldCerealContextMetric):
    """Share of the classified area under winter cereals (2021)."""

    key = "cereal_context"
    display_name = "Winter Cereal Context (2021)"
    display_name_fa = "بافت غلات دیم زمستانه (۲۰۲۱)"
    product = "wintercereals"
    season = "tc-wintercereals"
    mask_meaning = "winter cereals of the Triticeae tribe (wheat, barley, rye)"
    description = (
        "The share of the area classified as winter cereals by the ESA "
        "WorldCereal 2021 binary product, for the tc-wintercereals "
        "season. Cereals here means the Triticeae tribe: wheat, barley "
        "and rye, which the product does not separate."
    )
    limitations = (
        "The product is a binary mask for the single reference year 2021 "
        "and the winter-cereals season. It cannot describe other years "
        "or the spring-cereals season.",
        "Cereals means the Triticeae tribe: wheat, barley and rye are "
        "deliberately grouped and cannot be separated. There is no "
        "wheat-only map here and none may be inferred from it.",
        "This is crop context, not crop type: the mask says nothing "
        "about which species is grown beyond the Triticeae grouping.",
        "The mask is generated inside the temporary-crop mask, so it "
        "inherits that product's omissions.",
        "Areas without a product were not processed and are reported as "
        "missing data, never as zero cereals.",
        "Minimum mapping unit is around 0.5 hectares; smaller plots are "
        "unreliable.",
    )


# --------------------------------------------------------------------------
# Crop area
# --------------------------------------------------------------------------


class TemporaryCropAreaMetric(_WorldCerealContextMetric):
    """Estimated temporary-crop area, quality-aware and bounded.

    The value is the *fraction* of valid pixels classified as temporary
    crop (inherited from the context base), while the spatial statistics
    carry the derived area figure: ``valid_area_sq_m`` reports the
    classified area and the warning block states the estimated crop-covered
    area, the total geometry area and the resolution both rest on. Keeping
    the numeric value a fraction and the areas in the stats/warnings
    prevents the two kinds of area from being read as one number.
    """

    key = "temporary_crop_area"
    display_name = "Temporary Crop Area Estimate (2021)"
    display_name_fa = "برآورد سطح زیر کشت موقت (۲۰۲۱)"
    product = "temporarycrops"
    season = "tc-annual"
    mask_meaning = "temporary crops (annual crops; perennials and pastures excluded)"
    description = (
        "Estimated area under temporary crops within the requested "
        "geometry, counted from the ESA WorldCereal 2021 10 m binary "
        "product. Reports total geometry area and estimated crop-covered "
        "area separately, with the valid-pixel fraction enforced."
    )
    limitations = (
        "This is a pixel-count estimate at 10 m from a binary 2021 mask. "
        "It is not a survey-grade field boundary measurement and must "
        "not be used as one.",
        "Mixed pixels along field edges are assigned wholly to one side "
        "by the product, so the estimate carries an unquantified "
        "boundary error on the order of the pixel size.",
        "The ESA's own validation for this product reports user's "
        "accuracy 88.5 percent and producer's accuracy 92.1 percent; the "
        "area estimate inherits both omission and commission error at "
        "those rates.",
        "Perennial crops and pastures are excluded by the product's "
        "definition, so the estimate covers annual temporary crops only.",
        "The product covers the single reference year 2021 and cannot "
        "describe any other season.",
        "Areas without a product were not processed and contribute no "
        "area rather than zero area.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        # Reuse the context path for the share and its guards, then add
        # the area-specific reporting on top of the same reduction.
        base = super().compute(context)

        if base.status != "ok":
            return base

        import ee  # noqa: F401 - the base call already used it; import kept for symmetry

        dataset = self.primary_dataset()
        pixel_area = pixel_area_sq_m(WORLDCEREAL_WORKING_SCALE)

        # Re-derive the areas from the stats the base result carried. The
        # reduction is the same one, so no second Earth Engine call is
        # made and the numbers cannot disagree with the published share.
        stats = base.stats
        assert stats is not None  # an ok result always carries stats
        share = base.value
        assert share is not None

        valid_pixels = stats.valid_pixel_count
        crop_pixels = int(round(share * valid_pixels))
        classified_area_sq_m = valid_pixels * pixel_area
        crop_area_sq_m = crop_pixels * pixel_area
        total_area_sq_m = context.option("area_sq_m")

        warnings: List[str] = []
        if total_area_sq_m is not None:
            warnings.append(
                f"Total geometry area {total_area_sq_m:,.0f} m2; estimated "
                f"temporary-crop area {crop_area_sq_m:,.0f} m2 "
                f"({share * 100:.1f} percent of the "
                f"{classified_area_sq_m:,.0f} m2 the product classified, "
                f"at {WORLDCEREAL_WORKING_SCALE} m pixels)."
            )
            if valid_pixels * pixel_area < total_area_sq_m:
                warnings.append(
                    "The product did not classify the whole geometry; the "
                    "estimate covers only the classified part."
                )
        else:
            warnings.append(
                "The geometry's total area is unknown (for example a "
                "point), so the crop area is reported as a pixel count "
                "and a share only."
            )
        warnings.append(
            "Pixel-derived crop area is not a survey-grade field boundary "
            "measurement."
        )
        warnings.extend(base.warnings)

        # The share stays the numeric value; the area detail travels in
        # warnings and in the stats, which carry valid_area_sq_m.
        result = MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=share,
            unit=self.unit,
            stats=stats,
            provenance=base.provenance,
            warnings=warnings,
        )
        # Record the product identity once more for the serialised form.
        if result.provenance is not None:
            result.provenance.formula = (
                result.provenance.formula
                + f"; crop_area_sq_m = crop_pixels x {WORLDCEREAL_WORKING_SCALE}m^2, "
                "crop_pixels = round(share x valid_pixels)"
            )
            result.provenance.source_dataset_name = dataset.name
        return result


# --------------------------------------------------------------------------
# Deliberately not produced: phenological event dates as agronomic dates
# --------------------------------------------------------------------------


PLANTING_UNAVAILABLE_CODE = "no_planting_date_product"
PLANTING_UNAVAILABLE_REASON = (
    "Not produced. Planting date cannot be read from any dataset "
    "registered in this engine. The WorldCereal products are binary masks "
    "for one 2021 reference season and carry no sowing information; a "
    "vegetation index rise marks canopy development, which can sit weeks "
    "away from sowing and depends on species, cultivar, irrigation and "
    "whether the crop was transplanted. Dynamic World's crops class is a "
    "land-cover probability with no temporal event semantics, and MCD12Q1 "
    "is an annual classification with a publication lag. A planting-date "
    "metric would therefore be an invented conversion from green-up to "
    "sowing, and it is declined."
)

HARVEST_UNAVAILABLE_CODE = "no_harvest_date_product"
HARVEST_UNAVAILABLE_REASON = (
    "Not produced. Harvest date cannot be read from any dataset "
    "registered in this engine. A vegetation index decline marks the loss "
    "of green canopy, which harvest can cause but so can senescence, "
    "drought stress, disease, hail or cutting for forage, and the end of "
    "the WorldCereal or vegetation-index season is defined by satellite "
    "observability, not by machinery. No registered dataset records "
    "harvest events, so a harvest-date metric would be an invented "
    "conversion and is declined."
)

FLOWERING_UNAVAILABLE_CODE = "no_flowering_signal_product"
FLOWERING_UNAVAILABLE_REASON = (
    "Not produced. Flowering date cannot be derived from NDVI or any "
    "other band in the registered datasets. The peak of a vegetation "
    "index is maximum green canopy or green biomass, not anthesis; for "
    "many crops flowering precedes or accompanies peak canopy only "
    "loosely, and for orchards and cereals the relationship differs. No "
    "registered dataset observes flowering, so a flowering-date metric "
    "would present an index peak as a reproductive event and is declined."
)


class _UnavailableCropMetric(Metric):
    """A crop metric that exists in the catalog but cannot carry a value.

    Mirrors the land-cover module's unavailable-metric base: ``compute``
    has no path that returns a value, so a later change cannot turn one of
    these into a fabricated indicator without deliberately deleting the
    class.
    """

    domain = MetricDomain.CROP
    measurement_basis = MeasurementBasis.INFERENCE
    dataset_ids: Tuple[str, ...] = ()

    unavailable_reason: str = ""
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


class CropPlantingDateMetric(_UnavailableCropMetric):
    key = "crop_planting_date"
    display_name = "Planting Date (not produced)"
    display_name_fa = "تاریخ کاشت (تولید نمی‌شود)"
    unit = "date"
    dataset_ids = (WORLDCEREAL_ID,)
    unavailable_reason = PLANTING_UNAVAILABLE_REASON
    unavailable_code = PLANTING_UNAVAILABLE_CODE
    description = (
        "Planting/sowing date. Not produced: no registered dataset "
        "observes sowing; vegetation green-up is not planting."
    )
    limitations = (
        "Not produced. See the unavailable reason for the full argument.",
    )


class CropHarvestDateMetric(_UnavailableCropMetric):
    key = "crop_harvest_date"
    display_name = "Harvest Date (not produced)"
    display_name_fa = "تاریخ برداشت (تولید نمی‌شود)"
    unit = "date"
    dataset_ids = (WORLDCEREAL_ID,)
    unavailable_reason = HARVEST_UNAVAILABLE_REASON
    unavailable_code = HARVEST_UNAVAILABLE_CODE
    description = (
        "Harvest date. Not produced: no registered dataset observes "
        "harvest; canopy decline is not harvest."
    )
    limitations = (
        "Not produced. See the unavailable reason for the full argument.",
    )


class FloweringDateMetric(_UnavailableCropMetric):
    key = "crop_flowering_date"
    display_name = "Flowering Date (not produced)"
    display_name_fa = "تاریخ گلدهی (تولید نمی‌شود)"
    unit = "date"
    unavailable_reason = FLOWERING_UNAVAILABLE_REASON
    unavailable_code = FLOWERING_UNAVAILABLE_CODE
    description = (
        "Flowering date. Not produced: no registered dataset observes "
        "flowering; an NDVI peak is peak green canopy, not anthesis."
    )
    limitations = (
        "Not produced. See the unavailable reason for the full argument.",
    )


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------

CROP_METRICS: Tuple[Metric, ...] = (
    TemporaryCropContextMetric(),
    MaizeCropContextMetric(),
    CerealCropContextMetric(),
    TemporaryCropAreaMetric(),
)

UNAVAILABLE_CROP_METRICS: Tuple[Metric, ...] = (
    CropPlantingDateMetric(),
    CropHarvestDateMetric(),
    FloweringDateMetric(),
)

ALL_CROP_METRICS: Tuple[Metric, ...] = CROP_METRICS + UNAVAILABLE_CROP_METRICS
