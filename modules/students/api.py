from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from core.auth import AuthenticatedUser, get_current_user
from core.database import get_db
from modules.students.repository import StudentRepository
from modules.students.schemas import (
    FavouriteLocationCreate,
    FavouriteLocationResponse,
    FavouriteLocationUpdate,
    StudentAcademicUpdate,
    StudentProfileCreate,
    StudentProfileResponse,
    StudentRideHistoryItem,
)
from modules.students.service import (
    FavouriteLocationNotFoundError,
    StudentAlreadyExistsError,
    StudentConflictError,
    StudentForbiddenError,
    StudentNotFoundError,
    StudentNotVerifiedError,
    StudentService,
)

router = APIRouter(prefix="/students", tags=["students"])


def get_student_service(db: Session = Depends(get_db)) -> StudentService:
    return StudentService(StudentRepository(db))


@router.post(
    "/profile",
    response_model=StudentProfileResponse,
    status_code=status.HTTP_410_GONE,
    deprecated=True,
)
def create_student_profile(
    _payload: StudentProfileCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: StudentService = Depends(get_student_service),
) -> StudentProfileResponse:
    """Manual student profile creation is deprecated; profiles are auto-created on first GET."""
    return service.ensure_profile(current_user)


@router.get("/profile", response_model=StudentProfileResponse)
def get_student_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: StudentService = Depends(get_student_service),
) -> StudentProfileResponse:
    try:
        return service.ensure_profile(current_user)
    except StudentNotVerifiedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email must be verified before accessing student profile",
        ) from exc
    except StudentForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except StudentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student profile could not be created",
        ) from exc


@router.patch("/profile", response_model=StudentProfileResponse)
def update_student_profile(
    payload: StudentAcademicUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: StudentService = Depends(get_student_service),
) -> StudentProfileResponse:
    try:
        # Ensure profile exists before patching; PATCH never creates a profile.
        service.ensure_profile(current_user)
        return service.update_academic_information(current_user.id, payload)
    except StudentNotVerifiedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email must be verified before updating student profile",
        ) from exc
    except StudentForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except StudentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        ) from exc
    except StudentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student profile could not be updated",
        ) from exc


@router.get("/rides", response_model=list[StudentRideHistoryItem])
def get_student_rides(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: StudentService = Depends(get_student_service),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[StudentRideHistoryItem]:
    try:
        rides = service.get_ride_history(current_user.id, limit=limit, offset=offset)
    except StudentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        ) from exc
    return [_serialize_ride(row) for row in rides]


@router.get(
    "/favourite-locations",
    response_model=list[FavouriteLocationResponse],
)
def list_favourite_locations(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: StudentService = Depends(get_student_service),
) -> list[FavouriteLocationResponse]:
    try:
        return service.list_favourite_locations(current_user.id)
    except StudentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        ) from exc


@router.post(
    "/favourite-locations",
    response_model=FavouriteLocationResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_favourite_location(
    payload: FavouriteLocationCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: StudentService = Depends(get_student_service),
) -> FavouriteLocationResponse:
    try:
        return service.add_favourite_location(current_user.id, payload)
    except StudentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        ) from exc
    except StudentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Favourite location could not be created",
        ) from exc


@router.patch(
    "/favourite-locations/{location_id}",
    response_model=FavouriteLocationResponse,
)
def update_favourite_location(
    location_id: str,
    payload: FavouriteLocationUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: StudentService = Depends(get_student_service),
) -> FavouriteLocationResponse:
    try:
        return service.update_favourite_location(current_user.id, location_id, payload)
    except (StudentNotFoundError, FavouriteLocationNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Favourite location not found",
        ) from exc
    except StudentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Favourite location could not be updated",
        ) from exc


@router.delete(
    "/favourite-locations/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_favourite_location(
    location_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: StudentService = Depends(get_student_service),
) -> Response:
    try:
        service.delete_favourite_location(current_user.id, location_id)
    except (StudentNotFoundError, FavouriteLocationNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Favourite location not found",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _serialize_ride(row: dict[str, Any]) -> StudentRideHistoryItem:
    return StudentRideHistoryItem(
        id=str(row.get("id")),
        status=row.get("status"),
        pickup_location=row.get("pickup_location") or row.get("pickup_address"),
        dropoff_location=(
            row.get("destination_location")
            or row.get("dropoff_location")
            or row.get("dropoff_address")
        ),
        fare=(
            row.get("final_fare")
            or row.get("estimated_fare")
            or row.get("fare")
            or row.get("total_fare")
        ),
        requested_at=row.get("requested_at"),
        completed_at=row.get("completed_at"),
        created_at=row.get("created_at"),
        raw=row,
    )
