from dataclasses import dataclass
from typing import Any
import json
import urllib.request
import asyncio

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import get_db
from modules.users.models import BetterAuthUser


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None = None
    name: str | None = None
    phone_number: str | None = None
    role: str = "user"
    email_verified: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _read_attr_or_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


async def fetch_betterauth_session(request: Request):
    """Fetch session from the frontend BetterAuth endpoint."""
    cookie = request.headers.get("cookie")
    if not cookie:
        return None

    def _fetch():
        req = urllib.request.Request("http://localhost:3000/api/auth/get-session")
        req.add_header("cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    return data.get("session", {}).get("user") or data.get("user")
        except Exception as e:
            print(f"Error fetching session: {e}")
        return None

    return await asyncio.to_thread(_fetch)


def _sync_backend_user(db: Session, user: AuthenticatedUser) -> None:
    try:
        db_user = db.get(BetterAuthUser, user.id)
        if db_user is None:
            db.add(
                BetterAuthUser(
                    id=user.id,
                    auth_provider_id=user.id,
                    email=user.email,
                    phone_number=user.phone_number,
                    role=user.role,
                    emailVerified=user.email_verified,
                )
            )
        else:
            db_user.auth_provider_id = db_user.auth_provider_id or user.id
            db_user.email = user.email or db_user.email
            db_user.phone_number = user.phone_number or db_user.phone_number
            db_user.role = user.role or db_user.role
            db_user.emailVerified = user.email_verified
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes", "on"}
    return bool(value)


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    """Return the BetterAuth user attached by upstream auth middleware."""
    user = getattr(request.state, "betterauth_user", None) or getattr(
        request.state, "user", None
    )
    user_id = getattr(request.state, "betterauth_user_id", None) or getattr(
        request.state, "user_id", None
    )
    
    if not user:
        fetched_user = await fetch_betterauth_session(request)
        if fetched_user:
            user = fetched_user
            user_id = fetched_user.get("id")

    if user is not None:
        user_id = user_id or _read_attr_or_key(user, "id")
        email = _read_attr_or_key(user, "email")
        name = _read_attr_or_key(user, "name")
        phone_number = _read_attr_or_key(user, "phone_number")
        email_verified = _coerce_bool(_read_attr_or_key(user, "emailVerified"))
        role = _read_attr_or_key(user, "role") or "user"
    else:
        email = None
        name = None
        phone_number = None
        email_verified = False
        role = "user"

    role = getattr(request.state, "role", None) or getattr(
        request.state, "user_role", None
    ) or role

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    authenticated = AuthenticatedUser(
        id=str(user_id),
        email=email,
        name=name,
        phone_number=phone_number,
        role=str(role),
        email_verified=email_verified,
    )
    _sync_backend_user(db, authenticated)
    return authenticated
