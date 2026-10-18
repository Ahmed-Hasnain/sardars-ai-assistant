"""Authenticate before reading and validating a bounded question body."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from app.api.request_limits import bounded_body
from app.api.rate_limits import QUESTION_LIMITER, enforce_limit
from app.auth.dependencies import get_current_user
from app.db.models import User
from app.schemas.chat import ChatRequest


# Leave room for 2,000 characters encoded as JSON surrogate-pair escapes.
MAX_QUESTION_BODY_BYTES = 32 * 1024
QUESTION_REQUEST_OPENAPI = {
    "requestBody": {"required": True, "content": {"application/json": {
        "schema": ChatRequest.model_json_schema(),
        "example": {"message": "What is a mixer?"},
    }}},
}


async def parse_question_request(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> ChatRequest:
    """Use actual streamed bytes, including when Content-Length is absent."""
    if isinstance(getattr(user, "id", None), int):
        enforce_limit(QUESTION_LIMITER, user.id)
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(415, "Use application/json")
    try:
        raw = await bounded_body(request, MAX_QUESTION_BODY_BYTES)
        return ChatRequest.model_validate_json(raw)
    except ValidationError as exc:
        # Pydantic's default errors can include private input values.
        raise HTTPException(422, "Invalid question request") from exc
    except TimeoutError as exc:
        raise HTTPException(408, "Request body timed out") from exc
    except ClientDisconnect as exc:
        raise HTTPException(400, "Request body interrupted") from exc
