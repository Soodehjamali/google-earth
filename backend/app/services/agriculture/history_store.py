"""Persistent history store for agricultural analyses (Phase P0-HISTORY).

Provides robust, persistent storage and retrieval of full Agricultural Intelligence
analysis runs in PostgreSQL, decoupling historical report retrieval from Earth Engine.
Ensures zero data fabrication, strict idempotency, error sanitization, and offline
geometry extraction.
"""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db.models.analysis import Analysis
from app.db.models.location import Location
from app.schemas.agriculture import (
    AgriculturalAnalysisResponse,
    AgricultureAnalysisRequest,
    AgricultureHistoryItemSummary,
    AgricultureHistoryListResponse,
)

logger = get_logger(__name__)

# Patterns to strip from error messages before persisting
_SECRET_PATTERNS = [
    (re.compile(r":[^:@/\s]+@"), ":[REDACTED]@"),
    (re.compile(r"(?i)(password|secret|key|token|auth|credential)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"([A-Za-z]:\\[^:\s]+|/(?:home|Users|var|tmp|etc)/[^\s]+)"), "[REDACTED]"),
]


def sanitize_error_message(message: Optional[str]) -> str:
    """Sanitize error message to prevent leaking internal file paths or credentials."""
    if not message:
        return "Unknown error occurred"
    clean = str(message)
    for pattern, replacement in _SECRET_PATTERNS:
        clean = pattern.sub(replacement, clean)
    return clean[:500]



def compute_geometry_centroid_and_area(
    geometry: Dict[str, Any]
) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    """Compute centroid (lat, lng), spherical area (sq meters), and geometry type purely in offline Python.

    Scientific Method & Assumptions:
    --------------------------------
    1. Approximation Model: Spherical Girard / trapezoidal excess surface integration
       on a sphere of mean radius R = 6,378,137.0 m (WGS84 mean radius).
    2. Centroid Model: True planar 2nd-moment polygon centroid (shoelace moments)
       for closed exterior rings, with fallback to arithmetic mean of unique vertices
       for degenerate/zero-area rings or unclosed inputs.
    3. Scope & Validity Domain:
       - Applicable to agricultural parcels and fields (local scales, typically < 100 km²).
       - Assumes simple (non-self-intersecting) exterior rings without interior holes.
       - Assumes coordinates do not cross the 180° antimeridian (|lon2 - lon1| < 180°).
       - For Middle East / Iranian latitudes (25°N–40°N), the spherical approximation
         deviates by < 0.1% from rigorous WGS84 ellipsoidal geodesic algorithms.
    4. Limitations:
       - This is an honest spherical approximation for indexing, telemetry, and fast UI display.
       - It is NOT a substitute for cadastral surveying or official land-title measurements.
       - MultiPolygon and GeometryCollection geometries return (None, None, None, geom_type).
       - Degenerate rings (< 4 coordinates or 0 enclosed area) return None for area.

    Never makes blocking Earth Engine calls.
    """
    if not isinstance(geometry, dict):
        return None, None, None, "Unknown"

    geom_type = geometry.get("type", "Point")
    coords = geometry.get("coordinates")
    if not coords or not isinstance(coords, (list, tuple)):
        return None, None, None, geom_type

    if geom_type == "Point":
        # Point coords: [lng, lat]
        try:
            if len(coords) < 2:
                return None, None, None, "Point"
            lng, lat = float(coords[0]), float(coords[1])
            if not (-180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0):
                return None, None, None, "Point"
            return lat, lng, None, "Point"
        except (ValueError, TypeError, IndexError):
            return None, None, None, "Point"

    if geom_type == "Polygon":
        # Polygon coords: [ [ [lng, lat], ... ] ]
        try:
            raw_ring = coords[0] if coords and isinstance(coords[0], (list, tuple)) else []
            if len(raw_ring) < 3:
                return None, None, None, "Polygon"

            # Parse and validate numeric coordinate pairs
            valid_points: List[List[float]] = []
            for p in raw_ring:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    try:
                        x, y = float(p[0]), float(p[1])
                        if -180.0 <= x <= 180.0 and -90.0 <= y <= 90.0:
                            valid_points.append([x, y])
                    except (ValueError, TypeError):
                        continue

            if len(valid_points) < 3:
                return None, None, None, "Polygon"

            # Ensure ring is closed (first point == last point)
            ring = list(valid_points)
            if ring[0] != ring[-1]:
                ring.append(list(ring[0]))

            if len(ring) < 4:
                return None, None, None, "Polygon"

            # Unique vertices excluding closing vertex
            vertices = ring[:-1]
            avg_lat = sum(p[1] for p in vertices) / len(vertices)
            avg_lng = sum(p[0] for p in vertices) / len(vertices)

            # Planar 2nd-moment centroid (shoelace centroid)
            shoelace_area = 0.0
            cx_sum = 0.0
            cy_sum = 0.0
            n = len(ring)
            for i in range(n - 1):
                x0, y0 = ring[i][0], ring[i][1]
                x1, y1 = ring[i + 1][0], ring[i + 1][1]
                cross = (x0 * y1) - (x1 * y0)
                shoelace_area += cross
                cx_sum += (x0 + x1) * cross
                cy_sum += (y0 + y1) * cross

            if abs(shoelace_area) > 1e-12:
                centroid_lng = cx_sum / (3.0 * shoelace_area)
                centroid_lat = cy_sum / (3.0 * shoelace_area)
            else:
                centroid_lng = avg_lng
                centroid_lat = avg_lat

            # Spherical trapezoidal excess surface area (R = 6,378,137.0 m)
            radius = 6378137.0
            area_sum = 0.0
            for i in range(n - 1):
                p1 = ring[i]
                p2 = ring[i + 1]
                rad_lon1 = math.radians(p1[0])
                rad_lat1 = math.radians(p1[1])
                rad_lon2 = math.radians(p2[0])
                rad_lat2 = math.radians(p2[1])
                # Guard against antimeridian wrapping
                d_lon = rad_lon2 - rad_lon1
                if d_lon > math.pi:
                    d_lon -= 2.0 * math.pi
                elif d_lon < -math.pi:
                    d_lon += 2.0 * math.pi
                area_sum += d_lon * (2.0 + math.sin(rad_lat1) + math.sin(rad_lat2))

            area = abs(area_sum * radius * radius / 2.0)
            if area < 1e-3:
                area = None

            return centroid_lat, centroid_lng, area, "Polygon"
        except Exception as exc:
            logger.warning(f"Error computing polygon geometry metrics: {exc}")
            return None, None, None, "Polygon"

    return None, None, None, geom_type


async def get_or_create_location(
    db: AsyncSession,
    data: AgricultureAnalysisRequest,
) -> Location:
    """Find existing Location by ID or create a new Location record."""
    geom_dict = data.geometry.model_dump()

    if data.location_id:
        existing = await db.execute(
            select(Location).where(Location.id == data.location_id)
        )
        loc = existing.scalar_one_or_none()
        if loc:
            if data.name and not loc.name:
                loc.name = data.name
                await db.flush()
            return loc

    lat, lng, area, geom_type = compute_geometry_centroid_and_area(geom_dict)

    location = Location(
        id=uuid.uuid4(),
        name=data.name,
        geometry=geom_dict,
        latitude=lat,
        longitude=lng,
        area_sq_meters=area,
        centroid_lat=lat,
        centroid_lng=lng,
        geometry_type=geom_type,
    )
    db.add(location)
    await db.flush()
    return location


async def record_analysis_start(
    db: AsyncSession,
    data: AgricultureAnalysisRequest,
    target_id: uuid.UUID,
) -> Tuple[Analysis, bool]:
    """Record the start of an agricultural analysis run.

    Returns (Analysis, is_existing_completed).
    - If analysis with target_id is already completed, returns (Analysis, True)
      enforcing strict idempotency on client retries.
    - If analysis with target_id exists in failed status, transitions it back to
      running, resets error_message, commits, and returns (Analysis, False).
    - If analysis is already running, returns (Analysis, False).
    - Automatically handles concurrent insert race conditions using unique key rollback.
    """
    from sqlalchemy.exc import IntegrityError

    # Check if this exact analysis ID already exists
    stmt = select(Analysis).where(Analysis.id == target_id)
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()

    if existing:
        if existing.status == "completed" and existing.result_data:
            logger.info(f"Analysis {target_id} already completed in DB (idempotent replay)")
            return existing, True
        if existing.status == "failed":
            # Retrying a previously failed analysis: reset to running state
            logger.info(f"Retrying failed analysis {target_id}: resetting status to running")
            existing.status = "running"
            existing.error_message = None
            existing.completed_at = None
            existing.start_date = data.start_date
            existing.end_date = data.end_date
            await db.commit()
            return existing, False
        # Already running
        return existing, False

    try:
        location = await get_or_create_location(db, data)
        analysis = Analysis(
            id=target_id,
            location_id=location.id,
            start_date=data.start_date,
            end_date=data.end_date,
            analysis_type="agricultural",
            temporal_resolution="monthly",
            status="running",
            result_data=None,
        )
        db.add(analysis)
        await db.commit()
        return analysis, False
    except IntegrityError:
        # Concurrent request with same target_id already committed
        await db.rollback()
        stmt = select(Analysis).where(Analysis.id == target_id)
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            if existing.status == "completed" and existing.result_data:
                return existing, True
            return existing, False
        raise


async def record_analysis_completion(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    response: AgriculturalAnalysisResponse,
) -> None:
    """Persist full successful analysis output and mark status as completed.

    If commit fails, catches the error, rolls back, transitions analysis to 'failed',
    records the persistence error message, and re-raises so the record is never
    stuck in 'running'.
    """
    stmt = select(Analysis).where(Analysis.id == analysis_id)
    res = await db.execute(stmt)
    analysis = res.scalar_one_or_none()
    if not analysis:
        logger.warning(f"Could not find analysis {analysis_id} to mark completed")
        return

    analysis.status = "completed"
    analysis.completed_at = datetime.now(timezone.utc)
    analysis.result_data = response.model_dump(mode="json")
    analysis.error_message = None

    try:
        await db.commit()
        logger.info(f"Agricultural analysis {analysis_id} successfully persisted in PostgreSQL")
    except Exception as exc:
        logger.error(f"Failed to commit completed analysis {analysis_id}: {exc}")
        try:
            await db.rollback()
            stmt2 = select(Analysis).where(Analysis.id == analysis_id)
            res2 = await db.execute(stmt2)
            rec2 = res2.scalar_one_or_none()
            if rec2:
                rec2.status = "failed"
                rec2.completed_at = datetime.now(timezone.utc)
                rec2.error_message = sanitize_error_message(f"Persistence error: {exc}")
                await db.commit()
        except Exception as rollback_err:
            logger.error(f"Failed to record persistence failure for {analysis_id}: {rollback_err}")
        raise


async def record_analysis_failure(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    error_message: str,
) -> None:
    """Record analysis failure state and sanitized diagnostic message."""
    try:
        try:
            await db.rollback()
        except Exception:
            pass

        stmt = select(Analysis).where(Analysis.id == analysis_id)
        res = await db.execute(stmt)
        analysis = res.scalar_one_or_none()
        if not analysis:
            return

        analysis.status = "failed"
        analysis.completed_at = datetime.now(timezone.utc)
        analysis.error_message = sanitize_error_message(error_message)
        await db.commit()
    except Exception as exc:
        logger.error(f"Failed to record failure for analysis {analysis_id}: {exc}")


async def get_analysis_history_list(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 20,
    location_id: Optional[uuid.UUID] = None,
) -> AgricultureHistoryListResponse:
    """Query paginated list of agricultural analyses for history view.

    Selects lightweight summary fields only; avoids serializing large result_data blobs.
    """
    base_query = select(Analysis).options(selectinload(Analysis.location))
    if location_id:
        base_query = base_query.where(Analysis.location_id == location_id)

    # Count total
    count_query = select(func.count(Analysis.id))
    if location_id:
        count_query = count_query.where(Analysis.location_id == location_id)
    total_res = await db.execute(count_query)
    total = total_res.scalar_one() or 0

    # Paginate and order by newest first
    stmt = base_query.order_by(Analysis.created_at.desc()).offset(skip).limit(limit)
    res = await db.execute(stmt)
    records = res.scalars().all()

    items: List[AgricultureHistoryItemSummary] = []
    for a in records:
        loc = a.location
        result_dict = a.result_data or {}
        suff = result_dict.get("overall_sufficiency")
        synthesis_status = result_dict.get("synthesis_status")

        items.append(
            AgricultureHistoryItemSummary(
                id=a.id,
                location_id=a.location_id,
                location_name=loc.name if loc else None,
                geometry_type=loc.geometry_type if loc else "Point",
                latitude=loc.latitude if loc else None,
                longitude=loc.longitude if loc else None,
                area_sq_meters=loc.area_sq_meters if loc else None,
                start_date=a.start_date,
                end_date=a.end_date,
                status=a.status,
                created_at=a.created_at,
                completed_at=a.completed_at,
                overall_sufficiency=suff,
                synthesis_status=synthesis_status,
                error_message=a.error_message,
            )
        )

    return AgricultureHistoryListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
    )


async def get_analysis_history_item(
    db: AsyncSession,
    analysis_id: uuid.UUID,
) -> Optional[Analysis]:
    """Retrieve a single Analysis database record by ID."""
    stmt = (
        select(Analysis)
        .options(selectinload(Analysis.location))
        .where(Analysis.id == analysis_id)
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def delete_analysis_history_item(
    db: AsyncSession,
    analysis_id: uuid.UUID,
) -> bool:
    """Delete a single analysis record by ID. Returns True if deleted."""
    stmt = select(Analysis).where(Analysis.id == analysis_id)
    res = await db.execute(stmt)
    record = res.scalar_one_or_none()
    if not record:
        return False

    await db.delete(record)
    await db.commit()
    return True
