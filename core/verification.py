"""Centralised onboarding/verification guard for riders and drivers.

Verification rules used to live in three different places (``RideService``,
``DriverService`` and ``VehicleService``), each with slightly different rules and
each raising a differently shaped 403. This module owns the rules once so every
endpoint enforces the same contract:

Students may not request rides until:
    * their student profile is completed (onboarding done)

Drivers may not go online, update availability or manage rides until:
    * their driver profile is completed (onboarding done, licence still valid)
    * a vehicle is registered and approved by an admin
    * KYC documents have been submitted
    * driver verification has been approved

A failure raises :class:`VerificationRequiredError`, which the app converts into
a single stable ``403`` payload the frontend uses to render a blocking modal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from modules.drivers.models import Driver
from modules.drivers.repository import DriverRepository
from modules.kyc.repository import KYCRepository
from modules.students.models import Student
from modules.students.repository import StudentRepository
from modules.vehicles.repository import VehicleRepository

#: Single error code the frontend keys its blocking modal off, per the API contract.
ERROR_CODE_PROFILE_INCOMPLETE = "PROFILE_INCOMPLETE"

STUDENT_ROLE = "student"
DRIVER_ROLE = "driver"

STUDENT_MESSAGE = "Complete your student profile before requesting rides."
DRIVER_MESSAGE = "Complete your registration before going online or accepting rides."

#: ``verification_status`` value that marks an applicant as approved. The KYC
#: module writes this flag when an application is approved.
VERIFIED_STATUSES = {"verified", "approved"}


@dataclass(frozen=True)
class VerificationStep:
    """One requirement in a role's onboarding checklist.

    ``key`` doubles as the key inside the ``next_step`` object of the 403 body,
    so the frontend can map a step straight onto a call-to-action.
    """

    key: str
    label: str
    satisfied: bool
    action_url: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "satisfied": self.satisfied,
            "action_url": self.action_url,
        }


@dataclass(frozen=True)
class VerificationStatus:
    """The full onboarding state for one user in one role."""

    role: str
    message: str
    steps: tuple[VerificationStep, ...]

    @property
    def is_verified(self) -> bool:
        return all(step.satisfied for step in self.steps)

    @property
    def missing_steps(self) -> tuple[VerificationStep, ...]:
        return tuple(step for step in self.steps if not step.satisfied)

    @property
    def completed_count(self) -> int:
        return sum(1 for step in self.steps if step.satisfied)

    @property
    def total_count(self) -> int:
        return len(self.steps)

    @property
    def progress_percent(self) -> int:
        if not self.steps:
            return 100
        return round((self.completed_count / self.total_count) * 100)

    @property
    def next_step_key(self) -> str | None:
        """The first outstanding step, i.e. what the user should do next."""
        missing = self.missing_steps
        return missing[0].key if missing else None

    def next_step(self) -> dict[str, bool]:
        """``{step_key: still_outstanding}`` for every step in the checklist.

        Every key is always present so the frontend can render a stable
        checklist; ``True`` means "this step still needs doing".
        """
        return {step.key: not step.satisfied for step in self.steps}

    def to_payload(self) -> dict[str, Any]:
        """The response body shared by the 403 guard and the status endpoint."""
        return {
            "success": self.is_verified,
            "error_code": None if self.is_verified else ERROR_CODE_PROFILE_INCOMPLETE,
            "message": self.message,
            "next_step": self.next_step(),
            "verification": {
                "role": self.role,
                "verified": self.is_verified,
                "next_step_key": self.next_step_key,
                "progress": {
                    "completed": self.completed_count,
                    "total": self.total_count,
                    "percent": self.progress_percent,
                },
                "steps": [step.to_payload() for step in self.steps],
            },
        }


class VerificationRequiredError(Exception):
    """Raised when a user has not finished the onboarding required for an action."""

    def __init__(self, status: VerificationStatus):
        super().__init__(status.message)
        self.status = status

    @property
    def error_code(self) -> str:
        return ERROR_CODE_PROFILE_INCOMPLETE

    def to_payload(self) -> dict[str, Any]:
        payload = self.status.to_payload()
        # A guard failure is never a success, even if a race made every step pass.
        payload["success"] = False
        payload["error_code"] = ERROR_CODE_PROFILE_INCOMPLETE
        return payload


class VerificationService:
    """Reads onboarding state and enforces it. The single source of truth."""

    def __init__(
        self,
        db: Session,
        student_repository: StudentRepository | None = None,
        driver_repository: DriverRepository | None = None,
        vehicle_repository: VehicleRepository | None = None,
        kyc_repository: KYCRepository | None = None,
    ):
        self.db = db
        self.student_repository = student_repository or StudentRepository(db)
        self.driver_repository = driver_repository or DriverRepository(db)
        self.vehicle_repository = vehicle_repository or VehicleRepository(db)
        self.kyc_repository = kyc_repository or KYCRepository(db)

    # ------------------------------------------------------------------
    # Status inspection (safe to call from anywhere, never raises)
    # ------------------------------------------------------------------
    def student_status(self, user_id: str) -> VerificationStatus:
        student = self.student_repository.get_by_user_id(user_id)
        approved = student is not None

        return VerificationStatus(
            role=STUDENT_ROLE,
            message=STUDENT_MESSAGE,
            steps=(
                VerificationStep(
                    key="complete_profile",
                    label="Complete your student profile",
                    satisfied=student is not None,
                    # Creating the profile happens on the onboarding page; /settings
                    # can only edit a profile that already exists.
                    action_url="/onboarding",
                ),
            ),
        )

    def driver_status(self, user_id: str) -> VerificationStatus:
        driver = self.driver_repository.get_by_user_id(user_id)
        approved = driver is not None and driver.verification_status in VERIFIED_STATUSES
        licence_valid = (
            driver is not None
            and (driver.license_expiry is None or driver.license_expiry >= date.today())
        )
        has_vehicle = driver is not None and bool(
            self.vehicle_repository.list_by_driver_id(driver.id)
        )
        vehicle_approved = driver is not None and self.vehicle_repository.has_approved_vehicle(
            driver.id
        )

        return VerificationStatus(
            role=DRIVER_ROLE,
            message=DRIVER_MESSAGE,
            steps=(
                VerificationStep(
                    key="complete_profile",
                    label="Complete your driver profile with a valid licence",
                    satisfied=driver is not None and licence_valid,
                    action_url="/driver/profile",
                ),
                VerificationStep(
                    key="register_vehicle",
                    label="Register your vehicle",
                    satisfied=has_vehicle,
                    action_url="/driver/vehicle",
                ),
                VerificationStep(
                    key="approve_vehicle",
                    label="Vehicle inspection approved",
                    satisfied=vehicle_approved,
                    action_url="/driver/vehicle",
                ),
                VerificationStep(
                    key="upload_documents",
                    label="Upload your driver documents",
                    satisfied=self._has_submitted_kyc(user_id, DRIVER_ROLE, approved),
                    action_url="/driver/profile",
                ),
                VerificationStep(
                    key="verify_driver",
                    label="Admin approval completed",
                    satisfied=approved,
                    action_url="/driver/profile",
                ),
            ),
        )

    def status_for_user(self, user_id: str) -> VerificationStatus:
        """Best-effort status for a user whose role we do not know up front.

        Falls back to the student checklist when the user has neither profile,
        because signing up as a rider is the default journey.
        """
        if self.driver_repository.get_by_user_id(user_id) is not None:
            return self.driver_status(user_id)
        return self.student_status(user_id)

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------
    def require_verified_student(self, user_id: str) -> Student:
        """Return the student record, or raise if the student profile is missing."""
        status = self.student_status(user_id)
        if not status.is_verified:
            raise VerificationRequiredError(status)

        student = self.student_repository.get_by_user_id(user_id)
        if student is None:  # pragma: no cover - guarded by the checklist above
            raise VerificationRequiredError(status)
        return student

    def require_verified_driver(self, user_id: str) -> Driver:
        """Return the driver record, or raise if onboarding is unfinished."""
        status = self.driver_status(user_id)
        if not status.is_verified:
            raise VerificationRequiredError(status)

        driver = self.driver_repository.get_by_user_id(user_id)
        if driver is None:  # pragma: no cover - guarded by the checklist above
            raise VerificationRequiredError(status)
        return driver

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _has_submitted_kyc(
        self, user_id: str, applicant_type: str, already_approved: bool
    ) -> bool:
        """Whether KYC documents exist for this applicant.

        Drivers still need this bookkeeping for their separate verification flow.
        """
        if already_approved:
            return True
        return self.kyc_repository.has_application(user_id, applicant_type)
