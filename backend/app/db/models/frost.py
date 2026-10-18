"""Frost Risk Module database models: Orchard, AlertRule, NotificationLog."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Orchard(Base, TimestampMixin):
    """Registered orchard parcel for frost risk monitoring and alert dispatch."""

    __tablename__ = "orchards"

    __table_args__ = (
        Index("ix_orchards_crop", "crop"),
        Index("ix_orchards_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    geometry: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    elevation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    crop: Mapped[str] = mapped_column(String(50), nullable=False, default="pistachio")
    default_phenology_stage: Mapped[str] = mapped_column(
        String(50), nullable=False, default="early_bloom"
    )

    # Relationships
    alert_rules = relationship(
        "AlertRule", back_populates="orchard", cascade="all, delete-orphan", lazy="selectin"
    )
    observations = relationship(
        "OrchardObservation", back_populates="orchard", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Orchard {self.id} ({self.name}, {self.crop})>"


class AlertRule(Base, TimestampMixin):
    """Notification dispatch rule binding an orchard to a recipient channel.

    NOTE ON PII:
    The `recipient` field stores the raw destination address (E.164 phone number,
    email address, or webhook URI) necessary to route and deliver outbound alerts
    to growers. Direct access to this table is restricted to authorized orchard owners
    and administrative operators.
    """

    __tablename__ = "alert_rules"

    __table_args__ = (
        Index("ix_alert_rules_orchard_id", "orchard_id"),
        Index("ix_alert_rules_enabled", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    orchard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchards.id", ondelete="CASCADE"), nullable=False
    )
    recipient: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Raw delivery destination (phone number/email). Kept for outbound routing; access restricted.",
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False, default="sms")
    lead_time_h: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    orchard = relationship("Orchard", back_populates="alert_rules", lazy="selectin")

    def __repr__(self) -> str:
        return f"<AlertRule {self.id} (orchard={self.orchard_id}, channel={self.channel})>"


class NotificationLog(Base, TimestampMixin):
    """Audit log of dispatched, dry-run, or blocked frost alert notifications.

    NOTE ON PII COMPLIANCE (D3):
    To prevent PII leakage, `recipient` in this table is strictly stored in masked
    format (e.g. `+989***89` or `fa***@domain.ir`). Raw phone numbers and personal
    emails MUST NEVER be persisted in `notification_log`. Audit trails link to the
    originating rule via `alert_rule_id`.
    """

    __tablename__ = "notification_log"

    __table_args__ = (
        Index("ix_notification_log_dispatched_at", "dispatched_at"),
        Index("ix_notification_log_orchard_id", "orchard_id"),
        Index("ix_notification_log_alert_rule_id", "alert_rule_id"),
        Index("ix_notification_log_status", "status"),
        Index("ix_notification_log_idempotency_key", "idempotency_key", unique=True),
        Index("ix_notification_log_rule_idempotency", "alert_rule_id", "idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True
    )
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    orchard_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchards.id", ondelete="SET NULL"), nullable=True
    )
    alert_rule_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True
    )
    recipient: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Masked recipient identifier (PII-scrubbed, e.g. +989***89). Raw phone/email never stored in logs.",
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # sent, dry_run, blocked_unverified, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<NotificationLog {self.id} ({self.channel} -> {self.recipient}, status={self.status})>"


class OrchardObservation(Base, TimestampMixin):
    """Ground-truth observation recorded for orchard model calibration.

    Records observed on-farm minimum temperature, phenological stage,
    and frost damage severity to calibrate empirical critical thresholds.
    """

    __tablename__ = "orchard_observations"

    __table_args__ = (
        Index("ix_orchard_observations_orchard_id", "orchard_id"),
        Index("ix_orchard_observations_date", "observation_date"),
        Index("ix_orchard_observations_severity", "damage_severity"),
        Index("ix_orchard_observations_orchard_date", "orchard_id", "observation_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    orchard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orchards.id", ondelete="CASCADE"), nullable=False
    )
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    phenological_stage: Mapped[str] = mapped_column(String(64), nullable=False)
    min_temp_observed_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    damage_observed_fa: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    damage_severity: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none"
    )  # none, light, moderate, severe, total
    notes_fa: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    orchard = relationship("Orchard", back_populates="observations", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<OrchardObservation {self.id} (orchard={self.orchard_id}, "
            f"date={self.observation_date}, severity={self.damage_severity})>"
        )
