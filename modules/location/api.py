import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from core.auth import AuthenticatedUser, get_current_user
from core.database import get_db
from modules.drivers.repository import DriverRepository
from modules.kyc.api import require_admin
from modules.location.schemas import (
    DriverLocationResponse,
    DriverLocationUpdate,
    NearbyDriverResponse,
    OfflineCleanupResponse,
)
from modules.location.service import (
    LocationDriverNotFoundError,
    LocationDriverUnavailableError,
    LocationService,
)
from modules.location.store import RedisLocationStore
from modules.rides.repository import RideRepository
from modules.safety.websocket import broadcast_location_update, manager as ws_manager

router = APIRouter(prefix="/locations", tags=["locations"])


def get_location_service(db: Session = Depends(get_db)) -> LocationService:
    return LocationService(DriverRepository(db), RedisLocationStore())


@router.put("/drivers/me", response_model=DriverLocationResponse)
def update_my_driver_location(
    payload: DriverLocationUpdate,
    background_tasks: BackgroundTasks,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: LocationService = Depends(get_location_service),
    db: Session = Depends(get_db),
) -> DriverLocationResponse:
    """Publish a live position.

    Not guarded directly: the service already requires the driver to be online
    and available, and becoming available is itself gated by the verification
    guard, so an unverified driver can never reach the matching pool.
    """
    try:
        result = service.update_driver_location(current_user.id, payload)
    except LocationDriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc
    except LocationDriverUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver must be online and available to publish location",
        ) from exc

    # Broadcast to trip share watchers if this driver has an active ride being tracked
    if ws_manager.active_ride_ids:
        driver_repo = DriverRepository(db)
        driver = driver_repo.get_by_user_id(current_user.id)
        if driver:
            ride_repo = RideRepository(db)
            active_ride = ride_repo.get_active_for_driver(driver.id)
            if active_ride and active_ride.id in ws_manager.active_ride_ids:
                background_tasks.add_task(
                    asyncio.run,
                    broadcast_location_update(active_ride.id, payload.latitude, payload.longitude),
                )

    return result


@router.get("/drivers/nearby", response_model=list[NearbyDriverResponse])
def get_nearby_drivers(
    _: AuthenticatedUser = Depends(get_current_user),
    service: LocationService = Depends(get_location_service),
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=3, gt=0, le=50),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[NearbyDriverResponse]:
    return service.get_nearby_drivers(latitude, longitude, radius_km, limit)


@router.delete("/drivers/me", status_code=status.HTTP_204_NO_CONTENT)
def remove_my_driver_location(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: LocationService = Depends(get_location_service),
) -> Response:
    try:
        service.remove_driver_location(current_user.id)
    except LocationDriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/admin/cleanup", response_model=OfflineCleanupResponse)
def remove_offline_drivers(
    _: AuthenticatedUser = Depends(require_admin),
    service: LocationService = Depends(get_location_service),
) -> OfflineCleanupResponse:
    return OfflineCleanupResponse(removed=service.remove_offline_drivers())
