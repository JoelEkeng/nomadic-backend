from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, selectinload

from modules.drivers.models import Driver
from modules.kyc.models import KYCApplication, KYCDocument, KYCReview
from modules.students.models import Student


class KYCRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_application(
        self,
        user_id: str,
        applicant_type: str,
        documents: list[dict[str, Any]],
    ) -> KYCApplication:
        application = KYCApplication(user_id=user_id, applicant_type=applicant_type)
        application.documents = [KYCDocument(**document) for document in documents]
        self.db.add(application)
        self.db.commit()
        return self.get_application_by_id(application.id) or application

    def get_application_by_id(self, application_id: str) -> KYCApplication | None:
        return (
            self.db.query(KYCApplication)
            .options(
                selectinload(KYCApplication.documents),
                selectinload(KYCApplication.reviews),
            )
            .filter(KYCApplication.id == application_id)
            .one_or_none()
        )

    def list_user_applications(self, user_id: str) -> list[KYCApplication]:
        return (
            self.db.query(KYCApplication)
            .options(
                selectinload(KYCApplication.documents),
                selectinload(KYCApplication.reviews),
            )
            .filter(KYCApplication.user_id == user_id)
            .order_by(KYCApplication.submitted_at.desc())
            .all()
        )

    def list_applications(
        self,
        status: str | None = None,
        applicant_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KYCApplication]:
        query = self.db.query(KYCApplication).options(
            selectinload(KYCApplication.documents),
            selectinload(KYCApplication.reviews),
        )
        if status is not None:
            query = query.filter(KYCApplication.status == status)
        if applicant_type is not None:
            query = query.filter(KYCApplication.applicant_type == applicant_type)
        return (
            query.order_by(KYCApplication.submitted_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def has_open_application(self, user_id: str, applicant_type: str) -> bool:
        return (
            self.db.query(KYCApplication.id)
            .filter(
                KYCApplication.user_id == user_id,
                KYCApplication.applicant_type == applicant_type,
                KYCApplication.status.in_(("DRAFT", "SUBMITTED", "PENDING_REVIEW", "PENDING", "UNDER_REVIEW")),
            )
            .first()
            is not None
        )

    def has_application(self, user_id: str, applicant_type: str) -> bool:
        """Whether the user has ever submitted KYC documents for this role."""
        return (
            self.db.query(KYCApplication.id)
            .filter(
                KYCApplication.user_id == user_id,
                KYCApplication.applicant_type == applicant_type,
            )
            .first()
            is not None
        )

    def has_approved_application(self, user_id: str, applicant_type: str) -> bool:
        """Whether the user holds an approved KYC application for this role."""
        return (
            self.db.query(KYCApplication.id)
            .filter(
                KYCApplication.user_id == user_id,
                KYCApplication.applicant_type == applicant_type,
                KYCApplication.status == "APPROVED",
            )
            .first()
            is not None
        )

    def review_application(
        self,
        application: KYCApplication,
        reviewer_id: str,
        action: str,
        notes: str | None,
    ) -> KYCApplication:
        previous_status = application.status
        application.status = action
        application.reviewer_id = reviewer_id
        application.reviewed_at = datetime.now(timezone.utc)
        application.rejection_reason = notes if action == "REJECTED" else None
        application.approved_at = application.reviewed_at if action == "APPROVED" else None
        for document in application.documents:
            document.verification_status = action
        application.reviews.append(
            KYCReview(
                reviewer_id=reviewer_id,
                action=action,
                previous_status=previous_status,
                new_status=action,
                notes=notes,
            )
        )
        self._sync_applicant_verification(application)
        self.db.commit()
        return self.get_application_by_id(application.id) or application

    def mark_under_review(
        self,
        application: KYCApplication,
        reviewer_id: str,
        notes: str | None,
    ) -> KYCApplication:
        previous_status = application.status
        application.status = "PENDING_REVIEW"
        application.reviewer_id = reviewer_id
        for document in application.documents:
            document.verification_status = "PENDING_REVIEW"
        application.reviews.append(
            KYCReview(
                reviewer_id=reviewer_id,
                action="PENDING_REVIEW",
                previous_status=previous_status,
                new_status="PENDING_REVIEW",
                notes=notes,
            )
        )
        self.db.commit()
        return self.get_application_by_id(application.id) or application

    def _sync_applicant_verification(self, application: KYCApplication) -> None:
        if application.applicant_type == "student":
            verification_status = "verified" if application.status == "APPROVED" else "rejected"
            student = (
                self.db.query(Student)
                .filter(Student.user_id == application.user_id)
                .one_or_none()
            )
            if student is not None:
                student.verification_status = verification_status
        elif application.applicant_type == "driver":
            verification_status = "approved" if application.status == "APPROVED" else "rejected"
            driver = (
                self.db.query(Driver)
                .filter(Driver.user_id == application.user_id)
                .one_or_none()
            )
            if driver is not None:
                driver.verification_status = verification_status
