from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import asin, cos, radians, sin, sqrt
from typing import Protocol

from modules.rides.schemas import RideLocation


@dataclass(frozen=True)
class FareEstimate:
    distance_km: Decimal
    estimated_fare: Decimal


class PricingService(Protocol):
    def estimate_fare(
        self, pickup: RideLocation, destination: RideLocation
    ) -> FareEstimate:
        pass


class SimplePricingService:
    base_fare = Decimal("3.00")
    per_km_rate = Decimal("1.75")

    def estimate_fare(
        self, pickup: RideLocation, destination: RideLocation
    ) -> FareEstimate:
        distance = _distance_km(
            pickup.latitude,
            pickup.longitude,
            destination.latitude,
            destination.longitude,
        )
        distance_decimal = Decimal(str(distance)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        fare = (self.base_fare + distance_decimal * self.per_km_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return FareEstimate(distance_km=distance_decimal, estimated_fare=fare)


def _distance_km(
    first_latitude: float,
    first_longitude: float,
    second_latitude: float,
    second_longitude: float,
) -> float:
    earth_radius_km = 6371.0
    lat_delta = radians(second_latitude - first_latitude)
    lon_delta = radians(second_longitude - first_longitude)
    first_latitude = radians(first_latitude)
    second_latitude = radians(second_latitude)
    haversine = (
        sin(lat_delta / 2) ** 2
        + cos(first_latitude) * cos(second_latitude) * sin(lon_delta / 2) ** 2
    )
    return 2 * earth_radius_km * asin(sqrt(haversine))
