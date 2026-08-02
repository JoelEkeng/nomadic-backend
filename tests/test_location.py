from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.auth import AuthenticatedUser, get_current_user
from core.database import Base, get_db
from main import app
from modules.drivers.models import Driver
from modules.drivers.repository import DriverRepository
from modules.location.api import get_location_service
from modules.location.service import LocationService
from modules.location.store import InMemoryLocationStore
from modules.users.models import UserRecord


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture()
def db_session():
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    db.add_all(
        [
            UserRecord(id="driver-user-1"),
            UserRecord(id="driver-user-2"),
            UserRecord(id="student-user"),
            UserRecord(id="admin-user"),
        ]
    )
    db.flush()
    db.add_all(
        [
            Driver(
                user_id="driver-user-1",
                license_number="DL-1001",
                license_expiry=date.today() + timedelta(days=365),
                verification_status="verified",
                availability_status="available",
                online_status=True,
            ),
            Driver(
                user_id="driver-user-2",
                license_number="DL-2002",
                license_expiry=date.today() + timedelta(days=365),
                verification_status="verified",
                availability_status="available",
                online_status=True,
            ),
        ]
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def auth_state():
    return {"user": AuthenticatedUser(id="driver-user-1")}


@pytest.fixture()
def location_store():
    return InMemoryLocationStore()


@pytest.fixture()
def client(db_session, auth_state, location_store):
    def override_get_db():
        yield db_session

    async def override_current_user():
        return auth_state["user"]

    def override_location_service():
        return LocationService(
            DriverRepository(db_session),
            location_store,
            location_ttl_seconds=90,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_location_service] = override_location_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def location_payload(
    latitude: float = 5.6037,
    longitude: float = -0.1870,
    timestamp: datetime | None = None,
) -> dict:
    timestamp = timestamp or datetime.now(timezone.utc)
    return {
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": timestamp.isoformat(),
    }


def test_driver_updates_location_in_redis_backed_store(client, db_session, location_store):
    driver = (
        db_session.query(Driver).filter(Driver.user_id == "driver-user-1").one()
    )

    response = client.put("/locations/drivers/me", json=location_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["driver_id"] == driver.id
    assert body["latitude"] == 5.6037
    assert driver.id in location_store.locations


def test_unavailable_driver_cannot_publish_location(client, db_session):
    driver = (
        db_session.query(Driver).filter(Driver.user_id == "driver-user-1").one()
    )
    driver.online_status = False
    db_session.commit()

    response = client.put("/locations/drivers/me", json=location_payload())

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Driver must be online and available to publish location"
    )


def test_location_update_requires_driver_profile(client, auth_state):
    auth_state["user"] = AuthenticatedUser(id="student-user")

    response = client.put("/locations/drivers/me", json=location_payload())

    assert response.status_code == 404
    assert response.json()["detail"] == "Driver profile not found"


def test_get_nearby_drivers_returns_sorted_locations(client, auth_state):
    assert client.put("/locations/drivers/me", json=location_payload()).status_code == 200
    auth_state["user"] = AuthenticatedUser(id="driver-user-2")
    assert (
        client.put(
            "/locations/drivers/me",
            json=location_payload(latitude=5.6500, longitude=-0.2000),
        ).status_code
        == 200
    )
    auth_state["user"] = AuthenticatedUser(id="student-user")

    response = client.get(
        "/locations/drivers/nearby",
        params={
            "latitude": 5.6037,
            "longitude": -0.1870,
            "radius_km": 10,
            "limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["distance_km"] <= body[1]["distance_km"]


def test_driver_removes_own_location_when_offline(client, db_session, location_store):
    driver = (
        db_session.query(Driver).filter(Driver.user_id == "driver-user-1").one()
    )
    assert client.put("/locations/drivers/me", json=location_payload()).status_code == 200

    response = client.delete("/locations/drivers/me")

    assert response.status_code == 204
    assert driver.id not in location_store.locations


def test_admin_cleanup_removes_stale_offline_drivers(client, auth_state, location_store):
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert (
        client.put(
            "/locations/drivers/me",
            json=location_payload(timestamp=stale_time),
        ).status_code
        == 200
    )
    auth_state["user"] = AuthenticatedUser(id="admin-user", role="admin")

    response = client.post("/locations/admin/cleanup")

    assert response.status_code == 200
    assert response.json()["removed"] == 1
    assert location_store.locations == {}


def test_non_admin_cannot_run_location_cleanup(client):
    response = client.post("/locations/admin/cleanup")

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin permissions required"
