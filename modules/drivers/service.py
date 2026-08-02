from datetime import date
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from core.verification import VerificationService
from modules.drivers.models import Driver
from modules.drivers.repository import DriverRepository
from modules.drivers.schemas import DriverAvailabilityUpdate, DriverOnboardingCreate
from modules.vehicles.repository import VehicleRepository
from modules.vehicles.service import VehicleNotApprovedError, VehicleService


class DriverAvailabilityPublisher(Protocol):
    def publish_availability_changed(self, driver: Driver) -> None:
        pass


class NoopDriverAvailabilityPublisher:
    def publish_availability_changed(self, driver: Driver) -> None:
        return None


class DriverError(Exception):
    pass


class DriverAlreadyExistsError(DriverError):
    pass


class DriverNotFoundError(DriverError):
    pass


class DriverConflictError(DriverError):
    pass


class DriverNotVerifiedError(DriverError):
    pass


class DriverLicenseExpiredError(DriverError):
    pass


class DriverService:
    def __init__(
        self,
        repository: DriverRepository,
        availability_publisher: DriverAvailabilityPublisher | None = None,
        vehicle_service: VehicleService | None = None,
        verification_service: VerificationService | None = None,
    ):
        self.repository = repository
        self.availability_publisher = (
            availability_publisher or NoopDriverAvailabilityPublisher()
        )
        self.vehicle_service = vehicle_service or VehicleService(
            VehicleRepository(repository.db), repository
        )
        # Verification rules live in one place; never re-implement them here.
        self.verification_service = verification_service or VerificationService(
            repository.db,
            driver_repository=repository,
        )

    def complete_onboarding(
        self, user_id: str, payload: DriverOnboardingCreate
    ) -> Driver:
        if self.repository.get_by_user_id(user_id):
            raise DriverAlreadyExistsError("Driver profile already exists")
        if payload.license_expiry is not None and payload.license_expiry < date.today():
            raise DriverLicenseExpiredError("Driver license has expired")
        try:
            return self.repository.create(user_id, payload.model_dump())
        except IntegrityError as exc:
            self.repository.db.rollback()
            raise DriverConflictError("Driver profile could not be created") from exc

    def get_profile(self, user_id: str) -> Driver:
        driver = self.repository.get_by_user_id(user_id)
        if driver is None:
            raise DriverNotFoundError("Driver profile not found")
        return driver

    def go_online(self, user_id: str) -> Driver:
        driver = self._require_verified(user_id)
        updated_driver = self.repository.update(
            driver,
            {"online_status": True, "availability_status": "available"},
        )
        self.availability_publisher.publish_availability_changed(updated_driver)
        return updated_driver

    def go_offline(self, user_id: str) -> Driver:
        driver = self.get_profile(user_id)
        updated_driver = self.repository.update(
            driver,
            {"online_status": False, "availability_status": "unavailable"},
        )
        self.availability_publisher.publish_availability_changed(updated_driver)
        return updated_driver

    def update_availability(
        self, user_id: str, payload: DriverAvailabilityUpdate
    ) -> Driver:
        if payload.availability_status == "available":
            driver = self._require_verified(user_id)
        else:
            driver = self.get_profile(user_id)
        updated_driver = self.repository.update(
            driver,
            {"availability_status": payload.availability_status},
        )
        self.availability_publisher.publish_availability_changed(updated_driver)
        return updated_driver

    def view_earnings(self, user_id: str) -> Driver:
        return self.get_profile(user_id)

    def view_performance(self, user_id: str) -> Driver:
        return self.get_profile(user_id)

    def _require_verified(self, user_id: str) -> Driver:
        """Delegates to the centralised guard.

        Raises ``VerificationRequiredError`` (rendered as the standard 403
        onboarding payload) when the driver has not finished registration.
        """
        self.get_profile(user_id)  # preserves the 404 for a missing profile
        return self.verification_service.require_verified_driver(user_id)
