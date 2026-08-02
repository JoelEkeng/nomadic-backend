from pydantic import BaseModel, Field, field_validator

from modules.vehicles.schemas import VehicleType


class GeoPoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class MatchRequest(BaseModel):
    pickup: GeoPoint
    destination: GeoPoint
    vehicle_type: VehicleType
    request_id: str | None = Field(default=None, max_length=128)
    radius_km: float = Field(default=5, gt=0, le=50)
    candidate_limit: int = Field(default=50, ge=1, le=200)

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class MatchCandidateResponse(BaseModel):
    driver_id: str
    distance_km: float
    eta_minutes: float
    rating: float
    acceptance_rate: float
    cancellation_rate: float
    score: float


class MatchAssignmentResponse(BaseModel):
    request_id: str
    assigned_driver_id: str
    vehicle_type: VehicleType
    candidate: MatchCandidateResponse
