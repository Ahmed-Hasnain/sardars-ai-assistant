"""Claims that a descriptive source cannot establish as current or safe links."""

import re


UNVERIFIED_BUSINESS_FACT = re.compile(
    r"\b(?:ceo|chief executive|owner|director|founder|prices?|pricing|stock|inventory|"
    r"availab(?:le|ility)|discount|promotion|sale|returns?|refunds?|warrant(?:y|ies)|"
    r"guarantee|deliver(?:s|ed|ing|y|ies)?|shipping|opening hours|address)\b",
    re.I,
)
INLINE_LINK = re.compile(r"\b(?:https?://|www\.)\S+", re.I)
CATALOG_PROMISE = re.compile(
    r"\b(?:warrant(?:y|ies)|guaranteed?\s+(?:delivery|shipping)|"
    r"free\s+(?:delivery|shipping)|in\s+stock|ships?\s+tomorrow)\b", re.I,
)


def unsafe_descriptive_claim(text: str) -> bool:
    """Only separately validated citation URLs may appear in company answers."""
    return bool(UNVERIFIED_BUSINESS_FACT.search(text) or INLINE_LINK.search(text))


def unsafe_catalog_display(text: str) -> bool:
    """A product name may say 'price'; only actual promises and links are rejected."""
    return bool(CATALOG_PROMISE.search(text) or INLINE_LINK.search(text))
