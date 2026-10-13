"""Create local admin/staff accounts without putting passwords in shell history."""

import argparse
from getpass import getpass

from sqlalchemy import func, select

from app.auth.security import hash_password, normalize_email
from app.db.models import User
from app.db.session import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an internal Sardars user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=("admin", "staff"), required=True)
    args = parser.parse_args()
    email = normalize_email(args.email)

    with SessionLocal() as db:
        user_count = db.scalar(select(func.count()).select_from(User)) or 0
        if user_count == 0 and args.role != "admin":
            raise SystemExit("The first user must be an admin")
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            raise SystemExit("This email already exists")

        password = getpass("Password (12–128 characters): ")
        if password != getpass("Confirm password: "):
            raise SystemExit("Passwords do not match")
        try:
            password_hash = hash_password(password)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

        db.add(User(email=email, password_hash=password_hash, role=args.role))
        db.commit()
    print(f"Created {args.role} user: {email}")


if __name__ == "__main__":
    main()
