"""Bounded SearXNG JSON search. Search snippets are untrusted, external evidence."""

from datetime import datetime, timezone
import ipaddress
import re
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings
from app.rag.text_safety import contains_prompt_instruction
from app.tools.schemas import WebSearchArguments, WebSearchHit, WebSearchResults

MAX_BODY_BYTES = 64 * 1024
PRIVATE_QUERY = re.compile(
    r"(?:\b(?:sardars?|sardar\s*(?:&|and)\s*co|sku|stock|inventory|"
    r"password|token|secret|confidential|private)\b|@|https?://|/api/|\b\d{5,}\b)", re.I,
)
PUBLIC_METAL_RATE = re.compile(
    r"\b(?:gold|silver)\b.{0,80}\b(?:rates?|prices?|spot)\b|"
    r"\b(?:rates?|prices?|spot)\b.{0,80}\b(?:gold|silver)\b", re.I,
)
PRICE_QUERY = re.compile(r"\b(?:prices?|pricing)\b", re.I)
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def public_search_query_allowed(query: str) -> bool:
    """Keep catalog pricing private while allowing public metal-market prices."""
    return not PRIVATE_QUERY.search(query) and (not PRICE_QUERY.search(query) or bool(PUBLIC_METAL_RATE.search(query)))


class SearchUnavailable(Exception):
    pass


class QueryNotAllowed(Exception):
    pass


def safe_result_url(raw: object) -> str | None:
    if not isinstance(raw, str) or len(raw) > 2048 or CONTROL.search(raw):
        return None
    try:
        url = urlsplit(raw)
        host = url.hostname
        if (url.scheme != "https" or not host or url.username or url.password
                or url.port not in (None, 443) or host.endswith((".local", ".internal", ".test", ".example"))
                or host == "localhost" or "." not in host
                or not re.fullmatch(r"[a-z0-9.-]+", host, re.I)):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        return raw
    except ValueError:
        return None


def _endpoint(settings: Settings) -> str:
    base = settings.web_search_base_url
    if not base:
        raise SearchUnavailable
    parsed = urlsplit(base)
    if (parsed.scheme != "http" or parsed.hostname not in {"searxng", "127.0.0.1"}
            or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise SearchUnavailable
    return base.rstrip("/") + "/search"


def search_web(arguments: WebSearchArguments, settings: Settings | None = None) -> WebSearchResults:
    """Only an explicit public-looking question may leave the application network."""
    query = " ".join(arguments.query.split())
    if not public_search_query_allowed(query) or CONTROL.search(query) or len(query) < 3:
        raise QueryNotAllowed
    # A vague metal-rate request needs one clearly labelled market and unit.
    # Pakistan is only a search reference; the answer must name that market.
    if PUBLIC_METAL_RATE.search(query) and not re.search(r"\b(?:pakistan|pkr|usd|world|global|international|india|uk|usa|united states)\b", query, re.I):
        metal = re.search(r"\b(?:gold|silver)\b", query, re.I).group(0).lower()
        search_query = f"{metal} rate Pakistan today PKR per tola 24K 22K"
    else:
        # Prefer an original publisher's release page over mirrors and summaries.
        search_query = query + " official" if (re.search(r"\b(?:release|version)\b", query, re.I)
                                               and len(query) <= 191) else query
    endpoint = _endpoint(settings or Settings())
    try:
        with httpx.Client(timeout=6, trust_env=False, follow_redirects=False) as client:
            response = client.get(endpoint, params={
                "q": search_query, "format": "json", "categories": "general", "safesearch": "2", "pageno": "1",
            })
            response.raise_for_status()
            if len(response.content) > MAX_BODY_BYTES:
                raise SearchUnavailable
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SearchUnavailable from exc
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise SearchUnavailable
    hits: list[WebSearchHit] = []
    seen: set[str] = set()
    for item in body["results"][:20]:
        if not isinstance(item, dict):
            continue
        url = safe_result_url(item.get("url"))
        if url is None or url in seen:
            continue
        title = item.get("title")
        snippet = item.get("content")
        if not isinstance(title, str) or not isinstance(snippet, str):
            continue
        title = CONTROL.sub(" ", title).strip()[:160]
        snippet = CONTROL.sub(" ", snippet).strip()[:500]
        if not title or not snippet:
            continue
        if contains_prompt_instruction(title) or contains_prompt_instruction(snippet):
            continue
        hits.append(WebSearchHit(title=title, url=url, snippet=snippet))
        seen.add(url)
        if len(hits) == 3:
            break
    return WebSearchResults(observed_at=datetime.now(timezone.utc), hits=hits)
