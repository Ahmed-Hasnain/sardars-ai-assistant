"""Authenticated access to the approved public-source answer seed."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
import httpx
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import Settings
from app.db.models import User
from app.db.session import get_db
from app.llm.base import ChatModel, ModelError
from app.llm.ollama import OllamaChatModel
from app.services.company_answer import answer_company
from app.schemas.ask import AskResponse, SourceCitation
from app.schemas.chat import ChatRequest


router = APIRouter(prefix="/api/v1", tags=["answers"])
answer_model: ChatModel = OllamaChatModel(Settings())


@router.post("/ask", response_model=AskResponse)
async def ask(
    request: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AskResponse:
    try:
        result = await answer_company(request.message, user.role, db, answer_model)
    except (httpx.HTTPError, ModelError) as exc:
        raise HTTPException(status_code=503, detail="Answer service unavailable") from exc

    sources = [SourceCitation(**vars(source)) for source in result.sources]
    return AskResponse(answer=result.text, sources=sources)
