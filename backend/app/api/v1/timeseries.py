"""Time series endpoints."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.db.models.analysis import Analysis
from app.db.models.timeseries import TimeSeries
from app.schemas.analysis import TimeSeriesPoint, TimeSeriesResponse

logger = get_logger(__name__)
router = APIRouter()


@router.get("/{analysis_id}/timeseries", response_model=TimeSeriesResponse)
async def get_timeseries(
    analysis_id: uuid.UUID,
    variable: Optional[str] = Query(None, description="Filter by variable (ndvi, evi, savi, ndwi)"),
    db: AsyncSession = Depends(get_db),
):
    """Get time series data for an analysis.

    Returns temporal vegetation index data (NDVI, EVI, SAVI, NDWI)
    aggregated by the analysis's temporal resolution.
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Try to get from database first
    query = select(TimeSeries).where(TimeSeries.analysis_id == analysis_id)
    if variable:
        query = query.where(TimeSeries.variable == variable)
    query = query.order_by(TimeSeries.date)

    db_result = await db.execute(query)
    timeseries_records = db_result.scalars().all()

    if timeseries_records:
        # Group by date
        date_data = {}
        for record in timeseries_records:
            date_str = record.date.isoformat()
            if date_str not in date_data:
                date_data[date_str] = {}
            date_data[date_str][record.variable] = record.value

        data_points = []
        for date_str, values in sorted(date_data.items()):
            data_points.append(TimeSeriesPoint(
                date=date_str,
                ndvi=values.get("ndvi"),
                evi=values.get("evi"),
                savi=values.get("savi"),
                ndwi=values.get("ndwi"),
            ))

        return TimeSeriesResponse(
            analysis_id=analysis_id,
            data=data_points,
            temporal_resolution=analysis.temporal_resolution,
            data_quality="good",
        )

    # Fall back to result_data if available
    if analysis.result_data and "timeseries" in analysis.result_data:
        ts_data = analysis.result_data["timeseries"]
        data_points = [
            TimeSeriesPoint(**point) for point in ts_data
        ]
        return TimeSeriesResponse(
            analysis_id=analysis_id,
            data=data_points,
            temporal_resolution=analysis.temporal_resolution,
            data_quality="good",
        )

    return TimeSeriesResponse(
        analysis_id=analysis_id,
        data=[],
        temporal_resolution=analysis.temporal_resolution,
        data_quality="insufficient",
    )
