import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from core.auth import AuthenticatedUser, get_current_user
from core.database import get_db
from core.dependencies import require_verified_driver, require_verified_student
from modules.drivers.models import Driver
from modules.drivers.repository import DriverRepository
from modules.matching.api import get_matching_service
from modules.matching.service import MatchingService
from modules.rides.repository import RideRepository
from modules.rides.schemas import (
    RideCancelRequest,
    RideCompleteRequest,
    RideCreate,
    RideResponse,
)
from modules.rides.service import (
    InvalidRideTransitionError,
    RideConflictError,
    RideForbiddenError,
    RideMatchingUnavailableError,
    RideNotFoundError,
    RideService,
)
from modules.safety.websocket import broadcast_status_update, manager as ws_manager
from modules.students.models import Student
from modules.students.repository import StudentRepository
from modules.vehicles.repository import VehicleRepository


def _broadcast_if_watched(background_tasks: BackgroundTasks, ride_id: str, new_status: str):
    """Queue a WebSocket status broadcast if anyone is watching this ride."""
    if ride_id in ws_manager.active_ride_ids:
        background_tasks.add_task(asyncio.run, broadcast_status_update(ride_id, new_status))

router = APIRouter(prefix="/rides", tags=["rides"])


def get_ride_service(
    db: Session = Depends(get_db),
    matching_service: MatchingService = Depends(get_matching_service),
) -> RideService:
    return RideService(
        RideRepository(db),
        StudentRepository(db),
        DriverRepository(db),
        VehicleRepository(db),
        matching_service,
    )


@router.post("", response_model=RideResponse, status_code=status.HTTP_201_CREATED)
async def create_ride(
    payload: RideCreate,
    student: Student = Depends(require_verified_student),
    service: RideService = Depends(get_ride_service),
) -> RideResponse:
    """Request a ride. Only students with a profile reach the service."""
    try:
        return await service.create_ride(student.user_id, payload)
    except RideForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except RideMatchingUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Matching drivers are already assigned",
        ) from exc
    except RideConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ride could not be created",
        ) from exc


@router.post("/{ride_id}/cancel", response_model=RideResponse)
def cancel_ride(
    ride_id: str,
    background_tasks: BackgroundTasks,
    _: RideCancelRequest | None = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: RideService = Depends(get_ride_service),
) -> RideResponse:
    try:
        ride = service.cancel_ride(current_user.id, ride_id)
        _broadcast_if_watched(background_tasks, ride_id, "CANCELLED")
        return ride
    except RideNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found",
        ) from exc
    except RideForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except InvalidRideTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post("/{ride_id}/accept", response_model=RideResponse)
def accept_ride(
    ride_id: str,
    background_tasks: BackgroundTasks,
    driver: Driver = Depends(require_verified_driver),
    service: RideService = Depends(get_ride_service),
) -> RideResponse:
    """Accept an assigned ride. Only fully verified drivers reach the service."""
    try:
        ride = service.accept_ride(driver.user_id, ride_id)
        _broadcast_if_watched(background_tasks, ride_id, "ACCEPTED")
        return ride
    except RideNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found",
        ) from exc
    except RideForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except InvalidRideTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post("/{ride_id}/start", response_model=RideResponse)
def start_ride(
    ride_id: str,
    background_tasks: BackgroundTasks,
    driver: Driver = Depends(require_verified_driver),
    service: RideService = Depends(get_ride_service),
) -> RideResponse:
    try:
        ride = service.start_ride(driver.user_id, ride_id)
        _broadcast_if_watched(background_tasks, ride_id, "STARTED")
        return ride
    except RideNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found",
        ) from exc
    except RideForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except InvalidRideTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post("/{ride_id}/arriving", response_model=RideResponse)
def mark_arriving(
    ride_id: str,
    background_tasks: BackgroundTasks,
    driver: Driver = Depends(require_verified_driver),
    service: RideService = Depends(get_ride_service),
) -> RideResponse:
    try:
        ride = service.mark_arriving(driver.user_id, ride_id)
        _broadcast_if_watched(background_tasks, ride_id, "ARRIVING")
        return ride
    except RideNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found",
        ) from exc
    except RideForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except InvalidRideTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post("/{ride_id}/complete", response_model=RideResponse)
def complete_ride(
    ride_id: str,
    payload: RideCompleteRequest,
    background_tasks: BackgroundTasks,
    driver: Driver = Depends(require_verified_driver),
    service: RideService = Depends(get_ride_service),
) -> RideResponse:
    try:
        ride = service.complete_ride(driver.user_id, ride_id, payload)
        _broadcast_if_watched(background_tasks, ride_id, "COMPLETED")
        return ride
    except RideNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride not found",
        ) from exc
    except RideForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except InvalidRideTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get("/history", response_model=list[RideResponse])
def ride_history(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: RideService = Depends(get_ride_service),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[RideResponse]:
    try:
        return service.get_ride_history(current_user.id, limit=limit, offset=offset)
    except RideForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
