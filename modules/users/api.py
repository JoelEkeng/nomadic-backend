from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from core.auth import AuthenticatedUser, get_current_user
from core.database import get_db
from modules.users.repository import UserProfileRepository
from modules.users.schemas import UserProfileResponse, UserProfileUpdate
from modules.users.service import (
    UserProfileConflictError,
    UserProfileNotFoundError,
    UserProfileService,
)

router = APIRouter(prefix="/users", tags=["users"])


def get_user_profile_service(db: Session = Depends(get_db)) -> UserProfileService:
    return UserProfileService(UserProfileRepository(db))


def serialize_profile(
    service: UserProfileService, profile
) -> UserProfileResponse:
    return UserProfileResponse.model_validate(
        {
            **profile.__dict__,
            "profile_completeness": service.calculate_profile_completeness(profile),
        }
    )


@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: UserProfileService = Depends(get_user_profile_service),
) -> UserProfileResponse:
    try:
        profile = service.ensure_profile(current_user.id)
    except UserProfileConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User profile could not be created",
        ) from exc
    return serialize_profile(service, profile)


@router.patch("/me", response_model=UserProfileResponse)
def update_my_profile(
    payload: UserProfileUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: UserProfileService = Depends(get_user_profile_service),
) -> UserProfileResponse:
    try:
        profile = service.ensure_profile(current_user.id)
        profile = service.update_profile(current_user.id, payload)
    except UserProfileConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User profile could not be updated",
        ) from exc
    return serialize_profile(service, profile)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: UserProfileService = Depends(get_user_profile_service),
) -> Response:
    try:
        service.delete_profile(current_user.id)
    except UserProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
