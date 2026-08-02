from sqlalchemy.exc import IntegrityError

from core.auth import AuthenticatedUser
from core.utils.name_parser import split_full_name
from modules.students.models import Student, StudentFavouriteLocation
from modules.students.repository import StudentRepository
from modules.students.schemas import (
    FavouriteLocationCreate,
    FavouriteLocationUpdate,
    StudentAcademicUpdate,
    StudentProfileCreate,
)


class StudentError(Exception):
    pass


class StudentAlreadyExistsError(StudentError):
    pass


class StudentNotFoundError(StudentError):
    pass


class StudentConflictError(StudentError):
    pass


class StudentNotVerifiedError(StudentError):
    pass


class StudentForbiddenError(StudentError):
    pass


class FavouriteLocationNotFoundError(StudentError):
    pass


class StudentService:
    VALID_STUDENT_ROLES = {"passenger", "student"}

    def __init__(self, repository: StudentRepository):
        self.repository = repository

    def create_profile(self, user_id: str, payload: StudentProfileCreate) -> Student:
        if self.repository.get_by_user_id(user_id):
            raise StudentAlreadyExistsError("Student profile already exists")

        data = payload.model_dump()

        try:
            return self.repository.create(user_id, data)
        except IntegrityError as exc:
            self.repository.db.rollback()
            raise StudentConflictError("Student profile could not be created") from exc

    def _validate_can_bootstrap(self, user: AuthenticatedUser) -> None:
        if user.role not in self.VALID_STUDENT_ROLES:
            raise StudentForbiddenError(
                f"Role '{user.role}' is not allowed to create a student profile"
            )
        if not user.email_verified:
            raise StudentNotVerifiedError(
                "Email must be verified before a student profile can be created"
            )

    def _build_profile_data(self, user: AuthenticatedUser) -> dict:
        first_name, last_name = split_full_name(user.name)
        return {
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": user.phone_number,
            "verification_status": "verified",
        }

    def ensure_profile(self, user: AuthenticatedUser) -> Student:
        """Return an existing student profile or create one idempotently.

        This method is safe under concurrent requests: if two requests race to
        create a profile, the unique ``user_id`` constraint causes one to fail
        with an integrity error; that request rolls back and re-fetches the
        profile created by the winner.
        """
        existing = self.repository.get_by_user_id(user.id)
        if existing is not None:
            return existing

        self._validate_can_bootstrap(user)
        data = self._build_profile_data(user)

        try:
            return self.repository.create(user.id, data)
        except IntegrityError:
            self.repository.db.rollback()
            # Another request likely created the profile concurrently. Re-fetch.
            existing = self.repository.get_by_user_id(user.id)
            if existing is not None:
                return existing
            raise StudentConflictError(
                "Student profile could not be created"
            ) from None

    def get_profile(self, user_id: str) -> Student:
        student = self.repository.get_by_user_id(user_id)
        if student is None:
            raise StudentNotFoundError("Student profile not found")
        return student

    def update_academic_information(
        self, user_id: str, payload: StudentAcademicUpdate
    ) -> Student:
        student = self.get_profile(user_id)
        data = payload.model_dump(exclude_unset=True)
        try:
            return self.repository.update(student, data)
        except IntegrityError as exc:
            self.repository.db.rollback()
            raise StudentConflictError("Student profile could not be updated") from exc

    def ensure_can_request_ride(self, user_id: str) -> Student:
        return self.get_profile(user_id)

    def get_ride_history(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        student = self.get_profile(user_id)
        return self.repository.get_ride_history(student, limit=limit, offset=offset)

    def add_favourite_location(
        self, user_id: str, payload: FavouriteLocationCreate
    ) -> StudentFavouriteLocation:
        student = self.get_profile(user_id)
        try:
            return self.repository.add_favourite_location(
                student, payload.model_dump()
            )
        except IntegrityError as exc:
            self.repository.db.rollback()
            raise StudentConflictError("Favourite location could not be created") from exc

    def list_favourite_locations(self, user_id: str) -> list[StudentFavouriteLocation]:
        student = self.get_profile(user_id)
        return self.repository.list_favourite_locations(student.id)

    def update_favourite_location(
        self, user_id: str, location_id: str, payload: FavouriteLocationUpdate
    ) -> StudentFavouriteLocation:
        student = self.get_profile(user_id)
        location = self.repository.get_favourite_location(student.id, location_id)
        if location is None:
            raise FavouriteLocationNotFoundError("Favourite location not found")
        try:
            return self.repository.update_favourite_location(
                location, payload.model_dump(exclude_unset=True)
            )
        except IntegrityError as exc:
            self.repository.db.rollback()
            raise StudentConflictError("Favourite location could not be updated") from exc

    def delete_favourite_location(self, user_id: str, location_id: str) -> None:
        student = self.get_profile(user_id)
        location = self.repository.get_favourite_location(student.id, location_id)
        if location is None:
            raise FavouriteLocationNotFoundError("Favourite location not found")
        self.repository.delete_favourite_location(location)
