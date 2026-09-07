"""Vegetation-specific Pydantic schemas."""

from typing import Optional

from pydantic import BaseModel, Field


class NDVIRequest(BaseModel):
    """Request for NDVI analysis at a point."""
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    cloud_max_percent: int = Field(default=20, ge=0, le=100)


class NDVIResult(BaseModel):
    """NDVI analysis result."""
    latitude: float
    longitude: float
    ndvi_mean: Optional[float]
    ndvi_min: Optional[float]
    ndvi_max: Optional[float]
    ndvi_std: Optional[float]
    observation_count: int
    cloud_coverage_percent: Optional[float]
    data_quality: str
    interpretation: str


class CompositeImage(BaseModel):
    """Satellite composite image info."""
    dataset_id: str
    visualization: dict
    date_range: str
    cloud_coverage: Optional[float]
    image_count: int
