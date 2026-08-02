from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VehicleType = Literal["car", "van", "motorcycle", "bus"]
InspectionStatus = Literal["draft", "pending", "approved", "rejected"]

SUPPORTED_DOCUMENT_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".webp")


def validate_document_reference(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Document reference is required")
    lower = value.lower().split("?", 1)[0]
    if not lower.endswith(SUPPORTED_DOCUMENT_EXTENSIONS):
        raise ValueError("Document must be a PDF or image")
    return value


class VehicleBase(BaseModel):
    registration_number: str | None = Field(default=None, max_length=64)
    plate_number: str | None = Field(default=None, max_length=64)
    make: str = Field(max_length=128)
    model: str = Field(max_length=128)
    year: int = Field(ge=1980, le=2100)
    color: str | None = Field(default=None, max_length=64)
    colour: str | None = Field(default=None, max_length=64)
    vehicle_type: VehicleType = "car"
    capacity: int = Field(default=4, ge=1, le=12)
    insurance_expiry: date | None = None
    registration_document: str | None = Field(default=None, max_length=2048)
    insurance_document: str | None = Field(default=None, max_length=2048)
    roadworthy_document: str | None = Field(default=None, max_length=2048)

    @field_validator("registration_number", "plate_number")
    @classmethod
    def normalize_registration_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not value:
            raise ValueError("Plate number cannot be empty")
        return value

    @field_validator("make", "model", "color", "colour")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be empty")
        return value

    @field_validator("registration_document", "insurance_document", "roadworthy_document")
    @classmethod
    def validate_document(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_document_reference(value)

    @model_validator(mode="after")
    def normalize_aliases(self):
        plate = self.plate_number or self.registration_number
        colour = self.colour or self.color
        if not plate:
            raise ValueError("Plate number is required")
        if not colour:
            raise ValueError("Colour is required")
        self.registration_number = plate
        self.plate_number = plate
        self.color = colour
        self.colour = colour
        return self


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    registration_number: str | None = Field(default=None, max_length=64)
    plate_number: str | None = Field(default=None, max_length=64)
    make: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    year: int | None = Field(default=None, ge=1980, le=2100)
    color: str | None = Field(default=None, max_length=64)
    colour: str | None = Field(default=None, max_length=64)
    vehicle_type: VehicleType | None = None
    capacity: int | None = Field(default=None, ge=1, le=12)
    insurance_expiry: date | None = None
    registration_document: str | None = Field(default=None, max_length=2048)
    insurance_document: str | None = Field(default=None, max_length=2048)
    roadworthy_document: str | None = Field(default=None, max_length=2048)

    @field_validator("registration_number", "plate_number")
    @classmethod
    def normalize_registration_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not value:
            raise ValueError("Plate number cannot be empty")
        return value

    @field_validator("make", "model", "color", "colour")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be empty")
        return value

    @field_validator("registration_document", "insurance_document", "roadworthy_document")
    @classmethod
    def validate_optional_document(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_document_reference(value)

    @model_validator(mode="after")
    def normalize_aliases(self):
        if self.plate_number and not self.registration_number:
            self.registration_number = self.plate_number
        if self.registration_number and not self.plate_number:
            self.plate_number = self.registration_number
        if self.colour and not self.color:
            self.color = self.colour
        if self.color and not self.colour:
            self.colour = self.color
        return self


class VehicleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    driver_id: str
    registration_number: str
    make: str
    model: str
    year: int
    color: str
    vehicle_type: VehicleType
    capacity: int
    insurance_expiry: date | None
    registration_document: str | None
    insurance_document: str | None
    roadworthy_document: str | None
    inspection_status: InspectionStatus
    created_at: datetime
    updated_at: datetime

    @property
    def plate_number(self) -> str:
        return self.registration_number

    @property
    def colour(self) -> str:
        return self.color
