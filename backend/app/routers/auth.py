"""Auth endpoints — login, logout, who-am-i.

There is **no** /register endpoint. Users are created out-of-band via
``backend/app/cli/create_user.py`` running on the server. PaperMind is a
single-tenant personal app; the absence of public signup is the simplest
possible access-control policy.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth_deps import SESSION_COOKIE_NAME, get_current_user
from app.config import settings
from app.db import get_db
from app.models import User
from app.schemas import LoginRequest, LoginResponse, UserOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    user = db.query(User).filter(User.email == payload.email.lower()).first()

    # Verify password unconditionally (even when the user doesn't exist) so the
    # timing of "no such user" and "wrong password" matches — small win against
    # email enumeration, costs ~250 ms either way.
    stored_hash = user.password_hash if user else "$2b$12$" + "x" * 53
    if not auth_service.verify_password(payload.password, stored_hash) or user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account is inactive")

    token = auth_service.create_access_token(user.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,           # JS can't read it → mitigates XSS exfiltration
        # HTTPS only — fine in prod, and the browser is permissive about Secure
        # cookies on localhost during Vite dev too.
        secure=True,
        samesite="lax",          # block CSRF on cross-site POST/DELETE
        max_age=60 * 60 * 24 * settings.jwt_session_days,
        path="/",
    )
    return LoginResponse(user=UserOut.model_validate(user), access_token=token)


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    """Clear the session cookie. Idempotent — safe to call when not logged in."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    """Whoami. Frontend hits this on page load to decide login vs main UI."""
    return current_user
