"""Spatial section orchestration for the Agriculture /analysis response.

P5.3-S integration phase: assembles already-computed P1.5 grid
intelligence into the additive ``spatial`` section of the analysis
response. Transport and orchestration only.

P1.5 is the scientific source of truth. Grid generation, cell
geometry and IDs, per-cell evaluation, area aggregation, anomaly
and concentration classification, concordance, persistence runs,
quality handling, and missing-data semantics all come from the
existing ``spatial_profile`` builders, serialized through their
canonical ``to_dict``. No grid algorithm, threshold, formula,
reprojection, smoothing, clustering, or score lives in this
module. One metric's failure can never fail the section: each key
is isolated and refusals are recorded as limitations.

Request-driven cost control: only requested metrics in P1.5's own
supported set are evaluated, over one fixed deterministic grid
(``GRID_ROWS`` by ``GRID_COLS`` cells, documented below), so one
request can never fan out into unbounded cell evaluation. Point
geometries have no extent to grid and yield an explicit
limitation instead of an invented grid.

Per-cell persistence runs on the single available period via
``track_cell_persistence``: with no caller-assembled multi-period
series in a single-window request this honestly reports
insufficient persistence rather than manufacturing runs. No
second temporal computation is performed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.core.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "GRID_ROWS",
    "GRID_COLS",
    "MAX_SPATIAL_CELLS",
    "build_spatial_section",
]

#: Fixed deterministic grid dimensions. Nine cells clear P1.5's own
#: three-usable-cell floor with margin while bounding per-request
#: cell evaluation to metrics x 9 computations. The grid is never
#: truncated: it is built whole or not at all.
GRID_ROWS = 3
GRID_COLS = 3

#: Upper bound on cells evaluated per request (GRID_ROWS x GRID_COLS).
MAX_SPATIAL_CELLS = GRID_ROWS * GRID_COLS


def _empty_section(
    context: Any, limitations: List[str]
) -> Dict[str, Any]:
    return {
        "window_start": context.start_date,
        "window_end": context.end_date,
        "grid_rows": 0,
        "grid_cols": 0,
        "bbox": [],
        "cells": [],
        "observations": [],
        "summaries": {},
        "concordance": [],
        "persistence": [],
        "limitations": list(limitations),
    }


def build_spatial_section(
    context: Any,
    geometry_dict: Dict[str, Any],
    metric_keys: Sequence[str],
) -> Optional[Dict[str, Any]]:
    """Assemble the additive spatial payload for an analysis request.

    Args:
        context: The request's ``MetricContext`` (geometry, window,
            scale, cloud tolerance, options carried into every cell
            evaluation by the builders themselves).
        geometry_dict: The request's GeoJSON geometry, used only to
            derive the deterministic grid bounding box.
        metric_keys: Resolved request metric keys; only keys in
            P1.5's own supported set are evaluated, nothing is
            substituted.

    Returns:
        Plain-data payload matching ``SpatialSectionModel``, or
        ``None`` when no requested metric is spatially supported.
        Never raises: failures are isolated per key and recorded
        in ``limitations``.
    """
    from app.services.agriculture.spatial_profile import (
        SUPPORTED_PROFILE_METRICS,
        aggregate_cells,
        bbox_of_geojson,
        cell_concordance,
        evaluate_grid,
        grid_cells,
        track_cell_persistence,
    )

    requested = set(metric_keys or ())
    eligible = [k for k in SUPPORTED_PROFILE_METRICS if k in requested]
    if not eligible:
        return None

    limitations: List[str] = []
    try:
        bbox = bbox_of_geojson(geometry_dict)
        cells = grid_cells(bbox, GRID_ROWS, GRID_COLS)
    except Exception as exc:  # noqa: BLE001 - transport must not fail analysis
        logger.warning("Spatial section skipped: %s", type(exc).__name__)
        return _empty_section(
            context,
            ["spatial grid unavailable for this geometry; "
             "a polygon with positive extent is required"],
        )

    by_metric: Dict[str, Any] = {}
    for key in eligible:
        try:
            observations = evaluate_grid(key, context, cells)
        except Exception as exc:  # noqa: BLE001 - per-key isolation
            logger.warning(
                "Spatial evaluation for %s skipped: %s",
                key, type(exc).__name__,
            )
            limitations.append(f"spatial observations unavailable for {key}")
            continue
        try:
            summary = aggregate_cells(observations)
        except Exception as exc:  # noqa: BLE001 - derived step isolation
            logger.warning(
                "Spatial summary for %s skipped: %s",
                key, type(exc).__name__,
            )
            limitations.append(f"spatial summary unavailable for {key}")
            continue
        by_metric[key] = (observations, summary)

    observations_all: List[Any] = []
    summaries: Dict[str, Any] = {}
    for key, (observations, summary) in by_metric.items():
        observations_all.extend(observations)
        summaries[key] = summary.to_dict()

    concordance = _concordance_payload(cells, by_metric, limitations)
    persistence = _persistence_payload(cells, by_metric)

    if not by_metric:
        limitations.append("no spatial metric produced observations")
    limitations.append(
        "per-cell persistence runs on the single requested window; "
        "multi-period persistence needs period series this request "
        "does not provide"
    )

    return {
        "window_start": context.start_date,
        "window_end": context.end_date,
        "grid_rows": GRID_ROWS,
        "grid_cols": GRID_COLS,
        "bbox": [float(v) for v in bbox],
        "cells": [cell.to_dict() for cell in cells],
        "observations": [obs.to_dict() for obs in observations_all],
        "summaries": summaries,
        "concordance": concordance,
        "persistence": persistence,
        "limitations": limitations,
    }


def _concordance_payload(
    cells: Sequence[Any],
    by_metric: Dict[str, Any],
    limitations: List[str],
) -> List[Dict[str, Any]]:
    """Per-cell multi-metric agreement from evaluated observations."""
    from app.services.agriculture.spatial_profile import cell_concordance

    if len(by_metric) < 1:
        return []
    by_cell: Dict[str, Dict[str, Any]] = {}
    for key, (observations, _summary) in by_metric.items():
        for obs in observations:
            by_cell.setdefault(obs.cell_id, {})[key] = obs
    records: List[Dict[str, Any]] = []
    for cell in cells:
        layers = by_cell.get(cell.cell_id, {})
        if not layers:
            continue
        try:
            records.append(cell_concordance(layers).to_dict())
        except Exception as exc:  # noqa: BLE001 - per-cell isolation
            logger.warning(
                "Spatial concordance for cell %s skipped: %s",
                cell.cell_id, type(exc).__name__,
            )
            limitations.append(
                f"spatial concordance unavailable for cell {cell.cell_id}"
            )
    return records


def _persistence_payload(
    cells: Sequence[Any],
    by_metric: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Per-cell persistence over the single available period.

    ``track_cell_persistence`` receives exactly the z-scores P1.5
    evaluation produced (none, since cells are unscored within one
    window) and reports insufficient persistence through P1.5's own
    refusal semantics. No period series is invented.
    """
    from app.services.agriculture.spatial_profile import (
        track_cell_persistence,
    )

    first_key = next(iter(by_metric), None)
    observations = (
        by_metric[first_key][0] if first_key is not None else ()
    )
    by_cell = {obs.cell_id: obs for obs in observations}
    records: List[Dict[str, Any]] = []
    for cell in cells:
        obs = by_cell.get(cell.cell_id)
        z_series = [obs.z_score] if obs is not None else [None]
        records.append(
            track_cell_persistence(cell.cell_id, z_series).to_dict()
        )
    return records


def eligible_spatial_metrics(
    metric_keys: Sequence[str],
) -> List[str]:
    """Requested keys P1.5 can actually evaluate, in registry order."""
    from app.services.agriculture.spatial_profile import (
        SUPPORTED_PROFILE_METRICS,
    )

    requested = set(metric_keys or ())
    return [k for k in SUPPORTED_PROFILE_METRICS if k in requested]
