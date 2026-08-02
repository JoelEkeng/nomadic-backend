import asyncio
import uuid

from modules.matching.ranking import DriverRanker, MatchCandidate
from modules.matching.schemas import MatchRequest
from modules.matching.store import MatchingStore


class MatchingError(Exception):
    pass


class NoMatchingDriversError(MatchingError):
    pass


class DriverAssignmentError(MatchingError):
    pass


class MatchingService:
    def __init__(
        self,
        store: MatchingStore,
        ranker: DriverRanker | None = None,
        reservation_ttl_seconds: int = 30,
    ):
        self.store = store
        self.ranker = ranker or DriverRanker()
        self.reservation_ttl_seconds = reservation_ttl_seconds

    async def assign_driver(self, payload: MatchRequest) -> dict:
        request_id = payload.request_id or str(uuid.uuid4())
        candidates = await asyncio.to_thread(
            self.store.get_nearby_candidates,
            payload.pickup.latitude,
            payload.pickup.longitude,
            payload.radius_km,
            payload.vehicle_type,
            payload.candidate_limit,
        )
        ranked_candidates = self.ranker.rank(candidates)
        if not ranked_candidates:
            raise NoMatchingDriversError("No matching drivers found")

        for candidate in ranked_candidates:
            reserved = await asyncio.to_thread(
                self.store.reserve_driver,
                candidate.driver_id,
                request_id,
                self.reservation_ttl_seconds,
            )
            if reserved:
                return {
                    "request_id": request_id,
                    "assigned_driver_id": candidate.driver_id,
                    "vehicle_type": payload.vehicle_type,
                    "candidate": self._serialize_candidate(candidate),
                }

        raise DriverAssignmentError("Matching drivers are already assigned")

    def rank_candidates(self, candidates: list[MatchCandidate]) -> list[MatchCandidate]:
        return self.ranker.rank(candidates)

    def cache_driver_profile(
        self,
        driver_id: str,
        vehicle_type: str,
        rating: float,
        acceptance_rate: float,
        cancellation_rate: float,
        ttl_seconds: int = 300,
    ) -> None:
        self.store.cache_driver_profile(
            driver_id=driver_id,
            vehicle_type=vehicle_type,
            rating=rating,
            acceptance_rate=acceptance_rate,
            cancellation_rate=cancellation_rate,
            ttl_seconds=ttl_seconds,
        )

    def release_driver(self, driver_id: str) -> None:
        self.store.release_driver(driver_id)

    def _serialize_candidate(self, candidate: MatchCandidate) -> dict:
        return {
            "driver_id": candidate.driver_id,
            "distance_km": round(candidate.distance_km, 4),
            "eta_minutes": candidate.eta_minutes,
            "rating": candidate.rating,
            "acceptance_rate": candidate.acceptance_rate,
            "cancellation_rate": candidate.cancellation_rate,
            "score": candidate.score,
        }
