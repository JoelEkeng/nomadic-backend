from datetime import date, timedelta
from decimal import Decimal

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
from modules.drivers.schemas import DriverOnboardingCreate
from modules.drivers.service import DriverService
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
            UserRecord(id="betterauth-user-1"),
            UserRecord(id="betterauth-user-2"),
            UserRecord(id="betterauth-user-3"),
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
        return AuthenticatedUser(id="betterauth-user-1")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_driver(db_session, user_id: str = "betterauth-user-1") -> Driver:
    service = DriverService(DriverRepository(db_session))
    return service.complete_onboarding(
        user_id,
        DriverOnboardingCreate(
            license_number=f" lic-{user_id} ",
            license_expiry=date.today() + timedelta(days=365),
        ),
    )


def create_approved_vehicle(db_session, driver: Driver) -> Vehicle:
    vehicle = Vehicle(
        driver_id=driver.id,
        registration_number=f"REG-{driver.id[:8]}",
        make="Toyota",
        model="Corolla",
        year=2021,
        color="White",
        vehicle_type="car",
        insurance_expiry=date.today() + timedelta(days=365),
        inspection_status="approved",
    )
    db_session.add(vehicle)
    db_session.commit()
    return vehicle


def test_complete_driver_onboarding(client):
    response = client.post(
        "/drivers/onboarding",
        json={
            "license_number": " dl-1001 ",
            "license_expiry": str(date.today() + timedelta(days=365)),
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == "betterauth-user-1"
    assert body["license_number"] == "DL-1001"
    assert body["verification_status"] == "pending"
    assert body["availability_status"] == "unavailable"
    assert body["online_status"] is False


def test_complete_driver_onboarding_rejects_duplicate(client, db_session):
    create_driver(db_session)

    response = client.post(
        "/drivers/onboarding",
        json={
            "license_number": "DL-2002",
            "license_expiry": str(date.today() + timedelta(days=365)),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Driver profile already exists"


def test_complete_driver_onboarding_rejects_expired_license(client):
    response = client.post(
        "/drivers/onboarding",
        json={
            "license_number": "DL-EXPIRED",
            "license_expiry": str(date.today() - timedelta(days=1)),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Driver license has expired"


def test_unverified_driver_cannot_go_online(client, db_session):
    create_driver(db_session)

    response = client.post("/drivers/online")

    assert response.status_code == 403
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "PROFILE_INCOMPLETE"
    assert body["next_step"]["verify_driver"] is True
    assert body["next_step"]["approve_vehicle"] is True


def test_verified_driver_can_go_online_and_offline(client, db_session):
    driver = create_driver(db_session)
    driver.verification_status = "verified"
    create_approved_vehicle(db_session, driver)
    db_session.commit()

    online_response = client.post("/drivers/online")
    assert online_response.status_code == 200
    assert online_response.json()["online_status"] is True
    assert online_response.json()["availability_status"] == "available"

    offline_response = client.post("/drivers/offline")
    assert offline_response.status_code == 200
    assert offline_response.json()["online_status"] is False
    assert offline_response.json()["availability_status"] == "unavailable"


def test_update_availability_requires_verification_for_available(client, db_session):
    create_driver(db_session)

    response = client.patch(
        "/drivers/availability",
        json={"availability_status": "available"},
    )

    assert response.status_code == 403
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "PROFILE_INCOMPLETE"
    assert body["next_step"]["verify_driver"] is True


def test_update_availability_to_busy(client, db_session):
    create_driver(db_session)

    response = client.patch(
        "/drivers/availability",
        json={"availability_status": "busy"},
    )

    assert response.status_code == 200
    assert response.json()["availability_status"] == "busy"
    assert response.json()["online_status"] is False


def test_view_earnings_and_performance(client, db_session):
    driver = create_driver(db_session)
    driver.earnings = Decimal("1234.50")
    driver.rating = Decimal("4.75")
    driver.total_trips = 42
    driver.cancellation_rate = Decimal("2.50")
    driver.acceptance_rate = Decimal("96.25")
    db_session.commit()

    earnings_response = client.get("/drivers/earnings")
    assert earnings_response.status_code == 200
    assert earnings_response.json()["earnings"] == "1234.50"

    performance_response = client.get("/drivers/performance")
    assert performance_response.status_code == 200
    body = performance_response.json()
    assert body["rating"] == "4.75"
    assert body["total_trips"] == 42
    assert body["cancellation_rate"] == "2.50"
    assert body["acceptance_rate"] == "96.25"


def test_available_online_driver_lookup_for_matching(db_session):
    first_driver = create_driver(db_session, "betterauth-user-1")
    second_driver = create_driver(db_session, "betterauth-user-2")
    third_driver = create_driver(db_session, "betterauth-user-3")

    first_driver.verification_status = "verified"
    first_driver.availability_status = "available"
    first_driver.online_status = True
    first_driver.rating = Decimal("4.50")
    first_driver.acceptance_rate = Decimal("90.00")

    second_driver.verification_status = "verified"
    second_driver.availability_status = "available"
    second_driver.online_status = True
    second_driver.rating = Decimal("4.80")
    second_driver.acceptance_rate = Decimal("80.00")

    third_driver.verification_status = "verified"
    third_driver.availability_status = "busy"
    third_driver.online_status = True
    db_session.commit()

    drivers = DriverRepository(db_session).get_available_online_drivers()

    assert [driver.id for driver in drivers] == [second_driver.id, first_driver.id]


def test_availability_publisher_is_called(db_session):
    class Publisher:
        def __init__(self):
            self.driver_ids = []

        def publish_availability_changed(self, driver):
            self.driver_ids.append(driver.id)

    driver = create_driver(db_session)
    driver.verification_status = "verified"
    create_approved_vehicle(db_session, driver)
    db_session.commit()
    publisher = Publisher()
    service = DriverService(DriverRepository(db_session), publisher)

    service.go_online("betterauth-user-1")

    assert publisher.driver_ids == [driver.id]
