import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import AuthenticatedUser, get_current_user
from core.database import get_db
from modules.drivers.repository import DriverRepository
from modules.rides.repository import RideRepository
from modules.safety.repository import (
    EmergencyAlertRepository,
    SafetyReportRepository,
    TripShareTokenRepository,
)
from modules.safety.schemas import (
    EmergencyAlertCreate,
    EmergencyAlertResponse,
    SafetyReportCreate,
    SafetyReportResponse,
    SharedTripPublic,
    TripShareCreate,
    TripShareResponse,
)
from modules.safety.service import (
    RideNotFoundError,
    SafetyService,
    ShareTokenExpiredError,
    ShareTokenNotFoundError,
)
from modules.vehicles.repository import VehicleRepository

router = APIRouter(prefix="/safety", tags=["safety"])


def get_safety_service(db: Session = Depends(get_db)) -> SafetyService:
    return SafetyService(
        alert_repository=EmergencyAlertRepository(db),
        share_repository=TripShareTokenRepository(db),
        report_repository=SafetyReportRepository(db),
        ride_repository=RideRepository(db),
        driver_repository=DriverRepository(db),
        vehicle_repository=VehicleRepository(db),
    )


# ─── Emergency Alerts ─────────────────────────────────────────────────────────


@router.post("/emergency", response_model=EmergencyAlertResponse, status_code=status.HTTP_201_CREATED)
def create_emergency_alert(
    payload: EmergencyAlertCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: SafetyService = Depends(get_safety_service),
) -> EmergencyAlertResponse:
    alert = service.create_emergency_alert(current_user.id, payload, user_name=current_user.name)
    service.alert_repository.db.commit()
    service.alert_repository.db.refresh(alert)
    return alert


@router.get("/emergency", response_model=list[EmergencyAlertResponse])
def get_my_alerts(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: SafetyService = Depends(get_safety_service),
) -> list[EmergencyAlertResponse]:
    return service.get_user_alerts(current_user.id)


# ─── Trip Sharing ─────────────────────────────────────────────────────────────


@router.post("/share", response_model=TripShareResponse, status_code=status.HTTP_201_CREATED)
def create_trip_share(
    payload: TripShareCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: SafetyService = Depends(get_safety_service),
) -> TripShareResponse:
    try:
        result = service.create_trip_share(current_user.id, payload)
        service.share_repository.db.commit()
        return result
    except RideNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found") from exc


@router.get("/share/{token}", response_model=SharedTripPublic)
def get_shared_trip(
    token: str,
    service: SafetyService = Depends(get_safety_service),
) -> SharedTripPublic:
    """Public endpoint - no authentication required. Accessible with valid token."""
    try:
        return service.get_shared_trip(token)
    except ShareTokenNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share link not found") from exc
    except ShareTokenExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Share link has expired") from exc
    except RideNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found") from exc


# ─── Safety Reports ───────────────────────────────────────────────────────────


@router.post("/report", response_model=SafetyReportResponse, status_code=status.HTTP_201_CREATED)
def create_safety_report(
    payload: SafetyReportCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: SafetyService = Depends(get_safety_service),
) -> SafetyReportResponse:
    report = service.create_report(current_user.id, payload)
    service.report_repository.db.commit()
    service.report_repository.db.refresh(report)
    # Parse attachments JSON back to list for response
    response_data = SafetyReportResponse.model_validate(report)
    if report.attachments:
        response_data.attachments = json.loads(report.attachments)
    return response_data


@router.get("/reports", response_model=list[SafetyReportResponse])
def get_my_reports(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: SafetyService = Depends(get_safety_service),
) -> list[SafetyReportResponse]:
    reports = service.get_user_reports(current_user.id)
    result = []
    for r in reports:
        resp = SafetyReportResponse.model_validate(r)
        if r.attachments:
            resp.attachments = json.loads(r.attachments)
        result.append(resp)
    return result
