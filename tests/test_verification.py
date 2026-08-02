"""Tests for the centralised verification guard.

Covers the service rules, the shared 403 contract, every guarded endpoint, and
the endpoints that deliberately stay open to unverified users.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.auth import AuthenticatedUser, get_current_user
from core.database import Base, get_db
from core.verification import (
    ERROR_CODE_PROFILE_INCOMPLETE,
    VerificationRequiredError,
    VerificationService,
)
from main import app
from modules.drivers.models import Driver
from modules.kyc.models import KYCApplication, KYCDocument
from modules.matching.api import get_matching_service
from modules.matching.service import MatchingService
from modules.matching.store import InMemoryMatchingStore
from modules.rides.models import Ride
from modules.students.models import Student
from modules.users.models import BetterAuthUser
from modules.vehicles.models import Vehicle

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

STUDENT_USER = "student-user"
DRIVER_USER = "driver-user"
STRANGER_USER = "stranger-user"


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
            BetterAuthUser(id=STUDENT_USER),
            BetterAuthUser(id=DRIVER_USER),
            BetterAuthUser(id=STRANGER_USER),
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
    return {"user": AuthenticatedUser(id=STUDENT_USER)}


@pytest.fixture()
def matching_service():
    return MatchingService(InMemoryMatchingStore())


@pytest.fixture()
def client(db_session, auth_state, matching_service):
    def override_get_db():
        yield db_session

    async def override_current_user():
        return auth_state["user"]

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_matching_service] = lambda: matching_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ----------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------
def make_student(db_session, *, verified: bool = False) -> Student:
    student = Student(
        user_id=STUDENT_USER,
        student_number="NMD-TEST-00001",
        preferred_pickup_location="Main gate",
        verification_status="verified" if verified else "pending",
    )
    db_session.add(student)
    db_session.commit()
    return student


def make_driver(
    db_session,
    *,
    verified: bool = False,
    licence_valid: bool = True,
    vehicle: str | None = None,
) -> Driver:
    """``vehicle`` is ``None``, ``"pending"`` or ``"approved"``."""
    driver = Driver(
        user_id=DRIVER_USER,
        license_number="DL-1001",
        license_expiry=(
            date.today() + timedelta(days=365)
            if licence_valid
            else date.today() - timedelta(days=1)
        ),
        verification_status="verified" if verified else "pending",
    )
    db_session.add(driver)
    db_session.flush()
    if vehicle is not None:
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
                inspection_status=vehicle,
            )
        )
    db_session.commit()
    return driver


def make_kyc_application(
    db_session, user_id: str, applicant_type: str, status: str = "PENDING"
) -> KYCApplication:
    application = KYCApplication(
        user_id=user_id, applicant_type=applicant_type, status=status
    )
    application.documents = [
        KYCDocument(type="id_card", file_url="https://example.test/id.png")
    ]
    db_session.add(application)
    db_session.commit()
    return application


def fully_verified_driver(db_session) -> Driver:
    driver = make_driver(db_session, verified=True, vehicle="approved")
    make_kyc_application(db_session, DRIVER_USER, "driver", "APPROVED")
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


def assigned_ride(db_session, student: Student, driver: Driver, status="MATCHING") -> Ride:
    ride = Ride(
        student_id=student.id,
        driver_id=driver.id,
        pickup_location="Campus gate",
        destination_location="Hostel",
        distance="5.40",
        estimated_fare="12.45",
        status=status,
    )
    db_session.add(ride)
    db_session.commit()
    return ride


def assert_guard_payload(response, *, expected_missing: list[str]):
    """Assert the shared verification 403 contract."""
    assert response.status_code == 403
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == ERROR_CODE_PROFILE_INCOMPLETE
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["next_step"], dict) and body["next_step"]
    for key in expected_missing:
        assert body["next_step"][key] is True, f"expected {key} to be outstanding"
    return body


# ----------------------------------------------------------------------
# Service rules
# ----------------------------------------------------------------------
def test_student_status_reports_every_step_outstanding_for_new_user(db_session):
    status = VerificationService(db_session).student_status(STUDENT_USER)

    assert status.is_verified is False
    assert status.next_step() == {
        "complete_profile": True,
    }
    assert status.progress_percent == 0
    assert status.next_step_key == "complete_profile"


def test_student_status_tracks_progress_as_steps_complete(db_session):
    service = VerificationService(db_session)

    make_student(db_session)
    status = service.student_status(STUDENT_USER)

    assert status.is_verified is True
    assert status.progress_percent == 100
    assert status.next_step_key is None
    assert status.next_step() == {
        "complete_profile": False,
    }


def test_student_status_is_verified_once_profile_exists(db_session):
    make_student(db_session)

    status = VerificationService(db_session).student_status(STUDENT_USER)

    assert status.is_verified is True
    assert status.progress_percent == 100


def test_driver_status_requires_profile_vehicle_and_verification(db_session):
    service = VerificationService(db_session)

    assert service.driver_status(DRIVER_USER).next_step() == {
        "complete_profile": True,
        "register_vehicle": True,
        "approve_vehicle": True,
        "upload_documents": True,
        "verify_driver": True,
    }

    make_driver(db_session, vehicle="pending")
    with_pending_vehicle = service.driver_status(DRIVER_USER)
    assert with_pending_vehicle.next_step()["register_vehicle"] is False
    assert with_pending_vehicle.next_step()["approve_vehicle"] is True
    assert with_pending_vehicle.is_verified is False


def test_driver_status_flags_expired_licence_as_incomplete_profile(db_session):
    make_driver(db_session, verified=True, licence_valid=False, vehicle="approved")

    status = VerificationService(db_session).driver_status(DRIVER_USER)

    assert status.next_step()["complete_profile"] is True
    assert status.is_verified is False


def test_driver_status_is_verified_when_all_requirements_met(db_session):
    fully_verified_driver(db_session)

    status = VerificationService(db_session).driver_status(DRIVER_USER)

    assert status.is_verified is True
    assert status.progress_percent == 100


def test_require_verified_student_raises_with_status_attached(db_session):
    service = VerificationService(db_session)

    with pytest.raises(VerificationRequiredError) as exc_info:
        service.require_verified_student(STUDENT_USER)

    payload = exc_info.value.to_payload()
    assert payload["success"] is False
    assert payload["error_code"] == ERROR_CODE_PROFILE_INCOMPLETE
    assert payload["verification"]["role"] == "student"
    assert payload["verification"]["progress"]["total"] == 1


def test_require_verified_returns_the_profile_when_eligible(db_session):
    student = make_student(db_session)
    driver = fully_verified_driver(db_session)
    service = VerificationService(db_session)

    assert service.require_verified_student(STUDENT_USER).id == student.id
    assert service.require_verified_driver(DRIVER_USER).id == driver.id


def test_status_for_user_picks_the_driver_checklist_for_drivers(db_session):
    make_driver(db_session)

    status = VerificationService(db_session).status_for_user(DRIVER_USER)

    assert status.role == "driver"


# ----------------------------------------------------------------------
# Guarded endpoint: students requesting rides
# ----------------------------------------------------------------------
def test_student_without_profile_cannot_request_ride(client):
    response = client.post("/rides", json=ride_payload())

    body = assert_guard_payload(response, expected_missing=["complete_profile"])
    assert body["message"] == "Complete your student profile before requesting rides."
    assert body["verification"]["progress"] == {
        "completed": 0,
        "total": 1,
        "percent": 0,
    }


def test_student_with_profile_can_request_ride(client, db_session):
    make_student(db_session)

    response = client.post("/rides", json=ride_payload())

    assert response.status_code == 201
    assert response.json()["status"] == "MATCHING"


def test_driver_cannot_request_ride_as_a_student(client, db_session, auth_state):
    fully_verified_driver(db_session)
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    assert_guard_payload(
        client.post("/rides", json=ride_payload()),
        expected_missing=["complete_profile"],
    )


# ----------------------------------------------------------------------
# Guarded endpoints: drivers going online / availability
# ----------------------------------------------------------------------
def test_driver_without_profile_cannot_go_online(client, auth_state):
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    assert_guard_payload(
        client.post("/drivers/online"),
        expected_missing=["complete_profile", "register_vehicle", "verify_driver"],
    )


def test_driver_without_approved_vehicle_cannot_go_online(
    client, db_session, auth_state
):
    make_driver(db_session, verified=True, vehicle="pending")
    make_kyc_application(db_session, DRIVER_USER, "driver", "APPROVED")
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    body = assert_guard_payload(
        client.post("/drivers/online"), expected_missing=["approve_vehicle"]
    )
    assert body["next_step"]["register_vehicle"] is False
    assert body["next_step"]["verify_driver"] is False


def test_driver_without_kyc_cannot_go_online(client, db_session, auth_state):
    make_driver(db_session, vehicle="approved")
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    assert_guard_payload(
        client.post("/drivers/online"),
        expected_missing=["upload_documents", "verify_driver"],
    )


def test_fully_verified_driver_can_go_online(client, db_session, auth_state):
    fully_verified_driver(db_session)
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    response = client.post("/drivers/online")

    assert response.status_code == 200
    assert response.json()["online_status"] is True


def test_unverified_driver_cannot_become_available(client, db_session, auth_state):
    make_driver(db_session, vehicle="approved")
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    assert_guard_payload(
        client.patch("/drivers/availability", json={"availability_status": "available"}),
        expected_missing=["verify_driver"],
    )


def test_unverified_driver_may_still_step_back_from_dispatch(
    client, db_session, auth_state
):
    """Going busy/unavailable or offline must never be blocked."""
    make_driver(db_session, vehicle="approved")
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    busy = client.patch("/drivers/availability", json={"availability_status": "busy"})
    offline = client.post("/drivers/offline")

    assert busy.status_code == 200
    assert busy.json()["availability_status"] == "busy"
    assert offline.status_code == 200
    assert offline.json()["online_status"] is False


# ----------------------------------------------------------------------
# Guarded endpoints: driver ride lifecycle
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "path,method,payload",
    [
        ("accept", "post", None),
        ("arriving", "post", None),
        ("start", "post", None),
        ("complete", "post", {"final_fare": "15.50"}),
    ],
)
def test_unverified_driver_cannot_manage_rides(
    client, db_session, auth_state, path, method, payload
):
    student = make_student(db_session, verified=True)
    driver = make_driver(db_session, vehicle="pending")
    ride = assigned_ride(db_session, student, driver)
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    response = getattr(client, method)(
        f"/rides/{ride.id}/{path}", json=payload if payload else None
    )

    assert_guard_payload(response, expected_missing=["approve_vehicle", "verify_driver"])


def test_verified_driver_can_accept_ride(client, db_session, auth_state):
    student = make_student(db_session, verified=True)
    driver = fully_verified_driver(db_session)
    ride = assigned_ride(db_session, student, driver)
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    response = client.post(f"/rides/{ride.id}/accept")

    assert response.status_code == 200
    assert response.json()["status"] == "ACCEPTED"


# ----------------------------------------------------------------------
# Endpoints that stay open to unverified users
# ----------------------------------------------------------------------
def test_ride_history_stays_available_to_unverified_student(client, db_session):
    make_student(db_session)

    response = client.get("/rides/history")

    assert response.status_code == 200
    assert response.json() == []


def test_ride_history_is_empty_not_forbidden_without_any_profile(client, auth_state):
    """A signed-in user with no rider/driver profile has no rides, not a 403.

    The dashboard loads history before the user has onboarded, so answering
    "forbidden" mislabels an empty result as a permission problem.
    """
    auth_state["user"] = AuthenticatedUser(id=STRANGER_USER)

    response = client.get("/rides/history")

    assert response.status_code == 200
    assert response.json() == []


def test_driver_earnings_stay_available_to_unverified_driver(
    client, db_session, auth_state
):
    make_driver(db_session)
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    assert client.get("/drivers/earnings").status_code == 200
    assert client.get("/drivers/performance").status_code == 200


def test_driver_onboarding_is_not_blocked_by_the_guard(client, auth_state):
    """A user must be able to register before they can be verified."""
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    response = client.post(
        "/drivers/onboarding",
        json={
            "license_number": "DL-NEW",
            "license_expiry": str(date.today() + timedelta(days=365)),
        },
    )

    assert response.status_code == 201


# ----------------------------------------------------------------------
# Progress endpoints used by the blocking modal
# ----------------------------------------------------------------------
def test_verification_status_endpoint_reports_student_checklist(client, db_session):
    make_student(db_session)

    response = client.get("/verification/status")

    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["role"] == "student"
    assert body["verification"]["progress"]["completed"] == 1
    assert [step["key"] for step in body["verification"]["steps"]] == [
        "complete_profile",
    ]
    assert all(step["label"] for step in body["verification"]["steps"])


def test_verification_status_endpoint_reports_driver_checklist(
    client, db_session, auth_state
):
    fully_verified_driver(db_session)
    auth_state["user"] = AuthenticatedUser(id=DRIVER_USER)

    response = client.get("/verification/status/driver")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error_code"] is None
    assert body["verification"]["verified"] is True


def test_verification_status_never_fails_for_a_user_with_no_profile(client, auth_state):
    auth_state["user"] = AuthenticatedUser(id=STRANGER_USER)

    response = client.get("/verification/status")

    assert response.status_code == 200
    assert response.json()["verification"]["verified"] is False


def test_profile_step_points_at_onboarding_for_a_user_without_a_profile(
    client, auth_state
):
    """The passenger layout redirects using this step, so its shape is a contract.

    It must be the *only* outstanding-profile signal the frontend needs: an
    unsatisfied ``complete_profile`` whose ``action_url`` is the onboarding page.
    """
    auth_state["user"] = AuthenticatedUser(id=STRANGER_USER)

    body = client.get("/verification/status").json()

    step = next(
        item
        for item in body["verification"]["steps"]
        if item["key"] == "complete_profile"
    )
    assert step["satisfied"] is False
    assert step["action_url"] == "/onboarding"
    assert body["next_step"]["complete_profile"] is True


def test_profile_step_is_satisfied_once_a_student_exists(client, db_session):
    """A student awaiting review must not be sent back to onboarding."""
    make_student(db_session)

    body = client.get("/verification/status").json()

    step = next(
        item
        for item in body["verification"]["steps"]
        if item["key"] == "complete_profile"
    )
    assert step["satisfied"] is True
    assert body["verification"]["verified"] is True


@pytest.mark.parametrize(
    "path",
    ["/verification/status", "/verification/status/student", "/verification/status/driver"],
)
def test_verification_status_is_served_under_the_versioned_prefix(client, db_session, path):
    """The frontend talks to /api/v1, so every route must exist there too.

    Module routers are mounted both at the root and under /api/v1; a route
    registered in only one place 404s for the browser while passing root-path
    tests, which is exactly how this was missed the first time.
    """
    make_student(db_session)

    assert client.get(path).status_code == 200
    assert client.get(f"/api/v1{path}").status_code == 200


# ----------------------------------------------------------------------
# Authentication must keep working unchanged
# ----------------------------------------------------------------------
def test_guard_does_not_replace_authentication(db_session, matching_service):
    """Without a session the request is still rejected as 401, not 403."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_matching_service] = lambda: matching_service
    with TestClient(app) as unauthenticated_client:
        response = unauthenticated_client.post("/rides", json=ride_payload())
    app.dependency_overrides.clear()

    assert response.status_code == 401
