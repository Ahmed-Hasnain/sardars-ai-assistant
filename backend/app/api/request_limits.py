"""Bound incoming bytes and read time after route authentication."""

import asyncio

from fastapi import HTTPException, Request


async def bounded_body(request: Request, limit: int) -> bytes:
    content = bytearray()
    async with asyncio.timeout(30):
        async for block in request.stream():
            content.extend(block)
            if len(content) > limit:
                raise HTTPException(413, "Request exceeds its size limit")
    return bytes(content)
