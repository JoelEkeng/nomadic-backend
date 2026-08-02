from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DriverLocationUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class DriverLocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    driver_id: str
    latitude: float
    longitude: float
    timestamp: datetime


class NearbyDriverResponse(DriverLocationResponse):
    distance_km: float


class OfflineCleanupResponse(BaseModel):
    removed: int
