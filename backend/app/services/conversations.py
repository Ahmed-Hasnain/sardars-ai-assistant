"""Owned conversation storage and bounded context; never a source of business facts."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from uuid import uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Conversation, ConversationMessage, SourceRegistration, User
from app.db.products import Product
from app.llm.base import ChatMessage
from app.rag.text_safety import contains_prompt_instruction
from app.schemas.ask import SourceCitation
from app.schemas.chat import ChatResponse
from app.services.web_search import safe_result_url
from app.schemas.conversations import ConversationPage, ConversationSummary, MessageView


RETENTION_DAYS = Settings().conversation_retention_days
MAX_CONTEXT_MESSAGES = 8
MAX_CONTEXT_CHARS = 1600
MAX_RECENT_ROWS = 12
HIDDEN_ANSWER = "This earlier answer is no longer available under your current source access."
FOLLOWUP = re.compile(r"^(?:and\b|what about\b|how about\b|which (?:of (?:these|those)|one)\b)|\b(?:it|its|they|them|those|these|their|this product|that product)\b", re.I)
PRODUCT_FOLLOWUP = re.compile(r"\b(?:which of these|which of those|which one|these|those|them|their|it|its|this product|that product)\b", re.I)
POLICY_TOPIC = re.compile(r"\b(?:warranty|return|refund|delivery|shipping|policy)\b", re.I)
SAFE_HANDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,199}\Z")


class ConversationNotFound(Exception):
    pass


class ConversationConflict(Exception):
    pass


def _safe_handles(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(
        handle for handle in raw
        if isinstance(handle, str) and SAFE_HANDLE.fullmatch(handle)
    ))[:3]


@dataclass(frozen=True)
class TurnContext:
    conversation: Conversation
    version: int
    recent: tuple[ConversationMessage, ...]

    @property
    def previous_question(self) -> str | None:
        return self.recent[-2].content if len(self.recent) >= 2 and self.recent[-2].role == "user" else None

    @property
    def previous_route(self) -> str | None:
        return self.recent[-1].route if self.recent and self.recent[-1].role == "assistant" else None

    @property
    def product_handles(self) -> list[str]:
        if self.previous_route in {"product", "product_search"}:
            return _safe_handles(self.recent[-1].product_handles)
        return []


def is_followup(question: str) -> bool:
    return bool(FOLLOWUP.search(question))


def inferred_product_handles(question: str, context: TurnContext | None) -> list[str]:
    if (context is None or not PRODUCT_FOLLOWUP.search(question)
        or POLICY_TOPIC.search(question)):
        return []
    return context.product_handles


def general_history(question: str, context: TurnContext | None) -> list[ChatMessage]:
    if context is None or context.previous_route != "general" or not is_followup(question):
        return []
    pairs: list[list[ChatMessage]] = []
    used = 0
    recent = context.recent
    for index in range(len(recent) - 2, -1, -2):
        user, assistant = recent[index], recent[index + 1]
        if user.role != "user" or assistant.role != "assistant" or assistant.route != "general":
            break
        if contains_prompt_instruction(user.content) or contains_prompt_instruction(assistant.content):
            break
        length = len(user.content) + len(assistant.content)
        if used + length > MAX_CONTEXT_CHARS or len(pairs) * 2 >= MAX_CONTEXT_MESSAGES:
            break
        pairs.append([
            {"role": "user", "content": user.content},
            {"role": "assistant", "content": assistant.content},
        ])
        used += length
        if not is_followup(user.content):
            break
    return [message for pair in reversed(pairs) for message in pair]


def company_search_query(question: str, context: TurnContext | None) -> str:
    if (context is not None and context.previous_route == "company"
        and context.previous_question and is_followup(question)):
        return context.previous_question[:250] + " " + question
    return question


def _bound_sql(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL statement_timeout = '2s'"))
        db.execute(text("SET LOCAL lock_timeout = '1s'"))


def load_owned(db: Session, user: User, conversation_id: str) -> TurnContext:
    _bound_sql(db)
    now = datetime.now(timezone.utc)
    conversation = db.scalar(select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
        Conversation.expires_at > now,
        Conversation.required_role.in_(["staff", "admin"] if user.role == "admin" else ["staff"]),
    ))
    if conversation is None:
        raise ConversationNotFound
    recent = tuple(reversed(db.scalars(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conversation_id,
    ).order_by(ConversationMessage.id.desc()).limit(MAX_RECENT_ROWS)).all()))
    return TurnContext(conversation, conversation.version, recent)


def save_turn(
    db: Session, user: User, request_text: str, request_handles: list[str],
    response: ChatResponse, context: TurnContext | None,
) -> str:
    _bound_sql(db)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=RETENTION_DAYS)
    if context is None:
        conversation_id = str(uuid4())
        db.add(Conversation(
            id=conversation_id, user_id=user.id, required_role=user.role, version=1,
            created_at=now, updated_at=now, expires_at=expires_at,
        ))
        db.flush()
    else:
        conversation_id = context.conversation.id
        elevated_role = "admin" if user.role == "admin" else context.conversation.required_role
        changed = db.execute(update(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
            Conversation.version == context.version,
            Conversation.expires_at > now,
        ).values(
            version=context.version + 1, required_role=elevated_role,
            updated_at=now, expires_at=expires_at,
        ).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise ConversationConflict
    db.add_all([
        ConversationMessage(
            conversation_id=conversation_id, role="user", content=request_text,
            product_handles=_safe_handles(request_handles), source_ids=[], created_at=now,
        ),
        ConversationMessage(
            conversation_id=conversation_id, role="assistant", content=response.answer,
            route=response.route, model=response.model, prompt_tokens=response.prompt_tokens,
            output_tokens=response.output_tokens, duration_ms=response.duration_ms,
            source_ids=[source.source_id for source in response.sources if source.origin == "company"][:8],
            web_sources=[source.model_dump(mode="json") for source in response.sources
                         if source.origin == "web"][:3],
            product_handles=_safe_handles(response.product_handles), created_at=now,
        ),
    ])
    db.commit()
    return conversation_id


def list_owned(db: Session, user: User, limit: int, offset: int) -> list[ConversationSummary]:
    _bound_sql(db)
    now = datetime.now(timezone.utc)
    allowed_roles = ["staff", "admin"] if user.role == "admin" else ["staff"]
    first_question = select(func.substr(ConversationMessage.content, 1, 100)).where(
        ConversationMessage.conversation_id == Conversation.id,
        ConversationMessage.role == "user",
    ).order_by(ConversationMessage.id).limit(1).correlate(Conversation).scalar_subquery()
    rows = db.execute(select(Conversation, first_question).where(
        Conversation.user_id == user.id, Conversation.expires_at > now,
        Conversation.required_role.in_(allowed_roles),
    ).order_by(Conversation.updated_at.desc(), Conversation.id.desc()).offset(offset).limit(limit)).all()
    return [ConversationSummary(
        id=row.id, created_at=row.created_at, updated_at=row.updated_at, expires_at=row.expires_at,
        preview=preview.strip() if preview else None,
    ) for row, preview in rows]


def _visible_history_ids(db: Session, user: User, messages: list[ConversationMessage]) -> tuple[dict[str, SourceRegistration], set[str]]:
    source_ids = {identity for message in messages for identity in (message.source_ids or [])}
    handles = {handle for message in messages if message.role == "assistant"
               for handle in (message.product_handles or [])}
    permitted = {"public", "staff", "admin"} if user.role == "admin" else {"public", "staff"}
    visible_sources: dict[str, SourceRegistration] = {}
    if source_ids:
        visible_sources = {source.source_id: source for source in db.scalars(select(SourceRegistration).where(
            SourceRegistration.source_id.in_(source_ids),
            SourceRegistration.is_active.is_(True),
            SourceRegistration.index_status == "ready",
            SourceRegistration.visibility.in_(permitted),
        )).all()}
    visible_handles = set()
    if handles:
        allowed_products = permitted & {"staff", "admin"}
        visible_handles = set(db.scalars(select(Product.handle).where(
            Product.handle.in_(handles),
            Product.visibility.in_(allowed_products),
            func.lower(Product.status) == "active",
        ).distinct()).all())
        # A handle may contain variants with different visibility. Without an
        # exact saved row list, hide the old answer if any row is now private.
        hidden_handles = set(db.scalars(select(Product.handle).where(
            Product.handle.in_(handles),
            ~Product.visibility.in_(allowed_products),
        ).distinct()).all())
        visible_handles -= hidden_handles
    return visible_sources, visible_handles


def read_page(
    db: Session, user: User, conversation_id: str, limit: int, before_message_id: int | None,
) -> ConversationPage:
    context = load_owned(db, user, conversation_id)
    query = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
    if before_message_id is not None:
        query = query.where(ConversationMessage.id < before_message_id)
    newest = db.scalars(query.order_by(ConversationMessage.id.desc()).limit(limit + 1)).all()
    more = len(newest) > limit
    page = list(reversed(newest[:limit]))
    visible_sources, visible_handles = _visible_history_ids(db, user, page)
    messages = []
    for row in page:
        authorized = (set(row.source_ids or []) <= set(visible_sources)
                      and set(row.product_handles or []) <= visible_handles) if row.role == "assistant" else True
        web_sources = []
        if authorized and row.role == "assistant":
            for raw in (row.web_sources or [])[:3]:
                if isinstance(raw, dict) and safe_result_url(raw.get("url")):
                    try:
                        citation = SourceCitation.model_validate(raw)
                    except ValueError:
                        continue
                    if citation.origin == "web" and citation.source_id.startswith("web:"):
                        web_sources.append(citation)
        messages.append(MessageView(
            id=row.id, role=row.role, content=row.content if authorized else HIDDEN_ANSWER,
            route=row.route, model=row.model, prompt_tokens=row.prompt_tokens,
            output_tokens=row.output_tokens, duration_ms=row.duration_ms,
            product_handles=list(row.product_handles or []) if authorized else [],
            sources=[SourceCitation(
                number=number, source_id=source_id,
                title=visible_sources[source_id].title or visible_sources[source_id].original_filename
                      or visible_sources[source_id].url,
                url=visible_sources[source_id].url,
                fetched_at=(visible_sources[source_id].fetched_at.isoformat()
                            if visible_sources[source_id].fetched_at else None),
            ) for number, source_id in enumerate(dict.fromkeys(row.source_ids or []), start=1)]
            + web_sources if authorized and row.role == "assistant" else [],
            created_at=row.created_at,
        ))
    return ConversationPage(
        conversation=ConversationSummary(
            id=context.conversation.id, created_at=context.conversation.created_at,
            updated_at=context.conversation.updated_at, expires_at=context.conversation.expires_at,
        ),
        messages=messages, next_before_message_id=page[0].id if more and page else None,
    )


def delete_owned(db: Session, user: User, conversation_id: str) -> None:
    _bound_sql(db)
    conversation = db.scalar(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user.id,
    ))
    if conversation is None:
        raise ConversationNotFound
    db.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id))
    db.delete(conversation)
    db.commit()


def purge_expired(db: Session, *, batch_size: int = 100) -> int:
    _bound_sql(db)
    expired = db.scalars(select(Conversation.id).where(
        Conversation.expires_at <= datetime.now(timezone.utc),
    ).limit(batch_size)).all()
    if expired:
        db.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id.in_(expired)))
        db.execute(delete(Conversation).where(Conversation.id.in_(expired)))
        db.commit()
    return len(expired)
