"""FastAPI dependency that resolves the session cookie (or Authorization
header) to a User row.

Kept in its own module to avoid an import cycle: `app.routers.*` need it,
and the auth router itself uses the same dependency to power `/auth/me`.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.services.auth import decode_access_token

SESSION_COOKIE_NAME = "papermind_session"


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Return the user behind the current request, or raise 401.

    Two ways to authenticate:
    - **Cookie** (`papermind_session`) — what the browser uses; set on /login.
    - **Authorization: Bearer <token>** header — for curl / scripts /
      anything not a browser.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "not authenticated",
            # WWW-Authenticate header is part of the HTTP spec for 401; the
            # browser doesn't act on Bearer challenges but curl with `-i`
            # will surface it, which helps debugging.
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "user not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
