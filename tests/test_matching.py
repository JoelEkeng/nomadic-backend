import asyncio

import pytest
from fastapi.testclient import TestClient

from core.auth import AuthenticatedUser, get_current_user
from main import app
from modules.matching.api import get_matching_service
from modules.matching.ranking import MatchCandidate
from modules.matching.service import MatchingService, NoMatchingDriversError
from modules.matching.store import InMemoryMatchingStore


@pytest.fixture()
def matching_store():
    return InMemoryMatchingStore()


@pytest.fixture()
def matching_service(matching_store):
    return MatchingService(matching_store, reservation_ttl_seconds=30)


@pytest.fixture()
def client(matching_service):
    async def override_current_user():
        return AuthenticatedUser(id="student-user")

    def override_matching_service():
        return matching_service

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_matching_service] = override_matching_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def match_payload(vehicle_type: str = "car") -> dict:
    return {
        "request_id": "ride-request-1",
        "pickup": {"latitude": 5.6037, "longitude": -0.1870},
        "destination": {"latitude": 5.6500, "longitude": -0.2000},
        "vehicle_type": vehicle_type,
        "radius_km": 10,
        "candidate_limit": 10,
    }


def cache_driver(
    store: InMemoryMatchingStore,
    driver_id: str,
    latitude: float,
    longitude: float,
    vehicle_type: str = "car",
    rating: float = 4.5,
    acceptance_rate: float = 90,
    cancellation_rate: float = 5,
) -> None:
    store.set_driver_location(driver_id, latitude, longitude)
    store.cache_driver_profile(
        driver_id=driver_id,
        vehicle_type=vehicle_type,
        rating=rating,
        acceptance_rate=acceptance_rate,
        cancellation_rate=cancellation_rate,
        ttl_seconds=300,
    )


def test_ranking_algorithm_balances_distance_eta_and_quality(matching_service):
    close_low_quality = MatchCandidate(
        driver_id="close-low-quality",
        distance_km=0.5,
        eta_minutes=1,
        rating=2.0,
        acceptance_rate=40,
        cancellation_rate=40,
        vehicle_type="car",
    )
    farther_high_quality = MatchCandidate(
        driver_id="farther-high-quality",
        distance_km=1.2,
        eta_minutes=2.4,
        rating=4.9,
        acceptance_rate=98,
        cancellation_rate=1,
        vehicle_type="car",
    )

    ranked = matching_service.rank_candidates(
        [close_low_quality, farther_high_quality]
    )

    assert ranked[0].driver_id == "farther-high-quality"
    assert ranked[0].score > ranked[1].score


def test_assign_driver_uses_best_ranked_nearby_candidate(
    client, matching_store
):
    cache_driver(
        matching_store,
        "driver-close-bad",
        5.6040,
        -0.1872,
        rating=2.0,
        acceptance_rate=50,
        cancellation_rate=35,
    )
    cache_driver(
        matching_store,
        "driver-best",
        5.6100,
        -0.1900,
        rating=4.9,
        acceptance_rate=99,
        cancellation_rate=1,
    )

    response = client.post("/matching/assign", json=match_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "ride-request-1"
    assert body["assigned_driver_id"] == "driver-best"
    assert matching_store.reservations["driver-best"] == "ride-request-1"


def test_matching_filters_by_vehicle_type(client, matching_store):
    cache_driver(matching_store, "car-driver", 5.6040, -0.1872, vehicle_type="car")
    cache_driver(matching_store, "van-driver", 5.6040, -0.1872, vehicle_type="van")

    response = client.post("/matching/assign", json=match_payload("van"))

    assert response.status_code == 200
    assert response.json()["assigned_driver_id"] == "van-driver"


def test_matching_skips_reserved_driver_and_assigns_next_best(
    client, matching_store
):
    cache_driver(
        matching_store,
        "best-driver",
        5.6040,
        -0.1872,
        rating=5.0,
        acceptance_rate=100,
        cancellation_rate=0,
    )
    cache_driver(
        matching_store,
        "next-driver",
        5.6050,
        -0.1880,
        rating=4.8,
        acceptance_rate=95,
        cancellation_rate=2,
    )
    matching_store.reserve_driver("best-driver", "other-request", ttl_seconds=30)

    response = client.post("/matching/assign", json=match_payload())

    assert response.status_code == 200
    assert response.json()["assigned_driver_id"] == "next-driver"


def test_matching_returns_404_when_no_driver_matches(client, matching_store):
    cache_driver(matching_store, "van-driver", 5.6040, -0.1872, vehicle_type="van")

    response = client.post("/matching/assign", json=match_payload("car"))

    assert response.status_code == 404
    assert response.json()["detail"] == "No matching drivers found"


def test_matching_service_raises_when_candidate_pool_empty(matching_service):
    with pytest.raises(NoMatchingDriversError):
        asyncio.run(
            matching_service.assign_driver(matching_service_request(vehicle_type="car"))
        )


def matching_service_request(vehicle_type: str):
    from modules.matching.schemas import GeoPoint, MatchRequest

    return MatchRequest(
        request_id="empty-request",
        pickup=GeoPoint(latitude=5.6037, longitude=-0.1870),
        destination=GeoPoint(latitude=5.6500, longitude=-0.2000),
        vehicle_type=vehicle_type,
        radius_km=10,
        candidate_limit=10,
    )
