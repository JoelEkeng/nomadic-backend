from datetime import datetime

from pydantic import BaseModel, Field


# ─── Emergency Alert ──────────────────────────────────────────────────────────


class EmergencyAlertCreate(BaseModel):
    ride_id: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    message: str | None = None
    alert_type: str = Field(default="general")


class EmergencyAlertResponse(BaseModel):
    id: str
    user_id: str
    ride_id: str | None
    driver_id: str | None
    alert_type: str
    latitude: float | None
    longitude: float | None
    message: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Trip Share ───────────────────────────────────────────────────────────────


class TripShareCreate(BaseModel):
    ride_id: str


class TripShareResponse(BaseModel):
    id: str
    ride_id: str
    token: str
    share_url: str
    whatsapp_url: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class SharedTripPublic(BaseModel):
    """Public trip info visible to anyone with a valid token."""

    student_first_name: str | None = None
    driver_name: str | None = None
    driver_photo: str | None = None
    driver_phone: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_color: str | None = None
    license_plate: str | None = None
    pickup: str
    destination: str
    status: str
    estimated_arrival: str | None = None
    driver_latitude: float | None = None
    driver_longitude: float | None = None
    created_at: datetime


# ─── Safety Report ────────────────────────────────────────────────────────────


class SafetyReportCreate(BaseModel):
    ride_id: str | None = None
    category: str = Field(
        ...,
        pattern="^(unsafe_driving|driver_misconduct|vehicle_issue|wrong_route|harassment|accident|other)$",
    )
    description: str | None = None
    attachments: list[str] | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)


class SafetyReportResponse(BaseModel):
    id: str
    user_id: str
    ride_id: str | None
    driver_id: str | None
    category: str
    description: str | None
    attachments: list[str] | None = None
    latitude: float | None
    longitude: float | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
