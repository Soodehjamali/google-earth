"""Terrain metrics: elevation, slope and aspect from a digital elevation model.

The two rules that govern this module
-------------------------------------
**1. An aspect of 0 degrees does not mean "flat".**

``ee.Terrain.aspect`` returns the downslope direction in degrees clockwise
from north. A slope that descends toward the east gives 90, one descending
toward the north gives 0. Flat ground *also* gives 0, because there is no
downslope direction to report.

Verified against live Earth Engine with synthetic planes rather than taken
from documentation, because the documentation does not state the flat-case
convention:

    plane descending eastward  -> aspect 90
    plane descending northward -> aspect  0
    genuinely flat terrain     -> aspect  0

So the value 0 carries two incompatible meanings, and a mean over a mixed
area is a blend of a direction and an absence. Reporting a bare mean aspect
would therefore publish a number that looks like a compass bearing and is
partly an artefact of flat ground.

This module responds by masking aspect to pixels at or above a documented
slope threshold, computing the direction as a *circular* mean rather than an
arithmetic one, and reporting the fraction of area excluded. That excluded
fraction is a first-class part of the result, not a footnote.

**2. An arithmetic mean of compass bearings is wrong.**

Aspect is an angle. Two pixels facing 350 and 10 degrees both face roughly
north, but their arithmetic mean is 180 — due south, the exact opposite
direction. The circular mean, taken through the sine and cosine components,
gives 0 as it should. ``circular_mean_degrees`` implements this and is
tested against that wrap-around case directly.

The digital elevation model
---------------------------
NASADEM is primary, SRTM is the fallback. Both are a single 2000 acquisition
and are therefore *static*: this module's metrics ignore the requested date
range for the elevation itself and say so in their provenance. The date range
is still checked against the declared coverage window so that a nonsensical
request fails loudly.

On topographic wetness index
----------------------------
Not produced. See ``TopographicWetnessIndexMetric`` for the full reasoning:
TWI needs flow accumulation, which is a globally serial quantity, and Earth
Engine exposes no primitive for it. A single focal pass is not a substitute.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
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
from app.services.agriculture.registry import (
    TERRAIN_ASPECT_MIN_SLOPE_DEG,
    TERRAIN_ASPECT_SECTORS,
    get_dataset,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    QualityLevel,
    SpatialStats,
)

logger = get_logger(__name__)

__all__ = [
    "NASADEM",
    "SRTM",
    "TERRAIN_WORKING_SCALE",
    "circular_mean_degrees",
    "circular_concentration",
    "resolve_aspect_sector",
    "ElevationMetric",
    "SlopeMetric",
    "AspectMetric",
    "TerrainRuggednessMetric",
    "TopographicWetnessIndexMetric",
    "TERRAIN_METRICS",
    "UNAVAILABLE_TERRAIN_METRICS",
    "ALL_TERRAIN_METRICS",
]


NASADEM = "NASA/NASADEM_HGT/001"
SRTM = "USGS/SRTMGL1_003"

#: Working scale for terrain reductions.
#:
#: The DEM is 30 m, but the *derivatives* are computed by Earth Engine over
#: the native 30 m grid and only then reduced. Reducing slope or aspect at a
#: coarser scale than the one they were derived on silently averages away the
#: very variation being measured, so this is pinned to the source resolution
#: rather than inherited from the analysis default.
TERRAIN_WORKING_SCALE = 30

#: Quality thresholds for a static product.
#:
#: Elevation has no cloud problem, no revisit and no scene count, so the
#: usual scene-count thresholds are all pinned to their floor of 1 and the
#: verdict rests on coverage. What matters here is how much of the
#: requested area actually carries a value: DEMs mask ocean, and NASADEM
#: also carries residual voids.
#:
#: The pixel floor is 10, matching the general default, because a standard
#: deviation over fewer than ten pixels does not describe an area.
TERRAIN_THRESHOLDS = QualityThresholds(
    excellent_min_images=1,
    good_min_images=1,
    moderate_min_images=1,
    poor_min_images=1,
    min_coverage_percent=20.0,
    min_valid_pixels=10,
    excellent_min_coverage=90.0,
    good_min_coverage=50.0,
)

_ASPECT_SLOPE_DISCLAIMER = (
    "Aspect is reported only over pixels at or above a slope threshold of "
    f"{TERRAIN_ASPECT_MIN_SLOPE_DEG:g} degrees, because below that a "
    "downslope direction is not meaningfully defined and Earth Engine "
    "returns 0, which is indistinguishable from due north."
)

_STATIC_DEM_DISCLAIMER = (
    "The elevation model is a single acquisition from February 2000. It "
    "does not reflect subsequent excavation, levelling, land subsidence, "
    "glacial retreat or volcanic change."
)


# ==========================================================================
# Circular statistics
# ==========================================================================


def circular_mean_degrees(
    sine_component: float,
    cosine_component: float,
) -> Optional[float]:
    """Return the circular mean of an angular distribution, in degrees.

    Takes the mean sine and cosine of the angles rather than the angles
    themselves. That is the whole point: an arithmetic mean of 350 and 10
    degrees is 180, the exact opposite of the direction both actually
    represent, whereas the circular mean is 0.

    Args:
        sine_component: Mean of sin(theta) over the sample.
        cosine_component: Mean of cos(theta) over the sample.

    Returns:
        The mean direction in ``[0, 360)``, or ``None`` when the two
        components are both zero. A zero resultant means the directions are
        uniformly spread and no mean direction exists — returning 0 there
        would invent a bearing out of a uniform distribution.
    """
    if sine_component is None or cosine_component is None:
        return None
    # The zero-resultant test must tolerate floating point. Six evenly
    # spaced directions sum to components around 1e-17, not exactly 0, and
    # atan2 of that noise is an arbitrary bearing: a uniform distribution
    # would be published as, say, 108 degrees. Anything below the epsilon
    # is numerically indistinguishable from no direction at all.
    if math.hypot(sine_component, cosine_component) < 1e-12:
        return None
    angle = math.degrees(math.atan2(sine_component, cosine_component))
    result = angle % 360.0
    # ``%`` can return exactly 360.0 for a tiny negative angle because of
    # floating-point rounding, and the same rounding can leave a value a
    # hair under 360, such as 359.99999994... for atan2 of -1e-9 radians.
    # Both are due north to far beyond any meaningful precision, and a
    # bearing outside the documented [0, 360) range is a contract breach,
    # so both are folded to 0.
    if result >= 360.0 - 1e-6:
        result = 0.0
    return result


def circular_concentration(
    sine_component: float,
    cosine_component: float,
) -> Optional[float]:
    """Return the mean resultant length R, a measure of directional agreement.

    ``R`` runs from 0 (directions uniformly spread over the compass, no
    prevailing direction) to 1 (every pixel faces the same way). It is
    reported alongside the mean so a reader can tell a genuine prevailing
    aspect from an average of noise.

    Args:
        sine_component: Mean of sin(theta) over the sample.
        cosine_component: Mean of cos(theta) over the sample.

    Returns:
        ``R`` in ``[0, 1]``, or ``None`` when either input is missing.
    """
    if sine_component is None or cosine_component is None:
        return None
    r = math.hypot(sine_component, cosine_component)
    # Guard against floating-point overshoot of the unit interval.
    return max(0.0, min(1.0, r))


def resolve_aspect_sector(aspect_degrees: Optional[float]) -> Optional[str]:
    """Name the compass sector an aspect falls in.

    Sectors are 45 degrees wide and centred on the eight cardinal and
    intercardinal directions, so the first sector wraps across 0 degrees.

    Args:
        aspect_degrees: An aspect in ``[0, 360)``, or ``None``.

    Returns:
        A short sector label such as ``"NW"``, or ``None`` when no aspect
        was supplied.
    """
    if aspect_degrees is None:
        return None
    value = float(aspect_degrees) % 360.0
    for name, low, high in TERRAIN_ASPECT_SECTORS:
        if low > high:
            # The wrapping sector, e.g. north spanning 337.5 to 22.5.
            if value >= low or value < high:
                return name
        elif low <= value < high:
            return name
    return None


# ==========================================================================
# DEM access
# ==========================================================================


def _dem_candidates(primary_id: str) -> Tuple[str, ...]:
    """The DEMs to try, most preferred first.

    NASADEM is preferred because it fills more voids than SRTM. The
    fallback is attempted only when the preferred product yields no
    values at all: a partially masked NASADEM is still better evidence
    than a clean SRTM pixel of a differently-defined surface, and both
    cover the same February 2000 acquisition.

    Args:
        primary_id: The metric's declared primary dataset ID.

    Returns:
        Candidate dataset IDs in preference order. A metric whose primary
        is already SRTM gets no fallback, because there is nothing lesser
        left to fall back to.
    """
    if primary_id == SRTM:
        return (SRTM,)
    return (primary_id, SRTM)


def _load_dem_image(ee_module: Any, dataset_id: str) -> Any:
    """Load a DEM as a single elevation image in metres.

    Both DEMs are static single-image products, so no collection filtering
    or compositing is involved. The image is cast to float: NASADEM's
    elevation band is stored as a signed integer, and integer arithmetic on
    the elevation differences that slope and aspect are built from would
    truncate the gradient and quantise the result.

    Ocean is masked by the product. A masked pixel is removed from the
    statistics rather than counted as a zero, which matters because a
    genuine elevation of zero is impossible over land here and a spurious
    sea-level pixel would drag a mean elevation down.
    """
    image = ee_module.Image(dataset_id).select("elevation")
    return image.toFloat()


def _reduce_dem_band(
    context: MetricContext,
    ee_module: Any,
    band_image: Any,
    band_name: str,
    reducer: Any,
    band_spec: Any = None,
) -> Tuple[SpatialStats, int]:
    """Reduce one terrain band and return its statistics.

    Args:
        context: The metric context supplying geometry and dates.
        ee_module: The Earth Engine module, injected.
        band_image: The image to reduce, already renamed if necessary.
        band_name: The band name Earth Engine will key the result under.
        reducer: The reducer to apply.
        band_spec: The registry band spec, which supplies the raw-to-physical
            conversion. Passing it is what makes the returned numbers
            physical; omitting it yields raw stored values.

    Returns:
        ``(stats, total_pixel_count)``.
    """
    total_pixels = estimate_pixel_count(
        context.option("area_sq_m"), TERRAIN_WORKING_SCALE
    )

    raw = band_image.reduceRegion(
        reducer=reducer,
        geometry=context.geometry,
        scale=TERRAIN_WORKING_SCALE,
        maxPixels=1e9,
    ).getInfo()

    stats = parse_reduction_result(
        raw,
        band=band_name,
        total_pixel_count=total_pixels,
        pixel_area_sq_m=pixel_area_sq_m(TERRAIN_WORKING_SCALE),
        band_spec=band_spec,
    )
    return stats, total_pixels


def _assess_terrain_quality(
    stats: SpatialStats,
    image_count: int,
) -> QualityLevel:
    """Grade a terrain result from coverage alone.

    Scene count is passed as the constant 1 because a DEM is a single
    static surface; the usual "too few scenes" test is meaningless here and
    would otherwise force a poor grade on perfectly good data.
    """
    return assess_quality(
        image_count=max(image_count, 1),
        coverage_percent=stats.coverage_percent,
        valid_pixel_count=stats.valid_pixel_count,
        thresholds=TERRAIN_THRESHOLDS,
    )


# ==========================================================================
# Elevation
# ==========================================================================


class ElevationMetric(Metric):
    """Elevation above the EGM96 geoid, as a spatial mean."""

    key = "elevation"
    display_name = "Elevation"
    display_name_fa = "ارتفاع از سطح دریا"
    domain = MetricDomain.TERRAIN
    unit = "m"
    dataset_ids = (NASADEM, SRTM)
    measurement_basis = MeasurementBasis.PRODUCT
    default_scale = TERRAIN_WORKING_SCALE
    description = (
        "Mean elevation above the EGM96 geoid over the requested area, from "
        "the NASADEM digital elevation model, falling back to SRTM where "
        "NASADEM has voids."
    )
    limitations = (
        _STATIC_DEM_DISCLAIMER,
        "This is a terrain elevation, not a canopy height and not a crop "
        "height. Over dense vegetation the radar surface sits closer to the "
        "top of the canopy than to the ground, so a forested area reads "
        "higher than its soil surface.",
        "Elevation is referenced to the EGM96 geoid. It is not a WGS84 "
        "ellipsoidal height, and the two differ by tens of metres depending "
        "on location.",
        "A mean elevation over a field is often of little agronomic "
        "interest on its own; the within-field range is usually what "
        "matters, and that is reported in the statistics rather than the "
        "mean alone.",
        "Ocean and other masked surfaces carry no elevation rather than an "
        "elevation of zero.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        stats: Optional[SpatialStats] = None
        dataset = None
        fallback_from: Optional[str] = None
        # The preferred product is tried first; the fallback runs only if
        # the preferred product returned nothing at all.
        for candidate_id in _dem_candidates(self.dataset_ids[0]):
            candidate = get_dataset(candidate_id)
            dem = _load_dem_image(ee, candidate_id)
            candidate_stats, _total = _reduce_dem_band(
                context,
                ee,
                dem,
                "elevation",
                build_reducer(ee),
                band_spec=candidate.band("elevation"),
            )
            if candidate_stats.has_values:
                stats = candidate_stats
                dataset = candidate
                break
            if stats is None:
                # Keep the preferred product's empty reduction for its
                # provenance, so a total failure reports the source the
                # user was promised rather than the last fallback tried.
                stats = candidate_stats
                dataset = candidate

        if dataset is None:  # pragma: no cover - dataset_ids is non-empty
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message="No DEM dataset could be resolved.",
                unit=self.unit,
            )
        if dataset.id != self.dataset_ids[0]:
            fallback_from = self.dataset_ids[0]

        total_pixels = estimate_pixel_count(
            context.option("area_sq_m"), TERRAIN_WORKING_SCALE
        )

        quality = _assess_terrain_quality(stats, 1)
        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["elevation"],
            formula="mean of the DEM elevation band, in metres above EGM96",
            quality=quality,
            image_count=1,
            aggregation_method="spatial mean over the geometry",
            fallback_from=fallback_from,
            extra_limitations=self.limitations,
        )

        # ``MetricResult`` forbids a value whose provenance says quality
        # is INSUFFICIENT or UNAVAILABLE: those levels mean no number
        # exists, and attaching one is a contradiction rather than a
        # caveat. The pixel floor of ``TERRAIN_THRESHOLDS`` therefore
        # doubles as the floor for publishing a value at all.
        if quality is QualityLevel.INSUFFICIENT or not stats.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No usable elevation pixels were returned for this "
                    "area, or too few for a spatial statistic. The product "
                    "masks ocean and other surfaces, and reported "
                    "elevation of zero would be indistinguishable from a "
                    "genuine sea-level value."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if fallback_from:
            warnings.append(
                f"NASADEM carried no data here; the result was taken from "
                f"the {dataset.name} fallback instead."
            )
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


# ==========================================================================
# Slope
# ==========================================================================


class SlopeMetric(Metric):
    """Terrain slope in degrees."""

    key = "slope"
    display_name = "Slope"
    display_name_fa = "شیب زمین"
    domain = MetricDomain.TERRAIN
    unit = "degrees"
    dataset_ids = (NASADEM, SRTM)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = TERRAIN_WORKING_SCALE
    description = (
        "Mean terrain slope in degrees, derived from the NASADEM elevation "
        "model with SRTM as fallback. Slope is the magnitude of the local "
        "elevation gradient."
    )
    limitations = (
        _STATIC_DEM_DISCLAIMER,
        "Slope is derived from the DEM by Earth Engine using the four "
        "connected neighbours of each pixel, so slope is unavailable around "
        "the edges of the image.",
        "The DEM is 30 m. Slopes shorter than that — a terrace riser, a "
        "field ditch, a plough furrow — are not resolved and appear as "
        "smooth ground.",
        "Over dense vegetation the radar surface follows the canopy, so "
        "slope in forested terrain reflects the canopy surface rather than "
        "the soil surface beneath it.",
        "Slope is a local derivative and is sensitive to noise in the "
        "underlying DEM, so a single pixel may be steeper or flatter than "
        "the field it represents.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        stats: Optional[SpatialStats] = None
        dataset = None
        fallback_from: Optional[str] = None
        for candidate_id in _dem_candidates(self.dataset_ids[0]):
            candidate = get_dataset(candidate_id)
            dem = _load_dem_image(ee, candidate_id)
            # Earth Engine returns slope in degrees from the DEM. No unit
            # conversion is applied because none is needed, and inventing one
            # would be exactly the kind of silent error this engine guards
            # against.
            slope = ee.Terrain.slope(dem).rename("slope")
            candidate_stats, _total = _reduce_dem_band(
                context,
                ee,
                slope,
                "slope",
                build_reducer(ee),
            )
            if candidate_stats.has_values:
                stats = candidate_stats
                dataset = candidate
                break
            if stats is None:
                stats = candidate_stats
                dataset = candidate

        if dataset is None:  # pragma: no cover - dataset_ids is non-empty
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message="No DEM dataset could be resolved.",
                unit=self.unit,
            )
        if dataset.id != self.dataset_ids[0]:
            fallback_from = self.dataset_ids[0]

        quality = _assess_terrain_quality(stats, 1)
        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["elevation"],
            formula=(
                "slope = degrees of the local elevation gradient, computed "
                "from the DEM by the Earth Engine terrain routine over the "
                "four connected neighbours of each pixel"
            ),
            quality=quality,
            image_count=1,
            aggregation_method="spatial mean over the geometry",
            fallback_from=fallback_from,
            extra_limitations=self.limitations,
        )

        # Same contradiction guard as elevation: a value under an
        # INSUFFICIENT verdict is rejected by ``MetricResult`` itself, so
        # it must be downgraded to a proper insufficient result here.
        if quality is QualityLevel.INSUFFICIENT or not stats.has_values:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "No usable slope pixels were returned for this area, "
                    "or too few for a spatial statistic. Slope requires "
                    "neighbouring elevation values, so an area smaller "
                    "than a few pixels, or one fully masked by the DEM, "
                    "yields nothing."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if fallback_from:
            warnings.append(
                f"NASADEM carried no data here; the result was taken from "
                f"the {dataset.name} fallback instead."
            )
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


# ==========================================================================
# Aspect
# ==========================================================================


class AspectMetric(Metric):
    """Downslope aspect, reported as a circular mean over sloped ground.

    The value carried by this metric is the circular mean aspect in degrees
    clockwise from north, computed over pixels whose slope is at or above
    ``TERRAIN_ASPECT_MIN_SLOPE_DEG``. The excluded flat fraction is reported
    through the ``flat_fraction`` statistic on the result's metadata and in
    the message, because it is a property of the answer rather than a
    footnote: an aspect computed over 40 percent flat ground describes the
    minority of the area.
    """

    key = "aspect"
    display_name = "Aspect (downslope direction)"
    display_name_fa = "جهت شیب"
    domain = MetricDomain.TERRAIN
    unit = "degrees"
    dataset_ids = (NASADEM, SRTM)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = TERRAIN_WORKING_SCALE
    description = (
        "Mean downslope aspect in degrees clockwise from north, computed as "
        "a circular mean over pixels above a stated slope threshold. Flat "
        "ground is excluded and its share of the area is reported."
    )
    limitations = (
        _ASPECT_SLOPE_DISCLAIMER,
        "An aspect of 0 degrees means due north. It does not mean flat. "
        "Earth Engine returns 0 for both, so the two are only "
        "distinguishable by consulting the slope.",
        "Aspect is reported as a circular mean, which is a direction, not "
        "a quantity. It must never be averaged arithmetically with another "
        "aspect; the mean of 350 and 10 degrees taken that way is 180, the "
        "opposite of the truth.",
        "A mean aspect is meaningless where the terrain is not "
        "directionally consistent. The concentration value reported "
        "alongside it says how much the pixels actually agree; a low "
        "concentration means the mean direction describes little.",
        _STATIC_DEM_DISCLAIMER,
        "Over dense vegetation the aspect reflects the canopy surface "
        "rather than the ground beneath it.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        reduction: Optional[Dict[str, Any]] = None
        dataset = None
        fallback_from: Optional[str] = None
        for candidate_id in _dem_candidates(self.dataset_ids[0]):
            candidate = get_dataset(candidate_id)
            dem = _load_dem_image(ee, candidate_id)
            slope = ee.Terrain.slope(dem)
            aspect = ee.Terrain.aspect(dem)

            # Aspect is only meaningful where there is a downslope direction.
            # Below the threshold Earth Engine reports 0, which is also what it
            # reports for due north, so flat pixels are removed rather than
            # allowed to masquerade as north-facing ones.
            sloped = aspect.updateMask(slope.gte(TERRAIN_ASPECT_MIN_SLOPE_DEG))

            # The mean direction comes from the mean of the sine and cosine
            # components, never from a mean of the angles themselves.
            radians = sloped.multiply(math.pi / 180.0)
            components = ee.Image.cat(
                radians.sin().rename("aspect_sin"),
                radians.cos().rename("aspect_cos"),
            )

            raw_components = components.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=context.geometry,
                scale=TERRAIN_WORKING_SCALE,
                maxPixels=1e9,
            ).getInfo()

            # How many pixels survived the slope mask, so the excluded flat
            # fraction can be stated rather than hidden.
            sloped_count_raw = sloped.reduceRegion(
                reducer=ee.Reducer.count(),
                geometry=context.geometry,
                scale=TERRAIN_WORKING_SCALE,
                maxPixels=1e9,
            ).getInfo()
            sloped_count = int(_as_float(sloped_count_raw.get("aspect")) or 0)

            if sloped_count > 0 and any(
                _as_float(raw_components.get(k)) is not None
                for k in ("aspect_sin", "aspect_cos")
            ):
                reduction = (raw_components, sloped_count)
                dataset = candidate
                break
            if reduction is None:
                reduction = (raw_components, sloped_count)
                dataset = candidate

        if dataset is None:  # pragma: no cover - dataset_ids is non-empty
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message="No DEM dataset could be resolved.",
                unit=self.unit,
            )
        if dataset.id != self.dataset_ids[0]:
            fallback_from = self.dataset_ids[0]

        raw_components, sloped_count = reduction
        total_pixels = estimate_pixel_count(
            context.option("area_sq_m"), TERRAIN_WORKING_SCALE
        )

        mean_sin = _as_float(raw_components.get("aspect_sin"))
        mean_cos = _as_float(raw_components.get("aspect_cos"))

        mean_aspect = circular_mean_degrees(mean_sin, mean_cos)
        concentration = circular_concentration(mean_sin, mean_cos)

        stats = SpatialStats()
        stats.valid_pixel_count = sloped_count
        stats.total_pixel_count = max(total_pixels, sloped_count)
        stats.valid_area_sq_m = sloped_count * pixel_area_sq_m(
            TERRAIN_WORKING_SCALE
        )
        if stats.total_pixel_count > 0:
            stats.missing_pixel_count = max(
                stats.total_pixel_count - sloped_count, 0
            )
            stats.missing_percent = (
                stats.missing_pixel_count / stats.total_pixel_count * 100.0
            )

        flat_count = max(total_pixels - sloped_count, 0)
        flat_fraction = (
            flat_count / total_pixels if total_pixels > 0 else None
        )

        quality = _assess_terrain_quality(stats, 1)
        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["elevation"],
            formula=(
                "aspect = atan2(mean(sin(theta)), mean(cos(theta))) in "
                "degrees clockwise from north, over pixels with slope >= "
                f"{TERRAIN_ASPECT_MIN_SLOPE_DEG:g} degrees"
            ),
            quality=quality,
            image_count=1,
            aggregation_method=(
                "circular mean of the downslope direction over sloped "
                "pixels, with the excluded flat fraction reported separately"
            ),
            fallback_from=fallback_from,
            extra_limitations=self.limitations,
        )

        # The aspect path has two separate reasons to refuse a value: no
        # direction exists (all flat or all masked), or the quality verdict
        # says the sloped sample is too small to describe the area.
        if quality is QualityLevel.INSUFFICIENT:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Too few sloped pixels were returned for the aspect to "
                    "describe the area."
                ),
                unit=self.unit,
                provenance=provenance,
            )
        if mean_aspect is None or sloped_count == 0:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "Aspect could not be computed. Either the area carries "
                    "no elevation data, or every pixel in it falls below "
                    f"the {TERRAIN_ASPECT_MIN_SLOPE_DEG:g} degree slope "
                    "threshold, in which case there is no downslope "
                    "direction to report. Reporting 0 degrees here would "
                    "claim the ground faces due north."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = [
            _ASPECT_SLOPE_DISCLAIMER,
        ]
        if fallback_from:
            warnings.append(
                f"NASADEM carried no data here; the result was taken from "
                f"the {dataset.name} fallback instead."
            )
        if flat_fraction is not None and flat_fraction > 0.0:
            warnings.append(
                f"{flat_fraction * 100.0:.1f} percent of this area is below "
                "the slope threshold and is excluded from the aspect. The "
                "mean describes the remaining sloped portion only."
            )
        if concentration is not None and concentration < 0.5:
            warnings.append(
                "Directional agreement is low "
                f"(concentration {concentration:.2f}), so the mean aspect "
                "does not represent a prevailing direction in this area."
            )
        if mean_aspect is not None:
            sector = resolve_aspect_sector(mean_aspect)
            if sector is not None:
                warnings.append(
                    f"The mean downslope direction is {mean_aspect:.1f} "
                    f"degrees, which is {sector}."
                )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=mean_aspect,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )


def _as_float(value: Any) -> Optional[float]:
    """Coerce a reduction value to float, rejecting booleans and junk.

    Earth Engine returns numbers and occasionally strings, and ``bool`` is a
    subclass of ``int`` in Python, so a boolean must be rejected explicitly
    rather than silently treated as 0 or 1.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


# ==========================================================================
# Terrain ruggedness
# ==========================================================================


class TerrainRuggednessMetric(Metric):
    """Standard deviation of elevation within the area.

    Reported because it is frequently more useful than the mean elevation:
    a field on a uniform 2 percent grade and one straddling a gully can
    share a mean elevation, and the two are managed differently.
    """

    key = "terrain_ruggedness"
    display_name = "Terrain ruggedness (elevation standard deviation)"
    display_name_fa = "ناهمواری زمین"
    domain = MetricDomain.TERRAIN
    unit = "m"
    dataset_ids = (NASADEM, SRTM)
    measurement_basis = MeasurementBasis.DERIVED
    default_scale = TERRAIN_WORKING_SCALE
    description = (
        "Standard deviation of elevation over the requested area, in "
        "metres. A direct measure of how uneven the ground is within the "
        "area, independent of its overall height."
    )
    limitations = (
        _STATIC_DEM_DISCLAIMER,
        "The standard deviation describes the spread of elevation, not its "
        "arrangement. Level terraces on a steep hillside and uniform rough "
        "ground can produce the same value.",
        "It is computed over the whole geometry at once, so it does not "
        "show where the variation sits within the area.",
        "At 30 m the DEM smooths features shorter than a pixel, so a "
        "ploughed surface and a smooth one may be indistinguishable.",
    )

    def compute(self, context: MetricContext) -> MetricResult:
        import ee

        stats: Optional[SpatialStats] = None
        dataset = None
        fallback_from: Optional[str] = None
        for candidate_id in _dem_candidates(self.dataset_ids[0]):
            candidate = get_dataset(candidate_id)
            dem = _load_dem_image(ee, candidate_id)
            candidate_stats, total_pixels = _reduce_dem_band(
                context,
                ee,
                dem,
                "elevation",
                build_reducer(ee),
                band_spec=candidate.band("elevation"),
            )
            if candidate_stats.has_values:
                stats = candidate_stats
                dataset = candidate
                break
            if stats is None:
                stats = candidate_stats
                dataset = candidate

        if dataset is None:  # pragma: no cover - dataset_ids is non-empty
            return MetricResult.unavailable(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message="No DEM dataset could be resolved.",
                unit=self.unit,
            )
        if dataset.id != self.dataset_ids[0]:
            fallback_from = self.dataset_ids[0]

        quality = _assess_terrain_quality(stats, 1)
        provenance = self.build_provenance(
            context=context,
            dataset=dataset,
            bands=["elevation"],
            formula="standard deviation of the DEM elevation band, in metres",
            quality=quality,
            image_count=1,
            aggregation_method="spatial standard deviation over the geometry",
            fallback_from=fallback_from,
            extra_limitations=self.limitations,
        )

        # Same contradiction guard: the INSUFFICIENT verdict must become
        # the result, not ride along under a published value.
        if quality is QualityLevel.INSUFFICIENT or stats.std_dev is None:
            return MetricResult.insufficient(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                message=(
                    "A standard deviation could not be computed for this "
                    "area, which usually means fewer than two valid pixels "
                    "were returned."
                ),
                unit=self.unit,
                provenance=provenance,
            )

        warnings: List[str] = []
        if fallback_from:
            warnings.append(
                f"NASADEM carried no data here; the result was taken from "
                f"the {dataset.name} fallback instead."
            )
        if stats.valid_pixel_count < 10:
            warnings.append(
                f"Only {stats.valid_pixel_count} valid pixels were returned. "
                "A standard deviation over so few samples is not a reliable "
                "description of the area."
            )
        if quality is QualityLevel.POOR:
            warnings.append(describe_quality(QualityLevel.POOR))

        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=stats.std_dev,
            unit=self.unit,
            stats=stats,
            provenance=provenance,
            warnings=warnings,
        )


# ==========================================================================
# Not produced
# ==========================================================================

TWI_UNAVAILABLE_CODE = "no_flow_accumulation_primitive"

TWI_UNAVAILABLE_REASON = (
    "Not produced. The topographic wetness index requires flow "
    "accumulation — how many upstream cells drain through a point — and "
    "Earth Engine provides no flow accumulation, flow direction or "
    "watershed routine. Its terrain module offers only local per-pixel "
    "derivatives: slope, aspect, hillshade, products and fillMinima. Flow "
    "accumulation is a globally serial quantity: a cell's value depends on "
    "its upslope neighbours, whose values depend on theirs, recursively to "
    "the watershed divide. Any correct implementation therefore needs a "
    "loop with a round trip per iteration, which cannot be bounded for a "
    "real catchment. A single focal pass over the eight neighbours is not "
    "flow accumulation — it counts one pixel of upslope area, not the "
    "contributing area — so substituting it would yield a wetness map that "
    "looks plausible and is wrong wherever flow concentrates. Reporting "
    "nothing is the honest outcome."
)

TWI_LIMITATIONS = (
    "TWI is ln(a / tan(beta)), where a is the upslope contributing area "
    "per unit contour length and beta is the local slope. Earth Engine can "
    "supply beta directly but not a.",
    "Flow accumulation is inherently serial. Earth Engine's reducer model "
    "operates on independent pixels and tiles, so there is no primitive for "
    "it, and no flow direction, watershed or drainage-network algorithm "
    "exists in the API.",
    "A D8 or multiple-flow-direction implementation can be written as an "
    "iterative loop, but each iteration depends on the previous one and "
    "requires a separate evaluation. Over a real catchment the iteration "
    "count is unbounded, so the computation does not terminate in "
    "predictable time or cost.",
    "Depression filling, a prerequisite for flow routing, is also absent. "
    "The fillMinima routine operates on integer images only and is not a "
    "hydrological conditioning algorithm.",
    "A one-pixel focal maximum counts a single upslope neighbour. It is a "
    "local convergence proxy, not a contributing area, and the two diverge "
    "most where wetness actually concentrates — in valleys and hollows.",
    "Because a plausible-looking but incorrect wetness index is more "
    "dangerous than none, this engine does not publish one.",
)


class TopographicWetnessIndexMetric(Metric):
    """TWI, registered as unavailable so the catalog can explain why.

    This exists so that a user asking "can you give me a wetness index?"
    receives a specific answer with the missing input named, rather than
    silence that could be read as an oversight, or — worse — a proxy that
    looks like a real wetness map.
    """

    key = "topographic_wetness_index"
    display_name = "Topographic Wetness Index (not produced)"
    display_name_fa = "شاخص رطوبت توپوگرافی (تولید نمی‌شود)"
    domain = MetricDomain.TERRAIN
    unit = "dimensionless"
    dataset_ids: Tuple[str, ...] = ()
    measurement_basis = MeasurementBasis.INFERENCE
    description = (
        "Not produced. TWI needs flow accumulation, and Earth Engine has no "
        "flow accumulation, flow direction or watershed routine."
    )
    limitations = TWI_LIMITATIONS
    unavailable_reason = TWI_UNAVAILABLE_REASON
    unavailable_code = TWI_UNAVAILABLE_CODE

    def compute(self, context: MetricContext) -> MetricResult:
        return MetricResult.unavailable(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            # The specific code, not the generic default: 'not_supported'
            # would describe any metric, where this names exactly which
            # Earth Engine primitive is missing.
            reason=self.unavailable_code,
            message=self.unavailable_reason,
            unit=self.unit,
        )

    def metadata(self) -> Dict[str, Any]:
        metadata = super().metadata()
        metadata["available"] = False
        metadata["unavailable_code"] = self.unavailable_code
        metadata["unavailable_reason"] = self.unavailable_reason
        return metadata


# ==========================================================================
# Collections
# ==========================================================================

TERRAIN_METRICS: Tuple[Metric, ...] = (
    ElevationMetric(),
    SlopeMetric(),
    AspectMetric(),
    TerrainRuggednessMetric(),
)

#: Registered so the catalog can answer "why is there no wetness index?"
#: with the specific missing input, rather than with silence.
UNAVAILABLE_TERRAIN_METRICS: Tuple[Metric, ...] = (
    TopographicWetnessIndexMetric(),
)

ALL_TERRAIN_METRICS: Tuple[Metric, ...] = (
    TERRAIN_METRICS + UNAVAILABLE_TERRAIN_METRICS
)
