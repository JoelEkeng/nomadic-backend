import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Driver(Base):
    __tablename__ = "drivers"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_drivers_user_id"),
        UniqueConstraint("license_number", name="uq_drivers_license_number"),
        CheckConstraint(
            "verification_status IN ('draft', 'submitted', 'pending_review', 'pending', 'verified', 'approved', 'rejected')",
            name="ck_drivers_verification_status",
        ),
        CheckConstraint(
            "availability_status IN ('available', 'unavailable', 'busy')",
            name="ck_drivers_availability_status",
        ),
        CheckConstraint("rating >= 0 AND rating <= 5", name="ck_drivers_rating_range"),
        CheckConstraint("total_trips >= 0", name="ck_drivers_total_trips_non_negative"),
        CheckConstraint(
            "cancellation_rate >= 0 AND cancellation_rate <= 100",
            name="ck_drivers_cancellation_rate_range",
        ),
        CheckConstraint(
            "acceptance_rate >= 0 AND acceptance_rate <= 100",
            name="ck_drivers_acceptance_rate_range",
        ),
        CheckConstraint("earnings >= 0", name="ck_drivers_earnings_non_negative"),
        Index("ix_drivers_user_id", "user_id"),
        Index("ix_drivers_license_number", "license_number"),
        Index("ix_drivers_verification_status", "verification_status"),
        Index("ix_drivers_availability_online", "availability_status", "online_status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    license_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    license_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft"
    )
    availability_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unavailable", server_default="unavailable"
    )
    online_status: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    current_vehicle_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    rating: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    total_trips: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cancellation_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    acceptance_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    earnings: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    vehicles: Mapped[list["Vehicle"]] = relationship(
        back_populates="driver",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
