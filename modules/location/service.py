from datetime import datetime, timedelta, timezone

from modules.drivers.models import Driver
from modules.drivers.repository import DriverRepository
from modules.location.schemas import DriverLocationUpdate
from modules.location.store import LocationStore


class LocationError(Exception):
    pass


class LocationDriverNotFoundError(LocationError):
    pass


class LocationDriverUnavailableError(LocationError):
    pass


class LocationService:
    def __init__(
        self,
        driver_repository: DriverRepository,
        store: LocationStore,
        location_ttl_seconds: int = 90,
    ):
        self.driver_repository = driver_repository
        self.store = store
        self.location_ttl_seconds = location_ttl_seconds

    def update_driver_location(
        self, user_id: str, payload: DriverLocationUpdate
    ) -> dict:
        driver = self._get_driver(user_id)
        self._ensure_driver_can_publish_location(driver)
        self.store.update_driver_location(
            driver_id=driver.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            timestamp=payload.timestamp,
            ttl_seconds=self.location_ttl_seconds,
        )
        return {
            "driver_id": driver.id,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "timestamp": payload.timestamp,
        }

    def get_nearby_drivers(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int,
    ) -> list[dict]:
        self.remove_offline_drivers()
        return self.store.get_nearby_drivers(latitude, longitude, radius_km, limit)

    def remove_driver_location(self, user_id: str) -> None:
        driver = self._get_driver(user_id)
        self.store.remove_driver(driver.id)

    def remove_offline_drivers(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self.location_ttl_seconds
        )
        return self.store.remove_stale_drivers(cutoff)

    def _get_driver(self, user_id: str) -> Driver:
        driver = self.driver_repository.get_by_user_id(user_id)
        if driver is None:
            raise LocationDriverNotFoundError("Driver profile not found")
        return driver

    def _ensure_driver_can_publish_location(self, driver: Driver) -> None:
        if not driver.online_status or driver.availability_status != "available":
            raise LocationDriverUnavailableError(
                "Driver must be online and available to publish location"
            )
