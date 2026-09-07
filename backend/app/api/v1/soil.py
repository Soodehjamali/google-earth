"""Soil analysis endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.db.models.analysis import Analysis

logger = get_logger(__name__)
router = APIRouter()


@router.get("/{analysis_id}/soil")
async def get_soil_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get soil analysis results.

    Returns soil moisture, organic carbon, texture data.
    Phase 4 implementation — returns structured placeholder for now.
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    soil_data = analysis.result_data.get("soil") if analysis.result_data else None
    if soil_data:
        return soil_data

    return {
        "status": "not_implemented",
        "message": "Soil analysis will be available in Phase 4",
        "analysis_id": str(analysis_id),
        "datasets": ["SoilGrids REST API"],
    }
