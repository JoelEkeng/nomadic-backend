"""Reusable FastAPI dependencies for the verification guard.

Endpoints should depend on :func:`require_verified_student` or
:func:`require_verified_driver` instead of re-implementing verification checks.
Both return the underlying profile, so a guarded endpoint gets the record it
needs without a second query.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from core.auth import AuthenticatedUser, get_current_user
from core.database import get_db
from core.verification import VerificationService, VerificationStatus
from modules.drivers.models import Driver
from modules.students.models import Student


def get_verification_service(db: Session = Depends(get_db)) -> VerificationService:
    return VerificationService(db)


def require_verified_student(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VerificationService = Depends(get_verification_service),
) -> Student:
    """Allow the request only if the caller is a fully verified student.

    Raises ``VerificationRequiredError``, rendered as a 403 with the onboarding
    checklist by the handler registered in ``main``.
    """
    return service.require_verified_student(current_user.id)


def require_verified_driver(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VerificationService = Depends(get_verification_service),
) -> Driver:
    """Allow the request only if the caller is a fully verified driver."""
    return service.require_verified_driver(current_user.id)


def get_my_verification_status(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: VerificationService = Depends(get_verification_service),
) -> VerificationStatus:
    """Read-only onboarding progress for the caller. Never raises."""
    return service.status_for_user(current_user.id)
