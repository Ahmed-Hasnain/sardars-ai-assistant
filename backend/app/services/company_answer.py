"""Apply source access policy before grounded company answer generation."""

import asyncio

from sqlalchemy.orm import Session

from app.llm.base import ChatModel
from app.rag.answer_seed import CitedAnswer, FALLBACK, answer_from_points
from app.rag.claim_safety import unsafe_descriptive_claim
from app.rag.text_safety import contains_prompt_instruction
from app.retrieval.authorization import authorized_points
from app.retrieval.search_seed import search_for_role


async def answer_company(
    question: str, role: str, db: Session, model: ChatModel,
    *, search_query: str | None = None,
) -> CitedAnswer:
    points = await asyncio.to_thread(search_for_role, search_query or question, role)
    points = authorized_points(db, role, points)
    answer = await answer_from_points(question, points, model)
    if answer.text == FALLBACK:
        return CitedAnswer(FALLBACK, [], answer.model)
    if (not answer.sources or unsafe_descriptive_claim(answer.text)
        or contains_prompt_instruction(answer.text)):
        return CitedAnswer(FALLBACK, [], answer.model)
    return answer
