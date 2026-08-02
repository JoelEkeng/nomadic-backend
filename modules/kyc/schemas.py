from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ApplicantType = Literal["student", "driver"]
KYCStatus = Literal["DRAFT", "SUBMITTED", "PENDING_REVIEW", "APPROVED", "REJECTED", "PENDING", "UNDER_REVIEW"]
ReviewAction = Literal["PENDING_REVIEW", "APPROVED", "REJECTED", "UNDER_REVIEW"]

STUDENT_DOCUMENT_TYPES = {"student_id", "admission_letter", "enrollment_proof"}
DRIVER_DOCUMENT_TYPES = {
    "driver_license",
    "national_id",
    "proof_of_address",
    "profile_photo",
    "roadworthy_certificate",
    "insurance",
}
REQUIRED_DRIVER_DOCUMENT_TYPES = {
    "driver_license",
    "national_id",
    "proof_of_address",
    "profile_photo",
}
DOCUMENT_TYPES_BY_APPLICANT = {
    "student": STUDENT_DOCUMENT_TYPES,
    "driver": DRIVER_DOCUMENT_TYPES,
}


class KYCDocumentUpload(BaseModel):
    type: str = Field(max_length=64)
    file_url: str = Field(max_length=2048)

    @field_validator("type")
    @classmethod
    def normalize_type(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("file_url")
    @classmethod
    def validate_file_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Document file URL is required")
        return value


class KYCApplicationSubmit(BaseModel):
    applicant_type: ApplicantType
    documents: list[KYCDocumentUpload] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_documents_for_applicant(self):
        allowed_types = DOCUMENT_TYPES_BY_APPLICANT[self.applicant_type]
        seen_types = set()
        for document in self.documents:
            if document.type not in allowed_types:
                raise ValueError(
                    f"{document.type} is not valid for {self.applicant_type} KYC"
                )
            if document.type in seen_types:
                raise ValueError(f"Duplicate document type: {document.type}")
            seen_types.add(document.type)
        if self.applicant_type == "driver" and any(
            document.type in {"national_id", "proof_of_address", "profile_photo"}
            for document in self.documents
        ):
            missing = REQUIRED_DRIVER_DOCUMENT_TYPES - seen_types
            if missing:
                raise ValueError(
                    f"Missing required driver KYC documents: {', '.join(sorted(missing))}"
                )
        return self


class KYCDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    verification_status: KYCStatus
    created_at: datetime
    updated_at: datetime


class KYCReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reviewer_id: str | None
    action: ReviewAction
    previous_status: KYCStatus
    new_status: KYCStatus
    notes: str | None
    created_at: datetime


class KYCApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    applicant_type: ApplicantType
    status: KYCStatus
    submitted_at: datetime
    reviewed_at: datetime | None
    reviewer_id: str | None
    rejection_reason: str | None = None
    approved_at: datetime | None = None
    documents: list[KYCDocumentResponse]
    reviews: list[KYCReviewResponse] = Field(default_factory=list)


class KYCReviewRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None
