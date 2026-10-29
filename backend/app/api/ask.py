"""Authenticated access to the approved public-source answer seed."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
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
from app.schemas.ask import AskResponse
from app.schemas.chat import ChatRequest
from app.services.model_assistant import answer_model_first


router = APIRouter(prefix="/api/v1", tags=["answers"])
_settings = Settings()
answer_model: ChatModel = OllamaChatModel(_settings.model_copy(update={
    "ollama_model": _settings.prototype_chat_model,
}), output_limit=160, tool_output_limit=96)


@router.post("/ask", response_model=AskResponse, openapi_extra=QUESTION_REQUEST_OPENAPI)
async def ask(
    request: Annotated[ChatRequest, Depends(parse_question_request)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AskResponse:
    if request.conversation_id is not None:
        raise HTTPException(status_code=422, detail="Conversation follow-ups use /api/v1/chat")
    try:
        result = await within_answer_deadline(answer_model_first(
            request.message, user, db, answer_model, product_handles=request.product_handles,
        ))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Answer timed out") from exc
    except (httpx.HTTPError, ModelError, SQLAlchemyError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Answer service unavailable") from exc

    return AskResponse(answer=result.answer, sources=result.sources)
