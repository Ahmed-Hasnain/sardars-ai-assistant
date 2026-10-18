"""Bounded lexical reranking of role-prefiltered semantic candidates."""

import re


WORD = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a", "about", "an", "and", "are", "can", "describe", "describes", "do",
    "does", "for", "from", "have", "how", "in", "include", "includes", "is",
    "it", "made", "me", "mention", "of", "or", "say", "says", "sardars",
    "tell", "the", "their", "this", "to", "us", "what", "which", "with",
}


def _terms(value: str) -> set[str]:
    return {
        word[:-1] if word.endswith("s") and len(word) > 4 else word
        for word in WORD.findall(value.lower())
        if word not in STOP_WORDS
    }


def rerank(question: str, points: list[dict], limit: int) -> list[dict]:
    """Prefer exact title/description terms, retaining semantic order for ties."""
    query = _terms(question)
    if not query:
        return points[:limit]

    def score(item: tuple[int, dict]) -> tuple[float, int]:
        index, point = item
        payload = point.get("payload")
        if not isinstance(payload, dict):
            return (0, -index)
        title = payload.get("title")
        body = payload.get("text")
        title_terms = _terms(title[:500]) if isinstance(title, str) else set()
        body_terms = _terms(body[:1500]) if isinstance(body, str) else set()
        title_hits = len(query & title_terms)
        body_hits = len(query & body_terms)
        # Keep semantic rank relevant when keyword evidence is weak.
        return (3 * title_hits + body_hits + 2 / (index + 1), -index)

    ranked = sorted(enumerate(points), key=score, reverse=True)
    return [point for _, point in ranked[:limit]]
