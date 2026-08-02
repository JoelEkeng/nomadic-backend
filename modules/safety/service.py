import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from modules.drivers.repository import DriverRepository
from modules.rides.models import Ride
from modules.rides.repository import RideRepository
from modules.safety.models import EmergencyAlert, SafetyReport, TripShareToken
from modules.safety.notifications import (
    EmergencyNotification,
    NoopSafetyNotificationService,
    SafetyNotificationService,
)
from modules.safety.repository import (
    EmergencyAlertRepository,
    SafetyReportRepository,
    TripShareTokenRepository,
)
from modules.safety.schemas import (
    EmergencyAlertCreate,
    SafetyReportCreate,
    SharedTripPublic,
    TripShareCreate,
    TripShareResponse,
)
from modules.vehicles.repository import VehicleRepository


SHARE_TOKEN_LENGTH = 16
SHARE_EXPIRY_HOURS = 12
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")


class SafetyError(Exception):
    pass


class RideNotFoundError(SafetyError):
    pass


class ShareTokenExpiredError(SafetyError):
    pass


class ShareTokenNotFoundError(SafetyError):
    pass


class ReportNotFoundError(SafetyError):
    pass


class SafetyService:
    def __init__(
        self,
        alert_repository: EmergencyAlertRepository,
        share_repository: TripShareTokenRepository,
        report_repository: SafetyReportRepository,
        ride_repository: RideRepository,
        driver_repository: DriverRepository,
        vehicle_repository: VehicleRepository,
        notification_service: SafetyNotificationService | None = None,
    ):
        self.alert_repository = alert_repository
        self.share_repository = share_repository
        self.report_repository = report_repository
        self.ride_repository = ride_repository
        self.driver_repository = driver_repository
        self.vehicle_repository = vehicle_repository
        self.notification_service = notification_service or NoopSafetyNotificationService()

    # ─── Emergency ────────────────────────────────────────────────────────────

    def create_emergency_alert(
        self, user_id: str, payload: EmergencyAlertCreate, user_name: str | None = None
    ) -> EmergencyAlert:
        driver_id = None
        if payload.ride_id:
            ride = self.ride_repository.get_by_id(payload.ride_id)
            if ride:
                driver_id = ride.driver_id

        alert = self.alert_repository.create(
            {
                "user_id": user_id,
                "ride_id": payload.ride_id,
                "driver_id": driver_id,
                "alert_type": payload.alert_type,
                "latitude": payload.latitude,
                "longitude": payload.longitude,
                "message": payload.message,
                "status": "active",
            }
        )

        # Fire notifications
        notification = EmergencyNotification(
            user_id=user_id,
            user_name=user_name,
            alert_id=alert.id,
            alert_type=alert.alert_type,
            latitude=alert.latitude,
            longitude=alert.longitude,
            ride_id=alert.ride_id,
            message=alert.message,
        )
        self.notification_service.notify_emergency(notification)

        return alert

    def get_user_alerts(self, user_id: str) -> list[EmergencyAlert]:
        return self.alert_repository.list_for_user(user_id)

    def resolve_alert(self, alert_id: str) -> EmergencyAlert:
        alert = self.alert_repository.get_by_id(alert_id)
        if alert is None:
            raise SafetyError("Alert not found")
        return self.alert_repository.resolve(alert)

    # ─── Trip Sharing ─────────────────────────────────────────────────────────

    def create_trip_share(self, user_id: str, payload: TripShareCreate) -> TripShareResponse:
        ride = self.ride_repository.get_by_id(payload.ride_id)
        if ride is None:
            raise RideNotFoundError("Ride not found")

        # Reuse existing active token for this ride
        existing = self.share_repository.get_by_ride(payload.ride_id, user_id)
        if existing and existing.expires_at > datetime.now(timezone.utc):
            return self._build_share_response(existing, ride)

        token = secrets.token_urlsafe(SHARE_TOKEN_LENGTH)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=SHARE_EXPIRY_HOURS)

        share = self.share_repository.create(
            {
                "ride_id": payload.ride_id,
                "user_id": user_id,
                "token": token,
                "expires_at": expires_at,
            }
        )

        return self._build_share_response(share, ride)

    def get_shared_trip(self, token: str) -> SharedTripPublic:
        share = self.share_repository.get_by_token(token)
        if share is None:
            raise ShareTokenNotFoundError("Share link not found or expired")

        if share.expires_at < datetime.now(timezone.utc):
            raise ShareTokenExpiredError("Share link has expired")

        ride = self.ride_repository.get_by_id(share.ride_id)
        if ride is None:
            raise RideNotFoundError("Ride not found")

        # If ride is completed, deactivate shares
        if ride.status in ("COMPLETED", "CANCELLED"):
            self.share_repository.deactivate_for_ride(ride.id)

        return self._build_public_trip(ride)

    def deactivate_shares_for_ride(self, ride_id: str) -> int:
        return self.share_repository.deactivate_for_ride(ride_id)

    # ─── Safety Reports ───────────────────────────────────────────────────────

    def create_report(self, user_id: str, payload: SafetyReportCreate) -> SafetyReport:
        driver_id = None
        if payload.ride_id:
            ride = self.ride_repository.get_by_id(payload.ride_id)
            if ride:
                driver_id = ride.driver_id

        report = self.report_repository.create(
            {
                "user_id": user_id,
                "ride_id": payload.ride_id,
                "driver_id": driver_id,
                "category": payload.category,
                "description": payload.description,
                "attachments": payload.attachments,
                "latitude": payload.latitude,
                "longitude": payload.longitude,
            }
        )

        self.notification_service.notify_report_received(report.id, user_id)
        return report

    def get_user_reports(self, user_id: str) -> list[SafetyReport]:
        return self.report_repository.list_for_user(user_id)

    def get_all_reports(self, status: str | None = None, limit: int = 50, offset: int = 0) -> list[SafetyReport]:
        return self.report_repository.list_all(status, limit, offset)

    def update_report_status(self, report_id: str, new_status: str) -> SafetyReport:
        report = self.report_repository.get_by_id(report_id)
        if report is None:
            raise ReportNotFoundError("Report not found")
        return self.report_repository.update_status(report, new_status)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _build_share_response(self, share: TripShareToken, ride: Ride) -> TripShareResponse:
        share_url = f"{FRONTEND_BASE_URL}/share/{share.token}"
        whatsapp_msg = self._build_whatsapp_message(ride, share_url)
        whatsapp_url = f"https://wa.me/?text={quote(whatsapp_msg)}"

        return TripShareResponse(
            id=share.id,
            ride_id=share.ride_id,
            token=share.token,
            share_url=share_url,
            whatsapp_url=whatsapp_url,
            expires_at=share.expires_at,
            created_at=share.created_at,
        )

    def _build_whatsapp_message(self, ride: Ride, share_url: str) -> str:
        driver_name = "Unknown"
        vehicle_info = ""
        plate_info = ""

        if ride.driver_id:
            driver = self.driver_repository.get_by_id(ride.driver_id)
            if driver:
                driver_name = f"Driver #{driver.id[:8]}"
                vehicles = self.vehicle_repository.list_by_driver_id(driver.id)
                if vehicles:
                    v = vehicles[0]
                    vehicle_info = f"\nVehicle: {v.make} {v.model}"
                    plate_info = f"\nPlate: {v.plate_number}"

        return (
            f"Hi! I'm currently on a ride.\n\n"
            f"Driver: {driver_name}{vehicle_info}{plate_info}\n\n"
            f"Track my trip live:\n{share_url}"
        )

    def _build_public_trip(self, ride: Ride) -> SharedTripPublic:
        driver_name = None
        driver_photo = None
        driver_phone = None
        vehicle_make = None
        vehicle_model = None
        vehicle_color = None
        license_plate = None

        if ride.driver_id:
            driver = self.driver_repository.get_by_id(ride.driver_id)
            if driver:
                driver_name = f"Driver #{driver.id[:8]}"
                driver_phone = driver.phone_number
                vehicles = self.vehicle_repository.list_by_driver_id(driver.id)
                if vehicles:
                    v = vehicles[0]
                    vehicle_make = v.make
                    vehicle_model = v.model
                    vehicle_color = v.color
                    license_plate = v.plate_number

        return SharedTripPublic(
            student_first_name=None,  # Privacy: only first name if user profile available
            driver_name=driver_name,
            driver_photo=driver_photo,
            driver_phone=driver_phone,
            vehicle_make=vehicle_make,
            vehicle_model=vehicle_model,
            vehicle_color=vehicle_color,
            license_plate=license_plate,
            pickup=ride.pickup_location,
            destination=ride.destination_location,
            status=ride.status,
            estimated_arrival=None,
            driver_latitude=None,
            driver_longitude=None,
            created_at=ride.requested_at,
        )
