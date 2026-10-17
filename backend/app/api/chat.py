import asyncio
import re
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
from app.llm.base import ChatMessage, ChatModel, ModelError
from app.llm.ollama import OllamaChatModel
from app.rag.routing import scope_question
from app.rag.text_safety import contains_prompt_instruction
from app.schemas.ask import SourceCitation
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.company_answer import answer_company
from app.services.product_answer import PRODUCT_INTENT, answer_product
from app.services.product_discovery import answer_product_discovery

router = APIRouter(prefix="/api/v1", tags=["chat"])

SYSTEM_PROMPT = (
    "Answer general questions helpfully. You do not have verified Sardars "
    "company data. If asked about Sardars products, prices, stock, policies, "
    "or delivery, say that you cannot verify that information yet. Do not "
    "invent company facts."
)

chat_model: ChatModel = OllamaChatModel(Settings())
DISCOVERY_INTENT = re.compile(r"\b(?:recommend|suggest|compare|comparison|difference|cheaper|under|below|over|above|less than|more than|which is better|which one)\b", re.I)
PRODUCT_DOMAIN = re.compile(r"\b(?:products?|catalogue|catalog|sku|basin|mixer|faucet|tap|toilet|shower|sink|bath|vanity|tile|flush|plate)\b", re.I)


@router.post("/chat", response_model=ChatResponse, openapi_extra=QUESTION_REQUEST_OPENAPI)
async def chat(
    request: Annotated[ChatRequest, Depends(parse_question_request)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatResponse:
    try:
        return await within_answer_deadline(_answer_chat(request, user, db))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Answer timed out") from exc


async def _answer_chat(request: ChatRequest, user: User, db: Session) -> ChatResponse:
    scope = scope_question(request.message, has_product_context=bool(request.product_handles))
    if scope in {"unrelated", "health", "unsupported_action", "unsafe"}:
        replies = {
            "unrelated": "I can help with Sardars and general bathroom product questions.",
            "health": "I can't provide medical or fertility advice. Please ask a qualified healthcare professional.",
            "unsupported_action": "I can't carry out orders, messages, bookings, or product changes in this assistant.",
            "unsafe": "I can't disclose private information or change my access rules.",
        }
        return ChatResponse(answer=replies[scope], route="out_of_scope", model=None)
    if scope == "company" and (
        request.product_handles or
        (DISCOVERY_INTENT.search(request.message) and PRODUCT_DOMAIN.search(request.message))
    ):
        try:
            return await asyncio.wait_for(
                answer_product_discovery(request.message, user, db, request.product_handles), timeout=35,
            )
        except asyncio.TimeoutError:
            return ChatResponse(answer="Product search timed out.", route="product_search", model=None)
    if scope == "company" and PRODUCT_INTENT.search(request.message):
        try:
            return await asyncio.wait_for(answer_product(request.message, user, db), timeout=10)
        except asyncio.TimeoutError:
            return ChatResponse(answer="Product lookup timed out.", route="product", model=None)
    if scope == "company":
        try:
            answer = await answer_company(request.message, user.role, db, chat_model)
        except (httpx.HTTPError, ModelError, SQLAlchemyError, ValueError) as exc:
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

    if re.search(r"\b(?:sardars?|sardarandco\.com)\b", result.text, re.I) or contains_prompt_instruction(result.text):
        return ChatResponse(
            answer="I can't verify Sardars-specific information in a general answer.",
            route="general", model=result.model,
        )

    return ChatResponse(
        answer=result.text,
        route="general",
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        output_tokens=result.output_tokens,
        duration_ms=result.duration_ms,
    )
