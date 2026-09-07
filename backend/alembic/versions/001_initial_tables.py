"""Initial tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-09-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Locations table
    op.create_table(
        'locations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('geometry', JSONB, nullable=False),
        sa.Column('latitude', sa.Float, nullable=True),
        sa.Column('longitude', sa.Float, nullable=True),
        sa.Column('area_sq_meters', sa.Float, nullable=True),
        sa.Column('centroid_lat', sa.Float, nullable=True),
        sa.Column('centroid_lng', sa.Float, nullable=True),
        sa.Column('geometry_type', sa.String(50), nullable=False, server_default='Point'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Analyses table
    op.create_table(
        'analyses',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('location_id', UUID(as_uuid=True), sa.ForeignKey('locations.id'), nullable=False),
        sa.Column('start_date', sa.String(10), nullable=False),
        sa.Column('end_date', sa.String(10), nullable=False),
        sa.Column('analysis_type', sa.String(50), nullable=False, server_default='complete'),
        sa.Column('temporal_resolution', sa.String(20), nullable=False, server_default='monthly'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('result_data', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Dataset usages table
    op.create_table(
        'dataset_usages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('analysis_id', UUID(as_uuid=True), sa.ForeignKey('analyses.id'), nullable=False),
        sa.Column('dataset_id', sa.String(255), nullable=False),
        sa.Column('variable', sa.String(100), nullable=False),
        sa.Column('resolution', sa.String(50), nullable=True),
        sa.Column('date_range', JSONB, nullable=True),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Time series table
    op.create_table(
        'timeseries',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('analysis_id', UUID(as_uuid=True), sa.ForeignKey('analyses.id'), nullable=False),
        sa.Column('date', sa.Date, nullable=False),
        sa.Column('variable', sa.String(100), nullable=False),
        sa.Column('value', sa.Float, nullable=False),
        sa.Column('metadata', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Reports table
    op.create_table(
        'reports',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('analysis_id', UUID(as_uuid=True), sa.ForeignKey('analyses.id'), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=True),
        sa.Column('report_type', sa.String(50), nullable=False, server_default='pdf'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Indexes
    op.create_index('ix_locations_created_at', 'locations', ['created_at'])
    op.create_index('ix_analyses_location_id', 'analyses', ['location_id'])
    op.create_index('ix_analyses_status', 'analyses', ['status'])
    op.create_index('ix_analyses_created_at', 'analyses', ['created_at'])
    op.create_index('ix_dataset_usages_analysis_id', 'dataset_usages', ['analysis_id'])
    op.create_index('ix_timeseries_analysis_id', 'timeseries', ['analysis_id'])
    op.create_index('ix_timeseries_date', 'timeseries', ['date'])
    op.create_index('ix_reports_analysis_id', 'reports', ['analysis_id'])


def downgrade() -> None:
    op.drop_table('reports')
    op.drop_table('timeseries')
    op.drop_table('dataset_usages')
    op.drop_table('analyses')
    op.drop_table('locations')
