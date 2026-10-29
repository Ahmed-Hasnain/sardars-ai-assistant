"""Authenticated model-first chat with persisted, owner-scoped conversations."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.question_requests import QUESTION_REQUEST_OPENAPI, parse_question_request
from app.api.answer_deadlines import within_answer_deadline
from app.auth.dependencies import get_current_user
from app.core.config import Settings
from app.db.models import User
from app.db.session import get_db
from app.llm.base import ChatModel, ModelError
from app.llm.ollama import OllamaChatModel
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.conversations import (
    ConversationConflict, ConversationNotFound, TurnContext, company_search_query,
    inferred_product_handles, load_owned, save_turn,
)
from app.services.model_assistant import answer_model_first

router = APIRouter(prefix="/api/v1", tags=["chat"])
_settings = Settings()
chat_model: ChatModel = OllamaChatModel(_settings.model_copy(update={
    "ollama_model": _settings.prototype_chat_model,
}), output_limit=160, tool_output_limit=96)


@router.post("/chat", response_model=ChatResponse, openapi_extra=QUESTION_REQUEST_OPENAPI)
async def chat(
    request: Annotated[ChatRequest, Depends(parse_question_request)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatResponse:
    try:
        return await within_answer_deadline(_chat_turn(request, user, db))
    except TimeoutError as exc:
        db.rollback()
        raise HTTPException(status_code=504, detail="Answer timed out") from exc
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    except ConversationConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conversation changed; retry this turn") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Conversation service unavailable") from exc


@router.post("/chat/stream", openapi_extra=QUESTION_REQUEST_OPENAPI)
async def chat_stream(
    request: Annotated[ChatRequest, Depends(parse_question_request)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    response = await chat(request, user, db)

    async def events():
        yield _sse("start", {"conversation_id": response.conversation_id})
        for offset in range(0, len(response.answer), 100):
            yield _sse("chunk", {"text": response.answer[offset:offset + 100]})
        yield _sse("complete", response.model_dump(mode="json"))

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff",
    })


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _chat_turn(request: ChatRequest, user: User, db: Session) -> ChatResponse:
    user_id = getattr(user, "id", None)
    if request.conversation_id and not isinstance(user_id, int):
        raise ConversationNotFound
    context = load_owned(db, user, request.conversation_id) if request.conversation_id else None
    handles = request.product_handles or inferred_product_handles(request.message, context)
    response = await _answer_chat(request.model_copy(update={"product_handles": handles}), user, db, context)
    if isinstance(user_id, int):
        response.conversation_id = save_turn(db, user, request.message, handles, response, context)
    return response


async def _answer_chat(
    request: ChatRequest, user: User, db: Session, context: TurnContext | None = None,
) -> ChatResponse:
    try:
        return await answer_model_first(
            request.message, user, db, chat_model,
            search_query=company_search_query(request.message, context),
            product_handles=request.product_handles,
            previous_question=context.previous_question if context else None,
        )
    except (httpx.HTTPError, ModelError, SQLAlchemyError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Answer service unavailable") from exc
