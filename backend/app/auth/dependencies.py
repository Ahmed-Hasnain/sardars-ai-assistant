"""Load the user on every request so revocation and role changes take effect."""

from dataclasses import dataclass
import re
import time
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import token_hash
from app.db.models import LoginSession, User
from app.db.session import get_db


bearer = HTTPBearer(auto_error=False)
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True)
class AuthContext:
    user: User
    login_session: LoginSession


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401, detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> AuthContext:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not TOKEN_PATTERN.fullmatch(credentials.credentials)
    ):
        raise _unauthorized()

    login_session = db.get(LoginSession, token_hash(credentials.credentials))
    if login_session is None or login_session.expires_at_epoch <= int(time.time()):
        raise _unauthorized()
    user = db.get(User, login_session.user_id)
    if user is None or not user.is_active or user.role not in {"admin", "staff"}:
        raise _unauthorized()
    return AuthContext(user=user, login_session=login_session)


def get_current_user(
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> User:
    return context.user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
