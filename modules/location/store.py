import os
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Protocol


class LocationStore(Protocol):
    def update_driver_location(
        self,
        driver_id: str,
        latitude: float,
        longitude: float,
        timestamp: datetime,
        ttl_seconds: int,
    ) -> None:
        pass

    def get_nearby_drivers(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int,
    ) -> list[dict]:
        pass

    def remove_driver(self, driver_id: str) -> None:
        pass

    def remove_stale_drivers(self, cutoff_timestamp: datetime) -> int:
        pass


class RedisLocationStore:
    geo_key = "driver_locations:geo"
    active_key = "driver_locations:last_seen"
    metadata_prefix = "driver_locations:data"

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

    def update_driver_location(
        self,
        driver_id: str,
        latitude: float,
        longitude: float,
        timestamp: datetime,
        ttl_seconds: int,
    ) -> None:
        metadata_key = self._metadata_key(driver_id)
        epoch = timestamp.timestamp()
        pipe = self.redis.pipeline(transaction=False)
        pipe.geoadd(self.geo_key, [longitude, latitude, driver_id])
        pipe.hset(
            metadata_key,
            mapping={
                "driver_id": driver_id,
                "latitude": latitude,
                "longitude": longitude,
                "timestamp": timestamp.isoformat(),
            },
        )
        pipe.expire(metadata_key, ttl_seconds)
        pipe.zadd(self.active_key, {driver_id: epoch})
        pipe.execute()

    def get_nearby_drivers(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int,
    ) -> list[dict]:
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
            pipe.hgetall(self._metadata_key(driver_id))
        metadata_rows = pipe.execute()

        nearby = []
        for (driver_id, distance_km), metadata in zip(ordered, metadata_rows):
            if not metadata:
                self.remove_driver(driver_id)
                continue
            nearby.append(
                {
                    "driver_id": driver_id,
                    "latitude": float(metadata["latitude"]),
                    "longitude": float(metadata["longitude"]),
                    "timestamp": datetime.fromisoformat(metadata["timestamp"]),
                    "distance_km": distance_km,
                }
            )
        return nearby

    def remove_driver(self, driver_id: str) -> None:
        pipe = self.redis.pipeline(transaction=False)
        pipe.zrem(self.geo_key, driver_id)
        pipe.zrem(self.active_key, driver_id)
        pipe.delete(self._metadata_key(driver_id))
        pipe.execute()

    def remove_stale_drivers(self, cutoff_timestamp: datetime) -> int:
        stale_driver_ids = self.redis.zrangebyscore(
            self.active_key,
            min="-inf",
            max=cutoff_timestamp.timestamp(),
        )
        if not stale_driver_ids:
            return 0

        pipe = self.redis.pipeline(transaction=False)
        for driver_id in stale_driver_ids:
            pipe.zrem(self.geo_key, driver_id)
            pipe.zrem(self.active_key, driver_id)
            pipe.delete(self._metadata_key(driver_id))
        pipe.execute()
        return len(stale_driver_ids)

    def _metadata_key(self, driver_id: str) -> str:
        return f"{self.metadata_prefix}:{driver_id}"


class InMemoryLocationStore:
    def __init__(self):
        self.locations: dict[str, dict] = {}

    def update_driver_location(
        self,
        driver_id: str,
        latitude: float,
        longitude: float,
        timestamp: datetime,
        ttl_seconds: int,
    ) -> None:
        self.locations[driver_id] = {
            "driver_id": driver_id,
            "latitude": latitude,
            "longitude": longitude,
            "timestamp": timestamp,
            "expires_at": datetime.now(timezone.utc).timestamp() + ttl_seconds,
        }

    def get_nearby_drivers(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int,
    ) -> list[dict]:
        nearby = []
        for location in self.locations.values():
            distance_km = _distance_km(
                latitude,
                longitude,
                location["latitude"],
                location["longitude"],
            )
            if distance_km <= radius_km:
                nearby.append({**location, "distance_km": distance_km})
        nearby.sort(key=lambda item: item["distance_km"])
        return nearby[:limit]

    def remove_driver(self, driver_id: str) -> None:
        self.locations.pop(driver_id, None)

    def remove_stale_drivers(self, cutoff_timestamp: datetime) -> int:
        stale_driver_ids = [
            driver_id
            for driver_id, location in self.locations.items()
            if location["timestamp"] <= cutoff_timestamp
        ]
        for driver_id in stale_driver_ids:
            self.remove_driver(driver_id)
        return len(stale_driver_ids)


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
