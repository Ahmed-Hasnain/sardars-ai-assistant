"""Internal bearer login, logout, and role inspection."""

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context, get_current_user, require_admin
from app.api.login_requests import LOGIN_REQUEST_OPENAPI, parse_login_request
from app.api.rate_limits import LOGIN_ACCOUNT_LIMITER, enforce_limit
from app.auth.security import new_token, token_hash, verify_password
from app.db.models import LoginSession, User
from app.db.session import get_db
from app.schemas.auth import LoginRequest, TokenResponse, UserPublic


router = APIRouter(prefix="/api/v1", tags=["auth"])
SESSION_SECONDS = 8 * 60 * 60


@router.post("/auth/login", response_model=TokenResponse, openapi_extra=LOGIN_REQUEST_OPENAPI)
def login(
    request: Annotated[LoginRequest, Depends(parse_login_request)],
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    enforce_limit(LOGIN_ACCOUNT_LIMITER, request.email)
    user = db.scalar(select(User).where(User.email == request.email))
    if not verify_password(request.password, user.password_hash if user else None):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    now = int(time.time())
    db.execute(delete(LoginSession).where(LoginSession.expires_at_epoch <= now))
    raw_token = new_token()
    db.add(LoginSession(
        token_hash=token_hash(raw_token), user_id=user.id,
        expires_at_epoch=now + SESSION_SECONDS,
    ))
    db.commit()
    LOGIN_ACCOUNT_LIMITER.forget(request.email)
    return TokenResponse(access_token=raw_token, expires_in_seconds=SESSION_SECONDS)


@router.post("/auth/logout", status_code=204)
def logout(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    db.delete(context.login_session)
    db.commit()


@router.get("/auth/me", response_model=UserPublic)
def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user


@router.get("/admin/users", response_model=list[UserPublic])
def list_users(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))
