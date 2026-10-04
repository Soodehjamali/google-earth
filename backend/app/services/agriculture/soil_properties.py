"""Soil properties and root-zone soil context.

Scope of this module
--------------------
This module implements the soil **property** domain: static physical and
chemical characteristics of the soil profile, as opposed to
:mod:`app.services.agriculture.soil`, which is about the *water currently
in* the soil. The two must never be conflated: a soil property is a
(time-invariant) attribute of the soil, soil moisture is a state.

What Earth Engine actually publishes
------------------------------------
The single most important fact in this module, and the one that
determines its whole shape, was established by querying the live Earth
Engine archive rather than by assuming it:

``ISRIC/SoilGrids250m/v2_0`` is an ``ImageCollection`` holding **exactly
three images** — ``/wv0010``, ``/wv0033`` and ``/wv1500`` — the
volumetric water retention predictions at 10, 33 and 1500 kPa suction.
The SoilGrids *soil property* layers (SOC, clay, sand, silt, bulk
density, pH, CEC, coarse fragments, nitrogen) are **not published as
Earth Engine assets**. Attempting to read ``ISRIC/SoilGrids250m/v2_0/soc``
or ``.../clay`` fails; those layers are served only by ISRIC's REST API,
which answers single-point queries and cannot perform an area reduction.

Consequences, all of which are enforced here:

* The only soil-property family this engine can compute from Earth
  Engine is **water retention**, from the two verified assets above.
* Texture, organic carbon, bulk density, pH, CEC and coarse fragments
  are registered as **unavailable metrics** whose reason names the
  missing Earth Engine layer and the point-query-only alternative, so a
  user asking for them receives a specific answer rather than silence or
  an invented proxy.
* No salinity proxy is constructed (see ``SoilSalinityMetric``).
* Soil *temperature* is a different dataset entirely (ERA5-Land, at
  declared depths) and is implemented here because the bands are
  registered and verified.

The 33 kPa / 1500 kPa convention
--------------------------------
SoilGrids does not publish "field capacity" or "wilting point" bands. It
publishes volumetric water content at declared matric suctions. The
standard soil-physics convention used here is:

* field capacity is approximated by the water content at **33 kPa**
  (``wv0033``);
* permanent wilting point is approximated by the water content at
  **1500 kPa** (``wv1500``);
* available water capacity is ``AWC = theta_33kPa - theta_1500kPa``.

These are **conventions, not measurements**. Field capacity is genuinely
a dynamic property that depends on drainage history and profile
structure; 33 kPa is the laboratory suction conventionally taken to
represent it in temperate soils, and it is a poorer approximation in
coarse, structured or shrink-swell soils. Every result this module
publishes says so in its own limitations, and the provenance records the
convention as the formula. This is the documented-relationship case the
specification permits; it is not an invented pedotransfer function.

Depth model
-----------
SoilGrids predicts at six standard GlobalSoilMap depth intervals. This
module aggregates the **0 to 100 cm** interval, which:

* is exactly covered by the first five registered intervals
  (0-5, 5-15, 15-30, 30-60, 60-100 cm), so no interpolation and no
  nearest-layer substitution is ever performed;
* matches the 0 to 100 cm root-zone definition already used by the SMAP
  L4 and ERA5-Land soil-moisture metrics, so the static water-retention
  context and the dynamic soil-moisture state describe the same column.

The aggregation is a **thickness-weighted mean**: each layer's weight is
its own thickness in centimetres, so a 30 cm layer carries six times the
weight of a 5 cm layer. A plain arithmetic mean across the six intervals
would implicitly claim the layers are equally thick, which is false, and
is the specific error this module exists not to make. The 100-200 cm
layer is excluded because it lies below the crop root zone.

Every layer is required for the aggregate to be published. A profile
with a missing layer is reported as ``insufficient_data``, never
silently re-weighted over the survivors: a depth-weighted mean over four
of five layers describes a different, shallower column, and the
provenance would then be claiming a 0 to 100 cm result it did not
compute.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture import units as u
from app.services.agriculture.aggregation import (
    build_reducer,
    estimate_pixel_count,
    parse_reduction_result,
    pixel_area_sq_m,
)
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.quality import (
    QualityThresholds,
    assess_quality,
    describe_quality,
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
    "SOILGRIDS",
    "SOILGRIDS_WV0033",
    "SOILGRIDS_WV1500",
    "ERA5_DAILY",
    "SOILGRIDS_SCALE",
    "SOILGRIDS_DEPTHS",
    "ROOT_ZONE_INTERVALS",
    "ROOT_ZONE_LAYER_THICKNESSES_CM",
    "ROOT_ZONE_DEPTH_CM",
    "depth_weighted_mean",
    "combine_layer_stats",
    "SoilFieldCapacityMetric",
    "SoilWiltingPointMetric",
    "SoilAvailableWaterCapacityMetric",
    "SoilTemperatureLevel1Metric",
    "SoilTemperatureLevel2Metric",
    "SOIL_PROPERTY_METRICS",
    "UNAVAILABLE_SOIL_PROPERTY_METRICS",
    "ALL_SOIL_PROPERTY_METRICS",
]


# ==========================================================================
# Dataset access
# ==========================================================================

#: SoilGrids 2.0 collection. Verified live: this collection contains
#: exactly three images (wv0010, wv0033, wv1500) and no soil-property
#: layers. See the module docstring.
SOILGRIDS = "ISRIC/SoilGrids250m/v2_0"

#: The asset holding the 33 kPa volumetric water content prediction.
#: ``wv0033`` is the SoilGrids band prefix; the asset is a single
#: ``ee.Image`` beneath the collection.
SOILGRIDS_WV0033 = f"{SOILGRIDS}/wv0033"

#: The asset holding the 1500 kPa volumetric water content prediction.
SOILGRIDS_WV1500 = f"{SOILGRIDS}/wv1500"

#: ERA5-Land daily aggregated, the source of the soil temperature bands.
ERA5_DAILY = "ECMWF/ERA5_LAND/DAILY_AGGR"

#: SoilGrids is published at 250 m. Reducing at a finer scale would
#: resample the grid and the reported resolution would be a lie.
SOILGRIDS_SCALE = 250

#: ERA5-Land is 0.1 degree, approximately 11.1 km.
ERA5_WORKING_SCALE = 11132

#: The six standard GlobalSoilMap depth intervals SoilGrids predicts at,
#: in the registry's band-name form. Verified against the Earth Engine
#: catalogue band table and against the live asset.
SOILGRIDS_DEPTHS: Tuple[str, ...] = (
    "0_5cm",
    "5_15cm",
    "15_30cm",
    "30_60cm",
    "60_100cm",
    "100_200cm",
)

#: The 0 to 100 cm analysis interval, in centimetres. This is a fixed,
#: explicitly documented analysis depth: it matches the root-zone depth
#: the SMAP L4 and ERA5-Land soil-moisture metrics already use, so the
#: static retention context and the dynamic moisture state describe the
#: same soil column. It is not a crop-specific rooting depth, and no
#: crop-specific rooting depth is claimed anywhere in this module.
ROOT_ZONE_DEPTH_CM: Tuple[float, float] = (0.0, 100.0)

#: The registered intervals that together tile the 0 to 100 cm analysis
#: interval, in order and each with its own thickness in centimetres.
#: 5 + 10 + 15 + 30 + 40 = 100 exactly, so the weights sum to the
#: analysis depth and no layer is partly counted. The 100-200 cm layer
#: is deliberately absent: it lies below the crop root zone.
ROOT_ZONE_INTERVALS: Tuple[Tuple[str, float], ...] = (
    ("0_5cm", 5.0),
    ("5_15cm", 10.0),
    ("15_30cm", 15.0),
    ("30_60cm", 30.0),
    ("60_100cm", 40.0),
)

#: Thickness weights alone, in interval order, for callers that need the
#: weights without the band names.
ROOT_ZONE_LAYER_THICKNESSES_CM: Tuple[float, ...] = tuple(
    thickness for _, thickness in ROOT_ZONE_INTERVALS
)

#: The sum of the layer thicknesses, in centimetres. Equal to the bottom
#: of the analysis interval, by construction.
ROOT_ZONE_TOTAL_THICKNESS_CM = sum(ROOT_ZONE_LAYER_THICKNESSES_CM)


#: Quality thresholds for a static soil map.
#:
#: A static product has no revisit and no scene count, so the image-count
#: thresholds all sit at their floor of 1 and the verdict rests on how
#: much of the requested area actually carries a prediction. The pixel
#: floor mirrors the terrain module's: a spread over fewer than ten
#: 250 m pixels does not describe an area.
SOIL_STATIC_THRESHOLDS = QualityThresholds(
    excellent_min_images=1,
    good_min_images=1,
    moderate_min_images=1,
    poor_min_images=1,
    min_coverage_percent=20.0,
    min_valid_pixels=10,
    excellent_min_coverage=90.0,
    good_min_coverage=50.0,
)

_STATIC_SOIL_DISCLAIMER = (
    "SoilGrids is a static modelled prediction produced once from a global "
    "compilation of soil profiles. It carries no observation date, is not a "
    "time series, and does not describe any change the soil has undergone "
    "since the profiles were sampled. The requested period is the analysis "
    "context, not an observation window."
)

_CONVENTION_DISCLAIMER = (
    "Field capacity and wilting point are approximated by the water content "
    "at 33 kPa and 1500 kPa suction respectively. This is the standard "
    "soil-physics convention, not a measurement of either quantity: field "
    "capacity is a dynamic property that depends on drainage history and "
    "profile structure, and the 33 kPa suction is a poorer approximation in "
    "coarse, strongly structured or shrink-swell soils than in uniform "
    "temperate soils."
)

_DEPTH_WEIGHTING_DISCLAIMER = (
    "The value is a thickness-weighted mean over the "
    f"{ROOT_ZONE_DEPTH_CM[0]:.0f} to {ROOT_ZONE_DEPTH_CM[1]:.0f} cm interval, "
    "weighting each SoilGrids layer by its own thickness in centimetres "
    + ", ".join(
        f"{depth.replace('_', '-')} ({thickness:.0f} cm)"
        for depth, thickness in ROOT_ZONE_INTERVALS
    )
    + ". An unweighted mean would implicitly treat these unequal layers as "
    "equally thick and would be wrong by an amount that depends on the "
    "profile. The 100-200 cm layer is excluded because it lies below the "
    "crop root zone."
)


# ==========================================================================
# Depth-weighted aggregation
# ==========================================================================


def depth_weighted_mean(
    values: Sequence[Optional[float]],
    weights: Sequence[float],
) -> Optional[float]:
    """Thickness-weighted mean of per-layer values.

    .. math::

        \\bar{x} = \\frac{\\sum_i w_i x_i}{\\sum_i w_i}

    where ``w_i`` is the thickness of layer ``i`` in centimetres. A layer
    contributing ``None`` contributes nothing to either sum, so the result
    over a partial profile is the weighted mean of the layers that do have
    a value — and callers that require a complete profile must check that
    separately, which the metrics below do.

    Returns ``None`` when no layer contributes, so a caller can never
    receive ``0.0`` for an empty profile.

    This is deliberately a separate, testable function rather than an
    inline expression: the weighting is the scientifically load-bearing
    step in this module, and an accidental unweighted mean would produce a
    plausible-looking number that is wrong by a profile-dependent amount.
    """
    if values is None or weights is None:
        return None
    numerator = 0.0
    denominator = 0.0
    for value, weight in zip(values, weights):
        if value is None or weight is None:
            continue
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            continue
        if weight <= 0.0 or not math.isfinite(weight):
            continue
        if value is None or not math.isfinite(value):
            continue
        numerator += weight * float(value)
        denominator += weight
    if denominator <= 0.0:
        return None
    return numerator / denominator


def combine_layer_stats(
    layer_stats: Sequence[Optional[SpatialStats]],
    weights: Sequence[float],
) -> SpatialStats:
    """Thickness-weighted combination of per-layer spatial statistics.

    Every statistic is combined with the same thickness weights, so the
    reported percentiles describe the same depth-weighted column as the
    mean rather than a different aggregation of it.

    Coverage is the **minimum** across layers, not the mean: the profile
    is only as complete as its least-covered layer, and averaging would
    conceal a layer that saw none of the geometry.
    """
    usable = [s for s in layer_stats if s is not None]
    if not usable:
        return SpatialStats()

    combined = SpatialStats(
        mean=depth_weighted_mean(
            [getattr(s, "mean", None) for s in layer_stats], weights
        ),
        median=depth_weighted_mean(
            [getattr(s, "median", None) for s in layer_stats], weights
        ),
        min=depth_weighted_mean(
            [getattr(s, "min", None) for s in layer_stats], weights
        ),
        max=depth_weighted_mean(
            [getattr(s, "max", None) for s in layer_stats], weights
        ),
        p10=depth_weighted_mean(
            [getattr(s, "p10", None) for s in layer_stats], weights
        ),
        p25=depth_weighted_mean(
            [getattr(s, "p25", None) for s in layer_stats], weights
        ),
        p75=depth_weighted_mean(
            [getattr(s, "p75", None) for s in layer_stats], weights
        ),
        p90=depth_weighted_mean(
            [getattr(s, "p90", None) for s in layer_stats], weights
        ),
        valid_pixel_count=int(min(s.valid_pixel_count for s in usable)),
        total_pixel_count=int(max(s.total_pixel_count for s in usable)),
    )
    # ``SpatialStats.__post_init__`` recomputes the missing-pixel fields
    # from the counts above, so they stay self-consistent.
    combined.valid_area_sq_m = sum(
        s.valid_area_sq_m for s in usable if s.valid_area_sq_m
    )
    return combined


# ==========================================================================
# Reduction helpers
# ==========================================================================


def _range_problem(value: Optional[float], band_spec: Any) -> Optional[str]:
    """Describe a physical-range violation, or None when the value is fine.

    This is the boundary where an out-of-range prediction is refused
    rather than clipped. Clipping would silently manufacture a defensible
    number out of an indefensible one, which is the exact failure mode
    this engine exists to prevent. The declared range is the registry's
    own bound for the quantity (a volumetric water content cannot exceed
    the porosity of mineral soil), not an invented clipping window.
    """
    if value is None or band_spec is None:
        return None
    valid_range = getattr(band_spec, "valid_range", None)
    if not valid_range:
        return None
    low, high = valid_range
    if not (low <= value <= high):
        return (
            f"The reduced value {value:.4f} lies outside the physical range "
            f"{low} to {high} declared for this band, so it is not a "
            "usable prediction. It is reported rather than clipped, "
            "because clipping would present an invented value as a "
            "measurement."
        )
    return None


def _reduce_soilgrids_layers(
    context: MetricContext,
    ee_module: Any,
    asset_id: str,
    layer_bands: Sequence[str],
    subtract_from: Optional[str] = None,
) -> Tuple[Dict[str, SpatialStats], int]:
    """Reduce the SoilGrids layers of one asset over the geometry.

    Args:
        context: The metric context supplying geometry and area.
        ee_module: The Earth Engine module, injected so this file stays
            importable without credentials.
        asset_id: The SoilGrids asset to read, e.g.
            ``ISRIC/SoilGrids250m/v2_0/wv0033``.
        layer_bands: The registered band names to reduce, one per layer.
        subtract_from: When given, the asset at this path is subtracted
            from ``asset_id`` band by band before the reduction, which is
            how the available-water layers are formed. Both assets share
            the band names and the scale factor, so the subtraction is
            exact in stored units and the single scale factor is then
            applied once to the difference.

    Returns:
        ``(stats_by_layer, total_pixel_count)``. A layer whose reduction
        yielded nothing is present in the mapping with an empty
        :class:`SpatialStats`, never silently omitted: the caller must be
        able to see that a layer is missing in order to refuse the
        aggregate.
    """
    dataset = get_dataset(SOILGRIDS)
    bands = list(layer_bands)

    image = ee_module.Image(asset_id).select(bands)
    if subtract_from is not None:
        # Per-band difference. Both assets were produced by the same
        # model on the same grid with identical band names, so the
        # difference is well defined per layer.
        image = image.subtract(ee_module.Image(subtract_from).select(bands))

    raw = image.reduceRegion(
        reducer=build_reducer(ee_module),
        geometry=context.geometry,
        scale=SOILGRIDS_SCALE,
        maxPixels=1e9,
    ).getInfo()

    total_pixels = estimate_pixel_count(
        context.option("area_sq_m"), SOILGRIDS_SCALE
    )

    stats_by_layer: Dict[str, SpatialStats] = {}
    for band in bands:
        # ``parse_reduction_result`` applies the band's scale factor
        # exactly once and drops nodata sentinels. Passing the registry
        # band spec is what turns raw stored integers into physical
        # values; omitting it would publish digital numbers.
        band_spec = dataset.band(band)
        stats_by_layer[band] = parse_reduction_result(
            raw or {},
            band=band,
            total_pixel_count=total_pixels,
            pixel_area_sq_m=pixel_area_sq_m(SOILGRIDS_SCALE),
            band_spec=band_spec,
        )

    return stats_by_layer, total_pixels


def _profile_quality(
    layer_stats: Dict[str, SpatialStats],
    total_pixels: int,
) -> Tuple[QualityLevel, Optional[str]]:
    """Grade a layered reduction and report the first missing layer.

    Returns ``(quality, missing_layer)``. A missing layer is reported by
    its registered interval name so the caller's message can name it.
    """
    missing = [
        depth
        for depth, _ in ROOT_ZONE_INTERVALS
        if not layer_stats.get(f"val_{depth}_mean", SpatialStats()).has_values
    ]
    if missing:
        return QualityLevel.INSUFFICIENT, missing[0]

    combined = combine_layer_stats(
        [layer_stats.get(f"val_{depth}_mean") for depth, _ in ROOT_ZONE_INTERVALS],
        ROOT_ZONE_LAYER_THICKNESSES_CM,
    )
    quality = assess_quality(
        image_count=1,
        coverage_percent=combined.coverage_percent,
        valid_pixel_count=combined.valid_pixel_count,
        thresholds=SOIL_STATIC_THRESHOLDS,
    )
    return quality, None


# ==========================================================================
# Water retention: field capacity, wilting point, available water
# ==========================================================================


def _layer_band(depth: str) -> str:
    """The registered mean-value band for one SoilGrids depth interval."""
    return f"val_{depth}_mean"


class _SoilGridsRetentionMetric(Metric):
    """Common machinery for the SoilGrids water-retention metrics.

    Subclasses declare which suction asset they read and how the result
    is described; the base class handles the layered reduction, the
    depth weighting, the quality verdict and the provenance.
    """

    domain = MetricDomain.SOIL
    unit = "cm3/cm3"
    dataset_ids = (SOILGRIDS,)
    measurement_basis = MeasurementBasis.MODELLED
    default_scale = SOILGRIDS_SCALE

    #: The suction asset to reduce, e.g. ``SOILGRIDS_WV0033``.
    asset_id: str = ""

    #: The suction this asset represents, for the formula string.
    suction_label: str = ""

    #: The optional second asset to subtract band-wise, for AWC.
    subtract_asset_id: Optional[str] = None

    #: Whether the result is a difference of two suctions.
    is_difference: bool = False

    #: Subclass-specific limitations.
    extra_limitations: Tuple[str, ...] = ()

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return tuple(_layer_band(depth) for depth, _ in ROOT_ZONE_INTERVALS)

    def _layer_stats(
        self, context: MetricContext, ee_module: Any
    ) -> Tuple[Dict[str, SpatialStats], int]:
        return _reduce_soilgrids_layers(
            context,
            ee_module,
            self.asset_id,
            list(self.source_bands),
            subtract_from=self.subtract_asset_id,
        )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()
        layer_stats, total_pixels = self._layer_stats(context, ee)

        quality, missing = _profile_quality(layer_stats, total_pixels)

        # The provenance names the layers read. For the available-water
        # metric both suction assets carry identical band names, so the
        # band list alone does not distinguish them; the formula string
        # below states both suctions explicitly.
        bands = list(self.source_bands)

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=bands,
            formula=self._formula(),
            quality=quality,
            image_count=1,
            aggregation_method=(
                "spatial reduction per SoilGrids layer, then "
                "thickness-weighted mean over the "
                f"{ROOT_ZONE_DEPTH_CM[0]:.0f}-{ROOT_ZONE_DEPTH_CM[1]:.0f} cm "
                "root zone"
            ),
            extra_limitations=self._all_limitations(),
        )

        if missing is not None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    f"The {missing.replace('_', '-')} cm layer returned no "
                    "usable prediction for this area, so a "
                    f"{ROOT_ZONE_DEPTH_CM[0]:.0f} to "
                    f"{ROOT_ZONE_DEPTH_CM[1]:.0f} cm depth-weighted value "
                    "cannot be computed. The aggregate is refused rather "
                    "than re-weighted over the remaining layers, because "
                    "that would describe a shallower column than the one "
                    "the result claims."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        combined = combine_layer_stats(
            [layer_stats[_layer_band(depth)] for depth, _ in ROOT_ZONE_INTERVALS],
            ROOT_ZONE_LAYER_THICKNESSES_CM,
        )

        if quality is QualityLevel.INSUFFICIENT or not combined.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Too little of the requested area carries a usable "
                    f"SoilGrids prediction ({combined.coverage_percent:.1f} "
                    "percent coverage, "
                    f"{combined.valid_pixel_count} valid pixel(s)). A "
                    "depth-weighted mean over so little of the field is not "
                    "a property of the field, so no value is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        # A prediction outside the physical range of the quantity is
        # refused rather than clipped. This is the registry's own declared
        # bound for the band, and refusing it keeps an impossible value
        # from being dressed as a measurement.
        band_spec = dataset.band(self.source_bands[0])
        range_problem = _range_problem(combined.mean, band_spec)
        if range_problem is not None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=range_problem,
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            _STATIC_SOIL_DISCLAIMER,
            _CONVENTION_DISCLAIMER,
        ]
        if self.is_difference:
            warnings.append(
                "Available water capacity is the difference between two "
                "modelled predictions, so its uncertainty is larger than "
                "either input's. It is a soil-water storage context figure, "
                "not an irrigation recommendation."
            )
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

    def _formula(self) -> str:
        weights = ", ".join(
            f"{thickness:.0f}*{depth.replace('_', '-')}"
            for depth, thickness in ROOT_ZONE_INTERVALS
        )
        if self.is_difference:
            return (
                "AWC_layer = theta(33 kPa) - theta(1500 kPa); "
                f"root-zone AWC = ({weights}) / "
                f"{ROOT_ZONE_TOTAL_THICKNESS_CM:.0f}"
            )
        return (
            f"root-zone value = ({weights}) / "
            f"{ROOT_ZONE_TOTAL_THICKNESS_CM:.0f}, from the "
            f"{self.suction_label} asset"
        )

    def _all_limitations(self) -> Tuple[str, ...]:
        return (
            _STATIC_SOIL_DISCLAIMER,
            _CONVENTION_DISCLAIMER,
            _DEPTH_WEIGHTING_DISCLAIMER,
        ) + tuple(self.extra_limitations)


class SoilFieldCapacityMetric(_SoilGridsRetentionMetric):
    """Water content at 33 kPa over the 0 to 100 cm root zone.

    This is the conventional surrogate for **field capacity**: the water
    content the soil retains after free drainage, approximated by the
    predicted water content at 33 kPa matric suction. It is a static
    modelled soil property, not a measurement and not a current moisture
    reading.
    """

    key = "soil_field_capacity"
    display_name = "Soil Water Content at 33 kPa (field capacity context)"
    display_name_fa = "ظرفیت زراعی خاک (۳۳ کیلوپاسکال)"
    asset_id = SOILGRIDS_WV0033
    suction_label = "33 kPa"
    description = (
        "Volumetric water content at 33 kPa matric suction, aggregated over "
        "the 0 to 100 cm root zone by thickness weighting. This is the "
        "conventional surrogate for field capacity."
    )
    limitations = (
        "This is a modelled prediction from a quantile random forest digital "
        "soil mapping model trained on a global compilation of soil "
        "profiles. No instrument measured the soil at this field.",
        "Field capacity is approximated by the 33 kPa water content. The two "
        "are not the same quantity: field capacity is a dynamic property "
        "that depends on drainage history and profile structure, and the "
        "33 kPa convention is a poorer approximation in coarse, strongly "
        "structured or shrink-swell soils.",
        "At 250 m a single cell covers 6.25 hectares, so within-field soil "
        "variability — often the largest source of error in a water balance "
        "— is not resolved.",
        "The value is a static soil property. It is not the soil's current "
        "water content and must not be compared with a soil-moisture "
        "retrieval as though the two measured the same thing.",
        "This is not an irrigation recommendation, and it implies nothing "
        "about when or how much to water.",
    )


class SoilWiltingPointMetric(_SoilGridsRetentionMetric):
    """Water content at 1500 kPa over the 0 to 100 cm root zone.

    This is the conventional surrogate for **permanent wilting point**:
    the water content below which plants can no longer extract water,
    approximated by the predicted water content at 1500 kPa suction.
    """

    key = "soil_wilting_point"
    display_name = "Soil Water Content at 1500 kPa (wilting point context)"
    display_name_fa = "نقطه پژمردگی دائمی خاک (۱۵۰۰ کیلوپاسکال)"
    asset_id = SOILGRIDS_WV1500
    suction_label = "1500 kPa"
    description = (
        "Volumetric water content at 1500 kPa matric suction, aggregated over "
        "the 0 to 100 cm root zone by thickness weighting. This is the "
        "conventional surrogate for permanent wilting point."
    )
    limitations = (
        "This is a modelled prediction, not a measurement at the field.",
        "Permanent wilting point is approximated by the 1500 kPa water "
        "content. The true wilting point is species-dependent and depends "
        "on root distribution and soil structure, none of which a static "
        "suction prediction captures.",
        "At 250 m within-field soil variability is not resolved.",
        "The value is a static soil property, not the soil's current water "
        "content.",
        "This is not a drought diagnosis and not an irrigation "
        "prescription.",
    )


class SoilAvailableWaterCapacityMetric(_SoilGridsRetentionMetric):
    """Plant-available water capacity over the 0 to 100 cm root zone.

    .. math::

        AWC = \\theta_{33 kPa} - \\theta_{1500 kPa}

    computed per SoilGrids layer and then thickness-weighted over the
    root zone. When every layer is present this is identically the
    difference of the two weighted means published by the field-capacity
    and wilting-point metrics; the per-layer form is used so that a
    partial profile is refused rather than silently re-weighted.
    """

    key = "soil_available_water_capacity"
    display_name = "Available Water Capacity (0-100 cm root zone)"
    display_name_fa = "ظرفیت آب قابل دسترس (ناحیه ریشه ۰-۱۰۰ سانتی‌متر)"
    asset_id = SOILGRIDS_WV0033
    subtract_asset_id = SOILGRIDS_WV1500
    suction_label = "33 kPa minus 1500 kPa"
    is_difference = True
    description = (
        "Volumetric water capacity available to plants over the 0 to 100 cm "
        "root zone: the difference between the 33 kPa and 1500 kPa water "
        "contents, per layer, then thickness-weighted."
    )
    limitations = (
        "This is a difference of two modelled predictions, so its "
        "uncertainty is larger than either input's.",
        "The 33 kPa and 1500 kPa conventions inherit all the limitations of "
        "the field-capacity and wilting-point surrogates they are built "
        "from. In soils where either convention is a poor approximation, "
        "the available water figure inherits the error.",
        "At 250 m within-field soil variability is not resolved, and a "
        "water balance built on this figure alone will mis-irrigate any "
        "field whose soil varies within the cell.",
        "This is a soil-water storage context figure. It is not an "
        "irrigation prescription, a yield forecast or a drought diagnosis.",
    )
    extra_limitations = (
        "Available water capacity is expressed as a volume fraction "
        "(cm3/cm3). Multiplying it by the rooting depth in millimetres "
        "gives a storage depth in millimetres, but this engine does not "
        "perform that multiplication because a defensible crop-specific "
        "rooting depth is not available; the metric reports the volume "
        "fraction for the fixed 0 to 100 cm analysis interval only.",
    )


# ==========================================================================
# Soil temperature (ERA5-Land, at declared depths)
# ==========================================================================


class _SoilTemperatureMetric(Metric):
    """Soil temperature at a declared ERA5-Land level.

    ERA5-Land reports soil temperature for discrete model levels whose
    depths are declared in the catalogue and registered in the band
    description. This is genuinely soil temperature, and it is kept
    strictly apart from the 2 m air temperature and the land-surface
    temperature metrics: the three are different quantities measured (or
    modelled) in different places, and a soil-temperature metric that
    quietly read the 2 m air band would be reporting a different
    physical quantity under the right-sounding name.
    """

    domain = MetricDomain.SOIL
    dataset_ids = (ERA5_DAILY,)
    measurement_basis = MeasurementBasis.MODELLED
    default_scale = ERA5_WORKING_SCALE
    unit = "degC"
    source_unit = "K"
    conversion = "celsius = kelvin - 273.15"

    #: The registered ERA5-Land soil temperature band this metric reads.
    source_band: str = ""

    def convert(self, value: Optional[float]) -> Optional[float]:
        return u.kelvin_to_celsius(value)

    @property
    def source_bands(self) -> Tuple[str, ...]:
        return (self.source_band,)

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        dataset = self.primary_dataset()

        collection = (
            ee.ImageCollection(ERA5_DAILY)
            .filterDate(context.start_date, context.end_date)
            .filterBounds(context.geometry)
            .select([self.source_band])
        )
        day_count = int(collection.size().getInfo())

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
            band=self.source_band,
            total_pixel_count=estimate_pixel_count(
                area_sq_m, ERA5_WORKING_SCALE
            ),
            pixel_area_sq_m=pixel_area_sq_m(ERA5_WORKING_SCALE),
            band_spec=dataset.band(self.source_band),
        )

        quality = assess_quality(
            image_count=max(day_count, 1),
            coverage_percent=stats.coverage_percent,
            valid_pixel_count=stats.valid_pixel_count,
            thresholds=QualityThresholds(
                excellent_min_images=10,
                good_min_images=5,
                moderate_min_images=3,
                poor_min_images=1,
                min_coverage_percent=5.0,
                min_valid_pixels=1,
                excellent_min_coverage=95.0,
                good_min_coverage=50.0,
            ),
        )

        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=[self.source_band],
            formula=(
                f"{self.source_band} in kelvin, time mean over the period, "
                "then spatial mean; "
                f"{self.conversion}"
            ),
            quality=quality,
            image_count=day_count,
            aggregation_method=(
                "time mean of daily values, then spatial mean, converted to "
                "degrees Celsius"
            ),
            extra_limitations=self.limitations,
        )

        if day_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No ERA5-Land days were available for the requested "
                    "period, so no soil temperature is reported."
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
                    f"{day_count} ERA5-Land day(s) were found but no valid "
                    "pixels were returned for this area, so no soil "
                    "temperature is reported."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        converted = self._convert_stats(stats)

        warnings: List[str] = [
            "This is a land surface model field at roughly 11 km, not a "
            "soil-temperature probe reading at the field.",
        ]
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
        """Apply the kelvin-to-celsius shift to every statistic.

        A temperature difference has the same size in both units, so the
        standard deviation needs no conversion; every absolute statistic
        does.
        """
        return SpatialStats(
            mean=self.convert(stats.mean),
            median=self.convert(stats.median),
            min=self.convert(stats.min),
            max=self.convert(stats.max),
            std_dev=stats.std_dev,
            p10=self.convert(stats.p10),
            p25=self.convert(stats.p25),
            p75=self.convert(stats.p75),
            p90=self.convert(stats.p90),
            valid_pixel_count=stats.valid_pixel_count,
            total_pixel_count=stats.total_pixel_count,
            valid_area_sq_m=stats.valid_area_sq_m,
        )


class SoilTemperatureLevel1Metric(_SoilTemperatureMetric):
    """Soil temperature of the 0 to 7 cm layer, from ERA5-Land."""

    key = "soil_temperature_0_7cm"
    display_name = "Soil Temperature (0-7 cm)"
    display_name_fa = "دمای خاک (۰-۷ سانتی‌متر)"
    source_band = "soil_temperature_level_1"
    description = (
        "Mean soil temperature of the 0 to 7 cm layer over the requested "
        "period, from the ERA5-Land reanalysis land surface model."
    )
    limitations = (
        "THIS IS A MODEL FIELD, NOT A MEASUREMENT. ERA5-Land is a "
        "reanalysis: a land surface model constrained by observations at a "
        "scale far coarser than a field. No instrument measured the soil "
        "temperature at this location.",
        "At roughly 11 km the model grid cell is far larger than a field, "
        "so the value describes a region and cannot be attributed to one "
        "plot.",
        "This is SOIL temperature at 0 to 7 cm. It is not the 2 m air "
        "temperature and not the land-surface skin temperature, and the "
        "three must not be interchanged.",
        "The model does not know the field's mulch, residue cover or "
        "irrigation, all of which change shallow soil temperature "
        "substantially.",
        "The value is a period mean. Shallow soil temperature has a large "
        "diurnal cycle, so the mean describes neither midday nor dawn.",
    )


class SoilTemperatureLevel2Metric(_SoilTemperatureMetric):
    """Soil temperature of the 7 to 28 cm layer, from ERA5-Land."""

    key = "soil_temperature_7_28cm"
    display_name = "Soil Temperature (7-28 cm)"
    display_name_fa = "دمای خاک (۷-۲۸ سانتی‌متر)"
    source_band = "soil_temperature_level_2"
    description = (
        "Mean soil temperature of the 7 to 28 cm layer over the requested "
        "period, from the ERA5-Land reanalysis land surface model."
    )
    limitations = (
        "THIS IS A MODEL FIELD, NOT A MEASUREMENT.",
        "At roughly 11 km the value describes a region, not a field.",
        "This is SOIL temperature at 7 to 28 cm, distinct from the 2 m air "
        "temperature, the land-surface skin temperature and the shallower "
        "0 to 7 cm soil layer. The layers are not interchangeable: shallow "
        "soil follows the diurnal cycle closely while 7 to 28 cm lags and "
        "damps it.",
        "The value is a period mean and describes no specific time of day.",
    )


# ==========================================================================
# Not produced: soil properties absent from Earth Engine
# ==========================================================================
#
# Every metric below exists for the same reason: a user asking for soil
# texture or organic carbon must receive a specific, checkable answer
# rather than silence that reads as an oversight, or — worse — a proxy
# that looks like a measurement. The reason is therefore the same in
# every case and is stated in full once here so the individual strings
# can stay short enough to be read.
#
# The reason, verified live against the Earth Engine archive:
#
#   ISRIC/SoilGrids250m/v2_0  ->  ImageCollection of exactly 3 images:
#                                 /wv0010, /wv0033, /wv1500
#   ISRIC/SoilGrids250m/v2_0/soc, /clay, /sand, /silt, /bdod, /phh2o,
#   /cec, /cfvo                              ->  NOT FOUND
#
# The property layers are served only by the ISRIC REST API, which
# answers single-point queries and cannot reduce an area, and whose
# published units were confirmed during this phase against the live
# service. Building an area-mean soil-property metric on a point API is
# a separate subsystem with its own sampling and rate-limit questions,
# and is deliberately out of scope for this phase rather than approximated.

_PROPERTY_UNAVAILABLE_CODE = "no_earth_engine_soil_property_layer"
_PROPERTY_UNAVAILABLE_REASON = (
    "Not produced. The SoilGrids 2.0 collection in Earth Engine "
    "({dataset}) was verified against the live archive and contains "
    "exactly three images — the volumetric water retention assets "
    "wv0010, wv0033 and wv1500 — and no {property} layer. The asset "
    "ISRIC/SoilGrids250m/v2_0/{code} does not resolve. The {property} "
    "prediction is served only by ISRIC's REST API, which answers "
    "single-point queries and cannot perform an area reduction, so an "
    "area-mean {property} metric cannot be built on the verified Earth "
    "Engine datasets this engine reads. Registering the gap states it "
    "rather than leaving a user to guess whether the omission was "
    "deliberate. A point-sampled soil-property service is a legitimate "
    "later addition; an invented proxy is not."
).format(
    dataset=SOILGRIDS,
    property="{property}",
    code="{code}",
)

_PROPERTY_LIMITATIONS = (
    "SoilGrids is a modelled prediction from a quantile random forest "
    "trained on a global compilation of soil profiles, not a laboratory "
    "measurement at the field.",
    "At 250 m within-field soil variability is not resolved.",
    "A gridded soil prediction is not a substitute for laboratory soil "
    "analysis, and it is not a fertility diagnosis, a nutrient-deficiency "
    "diagnosis or a fertiliser recommendation.",
)


class _UnavailableSoilPropertyMetric(Metric):
    """Base class for soil properties the verified datasets cannot supply.

    Subclasses set :attr:`property_name` and :attr:`property_code`; the
    reason is assembled from those so it always names the specific layer
    that is missing rather than describing the situation generically.
    """

    domain = MetricDomain.SOIL
    dataset_ids: Tuple[str, ...] = ()
    measurement_basis = MeasurementBasis.MODELLED
    unit = "unavailable"

    #: Human-readable property name, used in the reason text.
    property_name: str = ""
    #: The SoilGrids property code the REST API publishes it under.
    property_code: str = ""
    #: The unit the verified source would publish it in.
    property_unit: str = ""

    unavailable_code = _PROPERTY_UNAVAILABLE_CODE
    unavailable_reason = _PROPERTY_UNAVAILABLE_REASON

    def __init__(self) -> None:
        super().__init__()
        if not self.property_name or not self.property_code:
            raise ValueError(
                f"{type(self).__name__} must declare property_name and "
                "property_code so its unavailability reason names the "
                "specific missing layer."
            )

    def metadata(self) -> Dict[str, Any]:
        metadata = super().metadata()
        metadata["available"] = False
        metadata["unavailable_code"] = self.unavailable_code
        metadata["unavailable_reason"] = self._reason()
        return metadata

    def compute(self, context: MetricContext) -> MetricResult:
        return MetricResult.unavailable(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            reason=self.unavailable_code,
            message=self._reason(),
            unit=self.property_unit,
        )

    def _reason(self) -> str:
        return self.unavailable_reason.format(
            property=self.property_name,
            code=self.property_code,
        )


class SoilOrganicCarbonMetric(_UnavailableSoilPropertyMetric):
    """Soil organic carbon — no Earth Engine layer exists."""

    key = "soil_organic_carbon"
    display_name = "Soil Organic Carbon (not produced)"
    display_name_fa = "کربن آلی خاک (تولید نمی‌شود)"
    property_name = "soil organic carbon"
    property_code = "soc"
    property_unit = "g/kg"
    description = (
        "Not produced. SoilGrids 2.0 publishes no soil organic carbon layer "
        "inside Earth Engine; only the water-retention assets are served "
        "there."
    )
    limitations = _PROPERTY_LIMITATIONS


class SoilClayContentMetric(_UnavailableSoilPropertyMetric):
    """Clay content — no Earth Engine layer exists."""

    key = "soil_clay_content"
    display_name = "Clay Content (not produced)"
    display_name_fa = "درصد رس خاک (تولید نمی‌شود)"
    property_name = "clay content"
    property_code = "clay"
    property_unit = "percent"
    description = (
        "Not produced. SoilGrids 2.0 publishes no clay content layer inside "
        "Earth Engine; only the water-retention assets are served there."
    )
    limitations = _PROPERTY_LIMITATIONS


class SoilSandContentMetric(_UnavailableSoilPropertyMetric):
    """Sand content — no Earth Engine layer exists."""

    key = "soil_sand_content"
    display_name = "Sand Content (not produced)"
    display_name_fa = "درصد شن خاک (تولید نمی‌شود)"
    property_name = "sand content"
    property_code = "sand"
    property_unit = "percent"
    description = (
        "Not produced. SoilGrids 2.0 publishes no sand content layer inside "
        "Earth Engine; only the water-retention assets are served there."
    )
    limitations = _PROPERTY_LIMITATIONS


class SoilSiltContentMetric(_UnavailableSoilPropertyMetric):
    """Silt content — no Earth Engine layer exists."""

    key = "soil_silt_content"
    display_name = "Silt Content (not produced)"
    display_name_fa = "درصد سیلت خاک (تولید نمی‌شود)"
    property_name = "silt content"
    property_code = "silt"
    property_unit = "percent"
    description = (
        "Not produced. SoilGrids 2.0 publishes no silt content layer inside "
        "Earth Engine; only the water-retention assets are served there."
    )
    limitations = _PROPERTY_LIMITATIONS


class SoilBulkDensityMetric(_UnavailableSoilPropertyMetric):
    """Bulk density of the fine earth — no Earth Engine layer exists."""

    key = "soil_bulk_density"
    display_name = "Bulk Density (not produced)"
    display_name_fa = "چگالی ظاهری خاک (تولید نمی‌شود)"
    property_name = "bulk density"
    property_code = "bdod"
    property_unit = "kg/dm3"
    description = (
        "Not produced. SoilGrids 2.0 publishes no bulk density layer inside "
        "Earth Engine; only the water-retention assets are served there."
    )
    limitations = _PROPERTY_LIMITATIONS


class SoilPhMetric(_UnavailableSoilPropertyMetric):
    """Soil pH in water — no Earth Engine layer exists."""

    key = "soil_ph"
    display_name = "Soil pH (not produced)"
    display_name_fa = "pH خاک (تولید نمی‌شود)"
    property_name = "soil pH"
    property_code = "phh2o"
    property_unit = "pH"
    description = (
        "Not produced. SoilGrids 2.0 publishes no soil pH layer inside "
        "Earth Engine; only the water-retention assets are served there."
    )
    limitations = _PROPERTY_LIMITATIONS + (
        "Soil pH is a chemical property of the soil. It is not a nutrient "
        "deficiency diagnosis and not a fertiliser recommendation.",
    )


class SoilCationExchangeCapacityMetric(_UnavailableSoilPropertyMetric):
    """Cation exchange capacity — no Earth Engine layer exists."""

    key = "soil_cation_exchange_capacity"
    display_name = "Cation Exchange Capacity (not produced)"
    display_name_fa = "ظرفیت تبادل کاتیونی خاک (تولید نمی‌شود)"
    property_name = "cation exchange capacity"
    property_code = "cec"
    property_unit = "cmol(c)/kg"
    description = (
        "Not produced. SoilGrids 2.0 publishes no cation exchange capacity "
        "layer inside Earth Engine; only the water-retention assets are "
        "served there."
    )
    limitations = _PROPERTY_LIMITATIONS


class SoilCoarseFragmentsMetric(_UnavailableSoilPropertyMetric):
    """Coarse fragment volume — no Earth Engine layer exists."""

    key = "soil_coarse_fragments"
    display_name = "Coarse Fragments (not produced)"
    display_name_fa = "قطعات درشت خاک (تولید نمی‌شود)"
    property_name = "coarse fragment"
    property_code = "cfvo"
    property_unit = "cm3/100cm3"
    description = (
        "Not produced. SoilGrids 2.0 publishes no coarse fragment layer "
        "inside Earth Engine; only the water-retention assets are served "
        "there."
    )
    limitations = _PROPERTY_LIMITATIONS


class SoilTextureClassMetric(_UnavailableSoilPropertyMetric):
    """USDA texture class — unavailable because its inputs are unavailable.

    A texture class is derived from the sand, silt and clay percentages.
    All three are absent from Earth Engine, so no classification can be
    produced. This is registered separately from the three fraction
    metrics because the question "what texture class is this soil?" is a
    distinct user question, and because the answer names a different
    missing input than the fraction metrics do.
    """

    key = "soil_texture_class"
    display_name = "Soil Texture Class (not produced)"
    display_name_fa = "طبقه بافت خاک (تولید نمی‌شود)"
    property_name = "texture class"
    property_code = "clay"
    property_unit = "class"
    unavailable_code = "no_texture_fractions"
    unavailable_reason = (
        "Not produced. A USDA texture class is derived from the sand, silt "
        "and clay percentages, and none of the three is published as an "
        "Earth Engine layer: the verified SoilGrids 2.0 collection "
        f"({SOILGRIDS}) contains only the water-retention assets wv0010, "
        "wv0033 and wv1500. With no fractions there is nothing to "
        "classify, and estimating a class from water retention alone would "
        "be an invented proxy presented as a measurement."
    )
    description = (
        "Not produced. Texture classification needs sand, silt and clay "
        "fractions, none of which Earth Engine serves for SoilGrids 2.0."
    )
    limitations = (
        "The USDA texture triangle classifies a soil from its sand, silt "
        "and clay percentages. It is a summary of those three numbers, not "
        "a substitute for them, and a class derived from any other input "
        "would not be a texture class at all.",
        "A texture class is a coarse summary. Two soils of the same class "
        "can differ substantially in the properties that actually govern "
        "water movement.",
    )


class SoilSalinityMetric(_UnavailableSoilPropertyMetric):
    """Soil salinity — no direct observation exists in any verified dataset.

    Registered so that the question "is this soil saline?" receives a
    precise answer instead of silence. SoilGrids pH, organic carbon, clay
    and texture are **not** salinity, and none of them is used here to
    manufacture a salinity number. No electrical-conductivity or salinity
    band exists in any dataset this engine reads.
    """

    key = "soil_salinity"
    display_name = "Soil Salinity (not produced)"
    display_name_fa = "شوری خاک (تولید نمی‌شود)"
    property_name = "salinity"
    property_code = "ec"
    property_unit = "dS/m"
    unavailable_code = "no_direct_salinity_observation"
    unavailable_reason = (
        "Not produced. No verified dataset available to this engine "
        "provides a direct soil electrical conductivity or salinity "
        "observation. SoilGrids pH, soil organic carbon, clay content and "
        "texture are not salinity and are not used here as proxies for it: "
        "each measures a different quantity, and a number derived from "
        "them would be presented under a name it does not deserve. The "
        "only soil-property layers published inside Earth Engine for "
        f"({SOILGRIDS}) are the water-retention assets, none of which "
        "measures salinity. A remote-sensing salinity proxy may be a "
        "legitimate subject of a later dedicated phase, but it would need "
        "its own verified dataset and its own proxy disclaimer, not a "
        "renamed soil property."
    )
    description = (
        "Not produced. No verified direct soil salinity or electrical "
        "conductivity observation exists in the current dataset "
        "configuration."
    )
    limitations = (
        "Salinity is measured as electrical conductivity of a saturated "
        "extract or paste. No registered dataset provides it.",
        "Soil pH, organic carbon and texture are not salinity, and a "
        "salinity figure must never be derived from them silently.",
    )


# ==========================================================================
# Collections
# ==========================================================================

#: Soil-property metrics that carry a value.
SOIL_PROPERTY_METRICS: Tuple[Metric, ...] = (
    SoilFieldCapacityMetric(),
    SoilWiltingPointMetric(),
    SoilAvailableWaterCapacityMetric(),
    SoilTemperatureLevel1Metric(),
    SoilTemperatureLevel2Metric(),
)

#: Registered so the catalog can answer "can you tell me the soil "
#: texture / organic carbon / salinity?" with a reasoned no, rather than "
#: with silence that could be mistaken for an oversight.
UNAVAILABLE_SOIL_PROPERTY_METRICS: Tuple[Metric, ...] = (
    SoilOrganicCarbonMetric(),
    SoilClayContentMetric(),
    SoilSandContentMetric(),
    SoilSiltContentMetric(),
    SoilBulkDensityMetric(),
    SoilPhMetric(),
    SoilCationExchangeCapacityMetric(),
    SoilCoarseFragmentsMetric(),
    SoilTextureClassMetric(),
    SoilSalinityMetric(),
)

ALL_SOIL_PROPERTY_METRICS: Tuple[Metric, ...] = (
    SOIL_PROPERTY_METRICS + UNAVAILABLE_SOIL_PROPERTY_METRICS
)
