"""Vegetation analysis endpoints."""

from typing import Optional

from fastapi import APIRouter

from app.core.logging import get_logger
from app.schemas.vegetation import NDVIRequest, NDVIResult
from app.services.vegetation_service import VegetationService
from app.services.earth_engine.indices import get_all_index_definitions
from app.utils.geometry import validate_coordinates, create_ee_geometry
from app.utils.units import ndvi_health_label

logger = get_logger(__name__)
router = APIRouter()

vegetation_service = VegetationService()


@router.post("/ndvi", response_model=NDVIResult)
async def analyze_ndvi(data: NDVIRequest):
    """Analyze NDVI for a GPS point.

    Returns NDVI statistics for the given coordinates and date range.
    """
    validate_coordinates(data.latitude, data.longitude)

    geometry = {
        "type": "Point",
        "coordinates": [data.longitude, data.latitude],
    }

    ee_geometry = create_ee_geometry(geometry)

    result = vegetation_service.analyze(
        geometry=ee_geometry,
        start_date=data.start_date,
        end_date=data.end_date,
        cloud_max_percent=data.cloud_max_percent,
    )

    stats = result.get("statistics", {}).get("NDVI", {})

    return NDVIResult(
        latitude=data.latitude,
        longitude=data.longitude,
        ndvi_mean=stats.get("mean"),
        ndvi_min=stats.get("min"),
        ndvi_max=stats.get("max"),
        ndvi_std=stats.get("std"),
        observation_count=result.get("image_count", 0),
        cloud_coverage_percent=None,
        data_quality=result.get("data_quality", "unknown"),
        interpretation=result.get("interpretation", ""),
    )


@router.get("/indices")
async def get_indices():
    """Get documentation for all vegetation indices."""
    return get_all_index_definitions()
