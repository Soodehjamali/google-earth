"""Report database model."""

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Report(Base, TimestampMixin):
    """Generated report for an analysis."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False, default="pdf")

    # Relationships
    analysis = relationship("Analysis", back_populates="reports")

    def __repr__(self) -> str:
        return f"<Report {self.id} ({self.report_type})>"
