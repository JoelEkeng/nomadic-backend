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
from modules.matching.api import get_matching_service
from modules.matching.service import MatchingService
from modules.matching.store import InMemoryMatchingStore
from modules.rides.models import Ride
from modules.students.models import Student
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
            UserRecord(id="student-user"),
            UserRecord(id="driver-user"),
            UserRecord(id="other-user"),
        ]
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def matching_store():
    return InMemoryMatchingStore()


@pytest.fixture()
def matching_service(matching_store):
    return MatchingService(matching_store)


@pytest.fixture()
def current_user_id():
    return {"id": "student-user"}


@pytest.fixture()
def client(db_session, matching_service, current_user_id):
    def override_get_db():
        yield db_session

    async def override_current_user():
        return AuthenticatedUser(id=current_user_id["id"])

    def override_matching_service():
        return matching_service

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_matching_service] = override_matching_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_verified_student(db_session) -> Student:
    student = Student(
        user_id="student-user",
        student_number="UG-1001",
        verification_status="verified",
    )
    db_session.add(student)
    db_session.commit()
    return student


def create_verified_driver(db_session) -> Driver:
    driver = Driver(
        user_id="driver-user",
        license_number="DL-1001",
        license_expiry=date.today() + timedelta(days=365),
        verification_status="verified",
        availability_status="available",
        online_status=True,
    )
    db_session.add(driver)
    db_session.flush()
    db_session.add(
        Vehicle(
            driver_id=driver.id,
            registration_number="CAR-1001",
            make="Toyota",
            model="Corolla",
            year=2022,
            color="White",
            vehicle_type="car",
            insurance_expiry=date.today() + timedelta(days=365),
            inspection_status="approved",
        )
    )
    db_session.commit()
    return driver


def ride_payload() -> dict:
    return {
        "pickup_location": {
            "latitude": 5.6037,
            "longitude": -0.1870,
            "address": "Campus gate",
        },
        "destination_location": {
            "latitude": 5.6500,
            "longitude": -0.2000,
            "address": "Hostel",
        },
        "vehicle_type": "car",
    }


def cache_driver(matching_store, driver: Driver) -> None:
    matching_store.set_driver_location(driver.id, 5.6040, -0.1872)
    matching_store.cache_driver_profile(
        driver_id=driver.id,
        vehicle_type="car",
        rating=4.8,
        acceptance_rate=95,
        cancellation_rate=2,
        ttl_seconds=300,
    )


def create_assigned_ride(
    db_session,
    student: Student,
    driver: Driver,
    requested_at=None,
) -> Ride:
    data = {}
    if requested_at is not None:
        data["requested_at"] = requested_at
    ride = Ride(
        student_id=student.id,
        driver_id=driver.id,
        pickup_location="Campus gate",
        destination_location="Hostel",
        distance="5.40",
        estimated_fare="12.45",
        status="MATCHING",
        **data,
    )
    db_session.add(ride)
    db_session.commit()
    return ride


def test_create_ride_prices_and_assigns_matching_driver(
    client, db_session, matching_store
):
    create_verified_student(db_session)
    driver = create_verified_driver(db_session)
    cache_driver(matching_store, driver)

    response = client.post("/rides", json=ride_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["student_id"]
    assert body["driver_id"] == driver.id
    assert body["status"] == "MATCHING"
    assert body["pickup_location"] == "Campus gate"
    assert body["destination_location"] == "Hostel"
    assert float(body["distance"]) > 0
    assert float(body["estimated_fare"]) > 0
    db_session.refresh(driver)
    assert driver.availability_status == "busy"


def test_create_ride_stays_matching_when_no_driver_available(client, db_session):
    create_verified_student(db_session)

    response = client.post("/rides", json=ride_payload())

    assert response.status_code == 201
    assert response.json()["status"] == "MATCHING"
    assert response.json()["driver_id"] is None


def test_unverified_student_cannot_create_ride(client, db_session):
    db_session.add(
        Student(
            user_id="student-user",
            student_number="UG-1001",
            verification_status="pending",
        )
    )
    db_session.commit()

    response = client.post("/rides", json=ride_payload())

    assert response.status_code == 403
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "PROFILE_INCOMPLETE"
    assert body["message"] == "Complete your registration before requesting rides."
    assert body["next_step"]["verify_student"] is True


def test_driver_can_accept_start_and_complete_ride(
    client, db_session, current_user_id
):
    student = create_verified_student(db_session)
    driver = create_verified_driver(db_session)
    ride = create_assigned_ride(db_session, student, driver)
    current_user_id["id"] = "driver-user"

    accept_response = client.post(f"/rides/{ride.id}/accept")
    assert accept_response.status_code == 200
    assert accept_response.json()["status"] == "ACCEPTED"

    arriving_response = client.post(f"/rides/{ride.id}/arriving")
    assert arriving_response.status_code == 200
    assert arriving_response.json()["status"] == "ARRIVING"

    start_response = client.post(f"/rides/{ride.id}/start")
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "STARTED"

    complete_response = client.post(
        f"/rides/{ride.id}/complete",
        json={"final_fare": "15.50"},
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "COMPLETED"
    assert complete_response.json()["final_fare"] == "15.50"
    db_session.refresh(driver)
    assert driver.total_trips == 1
    assert str(driver.earnings) == "15.50"
    assert driver.availability_status == "available"


def test_invalid_lifecycle_transition_is_rejected(
    client, db_session, current_user_id
):
    student = create_verified_student(db_session)
    driver = create_verified_driver(db_session)
    ride = create_assigned_ride(db_session, student, driver)
    current_user_id["id"] = "driver-user"

    response = client.post(f"/rides/{ride.id}/complete", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == "Ride can only be completed after start"


def test_student_can_cancel_ride_and_history_is_ordered(client, db_session):
    student = create_verified_student(db_session)
    driver = create_verified_driver(db_session)
    now = datetime.now(timezone.utc)
    old_ride = create_assigned_ride(
        db_session, student, driver, requested_at=now - timedelta(minutes=5)
    )
    new_ride = create_assigned_ride(db_session, student, driver, requested_at=now)

    cancel_response = client.post(f"/rides/{new_ride.id}/cancel", json={})
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "CANCELLED"

    history_response = client.get("/rides/history")

    assert history_response.status_code == 200
    assert [ride["id"] for ride in history_response.json()] == [
        new_ride.id,
        old_ride.id,
    ]
