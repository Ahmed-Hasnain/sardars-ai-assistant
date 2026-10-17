"""Bound incoming bytes and read time after route authentication."""

import asyncio

from fastapi import HTTPException, Request


BODY_READ_TIMEOUT_SECONDS = 30.0


async def bounded_body(request: Request, limit: int) -> bytes:
    content = bytearray()
    async with asyncio.timeout(BODY_READ_TIMEOUT_SECONDS):
        async for block in request.stream():
            if len(content) + len(block) > limit:
                raise HTTPException(413, "Request exceeds its size limit")
            content.extend(block)
    return bytes(content)
