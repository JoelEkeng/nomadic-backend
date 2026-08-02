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
from modules.kyc.models import KYCApplication
from modules.kyc.repository import KYCRepository
from modules.students.models import Student
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
            UserRecord(id="student-user"),
            UserRecord(id="driver-user"),
            UserRecord(id="admin-user"),
            Student(
                user_id="student-user",
                student_number="UG-1001",
            ),
            Driver(
                user_id="driver-user",
                license_number="DL-1001",
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
    return {"user": AuthenticatedUser(id="student-user")}


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


def submit_student_kyc(client):
    return client.post(
        "/kyc/applications",
        json={
            "applicant_type": "student",
            "documents": [
                {
                    "type": "student_id",
                    "file_url": "https://files.example.com/raw/student-id.png",
                }
            ],
        },
    )


def test_user_submits_kyc_documents_without_exposing_file_urls(client, db_session):
    response = submit_student_kyc(client)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["documents"][0]["type"] == "student_id"
    assert "file_url" not in body["documents"][0]
    assert "https://files.example.com/raw/student-id.png" not in response.text

    application = db_session.query(KYCApplication).one()
    assert application.documents[0].file_url.startswith("protected://kyc/student-user/")
    assert application.documents[0].file_url != "https://files.example.com/raw/student-id.png"


def test_kyc_submission_validates_document_type(client):
    response = client.post(
        "/kyc/applications",
        json={
            "applicant_type": "student",
            "documents": [
                {
                    "type": "driver_license",
                    "file_url": "https://files.example.com/raw/license.png",
                }
            ],
        },
    )

    assert response.status_code == 422


def test_user_cannot_submit_duplicate_open_application(client):
    assert submit_student_kyc(client).status_code == 201

    response = submit_student_kyc(client)

    assert response.status_code == 409
    assert response.json()["detail"] == "An open KYC application already exists"


def test_user_cannot_access_another_users_kyc_application(client, db_session):
    application = KYCRepository(db_session).create_application(
        user_id="driver-user",
        applicant_type="driver",
        documents=[
            {
                "type": "driver_license",
                "file_url": "protected://kyc/driver-user/license",
                "verification_status": "PENDING",
            }
        ],
    )

    response = client.get(f"/kyc/applications/{application.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "KYC application access denied"


def test_non_admin_cannot_review_kyc(client):
    application_id = submit_student_kyc(client).json()["id"]

    response = client.post(
        f"/kyc/admin/applications/{application_id}/approve",
        json={"notes": "Looks good"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin permissions required"


def test_admin_marks_under_review_and_audit_logs(client, auth_state):
    application_id = submit_student_kyc(client).json()["id"]
    auth_state["user"] = AuthenticatedUser(id="admin-user", role="admin")

    response = client.post(
        f"/kyc/admin/applications/{application_id}/review",
        json={"notes": "Checking documents"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UNDER_REVIEW"
    assert body["documents"][0]["verification_status"] == "UNDER_REVIEW"
    assert body["reviews"][0]["action"] == "UNDER_REVIEW"
    assert body["reviews"][0]["previous_status"] == "PENDING"
    assert body["reviews"][0]["reviewer_id"] == "admin-user"
    assert "file_url" not in response.text


def test_admin_approves_student_kyc_and_updates_student_verification(
    client, auth_state, db_session
):
    application_id = submit_student_kyc(client).json()["id"]
    auth_state["user"] = AuthenticatedUser(id="admin-user", role="admin")

    response = client.post(
        f"/kyc/admin/applications/{application_id}/approve",
        json={"notes": "Approved"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["documents"][0]["verification_status"] == "APPROVED"
    assert body["reviews"][0]["new_status"] == "APPROVED"
    student = db_session.query(Student).filter(Student.user_id == "student-user").one()
    assert student.verification_status == "verified"


def test_admin_rejects_driver_kyc_and_updates_driver_verification(
    client, auth_state, db_session
):
    auth_state["user"] = AuthenticatedUser(id="driver-user")
    application_id = client.post(
        "/kyc/applications",
        json={
            "applicant_type": "driver",
            "documents": [
                {
                    "type": "driver_license",
                    "file_url": "https://files.example.com/raw/license.png",
                }
            ],
        },
    ).json()["id"]
    auth_state["user"] = AuthenticatedUser(id="admin-user", role="admin")

    response = client.post(
        f"/kyc/admin/applications/{application_id}/reject",
        json={"notes": "Document is blurry"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
    driver = db_session.query(Driver).filter(Driver.user_id == "driver-user").one()
    assert driver.verification_status == "rejected"


def test_finalized_application_cannot_be_reviewed_again(client, auth_state):
    application_id = submit_student_kyc(client).json()["id"]
    auth_state["user"] = AuthenticatedUser(id="admin-user", role="admin")
    assert (
        client.post(
            f"/kyc/admin/applications/{application_id}/approve",
            json={},
        ).status_code
        == 200
    )

    response = client.post(
        f"/kyc/admin/applications/{application_id}/reject",
        json={"notes": "Changed my mind"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "KYC application has already been finalized"
