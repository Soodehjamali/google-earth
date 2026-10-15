"""Spatial support policy for Point request geometries.

A GeoJSON ``Point`` has zero area. Two things go wrong when a metric
reduces imagery over one:

* ``area_sq_m`` is never set, so :func:`estimate_pixel_count` returns a
  denominator of zero, ``SpatialStats`` clamps the total up to the valid
  count, and coverage reports a confident 100 % for a geometry that
  covers nothing.
* the reduction visits exactly one pixel — the one containing the
  coordinate — which almost never clears a metric's ``min_valid_pixels``
  floor, so the real measurement is discarded as insufficient.

This module is the single place that decides what a Point request means.
It does not change any threshold, does not invent a value, and does not
touch Polygon requests at all: a Polygon is already an area, so it keeps
the behaviour it had.

The policy
----------
Every dataset whose grid is *not* queryable at a point is reduced over a
disc of a radius derived from that dataset's own native resolution. The
radius is chosen so the disc contains comfortably more pixels than the
loosest quality floor the engine applies, measured at the dataset's
native scale:

=====================  ========  ================  =====================
native resolution      family    radius            pixels at native scale
=====================  ========  ================  =====================
``<= 20 m``            field     ``60 m``          113 @ 10 m, 28 @ 20 m
``<= 120 m``           local     ``100 m``         34 @ 30 m, 3 @ 100 m
``<= 500 m``           soil      ``max(500, 1.5x)`` 12 @ 250 m, 7 @ 500 m
``<= 5000 m``          regional  ``1.5 x native``   7 @ 1000 m, 7 @ 4638 m
``> 5000 m``           coarse    ``1.5 x native``   7 @ 9000 m, 7 @ 11000 m
=====================  ========  ================  =====================

A handful of products sit on grids far coarser than any field, where a
disc would be a lie as much as a point would: an 11 km reanalysis cell
already *is* the neighbourhood. Those keep the containing-pixel
semantics and are listed in :data:`POINT_QUERYABLE_DATASET_IDS`.

Every value produced under this policy carries a provenance disclosure
(see :func:`apply_support_disclosure`) so the UI can say what the number
actually describes.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

from app.services.agriculture.types import DatasetSpec

__all__ = [
    "POINT_SUPPORT_POLICY_VERSION",
    "POINT_QUERYABLE_DATASET_IDS",
    "SupportRegion",
    "parse_native_resolution_m",
    "family_for_native_resolution_m",
    "support_radius_m",
    "resolve_support_context",
    "scope_context_for_dataset",
    "open_support_scope",
    "apply_support_disclosure",
    "support_identity",
]

logger = logging.getLogger(__name__)

#: Bumped whenever the policy below changes, so cached analyses that were
#: produced under a different meaning of "Point" can never be replayed.
POINT_SUPPORT_POLICY_VERSION = "point-support-v2"

FAMILY_FIELD = "field"
FAMILY_LOCAL = "local"
FAMILY_SOIL = "soil"
FAMILY_REGIONAL = "regional"
FAMILY_COARSE = "coarse"
FAMILY_POINT_QUERYABLE = "point_queryable"

#: Datasets that must keep the containing-pixel semantics. Each cell is
#: already a district-scale sample; buffering one would exchange a
#: coordinate that is too fine for a shape that is too precise to defend.
POINT_QUERYABLE_DATASET_IDS = frozenset(
    {
        "ECMWF/ERA5_LAND/DAILY_AGGR",
        "NASA/GLDAS/V021/NOAH/G025/T3H",
        "NASA/SMAP/SPL4SMGP/008",
    }
)

#: Disc radius for the fine grids (Sentinel-2, Sentinel-1, Dynamic
#: World, WorldCereal). Sized to clear the 20-pixel floor that the
#: Sentinel-2 and SAR threshold sets apply: 113 pixels at 10 m and 28 at
#: 20 m.
FIELD_RADIUS_M = 60.0

#: Disc radius for Landsat-class and NASADEM-class grids. Sized to clear
#: the 10-pixel floor of the terrain threshold set (34 pixels at 30 m)
#: while staying a sensible neighbourhood for a 100 m thermal band.
LOCAL_RADIUS_M = 100.0

#: Floor for the mid-resolution family, so a 250 m product reaches the
#: 10-pixel floor of the static-soil threshold set (12 pixels).
SOIL_MIN_RADIUS_M = 500.0

#: Beyond the mid-resolution band the radius tracks the pixel so the
#: disc always holds a stable number of pixels (``pi * 1.5^2 ~= 7``).
STRUCTURE_RATIO = 1.5

#: Families are defined by these cut-offs; see the module docstring.
_FIELD_MAX_NATIVE_M = 20.0
_LOCAL_MAX_NATIVE_M = 120.0
_SOIL_MAX_NATIVE_M = 500.0
_REGIONAL_MAX_NATIVE_M = 5000.0

#: First ``<number><unit>`` run in a declared resolution string such as
#: ``"10 m (B2,B3,B4,B8) / 20 m (B5,...)"`` or ``"4638.3 m (1/24
#: degree)"``. The unit guard keeps a bare ``m`` inside a word from
#: matching.
_RESOLUTION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(km|m)(?![A-Za-z])", re.IGNORECASE)

#: The opening sentence of every Point-support disclosure. Presence of a
#: limitation starting with this text is how re-attachment stays
#: idempotent.
DISCLOSURE_PREFIX = "Requested geometry is a Point."

#: Opening of the note added for each further dataset a derived metric
#: read on its own support region.
INPUT_DISCLOSURE_PREFIX = "Additional input:"


@dataclass(frozen=True)
class SupportRegion:
    """The support region a Point request was actually reduced over.

    Carried on :class:`~app.services.agriculture.base.MetricContext` once
    a metric has been re-scoped, and copied into the metric's provenance
    so the response can say what the number describes.
    """

    family: str
    radius_m: float
    area_sq_m: float
    dataset_id: Optional[str] = None
    native_resolution_m: Optional[float] = None
    policy: str = POINT_SUPPORT_POLICY_VERSION
    point_queryable: bool = False
    #: Earth Engine geometry the metric was reduced over. ``None`` for a
    #: point-queryable dataset, where the original Point is used as-is.
    geometry: Any = None


def parse_native_resolution_m(spatial_resolution: Optional[str]) -> Optional[float]:
    """Parse the first native resolution in a declared resolution string.

    Returns metres, or ``None`` when the string declares no resolution
    this parser understands. ``None`` means "do not re-scope", which is
    the safe answer: the metric keeps exactly the behaviour it has today.
    """
    if not spatial_resolution:
        return None
    match = _RESOLUTION_RE.search(str(spatial_resolution))
    if match is None:
        return None
    value = float(match.group(1))
    if value <= 0:
        return None
    if match.group(2).lower() == "km":
        value *= 1000.0
    return value


def family_for_native_resolution_m(native_m: Optional[float]) -> Optional[str]:
    """Map a native resolution onto its support family."""
    if native_m is None or native_m <= 0:
        return None
    if native_m <= _FIELD_MAX_NATIVE_M:
        return FAMILY_FIELD
    if native_m <= _LOCAL_MAX_NATIVE_M:
        return FAMILY_LOCAL
    if native_m <= _SOIL_MAX_NATIVE_M:
        return FAMILY_SOIL
    if native_m <= _REGIONAL_MAX_NATIVE_M:
        return FAMILY_REGIONAL
    return FAMILY_COARSE


def support_radius_m(native_m: Optional[float]) -> float:
    """Disc radius, in metres, for a dataset with this native resolution.

    Returns ``0.0`` when the resolution is unknown, which callers treat
    as "leave the context alone".
    """
    family = family_for_native_resolution_m(native_m)
    if family is None or native_m is None:
        return 0.0
    if family == FAMILY_FIELD:
        return FIELD_RADIUS_M
    if family == FAMILY_LOCAL:
        return LOCAL_RADIUS_M
    if family == FAMILY_SOIL:
        return max(SOIL_MIN_RADIUS_M, STRUCTURE_RATIO * native_m)
    # regional and coarse both scale with the pixel: a fixed radius would
    # be arbitrary once the pixel itself is measured in kilometres.
    return STRUCTURE_RATIO * native_m


def support_identity(spec: Optional[SupportRegion]) -> str:
    """Stable identity of the support policy that produced a value.

    Folded into every cache key so an analysis cached under one meaning
    of "Point" can never be replayed under another.
    """
    if spec is None:
        return "none"
    return (
        f"{spec.policy}:{spec.family}:{spec.radius_m:g}:"
        f"{spec.area_sq_m:.3f}:{1 if spec.point_queryable else 0}"
    )


def _primary_dataset(metric: Any) -> Optional[DatasetSpec]:
    """Resolve a metric's primary dataset, or ``None`` if it has none."""
    try:
        return metric.primary_dataset()
    except Exception:  # noqa: BLE001 - a metric with no dataset simply is not scoped
        return None


def _build_geometry(context: Any, geo: Dict[str, Any], radius_m: float) -> Any:
    """Buffer the original request Point, or return ``None`` on failure."""
    try:
        base = getattr(context, "original_geometry", None)
        if base is None:
            from app.utils.geometry import create_ee_geometry

            base = create_ee_geometry(geo)
        return base.buffer(radius_m)
    except Exception as exc:  # noqa: BLE001 - never fail a metric over scoping
        logger.warning(
            "Point support buffer at %.0f m failed (%s); leaving the "
            "metric on its original geometry.",
            radius_m,
            type(exc).__name__,
        )
        return None


def _cached_geometry(
    context: Any, geo: Dict[str, Any], radius_m: float
) -> Optional[Dict[str, Any]]:
    """Return ``{"geometry", "area_sq_m"}`` for a radius, building once.

    The plan lives on the context, so a request buffers each radius at
    most once no matter how many metrics share the family. Metric
    execution is concurrent; the worst a lost race can do is build the
    same deterministic buffer twice, and the dict key is derived from the
    radius so the two writers cannot disagree about what belongs there.
    """
    plan = getattr(context, "support_plan", None)
    if plan is None:
        plan = {}
        try:
            context.support_plan = plan
        except Exception:  # noqa: BLE001 - a frozen context just loses the cache
            pass
    key = f"{radius_m:.6f}"
    hit = plan.get(key)
    if hit is not None:
        return hit
    geometry = _build_geometry(context, geo, radius_m)
    if geometry is None:
        return None
    entry = {
        "geometry": geometry,
        "area_sq_m": math.pi * radius_m * radius_m,
    }
    plan[key] = entry
    return entry


def _spec_for(
    context: Any, geo: Dict[str, Any], metric: Any
) -> Optional[SupportRegion]:
    """Decide the support region for one metric, or ``None`` for none."""
    dataset = _primary_dataset(metric)
    if dataset is None:
        return None
    return _spec_for_dataset(context, geo, dataset)


def _spec_for_dataset(
    context: Any, geo: Dict[str, Any], dataset: DatasetSpec
) -> Optional[SupportRegion]:
    """Decide the support region for one dataset, or ``None`` for none."""
    native_m = parse_native_resolution_m(dataset.spatial_resolution)
    if native_m is None:
        # Declared resolution the policy cannot read. Re-scoping on a
        # guess would be worse than not re-scoping at all.
        return None

    if dataset.id in POINT_QUERYABLE_DATASET_IDS:
        return SupportRegion(
            family=FAMILY_POINT_QUERYABLE,
            radius_m=0.0,
            area_sq_m=0.0,
            dataset_id=dataset.id,
            native_resolution_m=native_m,
            point_queryable=True,
        )

    radius_m = support_radius_m(native_m)
    if radius_m <= 0.0:
        return None

    entry = _cached_geometry(context, geo, radius_m)
    if entry is None:
        return None

    return SupportRegion(
        family=family_for_native_resolution_m(native_m) or "",
        radius_m=radius_m,
        area_sq_m=entry["area_sq_m"],
        dataset_id=dataset.id,
        native_resolution_m=native_m,
        geometry=entry["geometry"],
    )


def resolve_support_context(context: Any, metric: Any) -> Any:
    """Return the context a metric should actually reduce over.

    Three outcomes:

    * **not a Point request** — the context is returned untouched. This
      is what keeps Polygon behaviour byte-identical, and what keeps
      unit tests that build a ``MetricContext`` by hand unaffected: the
      policy only ever engages when the caller has declared the original
      request geometry.
    * **already scoped to this radius** — returned untouched, so nested
      metric calls and profile builders are idempotent.
    * **needs scoping** — a fresh context carrying the support geometry
      and the support area as ``options["area_sq_m"]``, which is the
      denominator the coverage arithmetic has been missing.

    Any failure falls back to the original context rather than raising:
    a metric that cannot be re-scoped should still get the chance to
    answer, and its provenance will simply not claim a support region.
    """
    try:
        geo = getattr(context, "requested_geometry", None)
        if not isinstance(geo, dict) or geo.get("type") != "Point":
            return context

        spec = _spec_for(context, geo, metric)
        if spec is None:
            return context
        return _rescope(context, spec)
    except Exception as exc:  # noqa: BLE001 - scoping must never sink a metric
        logger.warning(
            "Point support resolution for metric %r failed (%s); using the "
            "original geometry.",
            getattr(metric, "key", "?"),
            type(exc).__name__,
        )
        return context


def _rescope(context: Any, spec: SupportRegion) -> Any:
    """Return ``context`` re-scoped to ``spec``, idempotently."""
    current = getattr(context, "support_spec", None)
    if current is not None and current.radius_m == spec.radius_m:
        # Same spatial support already in force: whether that came from a
        # point-queryable parent or a buffered one.
        if current.point_queryable == spec.point_queryable:
            return context

    if spec.point_queryable:
        if current is None:
            # Nothing was ever buffered, so the geometry is already the
            # original Point and the options carry no area. Recording the
            # spec is what makes the value disclose that it is a single
            # containing pixel.
            return replace(context, support_spec=spec)
        options = {
            key: value
            for key, value in context.options.items()
            if key != "area_sq_m"
        }
        return replace(
            context,
            geometry=getattr(context, "original_geometry", None)
            or context.geometry,
            options=options,
            support_spec=spec,
        )

    options = dict(context.options or {})
    options["area_sq_m"] = spec.area_sq_m
    return replace(
        context,
        geometry=spec.geometry,
        options=options,
        support_spec=spec,
    )


def _record_input(context: Any, spec: SupportRegion) -> None:
    """Note a support region in the metric's input log, once per dataset."""
    log = getattr(context, "support_log", None)
    if log is None:
        return
    if any(
        item.dataset_id == spec.dataset_id and item.radius_m == spec.radius_m
        for item in log
    ):
        return
    log.append(spec)


def scope_context_for_dataset(context: Any, dataset_id: str) -> Any:
    """Return the context to reduce *this dataset* over.

    :func:`resolve_support_context` scopes a metric by its primary
    dataset. A derived metric can read a second dataset on a different
    grid, for instance a SMAP root-zone metric that divides by a
    SoilGrids field capacity. That second reduction must not inherit the
    primary's geometry: a point-queryable primary would leave the
    250 m SoilGrids layer reduced over a bare Point, which is the
    zero-area failure this policy exists to remove. Shared reducers call
    this for the dataset they actually read.

    The support region is recorded on the metric's input log so the
    result can disclose every support it was built from. A context that
    is not a Point request, or a dataset whose resolution is not known,
    comes back unchanged.
    """
    try:
        geo = getattr(context, "requested_geometry", None)
        if not isinstance(geo, dict) or geo.get("type") != "Point":
            return context

        from app.services.agriculture.registry import get_dataset

        spec = _spec_for_dataset(context, geo, get_dataset(dataset_id))
        if spec is None:
            return context
        scoped = _rescope(context, spec)
        _record_input(scoped, spec)
        return scoped
    except Exception as exc:  # noqa: BLE001 - scoping must never sink a metric
        logger.warning(
            "Point support resolution for dataset %r failed (%s); using the "
            "context as given.",
            dataset_id,
            type(exc).__name__,
        )
        return context


def open_support_scope(context: Any, metric: Any) -> Any:
    """Scope a metric's context and open its input log.

    The log is fresh for every metric computation and is shared by
    reference with every context derived from the returned one, so the
    reducers a metric calls can record the support they used without the
    metric having to thread anything through.
    """
    scoped = resolve_support_context(context, metric)
    geo = getattr(scoped, "requested_geometry", None)
    if not isinstance(geo, dict) or geo.get("type") != "Point":
        return scoped
    log = []
    spec = getattr(scoped, "support_spec", None)
    if spec is not None:
        log.append(spec)
    try:
        return replace(scoped, support_log=log)
    except Exception:  # noqa: BLE001 - a context without the field keeps working
        return scoped


def apply_support_disclosure(result: Any, context: Any) -> Any:
    """Attach the Point-support disclosure to a computed result.

    Called once per metric, after its ``compute``, so it covers every
    metric regardless of how that metric assembled its own provenance.
    Nothing is added when the context carries no support region, so
    Polygon results and hand-built test results are untouched.
    """
    if result is None:
        return result
    log = list(getattr(context, "support_log", None) or [])
    spec = log[0] if log else getattr(context, "support_spec", None)
    if spec is None:
        return result
    provenance = getattr(result, "provenance", None)
    if provenance is None:
        return result

    # Replace, never stack: a subclass that wraps a parent's compute is
    # disclosed twice, and the outer pass sees the fuller input log.
    existing = [
        item
        for item in (provenance.limitations or [])
        if not (
            isinstance(item, str)
            and item.startswith((DISCLOSURE_PREFIX, INPUT_DISCLOSURE_PREFIX))
        )
    ]

    resolution = provenance.spatial_resolution or "native"
    if spec.point_queryable:
        disclosure = (
            f"{DISCLOSURE_PREFIX} This value is the single native pixel "
            f"containing the selected location on the {resolution} grid; "
            "no wider support area is aggregated."
        )
    else:
        disclosure = (
            f"{DISCLOSURE_PREFIX} This value describes the "
            f"{spec.radius_m:g} m-radius support region around the "
            f"selected location (about {spec.area_sq_m:,.0f} m2 on the "
            f"{resolution} grid), not the pinpoint coordinate alone."
        )
        if spec.family in (FAMILY_SOIL, FAMILY_REGIONAL, FAMILY_COARSE):
            disclosure += (
                " The native pixel of this product is far larger than a "
                "field, so the value is regional/district-scale context, "
                "not a pinpoint field measurement."
            )

    provenance.geometry_type = "Point"
    provenance.support_radius_m = spec.radius_m
    provenance.support_area_sq_m = spec.area_sq_m
    provenance.support_family = spec.family
    provenance.support_policy = spec.policy
    provenance.support_native_resolution_m = spec.native_resolution_m
    original = getattr(context, "requested_geometry", None)
    provenance.original_geometry = (
        dict(original) if isinstance(original, dict) else None
    )
    notes = [_input_note(item) for item in log[1:]]
    # Every support region the value was built from, primary first. The
    # scalar fields above describe the primary one.
    provenance.support_inputs = [_input_record(item) for item in log] or None
    provenance.limitations = existing + [disclosure] + notes
    return result


def _input_record(spec: SupportRegion) -> Dict[str, Any]:
    return {
        "dataset_id": spec.dataset_id,
        "family": spec.family,
        "radius_m": spec.radius_m,
        "area_sq_m": spec.area_sq_m,
        "native_resolution_m": spec.native_resolution_m,
        "point_queryable": spec.point_queryable,
    }


def _input_note(spec: SupportRegion) -> str:
    if spec.point_queryable:
        return (
            f"{INPUT_DISCLOSURE_PREFIX} {spec.dataset_id} was read as the "
            "single native pixel containing the selected location."
        )
    return (
        f"{INPUT_DISCLOSURE_PREFIX} {spec.dataset_id} was reduced over a "
        f"{spec.radius_m:g} m-radius support region around the selected "
        f"location (about {spec.area_sq_m:,.0f} m2)."
    )
