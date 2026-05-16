"""Interactive CLI for creating a PaperMind user.

The deliberate non-feature: there's no public ``/auth/register`` endpoint.
Users come into existence ONLY by running this on the server. That's the
whole access-control story for a single-tenant personal app — if you
control the box, you control who logs in.

Usage (from the ``backend`` directory):

    uv run python -m app.cli.create_user

The script:
1. Ensures the ``users`` table exists (calls ``create_all`` defensively in
   case it's a fresh DB).
2. Prompts for email — validated against EmailStr's rules.
3. Prompts for password twice (hidden input via ``getpass``), 8+ chars.
4. Refuses if the email is already taken.
5. Hashes with bcrypt and inserts.

Non-interactive use (CI, scripts) — pass values via environment variables:

    PAPERMIND_EMAIL=admin@example.com \\
    PAPERMIND_PASSWORD=changeme1234 \\
    uv run python -m app.cli.create_user --non-interactive
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.db import Base, SessionLocal, engine
from app.models import User
from app.services.auth import hash_password

_email_adapter: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)
MIN_PASSWORD_LEN = 8


def _validate_email(raw: str) -> str | None:
    """Return the normalised email (lowercased) or None on invalid input."""
    try:
        return _email_adapter.validate_python(raw.strip()).lower()
    except ValidationError:
        return None


def _prompt_email() -> str:
    while True:
        raw = input("Email: ")
        email = _validate_email(raw)
        if email is not None:
            return email
        print("  ✗ not a valid email — try again")


def _prompt_password() -> str:
    while True:
        pw = getpass.getpass(f"Password (min {MIN_PASSWORD_LEN} chars): ")
        if len(pw) < MIN_PASSWORD_LEN:
            print(f"  ✗ too short — must be at least {MIN_PASSWORD_LEN} chars")
            continue
        pw2 = getpass.getpass("Repeat password: ")
        if pw != pw2:
            print("  ✗ passwords don't match — try again")
            continue
        return pw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a PaperMind user.")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Take email/password from PAPERMIND_EMAIL / PAPERMIND_PASSWORD env vars.",
    )
    args = parser.parse_args(argv)

    # Make sure the users table exists. No-op on an existing DB.
    Base.metadata.create_all(engine)

    if args.non_interactive:
        email_raw = os.environ.get("PAPERMIND_EMAIL", "").strip()
        password = os.environ.get("PAPERMIND_PASSWORD", "")
        email = _validate_email(email_raw)
        if not email:
            print("✗ PAPERMIND_EMAIL is missing or not a valid email", file=sys.stderr)
            return 2
        if len(password) < MIN_PASSWORD_LEN:
            print(
                f"✗ PAPERMIND_PASSWORD is missing or shorter than {MIN_PASSWORD_LEN} chars",
                file=sys.stderr,
            )
            return 2
    else:
        print("Create a PaperMind user")
        print()
        email = _prompt_email()
        password = _prompt_password()

    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first() is not None:
            print(f"✗ user with email {email!r} already exists", file=sys.stderr)
            return 1

        user = User(email=email, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"\n✓ created user id={user.id} email={user.email}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
