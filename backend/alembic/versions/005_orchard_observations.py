"""Orchard ground-truth observations table

Revision ID: 005_orchard_observations
Revises: 004_pii_masking
Create Date: 2026-10-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '005_orchard_observations'
down_revision: Union[str, None] = '004_pii_masking'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'orchard_observations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('orchard_id', UUID(as_uuid=True), sa.ForeignKey('orchards.id', ondelete='CASCADE'), nullable=False),
        sa.Column('observation_date', sa.Date(), nullable=False),
        sa.Column('phenological_stage', sa.String(64), nullable=False),
        sa.Column('min_temp_observed_c', sa.Float(), nullable=True),
        sa.Column('damage_observed_fa', sa.Text(), nullable=True),
        sa.Column('damage_severity', sa.String(32), nullable=False, server_default='none'),
        sa.Column('notes_fa', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_orchard_observations_orchard_id', 'orchard_observations', ['orchard_id'])
    op.create_index('ix_orchard_observations_date', 'orchard_observations', ['observation_date'])
    op.create_index('ix_orchard_observations_severity', 'orchard_observations', ['damage_severity'])
    op.create_index('ix_orchard_observations_orchard_date', 'orchard_observations', ['orchard_id', 'observation_date'])


def downgrade() -> None:
    op.drop_table('orchard_observations')
