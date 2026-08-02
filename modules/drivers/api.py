from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import AuthenticatedUser, get_current_user
from core.database import get_db
from core.dependencies import require_verified_driver
from modules.drivers.models import Driver
from modules.drivers.repository import DriverRepository
from modules.drivers.schemas import (
    DriverAvailabilityResponse,
    DriverAvailabilityUpdate,
    DriverEarningsResponse,
    DriverOnboardingCreate,
    DriverPerformanceResponse,
    DriverProfileResponse,
)
from modules.drivers.service import (
    DriverAlreadyExistsError,
    DriverConflictError,
    DriverLicenseExpiredError,
    DriverNotFoundError,
    DriverService,
)
from modules.vehicles.service import VehicleNotApprovedError

router = APIRouter(prefix="/drivers", tags=["drivers"])


def get_driver_service(db: Session = Depends(get_db)) -> DriverService:
    return DriverService(DriverRepository(db))


@router.post(
    "/onboarding",
    response_model=DriverProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def complete_driver_onboarding(
    payload: DriverOnboardingCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: DriverService = Depends(get_driver_service),
) -> DriverProfileResponse:
    try:
        return service.complete_onboarding(current_user.id, payload)
    except DriverAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver profile already exists",
        ) from exc
    except DriverConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver profile could not be created",
        ) from exc
    except DriverLicenseExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driver license has expired",
        ) from exc
    except VehicleNotApprovedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Driver must have an approved vehicle before accepting rides",
        ) from exc


@router.get("/profile", response_model=DriverProfileResponse)
def get_driver_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: DriverService = Depends(get_driver_service),
) -> DriverProfileResponse:
    try:
        return service.get_profile(current_user.id)
    except DriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc


@router.post("/online", response_model=DriverAvailabilityResponse)
def go_online(
    verified_driver: Driver = Depends(require_verified_driver),
    service: DriverService = Depends(get_driver_service),
) -> DriverAvailabilityResponse:
    """Go online. Only fully verified drivers reach the service."""
    driver = service.go_online(verified_driver.user_id)
    return _serialize_availability(driver)


@router.post("/offline", response_model=DriverAvailabilityResponse)
def go_offline(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: DriverService = Depends(get_driver_service),
) -> DriverAvailabilityResponse:
    try:
        driver = service.go_offline(current_user.id)
    except DriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc
    return _serialize_availability(driver)


@router.patch("/availability", response_model=DriverAvailabilityResponse)
def update_availability(
    payload: DriverAvailabilityUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: DriverService = Depends(get_driver_service),
) -> DriverAvailabilityResponse:
    """Change availability.

    Becoming ``available`` joins the dispatch pool and is gated by the shared
    verification guard inside the service. Marking yourself ``busy`` or
    ``unavailable`` is always allowed so a driver can stop receiving requests.
    """
    try:
        driver = service.update_availability(current_user.id, payload)
    except DriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc
    return _serialize_availability(driver)


@router.get("/earnings", response_model=DriverEarningsResponse)
def view_earnings(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: DriverService = Depends(get_driver_service),
) -> DriverEarningsResponse:
    try:
        driver = service.view_earnings(current_user.id)
    except DriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc
    return DriverEarningsResponse(driver_id=driver.id, earnings=driver.earnings)


@router.get("/performance", response_model=DriverPerformanceResponse)
def view_performance(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: DriverService = Depends(get_driver_service),
) -> DriverPerformanceResponse:
    try:
        driver = service.view_performance(current_user.id)
    except DriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc
    return DriverPerformanceResponse(
        driver_id=driver.id,
        rating=driver.rating,
        total_trips=driver.total_trips,
        cancellation_rate=driver.cancellation_rate,
        acceptance_rate=driver.acceptance_rate,
    )


def _serialize_availability(driver) -> DriverAvailabilityResponse:
    return DriverAvailabilityResponse(
        driver_id=driver.id,
        availability_status=driver.availability_status,
        online_status=driver.online_status,
    )
