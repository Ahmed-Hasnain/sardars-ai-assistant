"""Small local Ollama queueing probe; not a production load test."""

import asyncio
from time import perf_counter

import httpx

from app.core.config import Settings


async def main() -> None:
    settings = Settings()
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": "Define a bathroom tap in one short sentence."}],
        "stream": False,
        "think": False,
        "keep_alive": 300,
        "options": {"num_predict": 48},
    }
    async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
        async def call() -> tuple[float, int | None]:
            started = perf_counter()
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return round((perf_counter() - started) * 1000, 1), response.json().get("eval_count")

        await call()  # warm the model before comparing serial and overlapping calls
        started = perf_counter()
        serial = [await call(), await call()]
        serial_wall = round((perf_counter() - started) * 1000, 1)
        started = perf_counter()
        parallel = await asyncio.gather(call(), call())
        parallel_wall = round((perf_counter() - started) * 1000, 1)
        print({"serial_wall_ms": serial_wall, "serial_calls": serial,
               "parallel_wall_ms": parallel_wall, "parallel_calls": parallel})
        await client.post(url, json={**payload, "keep_alive": 0})  # restore unload


if __name__ == "__main__":
    asyncio.run(main())
