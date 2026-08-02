from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from core.verification import VerificationService
from modules.drivers.models import Driver
from modules.drivers.repository import DriverRepository
from modules.matching.schemas import MatchRequest
from modules.matching.service import (
    DriverAssignmentError,
    MatchingService,
    NoMatchingDriversError,
)
from modules.rides.models import Ride
from modules.rides.notifications import (
    NoopRideNotificationPublisher,
    RideNotificationPublisher,
)
from modules.rides.pricing import PricingService, SimplePricingService
from modules.rides.repository import RideRepository
from modules.rides.schemas import RideCompleteRequest, RideCreate
from modules.students.models import Student
from modules.students.repository import StudentRepository
from modules.vehicles.repository import VehicleRepository


class RideError(Exception):
    pass


class RideNotFoundError(RideError):
    pass


class RideConflictError(RideError):
    pass


class RideForbiddenError(RideError):
    pass


class InvalidRideTransitionError(RideError):
    pass


class RideMatchingUnavailableError(RideError):
    pass


class RideService:
    def __init__(
        self,
        repository: RideRepository,
        student_repository: StudentRepository,
        driver_repository: DriverRepository,
        vehicle_repository: VehicleRepository,
        matching_service: MatchingService,
        pricing_service: PricingService | None = None,
        notification_publisher: RideNotificationPublisher | None = None,
        verification_service: VerificationService | None = None,
    ):
        self.repository = repository
        self.student_repository = student_repository
        self.driver_repository = driver_repository
        self.vehicle_repository = vehicle_repository
        self.matching_service = matching_service
        # Verification rules live in one place; never re-implement them here.
        self.verification_service = verification_service or VerificationService(
            repository.db,
            student_repository=student_repository,
            driver_repository=driver_repository,
            vehicle_repository=vehicle_repository,
        )
        self.pricing_service = pricing_service or SimplePricingService()
        self.notification_publisher = (
            notification_publisher or NoopRideNotificationPublisher()
        )

    async def create_ride(self, user_id: str, payload: RideCreate) -> Ride:
        student = self._get_verified_student(user_id)
        estimate = self.pricing_service.estimate_fare(
            payload.pickup_location,
            payload.destination_location,
        )

        ride = self.repository.create(
            {
                "student_id": student.id,
                "pickup_location": payload.pickup_location.address,
                "destination_location": payload.destination_location.address,
                "distance": estimate.distance_km,
                "estimated_fare": estimate.estimated_fare,
                "status": "REQUESTED",
            }
        )
        self.repository.set_matching(ride)

        try:
            assignment = await self.matching_service.assign_driver(
                MatchRequest(
                    request_id=ride.id,
                    pickup=payload.pickup_location.to_geo_point(),
                    destination=payload.destination_location.to_geo_point(),
                    vehicle_type=payload.vehicle_type,
                )
            )
        except NoMatchingDriversError:
            self.repository.db.commit()
            self.repository.db.refresh(ride)
            self.notification_publisher.ride_requested(ride)
            return ride
        except DriverAssignmentError as exc:
            self.repository.db.rollback()
            raise RideMatchingUnavailableError(
                "Matching drivers are already assigned"
            ) from exc

        ride = self.repository.assign_driver(ride, assignment["assigned_driver_id"])
        self._set_driver_availability(ride.driver_id, "busy")

        try:
            self.repository.db.commit()
        except IntegrityError as exc:
            self.repository.db.rollback()
            self._release_driver(ride.driver_id)
            raise RideConflictError("Ride could not be created") from exc

        self.repository.db.refresh(ride)
        self.notification_publisher.ride_requested(ride)
        self.notification_publisher.driver_assigned(ride)
        return ride

    def cancel_ride(self, user_id: str, ride_id: str) -> Ride:
        ride = self._get_locked_ride(ride_id)
        self._ensure_can_cancel(user_id, ride)
        if ride.status in {"COMPLETED", "CANCELLED"}:
            raise InvalidRideTransitionError("Ride cannot be cancelled")

        driver_id = ride.driver_id
        ride = self.repository.cancel(ride)
        if driver_id is not None:
            self._set_driver_availability(driver_id, "available")

        self.repository.db.commit()
        self.repository.db.refresh(ride)
        self._release_driver(driver_id)
        self.notification_publisher.ride_cancelled(ride)
        return ride

    def accept_ride(self, user_id: str, ride_id: str) -> Ride:
        driver = self._get_verified_driver(user_id)
        ride = self._get_locked_ride(ride_id)
        self._ensure_assigned_driver(driver, ride)
        if ride.status != "MATCHING":
            raise InvalidRideTransitionError("Ride can only be accepted from MATCHING")

        ride = self.repository.accept(ride)
        self._set_driver_availability(driver.id, "busy")
        self.repository.db.commit()
        self.repository.db.refresh(ride)
        self.notification_publisher.ride_accepted(ride)
        return ride

    def start_ride(self, user_id: str, ride_id: str) -> Ride:
        driver = self._get_verified_driver(user_id)
        ride = self._get_locked_ride(ride_id)
        self._ensure_assigned_driver(driver, ride)
        if ride.status not in {"ACCEPTED", "ARRIVING"}:
            raise InvalidRideTransitionError(
                "Ride can only be started after it is accepted"
            )

        ride = self.repository.start(ride)
        self.repository.db.commit()
        self.repository.db.refresh(ride)
        self.notification_publisher.ride_started(ride)
        return ride

    def mark_arriving(self, user_id: str, ride_id: str) -> Ride:
        driver = self._get_verified_driver(user_id)
        ride = self._get_locked_ride(ride_id)
        self._ensure_assigned_driver(driver, ride)
        if ride.status != "ACCEPTED":
            raise InvalidRideTransitionError(
                "Ride can only move to ARRIVING after it is accepted"
            )

        ride = self.repository.mark_arriving(ride)
        self.repository.db.commit()
        self.repository.db.refresh(ride)
        return ride

    def complete_ride(
        self, user_id: str, ride_id: str, payload: RideCompleteRequest
    ) -> Ride:
        driver = self._get_verified_driver(user_id)
        ride = self._get_locked_ride(ride_id)
        self._ensure_assigned_driver(driver, ride)
        if ride.status != "STARTED":
            raise InvalidRideTransitionError("Ride can only be completed after start")

        final_fare = payload.final_fare or ride.estimated_fare
        ride = self.repository.complete(ride, final_fare)
        self._complete_driver_trip(driver, final_fare)
        self.repository.db.commit()
        self.repository.db.refresh(ride)
        self._release_driver(driver.id)
        self.notification_publisher.ride_completed(ride)
        return ride

    def get_ride_history(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[Ride]:
        student = self.student_repository.get_by_user_id(user_id)
        if student is not None:
            return self.repository.list_for_student(student.id, limit, offset)

        driver = self.driver_repository.get_by_user_id(user_id)
        if driver is not None:
            return self.repository.list_for_driver(driver.id, limit, offset)

        # An authenticated user who has not created a rider or driver profile yet
        # simply has no rides. That is an empty result, not a permission failure.
        return []

    def _get_verified_student(self, user_id: str) -> Student:
        """Delegates to the centralised guard, raising ``VerificationRequiredError``."""
        return self.verification_service.require_verified_student(user_id)

    def _get_verified_driver(self, user_id: str) -> Driver:
        """Delegates to the centralised guard, raising ``VerificationRequiredError``."""
        return self.verification_service.require_verified_driver(user_id)

    def _get_locked_ride(self, ride_id: str) -> Ride:
        ride = self.repository.get_for_update(ride_id)
        if ride is None:
            raise RideNotFoundError("Ride not found")
        return ride

    def _ensure_assigned_driver(self, driver: Driver, ride: Ride) -> None:
        if ride.driver_id != driver.id:
            raise RideForbiddenError("Ride is not assigned to this driver")

    def _ensure_can_cancel(self, user_id: str, ride: Ride) -> None:
        student = self.student_repository.get_by_user_id(user_id)
        if student is not None and student.id == ride.student_id:
            return

        driver = self.driver_repository.get_by_user_id(user_id)
        if driver is not None and driver.id == ride.driver_id:
            return

        raise RideForbiddenError("Ride cannot be cancelled by this user")

    def _set_driver_availability(self, driver_id: str | None, status: str) -> None:
        if driver_id is None:
            return
        driver = self.driver_repository.get_by_id(driver_id)
        if driver is None:
            return
        driver.availability_status = status
        driver.online_status = status == "available"
        self.repository.db.flush()

    def _complete_driver_trip(self, driver: Driver, final_fare: Decimal) -> None:
        driver.total_trips += 1
        driver.earnings += final_fare
        driver.availability_status = "available"
        driver.online_status = True
        self.repository.db.flush()

    def _release_driver(self, driver_id: str | None) -> None:
        if driver_id is not None:
            self.matching_service.release_driver(driver_id)
