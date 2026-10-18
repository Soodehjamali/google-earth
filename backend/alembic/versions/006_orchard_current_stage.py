"""Add current_stage and stage_updated_at to orchards table (R4)

Revision ID: 006_orchard_current_stage
Revises: 005_orchard_observations
Create Date: 2026-10-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '006_orchard_current_stage'
down_revision: Union[str, None] = '005_orchard_observations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'orchards',
        sa.Column('current_stage', sa.String(50), nullable=True)
    )
    op.add_column(
        'orchards',
        sa.Column('stage_updated_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('orchards', 'stage_updated_at')
    op.drop_column('orchards', 'current_stage')
