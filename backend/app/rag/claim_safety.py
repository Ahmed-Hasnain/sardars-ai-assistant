"""Claims that a descriptive source cannot establish as current or safe links."""

import re


UNVERIFIED_BUSINESS_FACT = re.compile(
    r"\b(?:ceo|chief executive|owner|director|founder|prices?|pricing|stock|inventory|"
    r"availab(?:le|ility)|discount|promotion|sale|returns?|refunds?|warrant(?:y|ies)|warrenty|"
    r"guarantee|deliver(?:s|ed|ing|y|ies)?|shipping|opening hours)\b",
    re.I,
)
PHYSICAL_ADDRESS = re.compile(
    r"\b(?:physical|street|postal|showroom|business|office)\s+address\b|"
    r"\baddress\s*(?:is\b|at\b|:)", re.I,
)
SAFE_QUALIFICATION = re.compile(
    r"\b(?:does not by itself prove|requires checking|check the|check for|"
    r"not automatically guaranteed|not verified|not confirmed|cannot verify|"
    r"can't verify|should not be presented as current)\b", re.I,
)
ASSERTED_SENSITIVE_VALUE = re.compile(
    r"\b(?:in stock|available now|currently available|warranty covers|"
    r"guarantee(?:d|s)? delivery|delivery tomorrow|deliver tomorrow)\b|"
    r"\b\d+(?:[.,]\d+)?\b", re.I,
)
INLINE_LINK = re.compile(r"\b(?:https?://|www\.)\S+", re.I)
CATALOG_PROMISE = re.compile(
    r"\b(?:warrant(?:y|ies)|guaranteed?\s+(?:delivery|shipping)|"
    r"free\s+(?:delivery|shipping)|in\s+stock|ships?\s+tomorrow)\b", re.I,
)


def unsafe_descriptive_claim(text: str) -> bool:
    """Only separately validated citation URLs may appear in company answers."""
    if INLINE_LINK.search(text) or PHYSICAL_ADDRESS.search(text):
        return True
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if UNVERIFIED_BUSINESS_FACT.search(sentence) and (
            not SAFE_QUALIFICATION.search(sentence)
            or ASSERTED_SENSITIVE_VALUE.search(sentence)
        ):
            return True
    return False


def unsafe_catalog_display(text: str) -> bool:
    """A product name may say 'price'; only actual promises and links are rejected."""
    return bool(CATALOG_PROMISE.search(text) or INLINE_LINK.search(text))
