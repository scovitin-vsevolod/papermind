"""Tests for the auth flow itself.

These run against ``unauthenticated_client`` (no ``get_current_user``
override) so the real cookie / bearer-token path is exercised end-to-end.

What's covered:
- /auth/login success → sets the session cookie and returns the user
- /auth/login failure modes — wrong password, missing user, inactive user
- /auth/login payload validation (bad email, short password)
- /auth/logout clears the cookie
- /auth/me with cookie and with bearer header
- 401 on protected endpoints (/documents, /ask, /graph, /auth/me) when
  no credentials are sent — confirms the router-level dependency is on
- Expired / tampered tokens are rejected
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth_deps import SESSION_COOKIE_NAME
from app.config import settings
from app.models import User
from app.services.auth import create_access_token, hash_password

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_user(
    db: Session,
    *,
    email: str = "alice@example.com",
    password: str = "correct-horse-battery",
    is_active: bool = True,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── /auth/login — success path ───────────────────────────────────────────────


def test_login_success_sets_cookie_and_returns_user(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    user = _make_user(db_session)

    response = unauthenticated_client.post(
        "/auth/login",
        json={"email": user.email, "password": "correct-horse-battery"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == user.email
    assert body["user"]["id"] == user.id
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20

    # Cookie was set on the response.
    assert SESSION_COOKIE_NAME in response.cookies
    # The TestClient also propagates it to subsequent requests, which is
    # what enables the next test cases.


def test_login_is_case_insensitive_for_email(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    _make_user(db_session, email="alice@example.com")

    response = unauthenticated_client.post(
        "/auth/login",
        json={"email": "ALICE@Example.COM", "password": "correct-horse-battery"},
    )

    assert response.status_code == 200


# ── /auth/login — failure paths ──────────────────────────────────────────────


def test_login_wrong_password_returns_401(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    _make_user(db_session)

    response = unauthenticated_client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "not-the-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid email or password"
    # No cookie on a failed login.
    assert SESSION_COOKIE_NAME not in response.cookies


def test_login_missing_user_returns_same_401_as_wrong_password(
    unauthenticated_client: TestClient,
) -> None:
    """Email enumeration mitigation: identical response for "no such user"
    and "wrong password"."""

    response = unauthenticated_client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "anything-long-enough"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid email or password"


def test_login_inactive_user_returns_403(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    _make_user(db_session, is_active=False)

    response = unauthenticated_client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "account is inactive"


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "password": "long-enough-password"},
        {"email": "alice@example.com", "password": "short"},  # < 8 chars
        {"email": "alice@example.com"},  # missing password
        {"password": "long-enough-password"},  # missing email
    ],
    ids=["bad-email", "short-password", "no-password", "no-email"],
)
def test_login_validation_errors_return_422(
    unauthenticated_client: TestClient,
    body: dict,
) -> None:
    response = unauthenticated_client.post("/auth/login", json=body)
    assert response.status_code == 422


# ── /auth/logout ─────────────────────────────────────────────────────────────


def test_logout_clears_cookie(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    _make_user(db_session)
    login = unauthenticated_client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "correct-horse-battery"},
    )
    assert login.status_code == 200
    assert SESSION_COOKIE_NAME in unauthenticated_client.cookies

    response = unauthenticated_client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # After logout the cookie jar should no longer carry the session.
    assert SESSION_COOKIE_NAME not in unauthenticated_client.cookies


def test_logout_is_idempotent_without_session(
    unauthenticated_client: TestClient,
) -> None:
    """Calling /auth/logout when not logged in is harmless — no error."""
    response = unauthenticated_client.post("/auth/logout")
    assert response.status_code == 200


# ── /auth/me ─────────────────────────────────────────────────────────────────


def test_me_with_cookie(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    login = unauthenticated_client.post(
        "/auth/login",
        json={"email": user.email, "password": "correct-horse-battery"},
    )
    # The cookie is set with Secure=True so the TestClient (which talks to
    # `http://testserver`) won't auto-replay it. Replay it manually — we
    # already verified Set-Cookie was issued in the success test.
    unauthenticated_client.cookies.set(
        SESSION_COOKIE_NAME, login.cookies[SESSION_COOKIE_NAME]
    )

    response = unauthenticated_client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == user.email


def test_me_with_bearer_token(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    """Non-browser clients can skip the cookie and send Authorization: Bearer."""
    user = _make_user(db_session)
    token = create_access_token(user.id)

    response = unauthenticated_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == user.email


def test_me_without_auth_returns_401(
    unauthenticated_client: TestClient,
) -> None:
    response = unauthenticated_client.get("/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "not authenticated"


def test_me_with_expired_token_returns_401(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    # Hand-crafted expired token (exp 1h in the past).
    past = datetime.now(UTC) - timedelta(hours=1)
    expired = jwt.encode(
        {
            "sub": str(user.id),
            "iat": int((past - timedelta(days=1)).timestamp()),
            "exp": int(past.timestamp()),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )

    response = unauthenticated_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid or expired session"


def test_me_with_tampered_token_returns_401(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    user = _make_user(db_session)
    # Sign with the wrong secret → signature check fails.
    bogus = jwt.encode({"sub": str(user.id)}, "not-the-real-secret", algorithm="HS256")

    response = unauthenticated_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {bogus}"}
    )

    assert response.status_code == 401


def test_me_for_deleted_user_returns_401(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    """If the user row vanishes after a token is issued, the session dies too."""
    user = _make_user(db_session)
    token = create_access_token(user.id)

    db_session.delete(user)
    db_session.commit()

    response = unauthenticated_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


# ── Protected endpoints are protected ────────────────────────────────────────


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("GET", "/documents", {}),
        ("POST", "/ask", {"json": {"question": "what?"}}),
        ("GET", "/graph", {}),
    ],
    ids=["documents-list", "ask", "graph"],
)
def test_protected_endpoints_return_401_without_auth(
    unauthenticated_client: TestClient,
    method: str,
    path: str,
    kwargs: dict,
) -> None:
    response = unauthenticated_client.request(method, path, **kwargs)
    assert response.status_code == 401
    # WWW-Authenticate is required by the HTTP spec on 401.
    assert "www-authenticate" in {h.lower() for h in response.headers}


def test_protected_endpoint_accepts_bearer_token(
    unauthenticated_client: TestClient,
    db_session: Session,
) -> None:
    """End-to-end: real token → protected endpoint returns 200, not 401."""
    user = _make_user(db_session)
    token = create_access_token(user.id)

    response = unauthenticated_client.get(
        "/documents",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Empty list is fine — the point is we got past auth.
    assert response.status_code == 200
    assert response.json() == []


# ── Password hashing primitives ──────────────────────────────────────────────


def test_hash_password_roundtrip() -> None:
    from app.services.auth import verify_password

    hashed = hash_password("super-secret-password")
    assert hashed != "super-secret-password"
    assert verify_password("super-secret-password", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_verify_password_handles_malformed_hash() -> None:
    """A garbage stored hash mustn't crash the login path."""
    from app.services.auth import verify_password

    assert verify_password("anything", "not-a-real-bcrypt-hash") is False
