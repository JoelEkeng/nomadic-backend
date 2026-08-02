from sqlalchemy.exc import IntegrityError

from modules.users.models import UserProfile
from modules.users.repository import UserProfileRepository
from modules.users.schemas import UserProfileCreate, UserProfileUpdate


class UserProfileError(Exception):
    pass


class UserProfileAlreadyExistsError(UserProfileError):
    pass


class UserProfileNotFoundError(UserProfileError):
    pass


class UserProfileConflictError(UserProfileError):
    pass


class UserProfileService:
    COMPLETENESS_FIELDS = (
        "phone_number",
        "avatar_url",
        "date_of_birth",
        "emergency_contact_name",
        "emergency_contact_phone",
        "notification_preferences",
    )

    def __init__(self, repository: UserProfileRepository):
        self.repository = repository

    def create_profile(self, user_id: str, payload: UserProfileCreate) -> UserProfile:
        if self.repository.get_by_user_id(user_id):
            raise UserProfileAlreadyExistsError("User profile already exists")
        try:
            return self.repository.create(
                user_id=user_id,
                data=payload.model_dump(),
            )
        except IntegrityError as exc:
            self.repository.db.rollback()
            raise UserProfileConflictError("User profile could not be created") from exc

    def update_profile(self, user_id: str, payload: UserProfileUpdate) -> UserProfile:
        profile = self.get_profile(user_id)
        data = payload.model_dump(exclude_unset=True)
        try:
            return self.repository.update(profile, data)
        except IntegrityError as exc:
            self.repository.db.rollback()
            raise UserProfileConflictError("User profile could not be updated") from exc

    def get_profile(self, user_id: str) -> UserProfile:
        profile = self.repository.get_by_user_id(user_id)
        if profile is None:
            raise UserProfileNotFoundError("User profile not found")
        return profile

    def ensure_profile(self, user_id: str) -> UserProfile:
        """Return existing profile or create a minimal active one."""
        profile = self.repository.get_by_user_id(user_id)
        if profile is not None:
            return profile
        try:
            return self.repository.create(
                user_id=user_id,
                data={"account_status": "active"},
            )
        except IntegrityError as exc:
            self.repository.db.rollback()
            existing = self.repository.get_by_user_id(user_id)
            if existing is not None:
                return existing
            raise UserProfileConflictError("User profile could not be created") from exc

    def delete_profile(self, user_id: str) -> None:
        profile = self.get_profile(user_id)
        self.repository.delete(profile)

    def calculate_profile_completeness(self, profile: UserProfile) -> int:
        completed = 0
        for field in self.COMPLETENESS_FIELDS:
            value = getattr(profile, field)
            if isinstance(value, dict):
                completed += bool(value)
            else:
                completed += value is not None and value != ""
        return round((completed / len(self.COMPLETENESS_FIELDS)) * 100)
