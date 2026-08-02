from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AccountStatus = Literal["active", "inactive", "suspended", "deleted"]


class UserProfileBase(BaseModel):
    phone_number: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=2048)
    date_of_birth: date | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    notification_preferences: dict[str, Any] = Field(default_factory=dict)
    account_status: AccountStatus = "active"

    @field_validator("phone_number", "emergency_contact_phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class UserProfileCreate(UserProfileBase):
    pass


class UserProfileUpdate(BaseModel):
    phone_number: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=2048)
    date_of_birth: date | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    notification_preferences: dict[str, Any] | None = None
    account_status: AccountStatus | None = None

    @field_validator("phone_number", "emergency_contact_phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class UserProfileResponse(UserProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    profile_completeness: int
    created_at: datetime
    updated_at: datetime
