"""Replay selected prior internal questions as read-only, standalone chat turns.

The JSON report is local evaluation data and may contain private questions.
This deliberately omits conversation history; it measures answer behavior, not
the saved-conversation API or a historical turn's original context.
"""

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

from sqlalchemy import text

from app.api.answer_deadlines import within_answer_deadline
from app.api.chat import _answer_chat
from app.core.config import Settings
from app.db.models import Conversation, ConversationMessage, User
from app.db.session import SessionLocal
from app.evaluation.observe_chat import observe
from app.evaluation.run_chat import data_fingerprint
from app.llm.ollama import OllamaChatModel
from app.schemas.chat import ChatRequest


async def run(message_ids: list[int], report: Path) -> None:
    if len(message_ids) != len(set(message_ids)) or not 1 <= len(message_ids) <= 8:
        raise ValueError("Choose one through eight distinct message IDs")
    if report.exists():
        raise ValueError("Report already exists; choose a new output file")

    settings = Settings()
    model = OllamaChatModel(settings)
    fingerprint_before = data_fingerprint()
    rows = []
    for message_id in message_ids:
        with SessionLocal() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            message = db.get(ConversationMessage, message_id)
            if message is None or message.role != "user":
                raise ValueError(f"Message {message_id} is not a saved user question")
            conversation = db.get(Conversation, message.conversation_id)
            user = db.get(User, conversation.user_id) if conversation else None
            if user is None or not user.is_active or user.role not in {"staff", "admin"}:
                raise ValueError(f"Message {message_id} has no active internal owner")
            started = perf_counter()
            with observe(model) as observation:
                response = await within_answer_deadline(
                    _answer_chat(ChatRequest(message=message.content), user, db)
                )
            rows.append({
                "message_id": message_id,
                "question": message.content,
                "role": user.role,
                "answer": response.answer,
                "route": response.route,
                "sources": [source.model_dump(mode="json") for source in response.sources],
                "model": response.model,
                "observation": asdict(observation),
                "total_ms": round((perf_counter() - started) * 1000, 1),
            })
            print(f"{message_id}: {response.route}, {rows[-1]['total_ms']} ms", flush=True)

    fingerprint_after = data_fingerprint()
    payload = {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "chat_model": settings.ollama_model,
            "question_sha256": sha256(json.dumps(
                [(row["message_id"], row["question"]) for row in rows],
                ensure_ascii=False, separators=(",", ":")
            ).encode()).hexdigest(),
            "data_fingerprint_before": fingerprint_before,
            "data_fingerprint_after": fingerprint_after,
            "scope": "Read-only standalone replay of selected prior internal questions; no history or HTTP auth",
        },
        "cases": rows,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    if fingerprint_before != fingerprint_after:
        raise RuntimeError("Database facts changed during evaluation")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message-ids", type=int, nargs="+", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.message_ids, args.report))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
