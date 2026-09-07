"""Risk analysis endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.db.models.analysis import Analysis

logger = get_logger(__name__)
router = APIRouter()


@router.get("/{analysis_id}/risk")
async def get_risk_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get agricultural risk score.

    Returns composite risk score (0-100) with component breakdown.
    Phase 7 implementation — returns structured placeholder for now.
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    risk_data = analysis.result_data.get("risk") if analysis.result_data else None
    if risk_data:
        return risk_data

    return {
        "status": "not_implemented",
        "message": "Risk analysis will be available in Phase 7",
        "analysis_id": str(analysis_id),
        "score": None,
        "level": None,
        "components": {},
    }
