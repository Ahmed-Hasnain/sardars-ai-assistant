"""Locally reset an account password and revoke its login sessions.

Run from the project root:
    PYTHONPATH=backend backend/.venv/bin/python -m app.auth.reset_password --email you@example.com
"""

import argparse
from getpass import getpass

from sqlalchemy import delete, select

from app.auth.security import hash_password, normalize_email
from app.db.models import LoginSession, User
from app.db.session import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset an internal account password locally")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    try:
        email = normalize_email(args.email)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            raise SystemExit("No user with that email")

        password = getpass("New password (12–128 characters): ")
        if password != getpass("Confirm new password: "):
            raise SystemExit("Passwords do not match")
        try:
            user.password_hash = hash_password(password)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

        db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        db.commit()
    print(f"Password changed and sessions revoked for {email}")


if __name__ == "__main__":
    main()
