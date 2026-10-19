"""Add archived_at to orchards table for soft delete (S5, T7)

Revision ID: 007_orchard_archived_at
Revises: 006_orchard_current_stage
Create Date: 2026-10-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '007_orchard_archived_at'
down_revision: Union[str, None] = '006_orchard_current_stage'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'orchards',
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        'ix_orchards_archived_at',
        'orchards',
        ['archived_at'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_orchards_archived_at', table_name='orchards')
    op.drop_column('orchards', 'archived_at')
