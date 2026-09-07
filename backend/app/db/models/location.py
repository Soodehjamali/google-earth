"""Location database model."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Location(Base, TimestampMixin):
    """A geographic location (point or polygon) for analysis."""

    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    geometry: Mapped[dict] = mapped_column(JSONB, nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    area_sq_meters: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    centroid_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    centroid_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geometry_type: Mapped[str] = mapped_column(String(50), nullable=False, default="Point")

    # Relationships
    analyses = relationship("Analysis", back_populates="location", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Location {self.id} ({self.geometry_type})>"
