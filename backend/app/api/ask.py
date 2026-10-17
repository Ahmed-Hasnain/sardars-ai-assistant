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
from app.rag.routing import scope_question
from app.rag.answer_seed import FALLBACK
from app.services.company_answer import answer_company
from app.schemas.ask import AskResponse, SourceCitation
from app.schemas.chat import ChatRequest


router = APIRouter(prefix="/api/v1", tags=["answers"])
answer_model: ChatModel = OllamaChatModel(Settings())


@router.post("/ask", response_model=AskResponse, openapi_extra=QUESTION_REQUEST_OPENAPI)
async def ask(
    request: Annotated[ChatRequest, Depends(parse_question_request)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AskResponse:
    if request.conversation_id is not None:
        raise HTTPException(status_code=422, detail="Conversation follow-ups use /api/v1/chat")
    if scope_question(request.message) in {"unsafe", "unsupported_action", "unrelated", "health"}:
        return AskResponse(answer=FALLBACK, sources=[])
    try:
        result = await within_answer_deadline(answer_company(request.message, user.role, db, answer_model))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Answer timed out") from exc
    except (httpx.HTTPError, ModelError, SQLAlchemyError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Answer service unavailable") from exc

    sources = [SourceCitation(**vars(source)) for source in result.sources]
    return AskResponse(answer=result.text, sources=sources)
