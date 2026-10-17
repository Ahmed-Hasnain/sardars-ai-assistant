"""Conservative first-pass routing for internal assistant questions."""

import re
from typing import Literal


QuestionScope = Literal["general", "company", "unrelated", "health", "unsupported_action", "unsafe"]
COMPANY_IDENTITY = re.compile(r"\b(?:sardars?|you|your|yours|we|our|ours|us)\b", re.I)
COMPANY_POSSESSIVE = re.compile(r"\b(?:sardars?|your|yours|we|our|ours|us)\b", re.I)
COMPANY_FACT = re.compile(
    r"\b(?:price|pricing|cost|stock|inventory|availability|available|"
    r"return|refund|delivery|shipping|order|showroom|store|catalogue|catalog|"
    r"brand|brands|product|products|warranty|opening hours)\b", re.I
)
GENERAL_EDUCATION = re.compile(
    r"^(?:what is an?\b|what are\b|define an?\b|explain what\b|"
    r"explain an?\b|can you explain\b|how (?:does|do)\b.+\bwork\b|"
    r"how (?:to|should i)\b)", re.I
)
GREETING = re.compile(r"^(?:hi|hello|hey|thanks|thank you)[!. ]*$", re.I)
GENERAL_CONCEPT = re.compile(
    r"^(?:(?:what is|define|explain what)\s+(?:a|an)\s+"
    r"(?:product|warranty|product warranty|return policy|inventory)|"
    r"how (?:does|do)\s+(?:a|an)\s+(?:warranty|product warranty|inventory)\s+work)\s*\??$",
    re.I,
)
PRODUCT_EDUCATION = re.compile(r"\b(?:basin|mixer|faucet|tap|toilet|shower|sink|bath|vanity|tile|flush|plumbing)\b", re.I)
HEALTH_TOPIC = re.compile(
    r"\b(?:conception|conceiv(?:e|ing)|fertility|infertility|pregnan\w*|"
    r"ovulat\w*|reproduct\w*|intercourse|sex(?:ual)?|birth control|contraception|"
    r"medical advice|doctors?|physicians?|diagnos\w*|symptoms?|"
    r"medications?|prescriptions?|vaccin\w*|treatments?|"
    r"diseases?|cancer|infections?)\b",
    re.I,
)
INSTRUCTION_OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|override|forget)\b.{0,80}\b(?:system|developer|previous)\s+(?:instructions?|prompts?|rules?)\b",
    re.I,
)
PRIVATE_REQUEST = re.compile(
    r"\b(?:reveal|show|print|give|send|leak|expose)\b.{0,80}"
    r"\b(?:system prompt|developer prompt|passwords?|access tokens?|api keys?|other users?'? (?:data|documents?|chats?))\b",
    re.I,
)
HARMFUL_REQUEST = re.compile(
    r"\b(?:how (?:to|do i)|teach me to|steps to)\b.{0,80}"
    r"\b(?:make (?:a |an )?(?:bomb|explosive)|poison someone|steal credentials|hack (?:an? )?account)\b",
    re.I,
)
ACTION_REQUEST = re.compile(
    r"\b(?:place|submit|cancel)\b.{0,60}\b(?:orders?|quotes?|bookings?)\b|"
    r"\b(?:send|write)\b.{0,60}\b(?:emails?|messages?)\b|"
    r"\b(?:change|update|delete|remove)\b.{0,60}\b(?:prices?|inventory|products?|sources?)\b",
    re.I,
)
UNRELATED = re.compile(
    r"\b(?:tell me a joke|write (?:python )?code|write a poem|weather|capital of|"
    r"solve (?:this |an? )?(?:equation|math problem))\b", re.I,
)


def scope_question(question: str, *, has_product_context: bool = False) -> QuestionScope:
    """Classify only clear exclusions; uncertain business questions remain grounded."""
    text = question.strip()
    if INSTRUCTION_OVERRIDE.search(text) or PRIVATE_REQUEST.search(text) or HARMFUL_REQUEST.search(text):
        return "unsafe"
    # Do not send health questions to an unsourced general model or company RAG.
    if HEALTH_TOPIC.search(text):
        return "health"
    if ACTION_REQUEST.search(text):
        return "unsupported_action"
    if has_product_context:
        return "company"
    if GENERAL_CONCEPT.fullmatch(text):
        return "general"
    if COMPANY_IDENTITY.search(text):
        if (not COMPANY_POSSESSIVE.search(text) and GENERAL_EDUCATION.match(text)
            and not COMPANY_FACT.search(text)):
            return "general"
        return "company"
    if GREETING.fullmatch(text):
        return "general"
    if GENERAL_EDUCATION.match(text) and not COMPANY_FACT.search(text):
        return "general"
    if UNRELATED.search(text) and not PRODUCT_EDUCATION.search(text):
        return "unrelated"
    return "company"


def route_question(question: str) -> QuestionScope:
    return scope_question(question)
