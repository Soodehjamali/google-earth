"""Pydantic schemas for Frost Risk endpoints."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class FrostAssessRequest(BaseModel):
    """Ad-hoc frost risk assessment request for an arbitrary geometry."""

    geometry: Dict[str, Any] = Field(..., description="GeoJSON polygon or point feature geometry.")
    crop: str = Field("pistachio", description="Target crop key, e.g. pistachio.")
    phenological_stage: str = Field("early_bloom", description="Target phenological stage.")
    horizon_h: int = Field(240, ge=24, le=384, description="Forecast horizon in hours (default 240h, hard-capped at 240h).")
    pooling_risk_proxy: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Optional pre-computed cold-air-pooling proxy (0.0 to 1.0)."
    )
    use_live_gee: Optional[bool] = Field(
        False,
        description="Deprecated. Forecast provider is controlled exclusively by server configuration.",
    )


class OrchardCreate(BaseModel):
    """Schema for registering a new orchard parcel."""

    name: str = Field(..., min_length=1, max_length=255, description="Orchard or parcel name.")
    geometry: Dict[str, Any] = Field(..., description="GeoJSON Polygon geometry.")
    latitude: Optional[float] = Field(None, description="Centroid latitude.")
    longitude: Optional[float] = Field(None, description="Centroid longitude.")
    elevation: Optional[float] = Field(None, description="Elevation in meters above sea level.")
    crop: str = Field("pistachio", description="Crop identifier, e.g. pistachio.")
    default_phenology_stage: str = Field("early_bloom", description="Default phenological stage.")


class AlertRuleCreate(BaseModel):
    """Schema for registering an alert rule bound to an orchard."""

    recipient: str = Field(..., min_length=1, max_length=255, description="Destination phone, chat ID, or URL.")
    channel: str = Field("sms", description="Notification channel: sms, telegram, webhook, or email.")
    lead_time_h: int = Field(24, ge=1, le=120, description="Lead time in hours for advance warning.")
    enabled: bool = Field(True, description="Whether this alert rule is active.")


class AlertRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    orchard_id: uuid.UUID
    recipient: str
    channel: str
    lead_time_h: int
    enabled: bool
    created_at: str


class OrchardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    geometry: Dict[str, Any]
    latitude: Optional[float]
    longitude: Optional[float]
    elevation: Optional[float]
    crop: str
    default_phenology_stage: str
    created_at: str
    alert_rules: List[AlertRuleResponse] = []


class EvaluateAlertsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = Field(True, description="If True, dispatches in dry-run mode without real delivery.")
    force_crop: Optional[str] = Field(None, description="Optional override crop for all orchards.")
    use_live_gee: Optional[bool] = Field(
        False,
        description="Deprecated. Forecast provider is controlled exclusively by server configuration.",
    )


class NotificationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dispatched_at: str
    orchard_id: Optional[uuid.UUID]
    alert_rule_id: Optional[uuid.UUID]
    recipient: str
    channel: str
    status: str
    error_message: Optional[str] = None
    payload: Dict[str, Any]


class EvaluateAlertsResponse(BaseModel):
    evaluated_orchards: int
    evaluated_rules: int
    dispatched_notifications: int
    dry_run: bool
    thresholds_verified: bool
    safety_lock_active: bool
    notifications: List[NotificationLogResponse]
