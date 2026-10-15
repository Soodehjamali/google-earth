"""Stress analysis endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.db.models.analysis import Analysis

logger = get_logger(__name__)
router = APIRouter()


@router.get("/{analysis_id}/stress")
async def get_stress_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get vegetation stress analysis.

    Returns spatial stress zones and classification.
    Phase 6 implementation — returns structured placeholder for now.
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    result_data = analysis.result_data or {}
    stress_data = (
        result_data.get("stress")
        or result_data.get("agriculture", {}).get("bundles", {}).get("stress")
        or result_data.get("evidence", {}).get("stress")
    )
    if stress_data:
        return stress_data

    return {
        "status": "not_available",
        "message": "Stress evidence was not included in this analysis run. Request the stress domain in /api/v1/agriculture/analysis.",
        "analysis_id": str(analysis_id),
    }
