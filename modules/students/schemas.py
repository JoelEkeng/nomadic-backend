from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


VerificationStatus = Literal["pending", "verified", "rejected"]


class StudentProfileBase(BaseModel):
    first_name: str | None = Field(default=None, max_length=128)
    last_name: str | None = Field(default=None, max_length=128)
    phone_number: str | None = Field(default=None, max_length=32)
    profile_image: str | None = Field(default=None, max_length=2048)
    emergency_contact: str | None = Field(default=None, max_length=255)
    preferred_pickup_location: str | None = Field(default=None, max_length=512)

    @field_validator(
        "first_name",
        "last_name",
        "phone_number",
        "profile_image",
        "emergency_contact",
        "preferred_pickup_location",
    )
    @classmethod
    def normalize_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class StudentProfileCreate(StudentProfileBase):
    pass


class StudentAcademicUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=128)
    last_name: str | None = Field(default=None, max_length=128)
    phone_number: str | None = Field(default=None, max_length=32)
    profile_image: str | None = Field(default=None, max_length=2048)
    emergency_contact: str | None = Field(default=None, max_length=255)
    preferred_pickup_location: str | None = Field(default=None, max_length=512)

    @field_validator(
        "first_name",
        "last_name",
        "phone_number",
        "profile_image",
        "preferred_pickup_location",
    )
    @classmethod
    def normalize_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class StudentProfileResponse(StudentProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    student_number: str
    first_name: str | None
    last_name: str | None
    phone_number: str | None
    profile_image: str | None
    emergency_contact: str | None
    verification_status: VerificationStatus
    rating: Decimal
    created_at: datetime
    updated_at: datetime


class FavouriteLocationBase(BaseModel):
    name: str = Field(max_length=255)
    address: str | None = Field(default=None, max_length=512)
    latitude: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal | None = Field(
        default=None, ge=Decimal("-180"), le=Decimal("180")
    )

    @field_validator("name", "address")
    @classmethod
    def normalize_location_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class FavouriteLocationCreate(FavouriteLocationBase):
    pass


class FavouriteLocationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=512)
    latitude: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal | None = Field(
        default=None, ge=Decimal("-180"), le=Decimal("180")
    )

    @field_validator("name", "address")
    @classmethod
    def normalize_location_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class FavouriteLocationResponse(FavouriteLocationBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    created_at: datetime
    updated_at: datetime


class StudentRideHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str | None = None
    pickup_location: str | None = None
    dropoff_location: str | None = None
    fare: Decimal | None = None
    requested_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
