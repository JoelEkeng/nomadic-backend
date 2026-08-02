from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.auth import AuthenticatedUser, get_current_user
from core.database import Base, get_db
from core.utils.name_parser import split_full_name
from main import app
from modules.rides.models import Ride
from modules.students.models import Student
from modules.students.repository import StudentRepository
from modules.students.schemas import StudentProfileCreate
from modules.students.service import (
    StudentForbiddenError,
    StudentNotVerifiedError,
    StudentService,
)
from modules.users.models import BetterAuthUser


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


def make_student_user(**overrides) -> AuthenticatedUser:
    defaults = {
        "id": "betterauth-user-1",
        "email": "student@university.edu",
        "name": "Jane Doe",
        "phone_number": None,
        "role": "passenger",
        "email_verified": True,
    }
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


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
            BetterAuthUser(id="betterauth-user-1"),
            BetterAuthUser(id="betterauth-user-2"),
        ]
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    async def override_current_user():
        return make_student_user()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def unverified_client(db_session):
    def override_get_db():
        yield db_session

    async def override_current_user():
        return make_student_user(email_verified=False)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def driver_client(db_session):
    def override_get_db():
        yield db_session

    async def override_current_user():
        return make_student_user(
            id="driver-user-1", email="driver@example.com", role="driver"
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client


def create_student(db_session, user_id: str = "betterauth-user-1") -> Student:
    service = StudentService(StudentRepository(db_session))
    return service.create_profile(
        user_id,
        StudentProfileCreate(preferred_pickup_location="Main gate"),
    )


def test_get_student_profile_creates_profile_on_first_request(client):
    response = client.get("/students/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "betterauth-user-1"
    assert body["first_name"] == "Jane"
    assert body["last_name"] == "Doe"
    assert body["student_number"].startswith("NMD-")
    assert body["verification_status"] == "verified"


def test_get_student_profile_is_idempotent(client):
    first = client.get("/students/profile").json()
    second = client.get("/students/profile").json()

    assert first["id"] == second["id"]
    assert first["student_number"] == second["student_number"]
    assert first["user_id"] == second["user_id"]


def test_get_student_profile_requires_verified_email(unverified_client):
    response = unverified_client.get("/students/profile")

    assert response.status_code == 403
    assert "email" in response.json()["detail"].lower()


def test_get_student_profile_rejects_non_student_role(driver_client):
    response = driver_client.get("/students/profile")

    assert response.status_code == 403


def test_post_profile_is_deprecated_and_returns_profile(client):
    """The old manual creation endpoint is deprecated but returns an auto-bootstrapped profile."""
    response = client.post("/students/profile", json={})

    assert response.status_code == 410
    body = response.json()
    assert body["user_id"] == "betterauth-user-1"


def test_update_profile_after_bootstrap(client):
    client.get("/students/profile")

    response = client.patch(
        "/students/profile",
        json={
            "preferred_pickup_location": "Science market",
            "emergency_contact": "+1234567890",
            "phone_number": "+10987654321",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preferred_pickup_location"] == "Science market"
    assert body["emergency_contact"] == "+1234567890"
    assert body["phone_number"] == "+10987654321"


def test_update_profile_without_existing_profile_bootstrap_then_updates(client):
    response = client.patch(
        "/students/profile",
        json={"preferred_pickup_location": "Library"},
    )

    assert response.status_code == 200
    assert response.json()["preferred_pickup_location"] == "Library"


def test_ensure_profile_copies_phone_number(db_session):
    service = StudentService(StudentRepository(db_session))
    user = make_student_user(phone_number="+233555000000")

    student = service.ensure_profile(user)

    assert student.phone_number == "+233555000000"


def test_ensure_profile_validates_role(db_session):
    service = StudentService(StudentRepository(db_session))
    user = make_student_user(role="driver")

    with pytest.raises(StudentForbiddenError):
        service.ensure_profile(user)


def test_ensure_profile_requires_verified_email(db_session):
    service = StudentService(StudentRepository(db_session))
    user = make_student_user(email_verified=False)

    with pytest.raises(StudentNotVerifiedError):
        service.ensure_profile(user)


def test_ensure_profile_is_idempotent_under_race(db_session):
    service = StudentService(StudentRepository(db_session))
    user = make_student_user()

    first = service.ensure_profile(user)

    # Simulating a concurrent request by bypassing the early-exit path and forcing a creation attempt.
    with patch.object(
        StudentRepository,
        "get_by_user_id",
        side_effect=[None, first],
    ):
        second = service.ensure_profile(user)

    assert first.id == second.id
    assert first.student_number == second.student_number


def test_split_full_name():
    assert split_full_name("John Doe") == ("John", "Doe")
    assert split_full_name("John Michael Doe") == ("John", "Michael Doe")
    assert split_full_name("Prince") == ("Prince", "")
    assert split_full_name("  Multiple   Spaces  ") == ("Multiple", "Spaces")
    assert split_full_name("") == ("", "")
    assert split_full_name(None) == ("", "")


def test_generate_student_number_is_unique(db_session):
    repository = StudentRepository(db_session)
    # Persist one student so the SQLite count-based fallback advances between calls.
    repository.create(
        "user-gen-1",
        {"first_name": "A", "last_name": "", "verification_status": "verified"},
    )
    first = repository.generate_student_number()
    repository.create(
        "user-gen-2",
        {"first_name": "B", "last_name": "", "verification_status": "verified"},
    )
    second = repository.generate_student_number()

    assert first != second
    assert first.startswith("NMD-")
    assert second.startswith("NMD-")


def test_student_profile_is_required_to_request_rides(db_session):
    service = StudentService(StudentRepository(db_session))

    with pytest.raises(Exception):
        service.ensure_can_request_ride("betterauth-user-1")


def test_student_can_request_rides_after_bootstrap(db_session):
    service = StudentService(StudentRepository(db_session))
    user = make_student_user()
    service.ensure_profile(user)

    assert service.ensure_can_request_ride(user.id) is not None


def test_student_clears_the_verification_checklist_after_bootstrap(client):
    """End to end: GET /students/profile creates a verified student profile."""
    assert client.get("/students/profile").status_code == 200

    body = client.get("/verification/status").json()

    assert body["verification"]["verified"] is True
    assert body["error_code"] is None
    assert all(step["satisfied"] for step in body["verification"]["steps"])


def test_manage_favourite_locations(client):
    client.get("/students/profile")  # bootstrap

    create_response = client.post(
        "/students/favourite-locations",
        json={
            "name": "Main gate",
            "address": "University main gate",
            "latitude": "5.650000",
            "longitude": "-0.190000",
        },
    )
    assert create_response.status_code == 201
    location_id = create_response.json()["id"]

    update_response = client.patch(
        f"/students/favourite-locations/{location_id}",
        json={"name": "Night market"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Night market"

    list_response = client.get("/students/favourite-locations")
    assert list_response.status_code == 200
    assert [location["name"] for location in list_response.json()] == ["Night market"]

    delete_response = client.delete(f"/students/favourite-locations/{location_id}")
    assert delete_response.status_code == 204
    assert client.get("/students/favourite-locations").json() == []


def test_get_student_rides_returns_history_ordered_by_requested_at(client, db_session):
    client.get("/students/profile")  # bootstrap
    student = StudentRepository(db_session).get_by_user_id("betterauth-user-1")

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Ride(
                id="ride-old",
                student_id=student.id,
                status="COMPLETED",
                pickup_location="Campus",
                destination_location="Airport",
                distance="10.00",
                estimated_fare="20.00",
                final_fare="20.00",
                requested_at=now - timedelta(hours=2),
                completed_at=now - timedelta(hours=1),
            ),
            Ride(
                id="ride-new",
                student_id=student.id,
                status="MATCHING",
                pickup_location="Library",
                destination_location="Hostel",
                distance="3.00",
                estimated_fare="8.25",
                requested_at=now,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/students/rides")

    assert response.status_code == 200
    assert [ride["id"] for ride in response.json()] == ["ride-new", "ride-old"]
