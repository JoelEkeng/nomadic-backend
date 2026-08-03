"""Clerk JWT authentication for the FastAPI backend.

Validates Bearer tokens issued by Clerk using JWKS public keys.
Extracts user claims and provides reusable dependencies for authorization.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import get_db
from modules.users.models import UserRecord

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "")
CLERK_ISSUER = os.getenv("CLERK_ISSUER", "")
CLERK_AUDIENCE = os.getenv("CLERK_AUDIENCE", "")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_API_BASE_URL = "https://api.clerk.com/v1"

# ─── JWKS Cache ───────────────────────────────────────────────────────────────

_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at: float = 0
_JWKS_CACHE_TTL = 3600  # seconds

# ─── Clerk User Cache ─────────────────────────────────────────────────────────
# Default Clerk session tokens only carry `sub`/`sid`/etc. and omit `email`,
# `public_metadata`, and `email_verified` unless a custom session token is
# configured in the Clerk Dashboard. Rather than requiring that dashboard
# configuration, we fall back to the Clerk Backend API for any claims that
# are missing from the token, with a short-lived cache to avoid hitting
# Clerk's rate limits on every request.

_clerk_user_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CLERK_USER_CACHE_TTL = 30  # seconds


def _fetch_clerk_user(user_id: str) -> dict[str, Any] | None:
    """Fetch a user's full record from the Clerk Backend API, with a short TTL cache."""
    if not CLERK_SECRET_KEY:
        return None

    now = time.time()
    cached = _clerk_user_cache.get(user_id)
    if cached and (now - cached[0] < _CLERK_USER_CACHE_TTL):
        return cached[1]

    try:
        response = httpx.get(
            f"{CLERK_API_BASE_URL}/users/{user_id}",
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        _clerk_user_cache[user_id] = (now, data)
        return data
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch Clerk user %s from Backend API: %s", user_id, exc)
        return None


def _get_signing_key(token: str) -> jwt.algorithms.RSAAlgorithm:
    """Fetch and cache JWKS keys from Clerk, returning the key matching the token's kid."""
    global _jwks_cache, _jwks_fetched_at

    if not CLERK_JWKS_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_JWKS_URL not configured",
        )

    now = time.time()
    if not _jwks_cache or (now - _jwks_fetched_at > _JWKS_CACHE_TTL):
        try:
            response = httpx.get(CLERK_JWKS_URL, timeout=10)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_fetched_at = now
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch Clerk JWKS: %s", exc)
            if not _jwks_cache:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Authentication service unavailable",
                ) from exc

    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")

    for key_data in _jwks_cache.get("keys", []):
        if key_data.get("kid") == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    # Kid not found - force refresh once
    try:
        response = httpx.get(CLERK_JWKS_URL, timeout=10)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_fetched_at = now
    except httpx.HTTPError as exc:
        logger.error("Failed to refresh Clerk JWKS: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from exc

    for key_data in _jwks_cache.get("keys", []):
        if key_data.get("kid") == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token signing key",
    )


# ─── Authenticated User ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None = None
    name: str | None = None
    role: str = "passenger"
    email_verified: bool = False
    phone_number: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_driver(self) -> bool:
        return self.role == "driver"

    @property
    def is_student(self) -> bool:
        return self.role in ("passenger", "student")


# ─── Token Extraction ─────────────────────────────────────────────────────────


def _extract_bearer_token(request: Request) -> str:
    """Extract Bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        logger.warning(
            "JWT auth failed: missing_or_invalid_authorization_header path=%s",
            request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def _decode_clerk_jwt(token: str) -> dict[str, Any]:
    """Validate and decode a Clerk JWT token."""
    try:
        signing_key = _get_signing_key(token)

        decode_options: dict[str, Any] = {
            "verify_exp": True,
            "verify_iat": True,
            "verify_nbf": True,
            "verify_aud": bool(CLERK_AUDIENCE),
            "verify_iss": bool(CLERK_ISSUER),
        }

        kwargs: dict[str, Any] = {
            "algorithms": ["RS256"],
            "options": decode_options,
        }

        if CLERK_ISSUER:
            kwargs["issuer"] = CLERK_ISSUER
        if CLERK_AUDIENCE:
            kwargs["audience"] = CLERK_AUDIENCE

        payload = jwt.decode(token, signing_key, **kwargs)
        logger.debug(
            "JWT validation succeeded: sub=%s iss=%s aud=%s",
            payload.get("sub"),
            payload.get("iss"),
            payload.get("aud"),
        )
        return payload

    except jwt.ExpiredSignatureError:
        logger.warning("JWT validation failed: expired_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidIssuerError:
        logger.warning("JWT validation failed: invalid_issuer expected=%s", CLERK_ISSUER)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
        )
    except jwt.InvalidAudienceError:
        logger.warning("JWT validation failed: invalid_audience expected=%s", CLERK_AUDIENCE)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
        )
    except jwt.DecodeError:
        logger.warning("JWT validation failed: decode_error")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


# ─── User Sync ────────────────────────────────────────────────────────────────


def _sync_user_record(db: Session, user: AuthenticatedUser) -> None:
    """Ensure the backend has a user record for FK references. Idempotent."""
    try:
        db_user = db.get(UserRecord, user.id)
        if db_user is None:
            db.add(
                UserRecord(
                    id=user.id,
                    email=user.email,
                    role=user.role,
                    email_verified=user.email_verified,
                )
            )
        else:
            db_user.email = user.email or db_user.email
            db_user.role = user.role or db_user.role
            db_user.email_verified = user.email_verified
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise


# ─── Main Dependency ──────────────────────────────────────────────────────────


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    """Validate Clerk JWT and return the authenticated user.

    Extracts user ID, email, name, and role from Clerk JWT claims.
    Syncs the user record to the local database for FK integrity.
    """
    token = _extract_bearer_token(request)
    payload = _decode_clerk_jwt(token)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    # Clerk stores metadata in custom claims
    metadata = payload.get("metadata", {}) or {}
    public_metadata = payload.get("public_metadata", {}) or metadata

    # Extract user info from Clerk JWT claims
    email = (
        payload.get("email")
        or payload.get("email_address")
        or (payload.get("email_addresses", [{}]) or [{}])[0].get("email_address")
    )
    name = payload.get("name") or payload.get("full_name")
    if not name:
        first = payload.get("first_name", "")
        last = payload.get("last_name", "")
        name = f"{first} {last}".strip() or None

    role = public_metadata.get("role")
    email_verified_claim = payload.get("email_verified")
    unsafe_metadata = payload.get("unsafe_metadata", {}) or {}
    phone_number = unsafe_metadata.get("phone_number")

    # The default Clerk session token (no custom claims configured) does not
    # include `email`, `public_metadata`, or `email_verified`. Fall back to
    # the Clerk Backend API for whatever is missing, so verification/role
    # checks work without requiring a Clerk Dashboard session token change.
    if email is None or role is None or email_verified_claim is None or phone_number is None:
        clerk_user = _fetch_clerk_user(str(user_id))
        if clerk_user:
            primary_email_id = clerk_user.get("primary_email_address_id")
            primary_email = next(
                (
                    ea
                    for ea in clerk_user.get("email_addresses", [])
                    if ea.get("id") == primary_email_id
                ),
                None,
            )

            if email is None and primary_email:
                email = primary_email.get("email_address")

            if email_verified_claim is None and primary_email:
                email_verified_claim = (
                    primary_email.get("verification", {}).get("status") == "verified"
                )

            if role is None:
                role = (clerk_user.get("public_metadata") or {}).get("role") or (
                    clerk_user.get("unsafe_metadata") or {}
                ).get("role")

            if phone_number is None:
                phone_number = (clerk_user.get("unsafe_metadata") or {}).get("phone_number")

            if not name:
                first = clerk_user.get("first_name") or ""
                last = clerk_user.get("last_name") or ""
                name = f"{first} {last}".strip() or None

    role = role or "passenger"
    email_verified = bool(email_verified_claim)

    authenticated = AuthenticatedUser(
        id=str(user_id),
        email=email,
        name=name,
        role=str(role),
        email_verified=email_verified,
        phone_number=phone_number,
    )

    _sync_user_record(db, authenticated)

    logger.info("Authenticated Clerk user: id=%s role=%s email_verified=%s", user_id, role, email_verified)
    return authenticated


# ─── Role-Based Authorization ─────────────────────────────────────────────────


def require_role(*roles: str):
    """Factory for role-based authorization dependencies."""

    async def _check_role(
        current_user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if current_user.role not in roles:
            logger.warning(
                "Authorization denied: user=%s role=%s required=%s",
                current_user.id,
                current_user.role,
                roles,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(roles)}",
            )
        return current_user

    return _check_role


require_admin = require_role("admin")
require_driver = require_role("driver")
require_student = require_role("passenger", "student")
