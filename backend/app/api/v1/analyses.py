"""Analysis endpoints."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.exceptions import AnalysisNotFoundError
from app.db.session import get_db
from app.db.models.analysis import Analysis
from app.db.models.location import Location
from app.schemas.analysis import AnalysisCreate, AnalysisResponse, AnalysisSummary
from app.services.analysis_service import analysis_service
from app.utils.dates import validate_date_range

logger = get_logger(__name__)
router = APIRouter()


@router.post("", response_model=AnalysisResponse, status_code=201)
async def create_analysis(
    data: AnalysisCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create and run a new analysis."""
    # Validate dates
    validate_date_range(data.start_date, data.end_date)

    # Create or find location
    location_id = data.location_id
    if not location_id:
        # Create a new location from the geometry
        from app.utils.geometry import (
            validate_geometry,
            calculate_area_sq_meters,
            calculate_centroid,
        )

        validate_geometry(data.geometry)
        geom_type = data.geometry.get("type", "Point")
        area = calculate_area_sq_meters(data.geometry) if geom_type == "Polygon" else None
        centroid_lat, centroid_lng = calculate_centroid(data.geometry)

        lat = data.geometry["coordinates"][1] if geom_type == "Point" else centroid_lat
        lng = data.geometry["coordinates"][0] if geom_type == "Point" else centroid_lng

        location = Location(
            id=uuid.uuid4(),
            geometry=data.geometry,
            latitude=lat,
            longitude=lng,
            area_sq_meters=area,
            centroid_lat=centroid_lat,
            centroid_lng=centroid_lng,
            geometry_type=geom_type,
        )
        db.add(location)
        await db.flush()
        location_id = location.id

    # Create analysis record
    analysis = Analysis(
        id=uuid.uuid4(),
        location_id=location_id,
        start_date=data.start_date,
        end_date=data.end_date,
        analysis_type=data.analysis_type,
        temporal_resolution=data.temporal_resolution,
        status="running",
    )
    db.add(analysis)
    await db.flush()

    # Run analysis
    result = await analysis_service.create_analysis(
        db=db,
        geometry=data.geometry,
        start_date=data.start_date,
        end_date=data.end_date,
        analysis_type=data.analysis_type,
        temporal_resolution=data.temporal_resolution,
        location_id=location_id,
    )

    # Update analysis record
    analysis.status = result.get("status", "failed")
    analysis.result_data = result.get("result_data")
    analysis.error_message = result.get("error_message")

    from datetime import datetime
    if analysis.status in ("completed", "failed"):
        analysis.completed_at = datetime.utcnow()

    await db.flush()
    await db.refresh(analysis)

    return AnalysisResponse(
        id=analysis.id,
        location_id=analysis.location_id,
        start_date=analysis.start_date,
        end_date=analysis.end_date,
        analysis_type=analysis.analysis_type,
        temporal_resolution=analysis.temporal_resolution,
        status=analysis.status,
        error_message=analysis.error_message,
        completed_at=analysis.completed_at,
        result_data=analysis.result_data,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
    )


@router.get("", response_model=list[AnalysisSummary])
async def list_analyses(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """List recent analyses."""
    result = await db.execute(
        select(Analysis).offset(skip).limit(limit).order_by(Analysis.created_at.desc())
    )
    analyses = result.scalars().all()

    return [
        AnalysisSummary(
            id=a.id,
            analysis_type=a.analysis_type,
            status=a.status,
            created_at=a.created_at,
            completed_at=a.completed_at,
        )
        for a in analyses
    ]


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get analysis by ID."""
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return AnalysisResponse(
        id=analysis.id,
        location_id=analysis.location_id,
        start_date=analysis.start_date,
        end_date=analysis.end_date,
        analysis_type=analysis.analysis_type,
        temporal_resolution=analysis.temporal_resolution,
        status=analysis.status,
        error_message=analysis.error_message,
        completed_at=analysis.completed_at,
        result_data=analysis.result_data,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
    )


@router.get("/{analysis_id}/summary")
async def get_analysis_summary(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get analysis summary."""
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    if not analysis.result_data:
        return {"status": analysis.status, "message": "Analysis not yet complete"}

    return analysis_service.get_analysis_summary(analysis.result_data)
