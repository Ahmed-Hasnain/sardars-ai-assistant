"""Shared, conservative instruction-pattern checks; not a complete detector."""

import re

PATTERNS = (
    re.compile(r"\b(?:ignore|disregard|override|forget)\b.{0,100}\b(?:instructions?|rules?|prompts?)\b", re.I),
    re.compile(r"\b(?:reveal|leak|print|expose)\b.{0,100}\b(?:secrets?|passwords?|tokens?|system prompts?)\b", re.I),
    re.compile(r"(?m)^\s*(?:system|developer|assistant)\s*:", re.I),
)


def contains_prompt_instruction(text: str) -> bool:
    return any(pattern.search(text) for pattern in PATTERNS)
