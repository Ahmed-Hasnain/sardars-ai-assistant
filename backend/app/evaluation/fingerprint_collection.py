"""Print a read-only content fingerprint for the configured Qdrant collection."""

import asyncio
from hashlib import sha256
import json

import httpx

from app.core.config import Settings
from app.retrieval.seed_config import COLLECTION


async def fingerprint() -> tuple[int, str]:
    settings = Settings()
    digest = sha256()
    count = 0
    offset = None
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            request = {"limit": 256, "with_payload": True, "with_vector": True}
            if offset is not None:
                request["offset"] = offset
            response = await client.post(
                f"{settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}/points/scroll",
                json=request,
            )
            response.raise_for_status()
            result = response.json()["result"]
            points = result["points"]
            if not isinstance(points, list) or len(points) > 256:
                raise ValueError("Invalid Qdrant scroll response")
            for point in points:
                digest.update(json.dumps(
                    (point["id"], point["payload"], point["vector"]), sort_keys=True,
                    ensure_ascii=False, separators=(",", ":"),
                ).encode())
                digest.update(b"\n")
                count += 1
            if count > 100_000:
                raise ValueError("Evaluation collection exceeds fingerprint limit")
            next_offset = result.get("next_page_offset")
            if next_offset is None:
                return count, digest.hexdigest()
            if next_offset == offset or not points:
                raise ValueError("Qdrant scroll did not advance")
            offset = next_offset


if __name__ == "__main__":
    print(*asyncio.run(fingerprint()))
