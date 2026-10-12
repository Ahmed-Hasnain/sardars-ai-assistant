from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.core.config import Settings
from app.db.models import User
from app.llm.base import ChatMessage, ChatModel, ModelError
from app.llm.ollama import OllamaChatModel
from app.schemas.chat import ChatRequest, ChatResponse

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
    _user: Annotated[User, Depends(get_current_user)],
) -> ChatResponse:
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
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        output_tokens=result.output_tokens,
        duration_ms=result.duration_ms,
    )
