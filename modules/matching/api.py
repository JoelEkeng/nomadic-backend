from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import AuthenticatedUser, get_current_user
from modules.matching.schemas import MatchAssignmentResponse, MatchRequest
from modules.matching.service import (
    DriverAssignmentError,
    MatchingService,
    NoMatchingDriversError,
)
from modules.matching.store import RedisMatchingStore

router = APIRouter(prefix="/matching", tags=["matching"])


def get_matching_service() -> MatchingService:
    return MatchingService(RedisMatchingStore())


@router.post("/assign", response_model=MatchAssignmentResponse)
async def assign_driver(
    payload: MatchRequest,
    _: AuthenticatedUser = Depends(get_current_user),
    service: MatchingService = Depends(get_matching_service),
) -> MatchAssignmentResponse:
    try:
        return await service.assign_driver(payload)
    except NoMatchingDriversError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No matching drivers found",
        ) from exc
    except DriverAssignmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Matching drivers are already assigned",
        ) from exc
