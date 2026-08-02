from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


VerificationStatus = Literal["draft", "submitted", "pending_review", "pending", "verified", "approved", "rejected"]
AvailabilityStatus = Literal["available", "unavailable", "busy"]


class DriverOnboardingCreate(BaseModel):
    phone_number: str | None = Field(default=None, max_length=32)
    license_number: str | None = Field(default=None, max_length=128)
    license_expiry: date | None = None

    @field_validator("phone_number", "license_number")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be empty")
        return value.upper() if any(ch.isdigit() for ch in value) else value


class DriverProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    phone_number: str | None
    license_number: str | None
    license_expiry: date | None
    verification_status: VerificationStatus
    availability_status: AvailabilityStatus
    online_status: bool
    current_vehicle_id: str | None
    rating: Decimal
    total_trips: int
    cancellation_rate: Decimal
    acceptance_rate: Decimal
    earnings: Decimal
    created_at: datetime
    updated_at: datetime


class DriverAvailabilityUpdate(BaseModel):
    availability_status: AvailabilityStatus


class DriverAvailabilityResponse(BaseModel):
    driver_id: str
    availability_status: AvailabilityStatus
    online_status: bool


class DriverEarningsResponse(BaseModel):
    driver_id: str
    earnings: Decimal


class DriverPerformanceResponse(BaseModel):
    driver_id: str
    rating: Decimal
    total_trips: int
    cancellation_rate: Decimal
    acceptance_rate: Decimal
