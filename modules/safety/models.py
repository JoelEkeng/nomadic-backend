import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class EmergencyAlert(Base):
    __tablename__ = "emergency_alerts"
    __table_args__ = (
        CheckConstraint(
            "alert_type IN ('campus_security', 'police', 'live_location', 'general')",
            name="ck_emergency_alerts_type",
        ),
        CheckConstraint(
            "status IN ('active', 'acknowledged', 'resolved', 'cancelled')",
            name="ck_emergency_alerts_status",
        ),
        Index("ix_emergency_alerts_user_id", "user_id"),
        Index("ix_emergency_alerts_ride_id", "ride_id"),
        Index("ix_emergency_alerts_status", "status"),
        Index("ix_emergency_alerts_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    ride_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rides.id", ondelete="SET NULL"), nullable=True
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True
    )
    alert_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="general"
    )
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TripShareToken(Base):
    __tablename__ = "trip_share_tokens"
    __table_args__ = (
        Index("ix_trip_share_tokens_token", "token", unique=True),
        Index("ix_trip_share_tokens_ride_id", "ride_id"),
        Index("ix_trip_share_tokens_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rides.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SafetyReport(Base):
    __tablename__ = "safety_reports"
    __table_args__ = (
        CheckConstraint(
            "category IN ('unsafe_driving', 'driver_misconduct', 'vehicle_issue', "
            "'wrong_route', 'harassment', 'accident', 'other')",
            name="ck_safety_reports_category",
        ),
        CheckConstraint(
            "status IN ('pending', 'investigating', 'resolved', 'dismissed')",
            name="ck_safety_reports_status",
        ),
        Index("ix_safety_reports_user_id", "user_id"),
        Index("ix_safety_reports_ride_id", "ride_id"),
        Index("ix_safety_reports_status", "status"),
        Index("ix_safety_reports_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    ride_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rides.id", ondelete="SET NULL"), nullable=True
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON array of URLs
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
