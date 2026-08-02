"""Read-only onboarding progress, used by the frontend blocking modal."""

from typing import Any

from fastapi import APIRouter, Depends

from core.auth import AuthenticatedUser, get_current_user
from core.verification import DRIVER_ROLE, STUDENT_ROLE, VerificationService
from core.dependencies import get_verification_service

router = APIRouter(prefix="/verification", tags=["verification"])


@router.get("/status")
def get_my_verification_status(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VerificationService = Depends(get_verification_service),
) -> dict[str, Any]:
    """Onboarding checklist for the caller, inferred from their existing profile."""
    return service.status_for_user(current_user.id).to_payload()


@router.get("/status/student")
def get_student_verification_status(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VerificationService = Depends(get_verification_service),
) -> dict[str, Any]:
    """Onboarding checklist for the caller as a student."""
    return service.student_status(current_user.id).to_payload()


@router.get("/status/driver")
def get_driver_verification_status(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VerificationService = Depends(get_verification_service),
) -> dict[str, Any]:
    """Onboarding checklist for the caller as a driver."""
    return service.driver_status(current_user.id).to_payload()


__all__ = ["router", "STUDENT_ROLE", "DRIVER_ROLE"]
