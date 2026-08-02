import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("registration_number", name="uq_vehicles_registration_number"),
        UniqueConstraint("driver_id", name="uq_vehicles_driver_id_mvp"),
        CheckConstraint(
            "vehicle_type IN ('car', 'van', 'motorcycle', 'bus')",
            name="ck_vehicles_vehicle_type",
        ),
        CheckConstraint(
            "inspection_status IN ('draft', 'pending', 'approved', 'rejected')",
            name="ck_vehicles_inspection_status",
        ),
        CheckConstraint("year >= 1980", name="ck_vehicles_year_min"),
        Index("ix_vehicles_driver_id", "driver_id"),
        Index("ix_vehicles_registration_number", "registration_number"),
        Index("ix_vehicles_inspection_status", "inspection_status"),
        Index("ix_vehicles_driver_status", "driver_id", "inspection_status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    driver_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("drivers.id", ondelete="CASCADE"),
        nullable=False,
    )
    registration_number: Mapped[str] = mapped_column(String(64), nullable=False)
    make: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="car", server_default="car"
    )
    capacity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4, server_default="4"
    )
    insurance_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    registration_document: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    insurance_document: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    roadworthy_document: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    inspection_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
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
    driver: Mapped["Driver"] = relationship(back_populates="vehicles")
