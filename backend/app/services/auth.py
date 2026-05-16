"""Password hashing + JWT session tokens for PaperMind.

bcrypt for password storage (battle-tested, OWASP-recommended; argon2 would
be slightly stronger but its Python wheel is heavier and bcrypt is fine for
a personal-tier threat model).

JWT in an httpOnly cookie for session — stateless (no server-side session
store needed), invalidated either by waiting out the expiry or by rotating
``settings.jwt_secret`` (which kills every active session immediately).

Why not localStorage:
- httpOnly cookie is opaque to JavaScript → XSS can't lift the token.
- Cookies are auto-sent with same-origin requests; the frontend doesn't
  have to thread tokens through every fetch() call.
- SameSite=lax blocks CSRF on the dangerous methods we use (POST/DELETE).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings

_JWT_ALG = "HS256"


def hash_password(password: str) -> str:
    """Bcrypt-hash a plaintext password.

    Returns the 60-char ASCII hash including the algorithm marker, cost,
    and random salt — everything needed to verify later. Cost 12 is a
    reasonable 2026 default (~250 ms per hash on modern hardware).
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time check against a stored bcrypt hash.

    Returns False instead of raising on malformed input — the caller is
    typically in a login path that should treat "couldn't verify" the same
    as "wrong password" rather than 500.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    """Sign a JWT carrying the user id and an expiry claim."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.jwt_session_days)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALG)


def decode_access_token(token: str) -> int | None:
    """Verify signature + expiry and return the user id, or None on failure.

    Any invalid token (expired, wrong signature, missing sub, malformed)
    collapses to None so callers can treat the auth failure uniformly.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALG])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None
