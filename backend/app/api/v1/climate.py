"""Climate analysis endpoints."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.db.models.analysis import Analysis

logger = get_logger(__name__)
router = APIRouter()


@router.get("/{analysis_id}/climate")
async def get_climate_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get climate analysis results.

    Returns temperature, precipitation, and evapotranspiration data.
    Phase 3 implementation — returns structured placeholder for now.
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    if analysis.status != "completed" or not analysis.result_data:
        raise HTTPException(status_code=400, detail="Analysis not yet complete")

    # Check if climate data exists in result
    climate_data = analysis.result_data.get("climate")
    if climate_data:
        return climate_data

    return {
        "status": "not_implemented",
        "message": "Climate analysis will be available in Phase 3",
        "analysis_id": str(analysis_id),
        "datasets": ["ECMWF/ERA5_LAND/DAILY_AGGR", "ECMWF/ERA5_MONTHLY_AGGR"],
    }
