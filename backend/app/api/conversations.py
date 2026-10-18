"""Owned conversation history, with bounded pages and safe errors."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.api.rate_limits import HISTORY_LIMITER, enforce_limit
from app.db.models import User
from app.db.session import get_db
from app.schemas.conversations import ConversationPage, ConversationSummary
from app.services.conversations import ConversationNotFound, delete_owned, list_owned, read_page


router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])
ConversationId = Annotated[str, Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=1000)] = 0,
) -> list[ConversationSummary]:
    enforce_limit(HISTORY_LIMITER, user.id)
    try:
        return list_owned(db, user, limit, offset)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Conversation service unavailable") from exc


@router.get("/{conversation_id}", response_model=ConversationPage)
def get_conversation(
    conversation_id: ConversationId,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    before_message_id: Annotated[int | None, Query(ge=1)] = None,
) -> ConversationPage:
    enforce_limit(HISTORY_LIMITER, user.id)
    try:
        return read_page(db, user, conversation_id, limit, before_message_id)
    except ConversationNotFound as exc:
        raise HTTPException(404, "Conversation not found") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Conversation service unavailable") from exc


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: ConversationId,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    enforce_limit(HISTORY_LIMITER, user.id)
    try:
        delete_owned(db, user, conversation_id)
    except ConversationNotFound as exc:
        raise HTTPException(404, "Conversation not found") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(503, "Conversation service unavailable") from exc
