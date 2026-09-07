"""Report generation endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.db.models.analysis import Analysis
from app.db.models.report import Report
from app.schemas.report import ReportCreate, ReportResponse

logger = get_logger(__name__)
router = APIRouter()


@router.post("/{analysis_id}", response_model=ReportResponse, status_code=201)
async def create_report(
    analysis_id: uuid.UUID,
    data: ReportCreate,
    db: AsyncSession = Depends(get_db),
):
    """Generate a report for an analysis.

    Phase 9 implementation — returns structured placeholder for now.
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Create report record
    report = Report(
        analysis_id=analysis_id,
        report_type=data.report_type,
        file_path=None,
    )
    db.add(report)
    await db.flush()
    await db.refresh(report)

    return ReportResponse(
        id=report.id,
        analysis_id=report.analysis_id,
        report_type=report.report_type,
        file_path=report.file_path,
        created_at=report.created_at,
    )
