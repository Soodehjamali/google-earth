"""PII compliance: mask recipient in notification_log and document alert_rules.recipient

Revision ID: 004_pii_masking
Revises: 003_rule_idempotency
Create Date: 2026-10-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '004_pii_masking'
down_revision: Union[str, None] = '003_rule_idempotency'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update existing notification_log records to ensure recipient is masked (PII scrub)
    # Masks non-masked strings (phone numbers or emails)
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        op.execute(
            """
            UPDATE notification_log
            SET recipient = CASE
                WHEN recipient LIKE '%@%' THEN
                    substr(split_part(recipient, '@', 1), 1, 2) || '***@' || split_part(recipient, '@', 2)
                WHEN length(recipient) > 6 THEN
                    substr(recipient, 1, 4) || '***' || substr(recipient, length(recipient) - 1, 2)
                ELSE '***'
            END
            WHERE recipient NOT LIKE '%***%';
            """
        )
        op.alter_column(
            'notification_log',
            'recipient',
            comment="Masked recipient identifier (PII-scrubbed, e.g. +989***89). Raw phone/email never stored in logs."
        )
        op.alter_column(
            'alert_rules',
            'recipient',
            comment="Raw delivery destination (phone number/email). Kept for outbound routing; access restricted."
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == 'postgresql':
        op.alter_column('notification_log', 'recipient', comment=None)
        op.alter_column('alert_rules', 'recipient', comment=None)
