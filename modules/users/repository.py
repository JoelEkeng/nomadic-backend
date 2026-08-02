from typing import Any

from sqlalchemy.orm import Session

from modules.users.models import UserProfile


class UserProfileRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_user_id(self, user_id: str) -> UserProfile | None:
        return (
            self.db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .one_or_none()
        )

    def create(self, user_id: str, data: dict[str, Any]) -> UserProfile:
        profile = UserProfile(user_id=user_id, **data)
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def update(self, profile: UserProfile, data: dict[str, Any]) -> UserProfile:
        for field, value in data.items():
            setattr(profile, field, value)
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def delete(self, profile: UserProfile) -> None:
        self.db.delete(profile)
        self.db.commit()
