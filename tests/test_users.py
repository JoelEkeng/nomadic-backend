from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.auth import AuthenticatedUser, get_current_user
from core.database import Base, get_db
from main import app
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
    db.add(UserRecord(id="betterauth-user-1"))
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


def test_get_profile_requires_auth():
    with TestClient(app) as test_client:
        response = test_client.get("/users/me")

    assert response.status_code == 401


def test_get_profile_returns_profile(client, db_session):
    from modules.users.schemas import UserProfileCreate
    from modules.users.repository import UserProfileRepository
    from modules.users.service import UserProfileService

    service = UserProfileService(UserProfileRepository(db_session))
    service.create_profile(
        "betterauth-user-1",
        UserProfileCreate(
            phone_number="+233555000111",
            date_of_birth=date(1995, 1, 1),
            emergency_contact_name="Ama",
            emergency_contact_phone="+233555222333",
            notification_preferences={"sms": True},
        ),
    )

    response = client.get("/users/me")

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "betterauth-user-1"
    assert body["phone_number"] == "+233555000111"
    assert body["profile_completeness"] == 83


def test_update_profile(client, db_session):
    from modules.users.schemas import UserProfileCreate
    from modules.users.repository import UserProfileRepository
    from modules.users.service import UserProfileService

    service = UserProfileService(UserProfileRepository(db_session))
    service.create_profile("betterauth-user-1", UserProfileCreate())

    response = client.patch(
        "/users/me",
        json={
            "phone_number": "+233555000111",
            "emergency_contact_name": "Kojo",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["phone_number"] == "+233555000111"
    assert body["emergency_contact_name"] == "Kojo"


def test_delete_profile(client, db_session):
    from modules.users.schemas import UserProfileCreate
    from modules.users.repository import UserProfileRepository
    from modules.users.service import UserProfileService

    service = UserProfileService(UserProfileRepository(db_session))
    service.create_profile("betterauth-user-1", UserProfileCreate())

    response = client.delete("/users/me")

    assert response.status_code == 204
    assert service.repository.get_by_user_id("betterauth-user-1") is None
