import hashlib
import logging
from typing import Protocol

from modules.kyc.models import KYCApplication
from modules.kyc.repository import KYCRepository
from modules.kyc.schemas import KYCApplicationSubmit, KYCReviewRequest
from modules.drivers.models import Driver

logger = logging.getLogger(__name__)


class DocumentStorage(Protocol):
    def protect_document(self, user_id: str, file_url: str) -> str:
        pass


class ProtectedDocumentStorage:
    def protect_document(self, user_id: str, file_url: str) -> str:
        digest = hashlib.sha256(f"{user_id}:{file_url}".encode()).hexdigest()
        return f"protected://kyc/{user_id}/{digest}"


class KYCAuditLogger(Protocol):
    def log_submission(self, application: KYCApplication) -> None:
        pass

    def log_review_action(
        self, application: KYCApplication, reviewer_id: str, action: str
    ) -> None:
        pass


class StructuredKYCAuditLogger:
    def log_submission(self, application: KYCApplication) -> None:
        logger.info(
            "kyc_application_submitted",
            extra={
                "kyc_application_id": application.id,
                "kyc_user_id": application.user_id,
                "kyc_applicant_type": application.applicant_type,
                "kyc_status": application.status,
                "kyc_document_count": len(application.documents),
            },
        )

    def log_review_action(
        self, application: KYCApplication, reviewer_id: str, action: str
    ) -> None:
        logger.info(
            "kyc_application_reviewed",
            extra={
                "kyc_application_id": application.id,
                "kyc_user_id": application.user_id,
                "kyc_reviewer_id": reviewer_id,
                "kyc_applicant_type": application.applicant_type,
                "kyc_action": action,
                "kyc_status": application.status,
            },
        )


class KYCError(Exception):
    pass


class KYCApplicationNotFoundError(KYCError):
    pass


class KYCApplicationConflictError(KYCError):
    pass


class KYCApplicationFinalizedError(KYCError):
    pass


class KYCPermissionError(KYCError):
    pass


class KYCService:
    FINAL_STATUSES = {"APPROVED", "REJECTED"}

    def __init__(
        self,
        repository: KYCRepository,
        document_storage: DocumentStorage | None = None,
        audit_logger: KYCAuditLogger | None = None,
    ):
        self.repository = repository
        self.document_storage = document_storage or ProtectedDocumentStorage()
        self.audit_logger = audit_logger or StructuredKYCAuditLogger()

    def submit_application(
        self, user_id: str, payload: KYCApplicationSubmit
    ) -> KYCApplication:
        if self.repository.has_open_application(user_id, payload.applicant_type):
            raise KYCApplicationConflictError(
                "An open KYC application already exists"
            )
        documents = [
            {
                "type": document.type,
                "file_url": self.document_storage.protect_document(
                    user_id, document.file_url
                ),
                "verification_status": "PENDING",
            }
            for document in payload.documents
        ]
        application = self.repository.create_application(
            user_id=user_id,
            applicant_type=payload.applicant_type,
            documents=documents,
        )
        application.status = "SUBMITTED"
        if payload.applicant_type == "driver":
            driver = self.repository.db.query(Driver).filter(Driver.user_id == user_id).one_or_none()
            if driver is not None:
                driver.verification_status = "submitted"
        self.repository.db.commit()
        application = self.repository.get_application_by_id(application.id) or application
        self.audit_logger.log_submission(application)
        return application

    def list_my_applications(self, user_id: str) -> list[KYCApplication]:
        return self.repository.list_user_applications(user_id)

    def get_my_application(self, user_id: str, application_id: str) -> KYCApplication:
        application = self.get_application(application_id)
        if application.user_id != user_id:
            raise KYCPermissionError("KYC application access denied")
        return application

    def list_applications(
        self,
        status: str | None = None,
        applicant_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KYCApplication]:
        return self.repository.list_applications(
            status=status,
            applicant_type=applicant_type,
            limit=limit,
            offset=offset,
        )

    def get_application(self, application_id: str) -> KYCApplication:
        application = self.repository.get_application_by_id(application_id)
        if application is None:
            raise KYCApplicationNotFoundError("KYC application not found")
        return application

    def start_review(
        self, application_id: str, reviewer_id: str, payload: KYCReviewRequest
    ) -> KYCApplication:
        application = self.get_application(application_id)
        self._ensure_reviewable(application)
        application = self.repository.mark_under_review(
            application, reviewer_id, payload.notes
        )
        self.audit_logger.log_review_action(application, reviewer_id, "PENDING_REVIEW")
        return application

    def approve_application(
        self, application_id: str, reviewer_id: str, payload: KYCReviewRequest
    ) -> KYCApplication:
        application = self.get_application(application_id)
        self._ensure_reviewable(application)
        application = self.repository.review_application(
            application, reviewer_id, "APPROVED", payload.notes
        )
        self.audit_logger.log_review_action(application, reviewer_id, "APPROVED")
        return application

    def reject_application(
        self, application_id: str, reviewer_id: str, payload: KYCReviewRequest
    ) -> KYCApplication:
        application = self.get_application(application_id)
        self._ensure_reviewable(application)
        application = self.repository.review_application(
            application, reviewer_id, "REJECTED", payload.notes
        )
        self.audit_logger.log_review_action(application, reviewer_id, "REJECTED")
        return application

    def _ensure_reviewable(self, application: KYCApplication) -> None:
        if application.status in self.FINAL_STATUSES:
            raise KYCApplicationFinalizedError(
                "KYC application has already been finalized"
            )
