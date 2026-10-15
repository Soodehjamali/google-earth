"""Frost risk module tables (orchards, alert_rules, notification_log)

Revision ID: 002_frost
Revises: 001_initial
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision: str = '002_frost'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Support SQLite compilation for testing environments
try:
    from sqlalchemy.ext.compiler import compiles
    @compiles(JSONB, 'sqlite')
    def compile_jsonb_sqlite(type_, compiler, **kw):
        return 'JSON'
except Exception:
    pass


def upgrade() -> None:
    # 1. Orchards table
    op.create_table(
        'orchards',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('geometry', JSONB, nullable=False),
        sa.Column('latitude', sa.Float, nullable=True),
        sa.Column('longitude', sa.Float, nullable=True),
        sa.Column('elevation', sa.Float, nullable=True),
        sa.Column('crop', sa.String(50), nullable=False, server_default='pistachio'),
        sa.Column('default_phenology_stage', sa.String(50), nullable=False, server_default='early_bloom'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 2. Alert rules table
    op.create_table(
        'alert_rules',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('orchard_id', UUID(as_uuid=True), sa.ForeignKey('orchards.id', ondelete='CASCADE'), nullable=False),
        sa.Column('recipient', sa.String(255), nullable=False),
        sa.Column('channel', sa.String(50), nullable=False, server_default='sms'),
        sa.Column('lead_time_h', sa.Integer, nullable=False, server_default='24'),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 3. Notification log table
    op.create_table(
        'notification_log',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('idempotency_key', sa.String(255), unique=True, nullable=True),
        sa.Column('dispatched_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('orchard_id', UUID(as_uuid=True), sa.ForeignKey('orchards.id', ondelete='SET NULL'), nullable=True),
        sa.Column('alert_rule_id', UUID(as_uuid=True), sa.ForeignKey('alert_rules.id', ondelete='SET NULL'), nullable=True),
        sa.Column('recipient', sa.String(255), nullable=False),
        sa.Column('channel', sa.String(50), nullable=False),
        sa.Column('payload', JSONB, nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Indexes
    op.create_index('ix_orchards_crop', 'orchards', ['crop'])
    op.create_index('ix_orchards_created_at', 'orchards', ['created_at'])
    op.create_index('ix_alert_rules_orchard_id', 'alert_rules', ['orchard_id'])
    op.create_index('ix_alert_rules_enabled', 'alert_rules', ['enabled'])
    op.create_index('ix_notification_log_dispatched_at', 'notification_log', ['dispatched_at'])
    op.create_index('ix_notification_log_orchard_id', 'notification_log', ['orchard_id'])
    op.create_index('ix_notification_log_status', 'notification_log', ['status'])
    op.create_index('ix_notification_log_idempotency_key', 'notification_log', ['idempotency_key'], unique=True)


def downgrade() -> None:
    op.drop_table('notification_log')
    op.drop_table('alert_rules')
    op.drop_table('orchards')
