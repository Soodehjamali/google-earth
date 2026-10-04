"""Spatial anomaly and hotspot foundation (P1.5).

Reusable, domain-neutral spatial statistics over agricultural
observations.  This layer identifies WHERE statistically unusual
observations are spatially concentrated.  It does NOT establish the
cause of any pattern.

A spatial concentration of statistical anomalies indicates a spatial
pattern in the observed metric.  Possible causes can include
weather, irrigation, management, soil variability, phenology,
sensor/coverage effects, vegetation stress, pests, or disease.  The
hotspot layer must not choose among these causes: area states are
neutral (NORMAL_AREA, ANOMALOUS_AREA, CONCENTRATED_ANOMALY,
INSUFFICIENT), never pest/disease labels, with no ML, no risk
scores, and no probabilities.

Reused architecture (nothing re-derived):

* geometry validation via :func:`app.utils.geometry.validate_geometry`
  (GeoJSON Point/Polygon contract; WGS84 lon/lat axis order is
  preserved everywhere and no CRS change ever happens here);
* per-cell values from the metrics' own ``compute`` on sub-geometries
  (the CD-2/P1.1 sibling-compute pattern: same product, masking,
  compositing, and quality pipeline per cell);
* anomaly vocabulary from P1.2 (``CATEGORY_BELOW_BASELINE`` /
  ``CATEGORY_ABOVE_BASELINE`` define anomalous; missing is never
  anomalous);
* deviation runs via :func:`history.compute_persistence` (gaps and
  ties break runs) with P1.3's persistence states;
* the supported metric set from P1.1 (no implementation is
  duplicated).

Spatial unit: the repository has no canonical grid, so this module
introduces the smallest deterministic representation needed — a
regular lon/lat grid over a bounding box with row-major ``rXXcYY``
cell identifiers (row 0 is northernmost, columns run west to east).
This is not a GIS tiling framework: no projection, no administrative
boundaries, no spatial index.

Deliberate P1.5 parameters (structural, configurable, documented —
not biological thresholds):

* ``MIN_VALID_CELLS = 3`` — fewer usable cells than this and no area
  state is reported (mirrors the repository's recurring
  three-observation floor);
* ``CONCENTRATION_MIN_FRACTION = 0.5`` — at least half the usable
  cells anomalous for a concentration (majority rule);
* ``PERSISTENCE_MIN_RUN = 3`` — reused from P1.3 for per-cell runs.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.base import MetricContext
from app.services.agriculture.baseline_anomaly import (
    CATEGORY_ABOVE_BASELINE,
    CATEGORY_BELOW_BASELINE,
)
from app.services.agriculture.change_profile import (
    PERSISTENCE_INSUFFICIENT,
    PERSISTENCE_MIN_RUN,
    PERSISTENCE_NONE,
    PERSISTENCE_PERSISTENT,
)
from app.services.agriculture.history import compute_persistence
from app.services.agriculture.temporal_profile import SUPPORTED_PROFILE_METRICS
from app.utils.geometry import validate_geometry

logger = get_logger(__name__)

__all__ = [
    "MIN_VALID_CELLS",
    "CONCENTRATION_MIN_FRACTION",
    "STATE_NORMAL_AREA",
    "STATE_ANOMALOUS_AREA",
    "STATE_CONCENTRATED_ANOMALY",
    "STATE_INSUFFICIENT",
    "CONCORDANCE_SINGLE_METRIC",
    "CONCORDANCE_MULTI_METRIC",
    "CONCORDANCE_MIXED",
    "CONCORDANCE_NONE",
    "CONCORDANCE_INSUFFICIENT",
    "ANOMALOUS_CATEGORIES",
    "SpatialCell",
    "CellObservation",
    "SpatialSummary",
    "CellConcordance",
    "CellPersistence",
    "bbox_of_geojson",
    "grid_cells",
    "cell_cache_key",
    "evaluate_cell",
    "evaluate_grid",
    "aggregate_cells",
    "area_state",
    "cell_concordance",
    "track_cell_persistence",
]

#: Minimum usable cells for any area-level statement.  Mirrors the
#: repository's recurring three-observation sufficiency floor.
MIN_VALID_CELLS = 3

#: Minimum anomalous fraction of usable cells for a concentration.
#: A plain majority rule, configurable at the call site.
CONCENTRATION_MIN_FRACTION = 0.5

#: Neutral area states.  Spatial posture only.
STATE_NORMAL_AREA = "NORMAL_AREA"
STATE_ANOMALOUS_AREA = "ANOMALOUS_AREA"
STATE_CONCENTRATED_ANOMALY = "CONCENTRATED_ANOMALY"
STATE_INSUFFICIENT = "INSUFFICIENT"

#: Neutral per-cell multi-metric states.
CONCORDANCE_SINGLE_METRIC = "SINGLE_METRIC_ANOMALY"
CONCORDANCE_MULTI_METRIC = "MULTI_METRIC_ANOMALY"
CONCORDANCE_MIXED = "MIXED_METRICS"
CONCORDANCE_NONE = "NO_CONCORDANCE"
CONCORDANCE_INSUFFICIENT = "INSUFFICIENT"

#: P1.2 anomaly categories that count as anomalous for spatial
#: purposes.  Anything else (normal, missing, unscored) is not.
ANOMALOUS_CATEGORIES = frozenset(
    {CATEGORY_BELOW_BASELINE, CATEGORY_ABOVE_BASELINE}
)


@dataclass(frozen=True)
class SpatialCell:
    """One deterministic grid cell: bounds plus its GeoJSON polygon.

    Coordinates are WGS84 lon/lat in GeoJSON ``[lng, lat]`` order,
    closed ring, row-major identifiers (row 0 northernmost).
    """

    cell_id: str
    row: int
    col: int
    west: float
    south: float
    east: float
    north: float
    geometry: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.5 API contract models."""
        return {
            "cell_id": self.cell_id,
            "row": self.row,
            "col": self.col,
            "west": self.west,
            "south": self.south,
            "east": self.east,
            "north": self.north,
            "geometry": dict(self.geometry),
        }


@dataclass(frozen=True)
class CellObservation:
    """One cell's observation for one metric and window.

    ``z_score``/``category`` carry a P1.2-style anomaly assessment
    when the caller scored the cell; otherwise they stay ``None``
    (unscored is distinct from normal).  Every quality/coverage
    field passes through from the underlying metric result.
    """

    cell_id: str
    metric_key: str
    window_start: str
    window_end: str
    value: Optional[float]
    unit: str = ""
    z_score: Optional[float] = None
    category: Optional[str] = None
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.5 API contract models."""
        return {
            "cell_id": self.cell_id,
            "metric_key": self.metric_key,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "value": self.value,
            "unit": self.unit,
            "z_score": self.z_score,
            "category": self.category,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
            "image_count": self.image_count,
        }


@dataclass(frozen=True)
class SpatialSummary:
    """Area-level aggregation over one metric's cell observations."""

    metric_key: str
    window_start: str
    window_end: str
    n_cells: int
    n_usable: int
    n_missing: int
    mean: Optional[float]
    median: Optional[float]
    anomalous_count: int
    anomalous_fraction: Optional[float]
    min_coverage_percent: Optional[float]
    mean_coverage_percent: Optional[float]
    quality_counts: Dict[str, int] = field(default_factory=dict)
    state: str = STATE_INSUFFICIENT
    method: str = (
        "usable-cell means; anomalous means P1.2 below/above-baseline; "
        f"concentration at >= {CONCENTRATION_MIN_FRACTION} anomalous "
        f"fraction with >= {MIN_VALID_CELLS} usable cells"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.5 API contract models."""
        return {
            "metric_key": self.metric_key,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "n_cells": self.n_cells,
            "n_usable": self.n_usable,
            "n_missing": self.n_missing,
            "mean": self.mean,
            "median": self.median,
            "anomalous_count": self.anomalous_count,
            "anomalous_fraction": self.anomalous_fraction,
            "min_coverage_percent": self.min_coverage_percent,
            "mean_coverage_percent": self.mean_coverage_percent,
            "quality_counts": dict(self.quality_counts),
            "state": self.state,
            "method": self.method,
        }


@dataclass(frozen=True)
class CellConcordance:
    """Multi-metric agreement for one cell and window."""

    cell_id: str
    window_start: str
    window_end: str
    metrics: Tuple[str, ...] = ()
    anomalous_metrics: Tuple[str, ...] = ()
    state: str = CONCORDANCE_INSUFFICIENT

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.5 API contract models."""
        return {
            "cell_id": self.cell_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "metrics": list(self.metrics),
            "anomalous_metrics": list(self.anomalous_metrics),
            "state": self.state,
        }


@dataclass(frozen=True)
class CellPersistence:
    """Per-cell deviation runs across consecutive valid periods."""

    cell_id: str
    longest_run_below: int = 0
    longest_run_above: int = 0
    n_anomalous: int = 0
    n_observed: int = 0
    n_missing: int = 0
    state: str = PERSISTENCE_INSUFFICIENT

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P1.5 API contract models."""
        return {
            "cell_id": self.cell_id,
            "longest_run_below": self.longest_run_below,
            "longest_run_above": self.longest_run_above,
            "n_anomalous": self.n_anomalous,
            "n_observed": self.n_observed,
            "n_missing": self.n_missing,
            "state": self.state,
        }


def _is_finite_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def bbox_of_geojson(geometry: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """Bounding box of a GeoJSON geometry as ``(west, south, east, north)``.

    Validation reuses the repository's geometry contract (Point or
    Polygon in WGS84 lon/lat); anything else raises the same
    ``GeometryError`` the rest of the engine raises.  Pure coordinate
    minima/maxima — no Earth Engine, no reprojection, axis order
    preserved.
    """
    validate_geometry(geometry)
    if geometry.get("type") == "Point":
        lng, lat = geometry["coordinates"][0], geometry["coordinates"][1]
        return (float(lng), float(lat), float(lng), float(lat))
    ring = geometry["coordinates"][0]
    lngs = [float(coord[0]) for coord in ring]
    lats = [float(coord[1]) for coord in ring]
    return (min(lngs), min(lats), max(lngs), max(lats))


def grid_cells(
    bbox: Tuple[float, float, float, float], rows: int, cols: int
) -> Tuple[SpatialCell, ...]:
    """Regular lon/lat grid over a bounding box, row-major identifiers.

    Row 0 is northernmost, columns run west to east; every cell
    carries its own closed-ring GeoJSON polygon.  Deterministic:
    identical inputs always produce identical cells in identical
    order.  Zero-extent boxes and non-positive dimensions are
    refused — a grid over nothing would manufacture locations.
    """
    west, south, east, north = (float(v) for v in bbox)
    if (
        not isinstance(rows, int)
        or isinstance(rows, bool)
        or not isinstance(cols, int)
        or isinstance(cols, bool)
        or rows < 1
        or cols < 1
    ):
        raise ValueError(
            f"Grid dimensions must be positive integers, got rows={rows!r}, cols={cols!r}."
        )
    for value in (west, south, east, north):
        if not math.isfinite(value):
            raise ValueError(f"Bounding box must be finite, got {bbox!r}.")
    if not (west < east and south < north):
        raise ValueError(
            f"Bounding box must have positive extent, got {bbox!r}."
        )
    d_lng = (east - west) / cols
    d_lat = (north - south) / rows
    cells: List[SpatialCell] = []
    for row in range(rows):
        cell_north = north - row * d_lat
        cell_south = cell_north - d_lat
        for col in range(cols):
            cell_west = west + col * d_lng
            cell_east = cell_west + d_lng
            ring = [
                [cell_west, cell_south],
                [cell_east, cell_south],
                [cell_east, cell_north],
                [cell_west, cell_north],
                [cell_west, cell_south],
            ]
            cells.append(
                SpatialCell(
                    cell_id=f"r{row:02d}c{col:02d}",
                    row=row,
                    col=col,
                    west=cell_west,
                    south=cell_south,
                    east=cell_east,
                    north=cell_north,
                    geometry={"type": "Polygon", "coordinates": [ring]},
                )
            )
    return tuple(cells)


def _observation_from_result(
    cell_id: str,
    metric_key: str,
    unit: str,
    window_start: str,
    window_end: str,
    result: Any,
) -> CellObservation:
    """Translate one cell's metric result into an observation."""
    value = result.value if _is_finite_number(result.value) else None
    provenance = result.provenance
    quality = "unavailable"
    image_count: Optional[int] = None
    if provenance is not None:
        quality_level = provenance.quality_level
        quality = (
            quality_level.value
            if hasattr(quality_level, "value")
            else str(quality_level)
        )
        image_count = provenance.image_count
    coverage: Optional[float] = None
    stats = result.stats
    if stats is not None:
        raw_coverage = getattr(stats, "coverage_percent", None)
        if _is_finite_number(raw_coverage):
            coverage = float(raw_coverage)
    return CellObservation(
        cell_id=cell_id,
        metric_key=metric_key,
        window_start=window_start,
        window_end=window_end,
        value=float(value) if value is not None else None,
        unit=unit,
        quality=quality,
        coverage_percent=coverage,
        image_count=image_count,
    )


def _missing_observation(
    cell_id: str,
    metric_key: str,
    unit: str,
    window_start: str,
    window_end: str,
) -> CellObservation:
    return CellObservation(
        cell_id=cell_id,
        metric_key=metric_key,
        window_start=window_start,
        window_end=window_end,
        value=None,
        unit=unit,
        quality="unavailable",
        coverage_percent=None,
        image_count=None,
    )


def cell_cache_key(context: MetricContext, cell_id: str) -> str:
    """Cache identity for one cell evaluation.

    The parent geometry key namespaced to the cell, so two cells can
    never share a cached result even though they share the window,
    scale, and cloud tolerance that also enter the key downstream.
    Deterministic: identical inputs always produce identical keys.
    """
    return f"{context.geometry_key}#{cell_id}"


def evaluate_cell(
    metric_key: str,
    context: MetricContext,
    cell_id: str,
    cell_geometry: Any,
) -> CellObservation:
    """Evaluate one registered metric over one cell geometry.

    Runs the metric's own ``compute`` with the cell geometry swapped
    in (same window, scale, cloud tolerance, and options) and the
    cache key namespaced to the cell, so two cells can never share a
    cached result.  A failed or empty computation becomes a missing
    observation, never a zero and never an invented value.
    """
    if metric_key not in SUPPORTED_PROFILE_METRICS:
        supported = ", ".join(sorted(SUPPORTED_PROFILE_METRICS))
        raise ValueError(
            f"Spatial evaluation is not supported for {metric_key!r}. "
            f"Supported metrics: {supported}."
        )
    metric_cls = SUPPORTED_PROFILE_METRICS[metric_key]
    probe = metric_cls()
    sub_context = replace(
        context,
        geometry=cell_geometry,
        geometry_key=cell_cache_key(context, cell_id),
    )
    try:
        result = metric_cls().compute(sub_context)
    except Exception as exc:  # noqa: BLE001 - one cell cannot sink the grid
        logger.warning(
            "Spatial evaluation of %s in cell %s failed (%s); "
            "recording a missing observation.",
            metric_key,
            cell_id,
            type(exc).__name__,
        )
        return _missing_observation(
            cell_id,
            metric_key,
            probe.unit,
            context.start_date,
            context.end_date,
        )
    if result is None:
        return _missing_observation(
            cell_id,
            metric_key,
            probe.unit,
            context.start_date,
            context.end_date,
        )
    return _observation_from_result(
        cell_id,
        metric_key,
        probe.unit,
        context.start_date,
        context.end_date,
        result,
    )


def evaluate_grid(
    metric_key: str,
    context: MetricContext,
    cells: Sequence[SpatialCell],
) -> Tuple[CellObservation, ...]:
    """Evaluate one metric over every grid cell, in cell order.

    Each cell's ``geometry`` is passed to the metric opaque, exactly
    as the caller's production path prepared it (converted via the
    repository's geometry utilities upstream).  Deterministic:
    identical inputs produce identical observation sequences.
    """
    return tuple(
        evaluate_cell(metric_key, context, cell.cell_id, cell.geometry)
        for cell in cells
    )


def _check_same_series(
    observations: Sequence[CellObservation],
) -> Tuple[str, str, str]:
    """Validate that observations belong to one metric and window."""
    metric_keys = {obs.metric_key for obs in observations}
    if len(metric_keys) != 1:
        raise ValueError(
            f"Spatial aggregation needs one metric, got {sorted(metric_keys)}."
        )
    windows = {(obs.window_start, obs.window_end) for obs in observations}
    if len(windows) != 1:
        raise ValueError(
            f"Spatial aggregation needs one window, got {sorted(windows)}."
        )
    window_start, window_end = next(iter(windows))
    return next(iter(metric_keys)), window_start, window_end


def aggregate_cells(
    observations: Sequence[CellObservation],
    min_valid_cells: int = MIN_VALID_CELLS,
    min_fraction: float = CONCENTRATION_MIN_FRACTION,
) -> SpatialSummary:
    """Aggregate one metric's cell observations into an area summary.

    Statistics run over usable cells only; missing cells lower the
    counts but never enter a mean.  The area state follows the
    concentration rule: insufficient below ``min_valid_cells``
    usable cells, concentrated at or above ``min_fraction``
    anomalous fraction, anomalous when any anomaly exists,
    otherwise normal.
    """
    observations = list(observations)
    if not observations:
        raise ValueError("Spatial aggregation needs at least one observation.")
    metric_key, window_start, window_end = _check_same_series(observations)
    usable = [obs for obs in observations if _is_finite_number(obs.value)]
    n_usable = len(usable)
    n_missing = len(observations) - n_usable
    values = [float(obs.value) for obs in usable]  # type: ignore[arg-type]
    anomalous = sum(1 for obs in usable if obs.category in ANOMALOUS_CATEGORIES)
    coverages = [
        float(obs.coverage_percent)
        for obs in usable
        if _is_finite_number(obs.coverage_percent)
    ]
    quality_counts: Dict[str, int] = {}
    for obs in usable:
        quality_counts[obs.quality] = quality_counts.get(obs.quality, 0) + 1
    if n_usable < min_valid_cells:
        state = STATE_INSUFFICIENT
        fraction: Optional[float] = None
    else:
        fraction = anomalous / n_usable
        if fraction >= min_fraction:
            state = STATE_CONCENTRATED_ANOMALY
        elif anomalous > 0:
            state = STATE_ANOMALOUS_AREA
        else:
            state = STATE_NORMAL_AREA
    return SpatialSummary(
        metric_key=metric_key,
        window_start=window_start,
        window_end=window_end,
        n_cells=len(observations),
        n_usable=n_usable,
        n_missing=n_missing,
        mean=float(statistics.mean(values)) if values else None,
        median=float(statistics.median(values)) if values else None,
        anomalous_count=anomalous,
        anomalous_fraction=fraction,
        min_coverage_percent=min(coverages) if coverages else None,
        mean_coverage_percent=(
            sum(coverages) / len(coverages) if coverages else None
        ),
        quality_counts=quality_counts,
        state=state,
    )


def area_state(
    observations: Sequence[CellObservation],
    min_valid_cells: int = MIN_VALID_CELLS,
    min_fraction: float = CONCENTRATION_MIN_FRACTION,
) -> str:
    """Area state for one metric's cell observations (see aggregate_cells)."""
    return aggregate_cells(observations, min_valid_cells, min_fraction).state


def cell_concordance(
    layers: Mapping[str, CellObservation],
) -> CellConcordance:
    """Multi-metric agreement for one cell and window.

    Every layer must describe the same cell and window, otherwise the
    comparison would mix places or periods and is refused.  Missing
    layers are excluded, never negative evidence: a single anomalous
    layer among missing peers is SINGLE_METRIC_ANOMALY, while
    anomalous layers pulling opposite directions are MIXED_METRICS.
    """
    observations = list(layers.values())
    if not observations:
        raise ValueError("Concordance needs at least one metric layer.")
    cell_ids = {obs.cell_id for obs in observations}
    if len(cell_ids) != 1:
        raise ValueError(
            f"Concordance needs one cell, got {sorted(cell_ids)}."
        )
    windows = {(obs.window_start, obs.window_end) for obs in observations}
    if len(windows) != 1:
        raise ValueError(
            f"Concordance needs one window, got {sorted(windows)}."
        )
    usable = [
        obs for obs in observations if _is_finite_number(obs.value)
    ]
    if not usable:
        window_start, window_end = next(iter(windows))
        return CellConcordance(
            cell_id=next(iter(cell_ids)),
            window_start=window_start,
            window_end=window_end,
            metrics=tuple(sorted(layers)),
            anomalous_metrics=(),
            state=CONCORDANCE_INSUFFICIENT,
        )
    anomalous = sorted(
        obs.metric_key for obs in usable if obs.category in ANOMALOUS_CATEGORIES
    )
    below = sum(
        1
        for obs in usable
        if obs.category == CATEGORY_BELOW_BASELINE
    )
    above = sum(
        1
        for obs in usable
        if obs.category == CATEGORY_ABOVE_BASELINE
    )
    if len(anomalous) >= 2 and (below == 0 or above == 0):
        # Two or more anomalous layers pulling the same direction.
        # (len(anomalous) >= 2 with no mixed directions implies a
        # shared direction, since only two anomalous categories exist.)
        state = CONCORDANCE_MULTI_METRIC
    elif len(anomalous) >= 2:
        state = CONCORDANCE_MIXED
    elif len(anomalous) == 1:
        state = CONCORDANCE_SINGLE_METRIC
    else:
        state = CONCORDANCE_NONE
    window_start, window_end = next(iter(windows))
    return CellConcordance(
        cell_id=next(iter(cell_ids)),
        window_start=window_start,
        window_end=window_end,
        metrics=tuple(sorted(layers)),
        anomalous_metrics=tuple(anomalous),
        state=state,
    )


def track_cell_persistence(
    cell_id: str, z_by_period: Sequence[Optional[float]]
) -> CellPersistence:
    """Deviation runs for one cell across consecutive valid periods.

    Z-scores run through the repository's persistence counter against
    0.0, so gaps and exact zeros break runs exactly as they do for
    temporal profiles.  A longest run of at least
    ``PERSISTENCE_MIN_RUN`` in either direction is PERSISTENT.
    """
    z_series = [
        float(value) if _is_finite_number(value) else None for value in z_by_period
    ]
    record = compute_persistence(z_series, 0.0)
    n_observed = sum(1 for value in z_series if value is not None)
    n_missing = len(z_series) - n_observed
    if record is None:
        return CellPersistence(
            cell_id=cell_id,
            n_observed=n_observed,
            n_missing=n_missing,
            state=PERSISTENCE_INSUFFICIENT,
        )
    longest = max(record.longest_run_below, record.longest_run_above)
    return CellPersistence(
        cell_id=cell_id,
        longest_run_below=record.longest_run_below,
        longest_run_above=record.longest_run_above,
        n_anomalous=record.n_anomalous,
        n_observed=record.n_observed,
        n_missing=record.n_missing,
        state=PERSISTENCE_PERSISTENT
        if longest >= PERSISTENCE_MIN_RUN
        else PERSISTENCE_NONE,
    )
