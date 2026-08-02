from dataclasses import dataclass


@dataclass(frozen=True)
class MatchCandidate:
    driver_id: str
    distance_km: float
    eta_minutes: float
    rating: float
    acceptance_rate: float
    cancellation_rate: float
    vehicle_type: str
    score: float = 0


class DriverRanker:
    max_distance_km = 10.0
    max_eta_minutes = 20.0

    def rank(self, candidates: list[MatchCandidate]) -> list[MatchCandidate]:
        ranked = [
            MatchCandidate(
                driver_id=candidate.driver_id,
                distance_km=candidate.distance_km,
                eta_minutes=candidate.eta_minutes,
                rating=candidate.rating,
                acceptance_rate=candidate.acceptance_rate,
                cancellation_rate=candidate.cancellation_rate,
                vehicle_type=candidate.vehicle_type,
                score=self.score(candidate),
            )
            for candidate in candidates
        ]
        return sorted(
            ranked,
            key=lambda candidate: (
                -candidate.score,
                candidate.eta_minutes,
                candidate.distance_km,
            ),
        )

    def score(self, candidate: MatchCandidate) -> float:
        distance_score = 1 - min(candidate.distance_km / self.max_distance_km, 1)
        eta_score = 1 - min(candidate.eta_minutes / self.max_eta_minutes, 1)
        rating_score = min(candidate.rating / 5, 1)
        acceptance_score = min(candidate.acceptance_rate / 100, 1)
        cancellation_score = 1 - min(candidate.cancellation_rate / 100, 1)

        return round(
            distance_score * 0.35
            + eta_score * 0.25
            + rating_score * 0.20
            + acceptance_score * 0.15
            + cancellation_score * 0.05,
            6,
        )
