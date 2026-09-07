"""DatasetUsage database model."""

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class DatasetUsage(Base, TimestampMixin):
    """Records which datasets were used in an analysis."""

    __tablename__ = "dataset_usages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False
    )
    dataset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    variable: Mapped[str] = mapped_column(String(100), nullable=False)
    resolution: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    date_range: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # NB: attribute renamed (keeps DB column name 'metadata') because 'metadata'
    # is reserved by SQLAlchemy's Declarative Base.
    usage_metadata: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    # Relationships
    analysis = relationship("Analysis", back_populates="datasets")

    def __repr__(self) -> str:
        return f"<DatasetUsage {self.dataset_id} ({self.variable})>"
