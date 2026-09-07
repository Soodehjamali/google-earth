"""Land cover analysis endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.db.models.analysis import Analysis

logger = get_logger(__name__)
router = APIRouter()


@router.get("/{analysis_id}/landcover")
async def get_landcover_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get land cover analysis results.

    Returns land cover classification percentages.
    Phase 5 implementation — returns structured placeholder for now.
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    landcover_data = analysis.result_data.get("landcover") if analysis.result_data else None
    if landcover_data:
        return landcover_data

    return {
        "status": "not_implemented",
        "message": "Land cover analysis will be available in Phase 5",
        "analysis_id": str(analysis_id),
        "datasets": ["MODIS/061/MCD12Q1"],
    }
