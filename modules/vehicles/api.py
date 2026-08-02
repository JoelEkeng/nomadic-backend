from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from core.auth import AuthenticatedUser, get_current_user
from core.database import get_db
from modules.drivers.repository import DriverRepository
from modules.kyc.api import require_admin
from modules.vehicles.repository import VehicleRepository
from modules.vehicles.schemas import (
    InspectionStatus,
    VehicleCreate,
    VehicleResponse,
    VehicleUpdate,
)
from modules.vehicles.service import (
    VehicleConflictError,
    VehicleAlreadyRegisteredError,
    VehicleDriverNotFoundError,
    VehicleInsuranceExpiredError,
    VehicleNotFoundError,
    VehicleService,
)

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def get_vehicle_service(db: Session = Depends(get_db)) -> VehicleService:
    return VehicleService(VehicleRepository(db), DriverRepository(db))


@router.post("", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
def register_vehicle(
    payload: VehicleCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VehicleService = Depends(get_vehicle_service),
) -> VehicleResponse:
    try:
        return service.register_vehicle(current_user.id, payload)
    except VehicleDriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc
    except VehicleInsuranceExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle insurance has expired",
        ) from exc
    except VehicleAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Drivers may register exactly one vehicle for MVP",
        ) from exc
    except VehicleConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle could not be registered",
        ) from exc


@router.get("", response_model=list[VehicleResponse])
def list_my_vehicles(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VehicleService = Depends(get_vehicle_service),
) -> list[VehicleResponse]:
    try:
        return service.list_my_vehicles(current_user.id)
    except VehicleDriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc


@router.get("/admin/all", response_model=list[VehicleResponse])
def admin_list_vehicles(
    _: AuthenticatedUser = Depends(require_admin),
    service: VehicleService = Depends(get_vehicle_service),
    inspection_status: InspectionStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[VehicleResponse]:
    return service.list_vehicles(
        inspection_status=inspection_status,
        limit=limit,
        offset=offset,
    )


@router.get("/admin/{vehicle_id}", response_model=VehicleResponse)
def admin_get_vehicle(
    vehicle_id: str,
    _: AuthenticatedUser = Depends(require_admin),
    service: VehicleService = Depends(get_vehicle_service),
) -> VehicleResponse:
    try:
        return service.get_vehicle(vehicle_id)
    except VehicleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found",
        ) from exc


@router.post("/admin/{vehicle_id}/approve", response_model=VehicleResponse)
def admin_approve_vehicle(
    vehicle_id: str,
    _: AuthenticatedUser = Depends(require_admin),
    service: VehicleService = Depends(get_vehicle_service),
) -> VehicleResponse:
    try:
        return service.approve_vehicle(vehicle_id)
    except VehicleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found",
        ) from exc
    except VehicleInsuranceExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle insurance has expired",
        ) from exc


@router.post("/admin/{vehicle_id}/reject", response_model=VehicleResponse)
def admin_reject_vehicle(
    vehicle_id: str,
    _: AuthenticatedUser = Depends(require_admin),
    service: VehicleService = Depends(get_vehicle_service),
) -> VehicleResponse:
    try:
        return service.reject_vehicle(vehicle_id)
    except VehicleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found",
        ) from exc


@router.get("/{vehicle_id}", response_model=VehicleResponse)
def get_my_vehicle(
    vehicle_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VehicleService = Depends(get_vehicle_service),
) -> VehicleResponse:
    try:
        return service.get_my_vehicle(current_user.id, vehicle_id)
    except VehicleDriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc
    except VehicleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found",
        ) from exc


@router.patch("/{vehicle_id}", response_model=VehicleResponse)
def update_my_vehicle(
    vehicle_id: str,
    payload: VehicleUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VehicleService = Depends(get_vehicle_service),
) -> VehicleResponse:
    try:
        return service.update_my_vehicle(current_user.id, vehicle_id, payload)
    except VehicleDriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc
    except VehicleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found",
        ) from exc
    except VehicleInsuranceExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle insurance has expired",
        ) from exc
    except VehicleConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle could not be updated",
        ) from exc


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_vehicle(
    vehicle_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VehicleService = Depends(get_vehicle_service),
) -> Response:
    try:
        service.delete_my_vehicle(current_user.id, vehicle_id)
    except VehicleDriverNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        ) from exc
    except VehicleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
