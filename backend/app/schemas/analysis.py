"""Analysis Pydantic schemas."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AnalysisCreate(BaseModel):
    """Schema for creating an analysis."""
    geometry: Dict[str, Any] = Field(..., description="GeoJSON geometry (Point or Polygon)")
    start_date: str = Field(..., description="Start date YYYY-MM-DD")
    end_date: str = Field(..., description="End date YYYY-MM-DD")
    analysis_type: str = Field(
        default="complete",
        description="Type of analysis",
        pattern="^(complete|vegetation|climate|soil|water|landcover|historical)$",
    )
    temporal_resolution: str = Field(
        default="monthly",
        description="Temporal aggregation",
        pattern="^(daily|weekly|monthly|seasonal|yearly)$",
    )
    location_id: Optional[uuid.UUID] = Field(None, description="Existing location ID")

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Validate date format is YYYY-MM-DD."""
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date format: {v}. Expected YYYY-MM-DD")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_end_after_start(cls, v: str, info) -> str:
        """Validate end date is after start date."""
        start = info.data.get("start_date")
        if start and v <= start:
            raise ValueError("end_date must be after start_date")
        return v


class AnalysisResponse(BaseModel):
    """Schema for analysis response."""
    id: uuid.UUID
    location_id: uuid.UUID
    start_date: str
    end_date: str
    analysis_type: str
    temporal_resolution: str
    status: str
    error_message: Optional[str]
    completed_at: Optional[datetime]
    result_data: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnalysisSummary(BaseModel):
    """Compact analysis summary."""
    id: uuid.UUID
    analysis_type: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class VegetationStats(BaseModel):
    """Vegetation statistics for a single index."""
    index_name: str
    mean: Optional[float]
    median: Optional[float]
    min: Optional[float]
    max: Optional[float]
    std: Optional[float]
    percentile_10: Optional[float]
    percentile_25: Optional[float]
    percentile_75: Optional[float]
    percentile_90: Optional[float]
    unit: str = "dimensionless"
    data_quality: str = "good"
    observation_count: int = 0


class VegetationResponse(BaseModel):
    """Full vegetation analysis response."""
    analysis_id: uuid.UUID
    ndvi: Optional[VegetationStats]
    evi: Optional[VegetationStats]
    savi: Optional[VegetationStats]
    ndwi: Optional[VegetationStats]
    overall_health: str = "unknown"
    trend: str = "stable"
    data_quality: str = "good"
    interpretation: str = ""


class TimeSeriesPoint(BaseModel):
    """Single time-series data point."""
    date: str
    ndvi: Optional[float]
    evi: Optional[float]
    savi: Optional[float]
    ndwi: Optional[float]


class TimeSeriesResponse(BaseModel):
    """Time-series analysis response."""
    analysis_id: uuid.UUID
    data: List[TimeSeriesPoint]
    temporal_resolution: str
    data_quality: str = "good"
