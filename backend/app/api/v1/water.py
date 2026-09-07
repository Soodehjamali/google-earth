"""Water analysis endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.db.models.analysis import Analysis

logger = get_logger(__name__)
router = APIRouter()


@router.get("/{analysis_id}/water")
async def get_water_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get water analysis results.

    Returns precipitation, ET, soil moisture, water stress data.
    Phase 3 implementation — returns structured placeholder for now.
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    water_data = analysis.result_data.get("water") if analysis.result_data else None
    if water_data:
        return water_data

    return {
        "status": "not_implemented",
        "message": "Water analysis will be available in Phase 3",
        "analysis_id": str(analysis_id),
        "datasets": ["ECMWF/ERA5_LAND/DAILY_AGGR"],
    }
