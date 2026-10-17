"""One answer budget shared by async and threaded retrieval/model calls."""

import asyncio
from contextvars import ContextVar
from time import monotonic
from typing import Awaitable, TypeVar

from app.core.config import Settings


ANSWER_TIMEOUT_SECONDS = Settings().answer_timeout_seconds
_deadline: ContextVar[float | None] = ContextVar("answer_deadline", default=None)
T = TypeVar("T")


async def within_answer_deadline(work: Awaitable[T]) -> T:
    seconds = ANSWER_TIMEOUT_SECONDS
    token = _deadline.set(monotonic() + seconds)
    try:
        async with asyncio.timeout(seconds):
            return await work
    finally:
        _deadline.reset(token)


def remaining_timeout(limit: float) -> float:
    deadline = _deadline.get()
    if deadline is None:
        return limit
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Answer deadline exceeded")
    return min(limit, max(0.001, remaining))
