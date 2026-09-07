"""Report Pydantic schemas."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReportCreate(BaseModel):
    """Schema for requesting report generation."""
    report_type: str = "pdf"


class ReportResponse(BaseModel):
    """Schema for report response."""
    id: uuid.UUID
    analysis_id: uuid.UUID
    report_type: str
    file_path: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
