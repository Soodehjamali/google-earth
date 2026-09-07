"""Analysis database model."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Analysis(Base, TimestampMixin):
    """An analysis job tied to a location."""

    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=False
    )
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False, default="complete")
    temporal_resolution: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    result_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Relationships
    location = relationship("Location", back_populates="analyses", lazy="selectin")
    datasets = relationship("DatasetUsage", back_populates="analysis", lazy="selectin")
    timeseries = relationship("TimeSeries", back_populates="analysis", lazy="selectin")
    reports = relationship("Report", back_populates="analysis", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Analysis {self.id} ({self.analysis_type}) {self.status}>"
