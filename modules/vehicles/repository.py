from typing import Any

from sqlalchemy.orm import Session

from modules.vehicles.models import Vehicle


class VehicleRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, driver_id: str, data: dict[str, Any]) -> Vehicle:
        vehicle = Vehicle(driver_id=driver_id, **data)
        self.db.add(vehicle)
        self.db.commit()
        self.db.refresh(vehicle)
        return vehicle

    def list_by_driver_id(self, driver_id: str) -> list[Vehicle]:
        return (
            self.db.query(Vehicle)
            .filter(Vehicle.driver_id == driver_id)
            .order_by(Vehicle.created_at.desc())
            .all()
        )

    def list_all(
        self,
        inspection_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Vehicle]:
        query = self.db.query(Vehicle)
        if inspection_status is not None:
            query = query.filter(Vehicle.inspection_status == inspection_status)
        return (
            query.order_by(Vehicle.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_by_id(self, vehicle_id: str) -> Vehicle | None:
        return self.db.query(Vehicle).filter(Vehicle.id == vehicle_id).one_or_none()

    def get_by_driver_id_and_id(self, driver_id: str, vehicle_id: str) -> Vehicle | None:
        return (
            self.db.query(Vehicle)
            .filter(Vehicle.driver_id == driver_id, Vehicle.id == vehicle_id)
            .one_or_none()
        )

    def has_approved_vehicle(self, driver_id: str) -> bool:
        return (
            self.db.query(Vehicle.id)
            .filter(
                Vehicle.driver_id == driver_id,
                Vehicle.inspection_status == "approved",
            )
            .first()
            is not None
        )

    def update(self, vehicle: Vehicle, data: dict[str, Any]) -> Vehicle:
        for field, value in data.items():
            setattr(vehicle, field, value)
        self.db.commit()
        self.db.refresh(vehicle)
        return vehicle

    def delete(self, vehicle: Vehicle) -> None:
        self.db.delete(vehicle)
        self.db.commit()
