from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from core.auth import AuthenticatedUser, get_current_user
from core.database import get_db
from modules.kyc.repository import KYCRepository
from modules.kyc.schemas import (
    ApplicantType,
    KYCApplicationResponse,
    KYCApplicationSubmit,
    KYCReviewRequest,
    KYCStatus,
)
from modules.kyc.service import (
    KYCApplicationConflictError,
    KYCApplicationFinalizedError,
    KYCApplicationNotFoundError,
    KYCPermissionError,
    KYCService,
)

router = APIRouter(prefix="/kyc", tags=["kyc"])


def get_kyc_service(db: Session = Depends(get_db)) -> KYCService:
    return KYCService(KYCRepository(db))


def require_admin(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permissions required",
        )
    return current_user


@router.post(
    "/applications",
    response_model=KYCApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_kyc_application(
    payload: KYCApplicationSubmit,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: KYCService = Depends(get_kyc_service),
) -> KYCApplicationResponse:
    try:
        return service.submit_application(current_user.id, payload)
    except KYCApplicationConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An open KYC application already exists",
        ) from exc


@router.get("/applications", response_model=list[KYCApplicationResponse])
def list_my_kyc_applications(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: KYCService = Depends(get_kyc_service),
) -> list[KYCApplicationResponse]:
    return service.list_my_applications(current_user.id)


@router.get("/applications/{application_id}", response_model=KYCApplicationResponse)
def get_my_kyc_application(
    application_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: KYCService = Depends(get_kyc_service),
) -> KYCApplicationResponse:
    try:
        return service.get_my_application(current_user.id, application_id)
    except KYCApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        ) from exc
    except KYCPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="KYC application access denied",
        ) from exc


@router.get("/admin/applications", response_model=list[KYCApplicationResponse])
def admin_list_kyc_applications(
    _: AuthenticatedUser = Depends(require_admin),
    service: KYCService = Depends(get_kyc_service),
    status_filter: KYCStatus | None = Query(default=None, alias="status"),
    applicant_type: ApplicantType | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[KYCApplicationResponse]:
    return service.list_applications(
        status=status_filter,
        applicant_type=applicant_type,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/admin/applications/{application_id}",
    response_model=KYCApplicationResponse,
)
def admin_get_kyc_application(
    application_id: str,
    _: AuthenticatedUser = Depends(require_admin),
    service: KYCService = Depends(get_kyc_service),
) -> KYCApplicationResponse:
    try:
        return service.get_application(application_id)
    except KYCApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        ) from exc


@router.post(
    "/admin/applications/{application_id}/review",
    response_model=KYCApplicationResponse,
)
def admin_start_kyc_review(
    application_id: str,
    payload: KYCReviewRequest,
    current_user: AuthenticatedUser = Depends(require_admin),
    service: KYCService = Depends(get_kyc_service),
) -> KYCApplicationResponse:
    try:
        return service.start_review(application_id, current_user.id, payload)
    except KYCApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        ) from exc
    except KYCApplicationFinalizedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="KYC application has already been finalized",
        ) from exc


@router.post(
    "/admin/applications/{application_id}/approve",
    response_model=KYCApplicationResponse,
)
def admin_approve_kyc_application(
    application_id: str,
    payload: KYCReviewRequest,
    current_user: AuthenticatedUser = Depends(require_admin),
    service: KYCService = Depends(get_kyc_service),
) -> KYCApplicationResponse:
    try:
        return service.approve_application(application_id, current_user.id, payload)
    except KYCApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        ) from exc
    except KYCApplicationFinalizedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="KYC application has already been finalized",
        ) from exc


@router.post(
    "/admin/applications/{application_id}/reject",
    response_model=KYCApplicationResponse,
)
def admin_reject_kyc_application(
    application_id: str,
    payload: KYCReviewRequest,
    current_user: AuthenticatedUser = Depends(require_admin),
    service: KYCService = Depends(get_kyc_service),
) -> KYCApplicationResponse:
    try:
        return service.reject_application(application_id, current_user.id, payload)
    except KYCApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC application not found",
        ) from exc
    except KYCApplicationFinalizedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="KYC application has already been finalized",
        ) from exc
