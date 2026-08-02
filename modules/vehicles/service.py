from datetime import date

from sqlalchemy.exc import IntegrityError

from modules.drivers.models import Driver
from modules.drivers.repository import DriverRepository
from modules.vehicles.models import Vehicle
from modules.vehicles.repository import VehicleRepository
from modules.vehicles.schemas import VehicleCreate, VehicleUpdate


class VehicleError(Exception):
    pass


class VehicleNotFoundError(VehicleError):
    pass


class VehicleConflictError(VehicleError):
    pass


class VehicleAlreadyRegisteredError(VehicleError):
    pass


class VehicleInsuranceExpiredError(VehicleError):
    pass


class VehicleNotApprovedError(VehicleError):
    pass


class VehiclePermissionError(VehicleError):
    pass


class VehicleDriverNotFoundError(VehicleError):
    pass


class VehicleService:
    def __init__(
        self,
        repository: VehicleRepository,
        driver_repository: DriverRepository,
    ):
        self.repository = repository
        self.driver_repository = driver_repository

    def register_vehicle(self, user_id: str, payload: VehicleCreate) -> Vehicle:
        driver = self._get_driver(user_id)
        if self.repository.list_by_driver_id(driver.id):
            raise VehicleAlreadyRegisteredError("Driver already has a registered vehicle")
        if payload.insurance_expiry is not None:
            self._ensure_insurance_valid(payload.insurance_expiry)
        data = payload.model_dump(exclude={"plate_number", "colour"})
        data["inspection_status"] = "pending"
        try:
            vehicle = self.repository.create(driver.id, data)
            self.driver_repository.update(driver, {"current_vehicle_id": vehicle.id})
            return vehicle
        except IntegrityError as exc:
            self.repository.db.rollback()
            raise VehicleConflictError("Vehicle could not be registered") from exc

    def list_my_vehicles(self, user_id: str) -> list[Vehicle]:
        driver = self._get_driver(user_id)
        return self.repository.list_by_driver_id(driver.id)

    def get_my_vehicle(self, user_id: str, vehicle_id: str) -> Vehicle:
        driver = self._get_driver(user_id)
        vehicle = self.repository.get_by_driver_id_and_id(driver.id, vehicle_id)
        if vehicle is None:
            raise VehicleNotFoundError("Vehicle not found")
        return vehicle

    def update_my_vehicle(
        self, user_id: str, vehicle_id: str, payload: VehicleUpdate
    ) -> Vehicle:
        vehicle = self.get_my_vehicle(user_id, vehicle_id)
        data = payload.model_dump(exclude_unset=True)
        data.pop("plate_number", None)
        data.pop("colour", None)
        if "insurance_expiry" in data:
            if data["insurance_expiry"] is not None:
                self._ensure_insurance_valid(data["insurance_expiry"])
        if data:
            data["inspection_status"] = "pending"
        try:
            return self.repository.update(vehicle, data)
        except IntegrityError as exc:
            self.repository.db.rollback()
            raise VehicleConflictError("Vehicle could not be updated") from exc

    def delete_my_vehicle(self, user_id: str, vehicle_id: str) -> None:
        vehicle = self.get_my_vehicle(user_id, vehicle_id)
        self.repository.delete(vehicle)

    def list_vehicles(
        self,
        inspection_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Vehicle]:
        return self.repository.list_all(
            inspection_status=inspection_status,
            limit=limit,
            offset=offset,
        )

    def get_vehicle(self, vehicle_id: str) -> Vehicle:
        vehicle = self.repository.get_by_id(vehicle_id)
        if vehicle is None:
            raise VehicleNotFoundError("Vehicle not found")
        return vehicle

    def approve_vehicle(self, vehicle_id: str) -> Vehicle:
        vehicle = self.get_vehicle(vehicle_id)
        if vehicle.insurance_expiry is not None:
            self._ensure_insurance_valid(vehicle.insurance_expiry)
        return self.repository.update(vehicle, {"inspection_status": "approved"})

    def reject_vehicle(self, vehicle_id: str) -> Vehicle:
        vehicle = self.get_vehicle(vehicle_id)
        return self.repository.update(vehicle, {"inspection_status": "rejected"})

    def ensure_driver_has_approved_vehicle(self, driver: Driver) -> None:
        if not self.repository.has_approved_vehicle(driver.id):
            raise VehicleNotApprovedError(
                "Driver must have an approved vehicle before accepting rides"
            )

    def _get_driver(self, user_id: str) -> Driver:
        driver = self.driver_repository.get_by_user_id(user_id)
        if driver is None:
            raise VehicleDriverNotFoundError("Driver profile not found")
        return driver

    def _ensure_insurance_valid(self, insurance_expiry: date) -> None:
        if insurance_expiry < date.today():
            raise VehicleInsuranceExpiredError("Vehicle insurance has expired")
