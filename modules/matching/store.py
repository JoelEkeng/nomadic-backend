import os
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from typing import Protocol

from modules.matching.ranking import MatchCandidate


class MatchingStore(Protocol):
    def cache_driver_profile(
        self,
        driver_id: str,
        vehicle_type: str,
        rating: float,
        acceptance_rate: float,
        cancellation_rate: float,
        ttl_seconds: int,
    ) -> None:
        pass

    def get_nearby_candidates(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        vehicle_type: str,
        limit: int,
    ) -> list[MatchCandidate]:
        pass

    def reserve_driver(self, driver_id: str, request_id: str, ttl_seconds: int) -> bool:
        pass

    def release_driver(self, driver_id: str) -> None:
        pass


class RedisMatchingStore:
    geo_key = "driver_locations:geo"
    location_prefix = "driver_locations:data"
    profile_prefix = "driver_matching:profile"
    reservation_prefix = "driver_matching:reservation"

    def __init__(self, redis_url: str | None = None):
        try:
            from redis import Redis
        except ImportError as exc:
            raise RuntimeError(
                "Redis support requires installing the 'redis' Python package"
            ) from exc

        self.redis = Redis.from_url(
            redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )

    def cache_driver_profile(
        self,
        driver_id: str,
        vehicle_type: str,
        rating: float,
        acceptance_rate: float,
        cancellation_rate: float,
        ttl_seconds: int,
    ) -> None:
        key = self._profile_key(driver_id)
        pipe = self.redis.pipeline(transaction=False)
        pipe.hset(
            key,
            mapping={
                "driver_id": driver_id,
                "vehicle_type": vehicle_type,
                "rating": rating,
                "acceptance_rate": acceptance_rate,
                "cancellation_rate": cancellation_rate,
            },
        )
        pipe.expire(key, ttl_seconds)
        pipe.execute()

    def get_nearby_candidates(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        vehicle_type: str,
        limit: int,
    ) -> list[MatchCandidate]:
        results = self.redis.geosearch(
            self.geo_key,
            longitude=longitude,
            latitude=latitude,
            radius=radius_km,
            unit="km",
            withdist=True,
            sort="ASC",
            count=limit,
        )
        if not results:
            return []

        pipe = self.redis.pipeline(transaction=False)
        ordered = []
        for driver_id, distance_km in results:
            ordered.append((driver_id, float(distance_km)))
            pipe.hgetall(self._profile_key(driver_id))
            pipe.exists(self._reservation_key(driver_id))
        rows = pipe.execute()

        candidates = []
        for index, (driver_id, distance_km) in enumerate(ordered):
            profile = rows[index * 2]
            is_reserved = bool(rows[index * 2 + 1])
            if is_reserved or not profile or profile.get("vehicle_type") != vehicle_type:
                continue
            eta_minutes = estimate_eta_minutes(distance_km)
            candidates.append(
                MatchCandidate(
                    driver_id=driver_id,
                    distance_km=distance_km,
                    eta_minutes=eta_minutes,
                    rating=float(profile["rating"]),
                    acceptance_rate=float(profile["acceptance_rate"]),
                    cancellation_rate=float(profile["cancellation_rate"]),
                    vehicle_type=profile["vehicle_type"],
                )
            )
        return candidates

    def reserve_driver(self, driver_id: str, request_id: str, ttl_seconds: int) -> bool:
        return bool(
            self.redis.set(
                self._reservation_key(driver_id),
                request_id,
                nx=True,
                ex=ttl_seconds,
            )
        )

    def release_driver(self, driver_id: str) -> None:
        self.redis.delete(self._reservation_key(driver_id))

    def _profile_key(self, driver_id: str) -> str:
        return f"{self.profile_prefix}:{driver_id}"

    def _reservation_key(self, driver_id: str) -> str:
        return f"{self.reservation_prefix}:{driver_id}"


class InMemoryMatchingStore:
    def __init__(self):
        self.locations: dict[str, dict] = {}
        self.profiles: dict[str, dict] = {}
        self.reservations: dict[str, str] = {}

    def set_driver_location(
        self,
        driver_id: str,
        latitude: float,
        longitude: float,
        timestamp: datetime | None = None,
    ) -> None:
        self.locations[driver_id] = {
            "latitude": latitude,
            "longitude": longitude,
            "timestamp": timestamp or datetime.utcnow(),
        }

    def cache_driver_profile(
        self,
        driver_id: str,
        vehicle_type: str,
        rating: float,
        acceptance_rate: float,
        cancellation_rate: float,
        ttl_seconds: int,
    ) -> None:
        self.profiles[driver_id] = {
            "driver_id": driver_id,
            "vehicle_type": vehicle_type,
            "rating": rating,
            "acceptance_rate": acceptance_rate,
            "cancellation_rate": cancellation_rate,
        }

    def get_nearby_candidates(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        vehicle_type: str,
        limit: int,
    ) -> list[MatchCandidate]:
        candidates = []
        for driver_id, location in self.locations.items():
            if driver_id in self.reservations:
                continue
            profile = self.profiles.get(driver_id)
            if profile is None or profile["vehicle_type"] != vehicle_type:
                continue
            distance_km = distance_between_km(
                latitude,
                longitude,
                location["latitude"],
                location["longitude"],
            )
            if distance_km > radius_km:
                continue
            candidates.append(
                MatchCandidate(
                    driver_id=driver_id,
                    distance_km=distance_km,
                    eta_minutes=estimate_eta_minutes(distance_km),
                    rating=profile["rating"],
                    acceptance_rate=profile["acceptance_rate"],
                    cancellation_rate=profile["cancellation_rate"],
                    vehicle_type=profile["vehicle_type"],
                )
            )
        candidates.sort(key=lambda candidate: candidate.distance_km)
        return candidates[:limit]

    def reserve_driver(self, driver_id: str, request_id: str, ttl_seconds: int) -> bool:
        if driver_id in self.reservations:
            return False
        self.reservations[driver_id] = request_id
        return True

    def release_driver(self, driver_id: str) -> None:
        self.reservations.pop(driver_id, None)


def estimate_eta_minutes(distance_km: float, average_speed_kmh: float = 30) -> float:
    return round((distance_km / average_speed_kmh) * 60, 2)


def distance_between_km(
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
