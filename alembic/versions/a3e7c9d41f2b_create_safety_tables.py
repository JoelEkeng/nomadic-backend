"""create_safety_tables

Revision ID: a3e7c9d41f2b
Revises: 665b1ddfc3b6
Create Date: 2026-08-02 14:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3e7c9d41f2b'
down_revision: Union[str, None] = '665b1ddfc3b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Emergency Alerts
    op.create_table(
        'emergency_alerts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(255), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ride_id', sa.String(36), sa.ForeignKey('rides.id', ondelete='SET NULL'), nullable=True),
        sa.Column('driver_id', sa.String(36), sa.ForeignKey('drivers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('alert_type', sa.String(32), nullable=False, server_default='general'),
        sa.Column('latitude', sa.Float, nullable=True),
        sa.Column('longitude', sa.Float, nullable=True),
        sa.Column('message', sa.Text, nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='active'),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "alert_type IN ('campus_security', 'police', 'live_location', 'general')",
            name='ck_emergency_alerts_type',
        ),
        sa.CheckConstraint(
            "status IN ('active', 'acknowledged', 'resolved', 'cancelled')",
            name='ck_emergency_alerts_status',
        ),
    )
    op.create_index('ix_emergency_alerts_user_id', 'emergency_alerts', ['user_id'])
    op.create_index('ix_emergency_alerts_ride_id', 'emergency_alerts', ['ride_id'])
    op.create_index('ix_emergency_alerts_status', 'emergency_alerts', ['status'])
    op.create_index('ix_emergency_alerts_created_at', 'emergency_alerts', ['created_at'])

    # Trip Share Tokens
    op.create_table(
        'trip_share_tokens',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('ride_id', sa.String(36), sa.ForeignKey('rides.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(255), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.String(64), nullable=False, unique=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_trip_share_tokens_token', 'trip_share_tokens', ['token'], unique=True)
    op.create_index('ix_trip_share_tokens_ride_id', 'trip_share_tokens', ['ride_id'])
    op.create_index('ix_trip_share_tokens_user_id', 'trip_share_tokens', ['user_id'])

    # Safety Reports
    op.create_table(
        'safety_reports',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(255), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ride_id', sa.String(36), sa.ForeignKey('rides.id', ondelete='SET NULL'), nullable=True),
        sa.Column('driver_id', sa.String(36), sa.ForeignKey('drivers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('category', sa.String(32), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('attachments', sa.Text, nullable=True),
        sa.Column('latitude', sa.Float, nullable=True),
        sa.Column('longitude', sa.Float, nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('is_deleted', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "category IN ('unsafe_driving', 'driver_misconduct', 'vehicle_issue', "
            "'wrong_route', 'harassment', 'accident', 'other')",
            name='ck_safety_reports_category',
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'investigating', 'resolved', 'dismissed')",
            name='ck_safety_reports_status',
        ),
    )
    op.create_index('ix_safety_reports_user_id', 'safety_reports', ['user_id'])
    op.create_index('ix_safety_reports_ride_id', 'safety_reports', ['ride_id'])
    op.create_index('ix_safety_reports_status', 'safety_reports', ['status'])
    op.create_index('ix_safety_reports_created_at', 'safety_reports', ['created_at'])


def downgrade() -> None:
    op.drop_table('safety_reports')
    op.drop_table('trip_share_tokens')
    op.drop_table('emergency_alerts')
