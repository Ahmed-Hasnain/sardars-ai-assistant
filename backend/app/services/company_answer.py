"""Apply source access policy before grounded company answer generation."""

import asyncio

from sqlalchemy.orm import Session

from app.llm.base import ChatModel
from app.rag.answer_seed import CitedAnswer, answer_from_points
from app.retrieval.authorization import authorized_points
from app.retrieval.search_seed import search_for_role


async def answer_company(
    question: str, role: str, db: Session, model: ChatModel
) -> CitedAnswer:
    points = await asyncio.to_thread(search_for_role, question, role)
    points = authorized_points(db, role, points)
    return await answer_from_points(question, points, model)
