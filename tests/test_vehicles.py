from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.auth import AuthenticatedUser, get_current_user
from core.database import Base, get_db
from main import app
from modules.drivers.models import Driver
from modules.users.models import UserRecord
from modules.vehicles.models import Vehicle


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
            ),
            Driver(
                user_id="driver-user-2",
                license_number="DL-2002",
                license_expiry=date.today() + timedelta(days=365),
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
def client(db_session, auth_state):
    def override_get_db():
        yield db_session

    async def override_current_user():
        return auth_state["user"]

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def vehicle_payload(registration_number: str = " ab-1234-26 ") -> dict:
    return {
        "registration_number": registration_number,
        "make": " Toyota ",
        "model": "Corolla",
        "year": 2021,
        "color": "White",
        "vehicle_type": "car",
        "insurance_expiry": str(date.today() + timedelta(days=90)),
    }


def register_vehicle(client, registration_number: str = " ab-1234-26 "):
    return client.post("/vehicles", json=vehicle_payload(registration_number))


def test_driver_registers_vehicle_with_pending_inspection(client, db_session):
    response = register_vehicle(client)

    assert response.status_code == 201
    body = response.json()
    assert body["registration_number"] == "AB-1234-26"
    assert body["make"] == "Toyota"
    assert body["inspection_status"] == "pending"
    vehicle = db_session.query(Vehicle).one()
    assert vehicle.driver.user_id == "driver-user-1"


def test_vehicle_registration_requires_driver_profile(client, auth_state):
    auth_state["user"] = AuthenticatedUser(id="admin-user")

    response = register_vehicle(client)

    assert response.status_code == 404
    assert response.json()["detail"] == "Driver profile not found"


def test_vehicle_registration_rejects_expired_insurance(client):
    payload = vehicle_payload()
    payload["insurance_expiry"] = str(date.today() - timedelta(days=1))

    response = client.post("/vehicles", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Vehicle insurance has expired"


def test_vehicle_registration_rejects_duplicate_registration(client, auth_state):
    assert register_vehicle(client, "DUP-100").status_code == 201
    auth_state["user"] = AuthenticatedUser(id="driver-user-2")

    response = register_vehicle(client, "dup-100")

    assert response.status_code == 409
    assert response.json()["detail"] == "Vehicle could not be registered"


def test_driver_can_list_get_update_and_delete_own_vehicle(client, db_session):
    vehicle_id = register_vehicle(client).json()["id"]

    list_response = client.get("/vehicles")
    assert list_response.status_code == 200
    assert [vehicle["id"] for vehicle in list_response.json()] == [vehicle_id]

    get_response = client.get(f"/vehicles/{vehicle_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == vehicle_id

    vehicle = db_session.get(Vehicle, vehicle_id)
    vehicle.inspection_status = "approved"
    db_session.commit()

    update_response = client.patch(
        f"/vehicles/{vehicle_id}",
        json={"color": "Black", "registration_number": "new-123"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["color"] == "Black"
    assert update_response.json()["registration_number"] == "NEW-123"
    assert update_response.json()["inspection_status"] == "pending"

    delete_response = client.delete(f"/vehicles/{vehicle_id}")
    assert delete_response.status_code == 204
    assert db_session.get(Vehicle, vehicle_id) is None


def test_driver_cannot_access_another_drivers_vehicle(client, auth_state):
    auth_state["user"] = AuthenticatedUser(id="driver-user-2")
    vehicle_id = register_vehicle(client, "OTHER-100").json()["id"]
    auth_state["user"] = AuthenticatedUser(id="driver-user-1")

    response = client.get(f"/vehicles/{vehicle_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Vehicle not found"


def test_vehicle_update_validates_blank_text(client):
    vehicle_id = register_vehicle(client).json()["id"]

    response = client.patch(f"/vehicles/{vehicle_id}", json={"make": "   "})

    assert response.status_code == 422


def test_non_admin_cannot_approve_vehicle(client):
    vehicle_id = register_vehicle(client).json()["id"]

    response = client.post(f"/vehicles/admin/{vehicle_id}/approve")

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin permissions required"


def test_admin_lists_approves_and_rejects_vehicles(client, auth_state):
    first_vehicle_id = register_vehicle(client, "APPROVE-1").json()["id"]
    second_vehicle_id = register_vehicle(client, "REJECT-1").json()["id"]
    auth_state["user"] = AuthenticatedUser(id="admin-user", role="admin")

    approve_response = client.post(f"/vehicles/admin/{first_vehicle_id}/approve")
    reject_response = client.post(f"/vehicles/admin/{second_vehicle_id}/reject")
    list_response = client.get("/vehicles/admin/all", params={"inspection_status": "approved"})

    assert approve_response.status_code == 200
    assert approve_response.json()["inspection_status"] == "approved"
    assert reject_response.status_code == 200
    assert reject_response.json()["inspection_status"] == "rejected"
    assert list_response.status_code == 200
    assert [vehicle["id"] for vehicle in list_response.json()] == [first_vehicle_id]


def test_driver_must_have_approved_vehicle_before_going_online(
    client, auth_state, db_session
):
    driver = db_session.query(Driver).filter(Driver.user_id == "driver-user-1").one()
    driver.verification_status = "verified"
    db_session.commit()

    no_vehicle_response = client.post("/drivers/online")
    assert no_vehicle_response.status_code == 403
    body = no_vehicle_response.json()
    assert body["error_code"] == "PROFILE_INCOMPLETE"
    assert body["next_step"]["register_vehicle"] is True
    assert body["next_step"]["approve_vehicle"] is True

    vehicle_id = register_vehicle(client).json()["id"]
    auth_state["user"] = AuthenticatedUser(id="admin-user", role="admin")
    assert client.post(f"/vehicles/admin/{vehicle_id}/approve").status_code == 200

    auth_state["user"] = AuthenticatedUser(id="driver-user-1")
    online_response = client.post("/drivers/online")

    assert online_response.status_code == 200
    assert online_response.json()["online_status"] is True
    assert online_response.json()["availability_status"] == "available"
