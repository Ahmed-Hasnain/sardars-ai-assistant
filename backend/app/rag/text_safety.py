"""Shared, conservative instruction-pattern checks; not a complete detector."""

import re

PATTERNS = (
    re.compile(r"\b(?:ignore|disregard|override|forget)\b.{0,100}\b(?:instructions?|rules?|prompts?)\b", re.I),
    re.compile(r"\b(?:reveal|leak|print|expose)\b.{0,100}\b(?:secrets?|passwords?|tokens?|system prompts?)\b", re.I),
    re.compile(r"(?m)^\s*(?:#{1,6}\s*)?(?:system|developer|assistant)\s*:", re.I),
    re.compile(r"(?:<\|im_start\|>\s*(?:system|developer|assistant)|\[INST\]|\[/INST\])", re.I),
    re.compile(r"\b(?:act as|pretend to be)\b.{0,80}\b(?:system|developer|administrator|admin)\b", re.I),
)


def contains_prompt_instruction(text: str) -> bool:
    return any(pattern.search(text) for pattern in PATTERNS)
