from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.matching.schemas import GeoPoint
from modules.vehicles.schemas import VehicleType


RideStatus = Literal[
    "REQUESTED",
    "MATCHING",
    "ACCEPTED",
    "ARRIVING",
    "STARTED",
    "COMPLETED",
    "CANCELLED",
]


class RideLocation(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str = Field(max_length=512)

    @field_validator("address")
    @classmethod
    def normalize_address(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Address cannot be empty")
        return value

    def to_geo_point(self) -> GeoPoint:
        return GeoPoint(latitude=self.latitude, longitude=self.longitude)


class RideCreate(BaseModel):
    pickup_location: RideLocation
    destination_location: RideLocation
    vehicle_type: VehicleType


class RideCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class RideCompleteRequest(BaseModel):
    final_fare: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class RideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    driver_id: str | None
    pickup_location: str
    destination_location: str
    distance: Decimal
    estimated_fare: Decimal
    final_fare: Decimal | None
    status: RideStatus
    requested_at: datetime
    accepted_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
