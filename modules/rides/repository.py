from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from modules.rides.models import Ride


class RideRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict[str, Any]) -> Ride:
        ride = Ride(**data)
        self.db.add(ride)
        self.db.flush()
        self.db.refresh(ride)
        return ride

    def get_by_id(self, ride_id: str) -> Ride | None:
        return self.db.query(Ride).filter(Ride.id == ride_id).one_or_none()

    def get_for_update(self, ride_id: str) -> Ride | None:
        return (
            self.db.query(Ride)
            .filter(Ride.id == ride_id)
            .with_for_update()
            .one_or_none()
        )

    def list_for_student(
        self, student_id: str, limit: int = 50, offset: int = 0
    ) -> list[Ride]:
        return (
            self.db.query(Ride)
            .filter(Ride.student_id == student_id)
            .order_by(Ride.requested_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def list_for_driver(
        self, driver_id: str, limit: int = 50, offset: int = 0
    ) -> list[Ride]:
        return (
            self.db.query(Ride)
            .filter(Ride.driver_id == driver_id)
            .order_by(Ride.requested_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def set_matching(self, ride: Ride) -> Ride:
        ride.status = "MATCHING"
        self.db.flush()
        self.db.refresh(ride)
        return ride

    def assign_driver(self, ride: Ride, driver_id: str) -> Ride:
        ride.driver_id = driver_id
        self.db.flush()
        self.db.refresh(ride)
        return ride

    def accept(self, ride: Ride) -> Ride:
        ride.status = "ACCEPTED"
        ride.accepted_at = datetime.now(timezone.utc)
        self.db.flush()
        self.db.refresh(ride)
        return ride

    def mark_arriving(self, ride: Ride) -> Ride:
        ride.status = "ARRIVING"
        self.db.flush()
        self.db.refresh(ride)
        return ride

    def start(self, ride: Ride) -> Ride:
        ride.status = "STARTED"
        ride.started_at = datetime.now(timezone.utc)
        self.db.flush()
        self.db.refresh(ride)
        return ride

    def complete(self, ride: Ride, final_fare: Decimal) -> Ride:
        ride.status = "COMPLETED"
        ride.final_fare = final_fare
        ride.completed_at = datetime.now(timezone.utc)
        self.db.flush()
        self.db.refresh(ride)
        return ride

    def cancel(self, ride: Ride) -> Ride:
        ride.status = "CANCELLED"
        ride.cancelled_at = datetime.now(timezone.utc)
        self.db.flush()
        self.db.refresh(ride)
        return ride

    def get_active_for_driver(self, driver_id: str) -> Ride | None:
        """Get the currently active ride for a driver (ACCEPTED, ARRIVING, or STARTED)."""
        return (
            self.db.query(Ride)
            .filter(
                Ride.driver_id == driver_id,
                Ride.status.in_(["ACCEPTED", "ARRIVING", "STARTED"]),
            )
            .order_by(Ride.requested_at.desc())
            .first()
        )
