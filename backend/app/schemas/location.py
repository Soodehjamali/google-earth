"""Location Pydantic schemas."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class PointGeometry(BaseModel):
    """GeoJSON Point geometry."""
    type: str = Field(default="Point", description="Geometry type")
    coordinates: List[float] = Field(..., description="[longitude, latitude]")


class PolygonGeometry(BaseModel):
    """GeoJSON Polygon geometry."""
    type: str = Field(default="Polygon", description="Geometry type")
    coordinates: List[List[List[float]]] = Field(
        ..., description="Polygon coordinates [[[lng, lat], ...]]"
    )

    @field_validator("coordinates")
    @classmethod
    def validate_polygon(cls, v: List[List[List[float]]]) -> List[List[List[float]]]:
        """Validate polygon has at least 4 points and is closed."""
        if not v or not v[0]:
            raise ValueError("Polygon must have at least one ring")
        ring = v[0]
        if len(ring) < 4:
            raise ValueError("Polygon ring must have at least 4 points")
        if ring[0] != ring[-1]:
            raise ValueError("Polygon ring must be closed (first == last point)")
        return v


GeometryInput = Union[PointGeometry, PolygonGeometry]


class LocationCreate(BaseModel):
    """Schema for creating a location."""
    name: Optional[str] = Field(None, max_length=255)
    latitude: Optional[float] = Field(None, ge=-90, le=90, description="GPS latitude")
    longitude: Optional[float] = Field(None, ge=-180, le=180, description="GPS longitude")
    geometry: Optional[Dict[str, Any]] = Field(None, description="GeoJSON geometry")

    @field_validator("geometry")
    @classmethod
    def validate_geometry_type(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Validate geometry is a supported type."""
        if v is not None:
            geom_type = v.get("type", "")
            if geom_type not in ("Point", "Polygon"):
                raise ValueError(f"Unsupported geometry type: {geom_type}")
        return v


class LocationResponse(BaseModel):
    """Schema for location response."""
    id: uuid.UUID
    name: Optional[str]
    geometry: Dict[str, Any]
    latitude: Optional[float]
    longitude: Optional[float]
    area_sq_meters: Optional[float]
    centroid_lat: Optional[float]
    centroid_lng: Optional[float]
    geometry_type: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LocationSummary(BaseModel):
    """Compact location summary."""
    id: uuid.UUID
    name: Optional[str]
    geometry_type: str
    area_sq_meters: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}
