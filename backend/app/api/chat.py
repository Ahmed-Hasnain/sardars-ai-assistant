from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
import httpx
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import Settings
from app.db.models import User
from app.db.session import get_db
from app.llm.base import ChatMessage, ChatModel, ModelError
from app.llm.ollama import OllamaChatModel
from app.rag.routing import route_question
from app.schemas.ask import SourceCitation
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.company_answer import answer_company

router = APIRouter(prefix="/api/v1", tags=["chat"])

SYSTEM_PROMPT = (
    "Answer general questions helpfully. You do not have verified Sardars "
    "company data. If asked about Sardars products, prices, stock, policies, "
    "or delivery, say that you cannot verify that information yet. Do not "
    "invent company facts."
)

chat_model: ChatModel = OllamaChatModel(Settings())


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatResponse:
    if route_question(request.message) == "company":
        try:
            answer = await answer_company(request.message, user.role, db, chat_model)
        except (httpx.HTTPError, ModelError) as exc:
            raise HTTPException(status_code=503, detail="Answer service unavailable") from exc
        return ChatResponse(
            answer=answer.text,
            route="company",
            sources=[SourceCitation(**vars(source)) for source in answer.sources],
            model=answer.model,
        )

    messages: list[ChatMessage] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request.message},
    ]

    try:
        result = await chat_model.chat(messages)
    except ModelError as exc:
        raise HTTPException(status_code=503, detail="Local model unavailable") from exc

    return ChatResponse(
        answer=result.text,
        route="general",
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        output_tokens=result.output_tokens,
        duration_ms=result.duration_ms,
    )
