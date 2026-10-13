"""Bounded extraction of public descriptive content from the Sardars sitemap.

Run with ``PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.public_site``.
This writes reviewable JSONL, not embeddings or model-ready trusted facts.
"""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from bs4 import BeautifulSoup
import httpx


SITE = "https://sardarandco.com"
SITEMAP = f"{SITE}/sitemap.xml"
USER_AGENT = "SardarsAssistantPrototype/0.1 (public descriptive content)"
NAMESPACE = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
MAX_XML_BYTES = 5_000_000
MAX_HTML_BYTES = 3_000_000
ALLOWED_TYPES = ("pages", "articles", "products")
BLOCKED_PAGE_PARTS = ("quote", "account", "checkout", "cart", "order")


def source_type(url: str) -> str | None:
    """Allow only public, descriptive HTML routes on the exact site host."""
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "sardarandco.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) == 2 and parts[0] == "pages":
        if any(word in parts[1].lower() for word in BLOCKED_PAGE_PARTS):
            return None
        return "pages"
    if len(parts) == 3 and parts[:2] == ["blogs", "news"]:
        return "articles"
    if len(parts) == 2 and parts[0] == "products":
        return "products"
    return None


def _get(client: httpx.Client, url: str, max_bytes: int) -> bytes:
    """Reject off-site and redirected requests, including URLs from sitemaps."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "sardarandco.com":
        raise ValueError(f"Off-site URL refused: {url}")
    with client.stream("GET", url) as response:
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError(f"Redirect refused: {url}")
        chunks = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"Response too large: {url}")
            chunks.append(chunk)
    return b"".join(chunks)


def _xml_urls(data: bytes, item: str) -> list[str]:
    root = ElementTree.fromstring(data)
    return [
        node.text.strip()
        for node in root.findall(f"sm:{item}/sm:loc", NAMESPACE)
        if node.text
    ]


def discover_urls(client: httpx.Client) -> dict[str, list[str]]:
    """Read the sitemap index and its public content child sitemaps."""
    result: dict[str, list[str]] = {kind: [] for kind in ALLOWED_TYPES}
    index = _get(client, SITEMAP, MAX_XML_BYTES)
    for child_url in _xml_urls(index, "sitemap"):
        child_name = urlparse(child_url).path.rsplit("/", 1)[-1]
        if not child_name.startswith(("sitemap_pages_", "sitemap_articles_", "sitemap_products_")):
            continue
        for url in _xml_urls(_get(client, child_url, MAX_XML_BYTES), "url"):
            kind = source_type(url)
            if kind:
                result[kind].append(url)
    for kind in ALLOWED_TYPES:
        result[kind] = list(dict.fromkeys(result[kind]))
    # Put the page matching the user-supplied company profile first.
    result["pages"].sort(key=lambda url: (url != f"{SITE}/pages/about-us", url))
    return result


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _product_description(soup: BeautifulSoup) -> str:
    descriptions = []
    for node in soup.select("main .product-description.rte.not-in-quickbuy"):
        text = _clean_text(node.get_text(" ", strip=True))
        if text and text not in descriptions:
            descriptions.append(text)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            description = data.get("description")
            if isinstance(description, str):
                text = _clean_text(BeautifulSoup(description, "html.parser").get_text(" "))
                if text and text not in descriptions:
                    descriptions.append(text)
            break
    return "\n\n".join(descriptions)


def extract_document(url: str, html: bytes) -> dict[str, str] | None:
    kind = source_type(url)
    if kind is None:
        return None
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main")
    if main is None:
        return None
    heading = main.select_one("h1")
    title = _clean_text(heading.get_text(" ", strip=True)) if heading else ""
    if not title and soup.title:
        title = _clean_text(soup.title.get_text(" ", strip=True))
    if kind == "products":
        content = _product_description(soup)
    elif kind == "articles":
        body = main.select_one(".rte.cf.spaced-row") or main.select_one(".rte")
        content = _clean_text(body.get_text(" ", strip=True)) if body else ""
    else:
        sections = main.select(".rte")
        if sections:
            content = "\n\n".join(
                dict.fromkeys(
                    text
                    for node in sections
                    if (text := _clean_text(node.get_text(" ", strip=True)))
                )
            )
        else:
            for node in main.select("script, style, form, button, nav"):
                node.decompose()
            content = _clean_text(main.get_text(" ", strip=True))
    if not title or len(content) < 40:
        return None
    text = f"{title}\n\n{content}"
    return {
        "source_id": sha256(url.encode()).hexdigest(),
        "source_type": kind,
        "visibility": "public",
        "review_status": "pending",
        "title": title,
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "content_sha256": sha256(text.encode()).hexdigest(),
        "text": text,
    }


def crawl(limit_per_type: int, output: Path, delay_seconds: float = 1.0) -> tuple[int, int]:
    if not 1 <= limit_per_type <= 1500:
        raise ValueError("limit_per_type must be between 1 and 1500")
    if delay_seconds < 0.5:
        raise ValueError("delay_seconds must be at least 0.5")
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=25, follow_redirects=False
    ) as client:
        robots = _get(client, f"{SITE}/robots.txt", MAX_XML_BYTES).decode("utf-8")
        rules = RobotFileParser()
        rules.parse(robots.splitlines())
        urls = discover_urls(client)
        output.parent.mkdir(parents=True, exist_ok=True)
        written = skipped = 0
        with output.open("w", encoding="utf-8") as stream:
            for kind in ALLOWED_TYPES:
                for url in urls[kind][:limit_per_type]:
                    if not rules.can_fetch(USER_AGENT, url):
                        skipped += 1
                        continue
                    try:
                        html = _get(client, url, MAX_HTML_BYTES)
                        document = extract_document(url, html)
                    except (httpx.HTTPError, ValueError) as exc:
                        print(f"Skipped {url}: {exc}")
                        skipped += 1
                        continue
                    if document is None:
                        skipped += 1
                    else:
                        stream.write(json.dumps(document, ensure_ascii=False) + "\n")
                        written += 1
                        print(f"Extracted {kind}: {url}")
                    time.sleep(delay_seconds)
    return written, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-per-type", type=int, default=1)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument(
        "--output", type=Path, default=Path("data/extracted/public_site.jsonl")
    )
    arguments = parser.parse_args()
    written, skipped = crawl(
        arguments.limit_per_type, arguments.output, arguments.delay_seconds
    )
    print(f"Wrote {written} documents to {arguments.output}; skipped {skipped}.")


if __name__ == "__main__":
    main()
