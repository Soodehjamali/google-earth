"""Location management endpoints."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.exceptions import ValidationError, GeometryError
from app.db.session import get_db
from app.db.models.location import Location
from app.schemas.location import LocationCreate, LocationResponse, LocationSummary
from app.utils.geometry import (
    validate_coordinates,
    validate_geometry,
    calculate_area_sq_meters,
    calculate_centroid,
    calculate_bounding_box,
    create_ee_geometry,
)

logger = get_logger(__name__)
router = APIRouter()


@router.post("", response_model=LocationResponse, status_code=201)
async def create_location(
    data: LocationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new location (point or polygon)."""
    # Build geometry
    if data.geometry:
        geometry = data.geometry
    elif data.latitude is not None and data.longitude is not None:
        validate_coordinates(data.latitude, data.longitude)
        geometry = {
            "type": "Point",
            "coordinates": [data.longitude, data.latitude],
        }
    else:
        raise ValidationError(
            message="Provide either geometry or latitude/longitude",
        )

    # Validate geometry
    validate_geometry(geometry)

    geom_type = geometry.get("type", "Point")

    # Calculate derived properties
    area = calculate_area_sq_meters(geometry) if geom_type == "Polygon" else None
    centroid_lat, centroid_lng = calculate_centroid(geometry)

    lat = geometry["coordinates"][1] if geom_type == "Point" else centroid_lat
    lng = geometry["coordinates"][0] if geom_type == "Point" else centroid_lng

    location = Location(
        id=uuid.uuid4(),
        name=data.name,
        geometry=geometry,
        latitude=lat,
        longitude=lng,
        area_sq_meters=area,
        centroid_lat=centroid_lat,
        centroid_lng=centroid_lng,
        geometry_type=geom_type,
    )

    db.add(location)
    await db.flush()
    await db.refresh(location)

    logger.info(f"Created location {location.id} ({geom_type})")

    return LocationResponse(
        id=location.id,
        name=location.name,
        geometry=location.geometry,
        latitude=location.latitude,
        longitude=location.longitude,
        area_sq_meters=location.area_sq_meters,
        centroid_lat=location.centroid_lat,
        centroid_lng=location.centroid_lng,
        geometry_type=location.geometry_type,
        created_at=location.created_at,
        updated_at=location.updated_at,
    )


@router.get("", response_model=List[LocationSummary])
async def list_locations(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List all locations."""
    result = await db.execute(
        select(Location).offset(skip).limit(limit).order_by(Location.created_at.desc())
    )
    locations = result.scalars().all()

    return [
        LocationSummary(
            id=loc.id,
            name=loc.name,
            geometry_type=loc.geometry_type,
            area_sq_meters=loc.area_sq_meters,
            created_at=loc.created_at,
        )
        for loc in locations
    ]


@router.get("/{location_id}", response_model=LocationResponse)
async def get_location(
    location_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a location by ID."""
    result = await db.execute(select(Location).where(Location.id == location_id))
    location = result.scalar_one_or_none()

    if not location:
        raise HTTPException(status_code=404, detail="Location not found")

    return LocationResponse(
        id=location.id,
        name=location.name,
        geometry=location.geometry,
        latitude=location.latitude,
        longitude=location.longitude,
        area_sq_meters=location.area_sq_meters,
        centroid_lat=location.centroid_lat,
        centroid_lng=location.centroid_lng,
        geometry_type=location.geometry_type,
        created_at=location.created_at,
        updated_at=location.updated_at,
    )


@router.delete("/{location_id}", status_code=204)
async def delete_location(
    location_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a location."""
    result = await db.execute(select(Location).where(Location.id == location_id))
    location = result.scalar_one_or_none()

    if not location:
        raise HTTPException(status_code=404, detail="Location not found")

    await db.delete(location)
