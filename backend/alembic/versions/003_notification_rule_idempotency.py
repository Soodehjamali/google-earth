"""Notification rule-level idempotency index

Revision ID: 003_rule_idempotency
Revises: 002_frost
Create Date: 2026-10-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '003_rule_idempotency'
down_revision: Union[str, None] = '002_frost'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add index on alert_rule_id for efficient per-rule dispatch lookups
    op.create_index('ix_notification_log_alert_rule_id', 'notification_log', ['alert_rule_id'])
    # Add composite index on alert_rule_id and idempotency_key for rule-level idempotency
    op.create_index('ix_notification_log_rule_idempotency', 'notification_log', ['alert_rule_id', 'idempotency_key'])


def downgrade() -> None:
    op.drop_index('ix_notification_log_rule_idempotency', table_name='notification_log')
    op.drop_index('ix_notification_log_alert_rule_id', table_name='notification_log')
