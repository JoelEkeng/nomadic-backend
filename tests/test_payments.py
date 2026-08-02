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
from modules.payments.models import RidePayment, Wallet
from modules.payments.service import PaymentService
from modules.rides.models import Ride
from modules.students.models import Student
from modules.users.models import BetterAuthUser

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
            BetterAuthUser(id="student-user"),
            BetterAuthUser(id="driver-user"),
            BetterAuthUser(id="admin-user"),
        ]
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def current_user():
    return {"id": "student-user", "role": "user"}


@pytest.fixture()
def client(db_session, current_user):
    def override_get_db():
        yield db_session

    async def override_current_user():
        return AuthenticatedUser(
            id=current_user["id"],
            role=current_user["role"],
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_test_student_and_driver(db):
    student = Student(
        user_id="student-user",
        student_number="UG-2001",
        verification_status="verified",
    )
    driver = Driver(
        user_id="driver-user",
        license_number="DL-2001",
        license_expiry=date.today() + timedelta(days=365),
        verification_status="verified",
        availability_status="available",
        online_status=True,
    )
    db.add_all([student, driver])
    db.commit()

    ride = Ride(
        student_id=student.id,
        driver_id=driver.id,
        pickup_location="Main Gate",
        destination_location="Library",
        distance=Decimal("3.50"),
        estimated_fare=Decimal("20.00"),
        status="COMPLETED",
    )
    db.add(ride)
    db.commit()
    return student, driver, ride


# ------------------------------------------------------------------
# Test Cases
# ------------------------------------------------------------------
def test_get_or_create_wallet_and_deposit(client, db_session):
    # Get user wallet
    res = client.get("/api/v1/payments/wallets/me")
    assert res.status_code == 200
    data = res.json()
    assert data["balance"] == "0.00"
    assert data["available_balance"] == "0.00"

    # Deposit
    dep_res = client.post(
        "/api/v1/payments/wallets/deposit",
        json={"amount": "100.00", "currency": "USD", "description": "Initial deposit"},
    )
    assert dep_res.status_code == 200
    assert dep_res.json()["amount"] == "100.00"

    # Verify balance
    res_after = client.get("/api/v1/payments/wallets/me")
    assert res_after.json()["balance"] == "100.00"
    assert res_after.json()["available_balance"] == "100.00"


def test_withdraw_and_insufficient_balance(client, db_session):
    # Deposit 50
    client.post("/api/v1/payments/wallets/deposit", json={"amount": "50.00"})

    # Withdraw 20
    w_res = client.post(
        "/api/v1/payments/wallets/withdraw",
        json={"amount": "20.00", "destination_account": "ACC-12345"},
    )
    assert w_res.status_code == 200
    assert w_res.json()["amount"] == "20.00"

    # Verify balance is 30
    bal_res = client.get("/api/v1/payments/wallets/me")
    assert bal_res.json()["balance"] == "30.00"

    # Attempt to withdraw 50 (exceeds balance)
    err_res = client.post(
        "/api/v1/payments/wallets/withdraw",
        json={"amount": "50.00"},
    )
    assert err_res.status_code == 400
    assert err_res.json()["detail"]["code"] == "INSUFFICIENT_BALANCE"


def test_idempotency_prevention(client, db_session):
    key = "IDEM-TEST-1001"
    payload = {"amount": "75.00", "idempotency_key": key}

    res1 = client.post("/api/v1/payments/wallets/deposit", json=payload, headers={"Idempotency-Key": key})
    assert res1.status_code == 200
    txn_id1 = res1.json()["id"]

    # Repeat exact request with same idempotency key
    res2 = client.post("/api/v1/payments/wallets/deposit", json=payload, headers={"Idempotency-Key": key})
    assert res2.status_code == 200
    assert res2.json()["id"] == txn_id1

    # Verify only single deposit of 75 was processed
    bal = client.get("/api/v1/payments/wallets/me").json()["balance"]
    assert bal == "75.00"


def test_peer_to_peer_transfer(client, db_session, current_user):
    service = PaymentService(db_session)
    w_student = service.get_or_create_user_wallet("student-user")
    w_driver = service.get_or_create_driver_wallet("driver-user")

    service.deposit(w_student.id, Decimal("150.00"))

    res = client.post(
        "/api/v1/payments/wallets/transfer",
        json={"target_wallet_id": w_driver.id, "amount": "50.00"},
    )
    assert res.status_code == 200
    assert res.json()["amount"] == "50.00"

    # Check student balance (100) and driver balance (50)
    db_session.refresh(w_student)
    db_session.refresh(w_driver)
    assert w_student.balance == Decimal("100.00")
    assert w_driver.balance == Decimal("50.00")


def test_ride_payment_full_flow(client, db_session, current_user):
    student, driver, ride = create_test_student_and_driver(db_session)
    service = PaymentService(db_session)

    # Fund student wallet with 100
    w_student = service.get_or_create_user_wallet("student-user")
    service.deposit(w_student.id, Decimal("100.00"))

    # 1. Authorize estimated fare of 20.00
    auth_res = client.post(
        f"/api/v1/payments/rides/{ride.id}/authorize",
        json={"ride_id": ride.id, "student_id": student.id, "estimated_fare": "20.00"},
    )
    assert auth_res.status_code == 200
    assert auth_res.json()["status"] == "AUTHORIZED"

    # Check locked balance
    db_session.refresh(w_student)
    assert w_student.locked_balance == Decimal("20.00")
    assert w_student.available_balance == Decimal("80.00")

    # 2. Capture final fare of 25.00 + 5.00 tip (15% platform commission = 3.75, driver net = 21.25 + 5.00 = 26.25)
    cap_res = client.post(
        f"/api/v1/payments/rides/{ride.id}/capture",
        json={"final_fare": "25.00", "tip_amount": "5.00"},
    )
    assert cap_res.status_code == 200
    assert cap_res.json()["status"] == "CAPTURED"
    assert cap_res.json()["platform_commission"] == "3.75"
    assert cap_res.json()["driver_net_earnings"] == "26.25"

    # Check balances after capture
    db_session.refresh(w_student)
    w_driver = service.get_or_create_driver_wallet(driver.id)
    w_platform = service.wallet_repo.get_or_create_platform_wallet()

    assert w_student.locked_balance == Decimal("0.00")
    assert w_student.balance == Decimal("70.00")  # 100 - 30 (25 + 5)
    assert w_driver.balance == Decimal("26.25")
    assert w_platform.balance == Decimal("3.75")


def test_ride_payment_cancel_auth(client, db_session):
    student, driver, ride = create_test_student_and_driver(db_session)
    service = PaymentService(db_session)
    w_student = service.get_or_create_user_wallet("student-user")
    service.deposit(w_student.id, Decimal("50.00"))

    # Authorize
    client.post(
        f"/api/v1/payments/rides/{ride.id}/authorize",
        json={"ride_id": ride.id, "student_id": student.id, "estimated_fare": "30.00"},
    )

    db_session.refresh(w_student)
    assert w_student.locked_balance == Decimal("30.00")

    # Cancel auth
    cancel_res = client.post(f"/api/v1/payments/rides/{ride.id}/cancel-auth")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    db_session.refresh(w_student)
    assert w_student.locked_balance == Decimal("0.00")
    assert w_student.available_balance == Decimal("50.00")


def test_refund_processing(client, db_session):
    student, driver, ride = create_test_student_and_driver(db_session)
    service = PaymentService(db_session)
    w_student = service.get_or_create_user_wallet("student-user")
    service.deposit(w_student.id, Decimal("100.00"))

    client.post(
        f"/api/v1/payments/rides/{ride.id}/authorize",
        json={"ride_id": ride.id, "student_id": student.id, "estimated_fare": "20.00"},
    )
    cap_res = client.post(
        f"/api/v1/payments/rides/{ride.id}/capture",
        json={"final_fare": "20.00", "tip_amount": "0.00"},
    )
    payment_id = cap_res.json()["id"]

    # Refund 10.00
    ref_res = client.post(
        "/api/v1/payments/refunds",
        json={"payment_id": payment_id, "amount": "10.00", "reason": "Driver arrived late"},
    )
    assert ref_res.status_code == 200
    assert ref_res.json()["status"] == "COMPLETED"
    assert ref_res.json()["amount"] == "10.00"

    # Check student balance (was 80 after 20 charge, now 90 after 10 refund)
    db_session.refresh(w_student)
    assert w_student.balance == Decimal("90.00")


def test_driver_earnings_summary(client, db_session, current_user):
    student, driver, ride = create_test_student_and_driver(db_session)
    service = PaymentService(db_session)
    w_student = service.get_or_create_user_wallet("student-user")
    service.deposit(w_student.id, Decimal("100.00"))

    client.post(
        f"/api/v1/payments/rides/{ride.id}/authorize",
        json={"ride_id": ride.id, "student_id": student.id, "estimated_fare": "40.00"},
    )
    client.post(
        f"/api/v1/payments/rides/{ride.id}/capture",
        json={"final_fare": "40.00", "tip_amount": "5.00"},
    )

    current_user["id"] = driver.id
    earn_res = client.get(f"/api/v1/payments/driver/earnings?driver_id={driver.id}")
    assert earn_res.status_code == 200
    body = earn_res.json()
    assert body["total_gross_fare"] == "40.00"
    assert body["total_tips"] == "5.00"
    assert body["total_commission"] == "6.00"  # 15% of 40 = 6
    assert body["total_net_earnings"] == "39.00"  # (40 - 6) + 5 = 39


def test_background_reconciliation(client, db_session, current_user):
    current_user["role"] = "admin"
    service = PaymentService(db_session)
    w_student = service.get_or_create_user_wallet("student-user")
    service.deposit(w_student.id, Decimal("100.00"))

    # Trigger admin reconciliation
    rec_res = client.post("/api/v1/payments/admin/reconcile", json={"auto_fix": False})
    assert rec_res.status_code == 200
    assert rec_res.json()["status"] == "PASSED"
    assert rec_res.json()["discrepancies_count"] == 0
