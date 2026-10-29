"""Choose bounded evidence only after checking current source permissions."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.retrieval.authorization import authorized_points
from app.retrieval.limits import CANDIDATE_LIMIT
from app.retrieval.rerank import rerank
from app.retrieval.search_seed import PRODUCT_DISCOVERY_QUESTION, _needs_company_profile


def select_authorized_points(
    db: Session, role: str, question: str, candidates: list[dict],
) -> list[dict]:
    points = authorized_points(db, role, candidates)
    if PRODUCT_DISCOVERY_QUESTION.search(question):
        # Broad discovery can have several valid products. Lexical ranking
        # over-promotes generic storage words and displaces cited evidence.
        return points[:CANDIDATE_LIMIT]
    profile_url = Settings().brand_definition_profile_url
    pinned = ([point for point in points if point["payload"].get("url") == profile_url][:2]
              if profile_url and _needs_company_profile(question) else [])
    pinned_refs = {id(point) for point in pinned}
    remaining = [point for point in points if id(point) not in pinned_refs]
    return pinned + rerank(question, remaining, CANDIDATE_LIMIT - len(pinned))
