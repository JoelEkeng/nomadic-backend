import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Ride(Base):
    __tablename__ = "rides"
    __table_args__ = (
        CheckConstraint(
            "status IN ('REQUESTED', 'MATCHING', 'ACCEPTED', 'ARRIVING', 'STARTED', 'COMPLETED', 'CANCELLED')",
            name="ck_rides_status",
        ),
        CheckConstraint("distance >= 0", name="ck_rides_distance_non_negative"),
        CheckConstraint(
            "estimated_fare >= 0", name="ck_rides_estimated_fare_non_negative"
        ),
        CheckConstraint(
            "final_fare IS NULL OR final_fare >= 0",
            name="ck_rides_final_fare_non_negative",
        ),
        Index("ix_rides_student_id", "student_id"),
        Index("ix_rides_driver_id", "driver_id"),
        Index("ix_rides_status", "status"),
        Index("ix_rides_student_status", "student_id", "status"),
        Index("ix_rides_driver_status", "driver_id", "status"),
        Index("ix_rides_requested_at", "requested_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    student_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("drivers.id", ondelete="SET NULL"),
        nullable=True,
    )
    pickup_location: Mapped[str] = mapped_column(String(512), nullable=False)
    destination_location: Mapped[str] = mapped_column(String(512), nullable=False)
    distance: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    estimated_fare: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    final_fare: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="REQUESTED", server_default="REQUESTED"
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    student: Mapped["Student"] = relationship()
    driver: Mapped["Driver | None"] = relationship()
