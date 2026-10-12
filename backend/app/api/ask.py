"""Authenticated access to the approved public-source answer seed."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
import httpx

from app.auth.dependencies import get_current_user
from app.core.config import Settings
from app.db.models import User
from app.llm.base import ChatModel, ModelError
from app.llm.ollama import OllamaChatModel
from app.rag.answer_seed import answer_from_points
from app.retrieval.search_seed import search_approved
from app.schemas.ask import AskResponse, SourceCitation
from app.schemas.chat import ChatRequest


router = APIRouter(prefix="/api/v1", tags=["answers"])
answer_model: ChatModel = OllamaChatModel(Settings())


@router.post("/ask", response_model=AskResponse)
async def ask(
    request: ChatRequest,
    _user: Annotated[User, Depends(get_current_user)],
) -> AskResponse:
    try:
        # search_approved applies public/approved filters before any text reaches the model.
        points = await asyncio.to_thread(search_approved, request.message)
        result = await answer_from_points(request.message, points, answer_model)
    except (httpx.HTTPError, ModelError) as exc:
        raise HTTPException(status_code=503, detail="Answer service unavailable") from exc

    sources = [SourceCitation(title=title, url=url) for title, url in dict.fromkeys(result.sources)]
    return AskResponse(answer=result.text, sources=sources)
