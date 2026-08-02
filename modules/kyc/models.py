import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class KYCApplication(Base):
    __tablename__ = "kyc_applications"
    __table_args__ = (
        CheckConstraint(
            "applicant_type IN ('student', 'driver')",
            name="ck_kyc_applications_applicant_type",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'SUBMITTED', 'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'PENDING', 'UNDER_REVIEW')",
            name="ck_kyc_applications_status",
        ),
        Index("ix_kyc_applications_user_id", "user_id"),
        Index("ix_kyc_applications_status", "status"),
        Index("ix_kyc_applications_applicant_type_status", "applicant_type", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    applicant_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewer_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    documents: Mapped[list["KYCDocument"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reviews: Mapped[list["KYCReview"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KYCDocument(Base):
    __tablename__ = "kyc_documents"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('DRAFT', 'SUBMITTED', 'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'PENDING', 'UNDER_REVIEW')",
            name="ck_kyc_documents_verification_status",
        ),
        Index("ix_kyc_documents_application_id", "application_id"),
        Index("ix_kyc_documents_type", "type"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    application_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("kyc_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", server_default="PENDING"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    application: Mapped[KYCApplication] = relationship(back_populates="documents")


class KYCReview(Base):
    __tablename__ = "kyc_reviews"
    __table_args__ = (
        CheckConstraint(
            "action IN ('PENDING_REVIEW', 'UNDER_REVIEW', 'APPROVED', 'REJECTED')",
            name="ck_kyc_reviews_action",
        ),
        Index("ix_kyc_reviews_application_id", "application_id"),
        Index("ix_kyc_reviews_reviewer_id", "reviewer_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    application_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("kyc_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(32), nullable=False)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    application: Mapped[KYCApplication] = relationship(back_populates="reviews")
