"""Process-local observers for the serial evaluation CLI, never for API workers."""

from contextlib import ExitStack, contextmanager
from collections.abc import Iterator
from dataclasses import dataclass, field
from time import perf_counter
from unittest.mock import patch

from app.api import chat
from app.llm.base import ChatMessage, ChatModel, ChatResult, ModelError, ToolChatResult
from app.services import company_answer, model_assistant, product_answer, product_discovery


@dataclass
class Observation:
    tools: list[dict] = field(default_factory=list)
    retrieval: list[dict] = field(default_factory=list)
    authorized_sources: list[dict] = field(default_factory=list)
    model_calls: list[dict] = field(default_factory=list)
    # Bounded authorized excerpts make independent claim/citation review possible.
    evidence: list[dict] = field(default_factory=list)


class ObservedModel:
    def __init__(self, model: ChatModel, observation: Observation):
        self.model = model
        self.observation = observation

    async def chat(self, messages: list[ChatMessage], *, output_limit: int | None = None) -> ChatResult:
        started = perf_counter()
        row = {"message_count": len(messages), "output_limit": output_limit,
               "context_characters": sum(len(message["content"]) for message in messages),
               "prompt_tokens": None, "output_tokens": None}
        self.observation.model_calls.append(row)
        try:
            result = await self.model.chat(messages, output_limit=output_limit)
            row.update(model=result.model, prompt_tokens=result.prompt_tokens,
                       output_tokens=result.output_tokens)
            return result
        except Exception as exc:
            row["error_type"] = type(exc).__name__
            raise
        finally:
            row["total_ms"] = round((perf_counter() - started) * 1000, 1)

    async def chat_with_tools(self, messages: list[dict], tools: list[dict]) -> ToolChatResult:
        started = perf_counter()
        row = {"message_count": len(messages), "context_characters": sum(len(message["content"]) for message in messages),
               "tool_choice": True, "prompt_tokens": None, "output_tokens": None}
        self.observation.model_calls.append(row)
        try:
            result = await self.model.chat_with_tools(messages, tools)
            if not isinstance(result, ToolChatResult):
                raise ModelError("Invalid tool choice result")
            row.update(model=result.model, prompt_tokens=result.prompt_tokens,
                       output_tokens=result.output_tokens, requested_tools=[call.name for call in result.tool_calls])
            return result
        except Exception as exc:
            row["error_type"] = type(exc).__name__
            raise
        finally:
            row["total_ms"] = round((perf_counter() - started) * 1000, 1)


@contextmanager
def observe(model: ChatModel) -> Iterator[Observation]:
    """Wrap real calls; retain no prompt, raw candidate text, or tool arguments.

    Patches affect this process only. Run cases serially in a dedicated CLI.
    Authorization is still performed by the original application function.
    """
    observation = Observation()

    def tool_wrapper(original):
        def execute(call, db, user):
            started = perf_counter()
            result = original(call, db, user)
            observation.tools.append({"name": call.name, "ok": result.ok,
                                      "error_code": None if result.ok else result.error.code,
                                      "total_ms": round((perf_counter() - started) * 1000, 1)})
            return result
        return execute

    def search_wrapper(original):
        def search(*args, **kwargs):
            started = perf_counter()
            row = {}
            observation.retrieval.append(row)
            try:
                points = original(*args, **kwargs)
                row["candidate_count"] = len(points)
                return points
            except Exception as exc:
                row["error_type"] = type(exc).__name__
                raise
            finally:
                row["total_ms"] = round((perf_counter() - started) * 1000, 1)
        return search

    def authorization_wrapper(original):
        def authorize(*args, **kwargs):
            points = original(*args, **kwargs)
            observation.authorized_sources.extend({
                "source_id": point["payload"]["source_id"], "url": point["payload"]["url"],
                "score": point.get("score"),
            } for point in points)
            return points
        return authorize

    def excerpt_wrapper(original):
        async def excerpts(*args, **kwargs):
            result = await original(*args, **kwargs)
            observation.evidence.extend({
                "source_id": item.source_id, "title": item.title, "url": item.url,
                "text": item.text[:model_assistant.MAX_EXCERPT_CHARS],
            } for item in result[:model_assistant.MAX_EXCERPTS])
            return result
        return excerpts

    with ExitStack() as stack:
        stack.enter_context(patch.object(chat, "chat_model", ObservedModel(model, observation)))
        stack.enter_context(patch.object(model_assistant, "_authorized_excerpts",
                                         excerpt_wrapper(model_assistant._authorized_excerpts)))
        for module in (model_assistant, product_answer, product_discovery):
            stack.enter_context(patch.object(module, "execute_tool", tool_wrapper(module.execute_tool)))
        for module, name, authorize_name in (
            (model_assistant, "search_for_role", "select_authorized_points"),
            (company_answer, "search_for_role", "select_authorized_points"),
            (product_answer, "fetch_product_points", "authorized_points"),
            (product_discovery, "fetch_product_points", "authorized_points"),
        ):
            stack.enter_context(patch.object(module, name, search_wrapper(getattr(module, name))))
            stack.enter_context(patch.object(module, authorize_name,
                                             authorization_wrapper(getattr(module, authorize_name))))
        yield observation
