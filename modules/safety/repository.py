import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from modules.safety.models import EmergencyAlert, SafetyReport, TripShareToken


class EmergencyAlertRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict[str, Any]) -> EmergencyAlert:
        alert = EmergencyAlert(**data)
        self.db.add(alert)
        self.db.flush()
        self.db.refresh(alert)
        return alert

    def get_by_id(self, alert_id: str) -> EmergencyAlert | None:
        return self.db.query(EmergencyAlert).filter(EmergencyAlert.id == alert_id).one_or_none()

    def list_active(self, limit: int = 50) -> list[EmergencyAlert]:
        return (
            self.db.query(EmergencyAlert)
            .filter(EmergencyAlert.status == "active")
            .order_by(EmergencyAlert.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_for_user(self, user_id: str, limit: int = 50) -> list[EmergencyAlert]:
        return (
            self.db.query(EmergencyAlert)
            .filter(EmergencyAlert.user_id == user_id)
            .order_by(EmergencyAlert.created_at.desc())
            .limit(limit)
            .all()
        )

    def resolve(self, alert: EmergencyAlert) -> EmergencyAlert:
        alert.status = "resolved"
        alert.resolved_at = datetime.now(timezone.utc)
        self.db.flush()
        self.db.refresh(alert)
        return alert


class TripShareTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict[str, Any]) -> TripShareToken:
        token = TripShareToken(**data)
        self.db.add(token)
        self.db.flush()
        self.db.refresh(token)
        return token

    def get_by_token(self, token: str) -> TripShareToken | None:
        return (
            self.db.query(TripShareToken)
            .filter(TripShareToken.token == token, TripShareToken.is_active == True)
            .one_or_none()
        )

    def get_by_ride(self, ride_id: str, user_id: str) -> TripShareToken | None:
        return (
            self.db.query(TripShareToken)
            .filter(
                TripShareToken.ride_id == ride_id,
                TripShareToken.user_id == user_id,
                TripShareToken.is_active == True,
            )
            .one_or_none()
        )

    def deactivate_for_ride(self, ride_id: str) -> int:
        count = (
            self.db.query(TripShareToken)
            .filter(TripShareToken.ride_id == ride_id, TripShareToken.is_active == True)
            .update({"is_active": False})
        )
        self.db.flush()
        return count


class SafetyReportRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict[str, Any]) -> SafetyReport:
        # Serialize attachments list to JSON string
        if "attachments" in data and data["attachments"] is not None:
            data["attachments"] = json.dumps(data["attachments"])
        report = SafetyReport(**data)
        self.db.add(report)
        self.db.flush()
        self.db.refresh(report)
        return report

    def get_by_id(self, report_id: str) -> SafetyReport | None:
        return (
            self.db.query(SafetyReport)
            .filter(SafetyReport.id == report_id, SafetyReport.is_deleted == False)
            .one_or_none()
        )

    def list_for_user(self, user_id: str, limit: int = 50) -> list[SafetyReport]:
        return (
            self.db.query(SafetyReport)
            .filter(SafetyReport.user_id == user_id, SafetyReport.is_deleted == False)
            .order_by(SafetyReport.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_all(self, status: str | None = None, limit: int = 50, offset: int = 0) -> list[SafetyReport]:
        query = self.db.query(SafetyReport).filter(SafetyReport.is_deleted == False)
        if status:
            query = query.filter(SafetyReport.status == status)
        return query.order_by(SafetyReport.created_at.desc()).limit(limit).offset(offset).all()

    def update_status(self, report: SafetyReport, new_status: str) -> SafetyReport:
        report.status = new_status
        if new_status == "resolved":
            report.resolved_at = datetime.now(timezone.utc)
        self.db.flush()
        self.db.refresh(report)
        return report
