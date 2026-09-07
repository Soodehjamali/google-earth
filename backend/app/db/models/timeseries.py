"""TimeSeries database model."""

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Date, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class TimeSeries(Base, TimestampMixin):
    """Time-series data point for an analysis."""

    __tablename__ = "timeseries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    variable: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    # NB: attribute renamed (keeps DB column name 'metadata') because 'metadata'
    # is reserved by SQLAlchemy's Declarative Base.
    point_metadata: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    # Relationships
    analysis = relationship("Analysis", back_populates="timeseries")

    def __repr__(self) -> str:
        return f"<TimeSeries {self.variable}={self.value} @ {self.date}>"
