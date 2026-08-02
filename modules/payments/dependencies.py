from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import AuthenticatedUser, get_current_user
from core.database import get_db
from modules.payments.models import Wallet
from modules.payments.service import PaymentService


def get_payment_service(db: Session = Depends(get_db)) -> PaymentService:
    return PaymentService(db)


def get_current_user_wallet(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
) -> Wallet:
    """Fetches or initializes user wallet for current authenticated user."""
    return service.get_or_create_user_wallet(user_id=current_user.id)


def require_admin_user(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Enforces admin role requirement for sensitive platform management endpoints."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this action",
        )
    return current_user
