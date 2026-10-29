"""Bound login attempts before consuming or validating a request body."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from app.api.rate_limits import LOGIN_IP_LIMITER, enforce_limit
from app.api.request_limits import bounded_body
from app.schemas.auth import LoginRequest


LOGIN_REQUEST_OPENAPI = {
    "requestBody": {"required": True, "content": {"application/json": {
        "schema": LoginRequest.model_json_schema(),
    }}},
}


async def parse_login_request(request: Request) -> LoginRequest:
    # Use the socket peer, never an unauthenticated forwarded-for header.
    enforce_limit(LOGIN_IP_LIMITER, request.client.host if request.client else "unknown")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Use application/json")
    try:
        raw = await bounded_body(request, 2 * 1024)
        return LoginRequest.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid login request") from exc
    except TimeoutError as exc:
        raise HTTPException(408, "Request body timed out") from exc
    except ClientDisconnect as exc:
        raise HTTPException(400, "Request body interrupted") from exc
