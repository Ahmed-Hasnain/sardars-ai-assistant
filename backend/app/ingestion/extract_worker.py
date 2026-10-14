"""Short-lived, resource-limited extraction process; no model or database access."""

import base64
from http.client import HTTPSConnection
from io import BytesIO
import ipaddress
import json
import resource
import socket
import ssl
import sys
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from pypdf import PdfReader

from app.ingestion.documents import valid_web_url
from app.ingestion.public_site import extract_document, source_type, USER_AGENT
from app.ingestion.site_documents import MAX_DOCUMENT_CHARS, MAX_DOCUMENT_WORDS

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_HTML_BYTES = 3 * 1024 * 1024
MAX_PAGES = 50


class ExtractionFailure(ValueError):
    """Controlled messages that are safe to return without imported text."""


def bounded_text(text: str) -> str:
    text = text.strip()
    if not text or "\x00" in text:
        raise ExtractionFailure("Document has no usable text; scanned PDFs require OCR")
    if len(text) > MAX_DOCUMENT_CHARS or len(text.split()) > MAX_DOCUMENT_WORDS:
        raise ExtractionFailure("Extracted document exceeds the text limit; split it into smaller documents")
    return text


def file_text(raw: bytes, kind: str) -> str:
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ExtractionFailure("File must contain between 1 byte and 5 MiB")
    if kind in {"text", "markdown"}:
        try:
            return bounded_text(raw.decode("utf-8-sig"))
        except UnicodeError as exc:
            raise ExtractionFailure("Text and Markdown files must use UTF-8 encoding") from exc
    if kind != "pdf" or not raw.startswith(b"%PDF-"):
        raise ExtractionFailure("Unsupported file or invalid PDF signature")
    reader = PdfReader(BytesIO(raw), strict=True)
    if reader.is_encrypted:
        raise ExtractionFailure("Encrypted PDFs are not supported")
    if len(reader.pages) > MAX_PAGES:
        raise ExtractionFailure("PDF exceeds the 50-page limit")
    parts = []
    length = 0
    for page in reader.pages:
        value = page.extract_text() or ""
        length += len(value)
        if length > MAX_DOCUMENT_CHARS:
            raise ExtractionFailure("PDF exceeds the extracted text limit")
        parts.append(value)
    return bounded_text("\n\n".join(parts))


class PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, host: str, address: str):
        super().__init__(host, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self) -> None:
        # Connect to the already checked address, retaining TLS hostname checks.
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def public_addresses(host: str) -> list[str]:
    addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ExtractionFailure("URL host must resolve only to public addresses")
    return addresses


def fetch(host: str, address: str, path: str, limit: int, *, robots: bool = False) -> bytes:
    connection = PinnedHTTPSConnection(host, address)
    try:
        connection.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        response = connection.getresponse()
        if robots and response.status == 404:
            return b""
        if response.status != 200:
            raise ExtractionFailure("URL fetch failed or redirected; use a direct HTTPS page")
        if response.getheader("Content-Encoding", "identity").lower() not in {"identity", ""}:
            raise ExtractionFailure("Compressed URL responses are not supported")
        if not robots and response.getheader("Content-Type", "").split(";")[0].lower() not in {"text/html", "application/xhtml+xml"}:
            raise ExtractionFailure("URL must serve HTML; upload PDFs through the file endpoint")
        content = bytearray()
        while block := response.read(64 * 1024):
            content.extend(block)
            if len(content) > limit:
                raise ExtractionFailure("URL response exceeds its size limit")
        return bytes(content)
    finally:
        connection.close()


def web_text(url: str, hosts: list[str]) -> dict:
    if not valid_web_url(url) or urlsplit(url).hostname not in hosts:
        raise ExtractionFailure("URL is not on a configured HTTPS host")
    host = urlsplit(url).hostname
    if host == "sardarandco.com" and source_type(url) is None:
        raise ExtractionFailure("Select a descriptive Sardars page, article, or product URL")
    address = public_addresses(host)[0]
    rules = RobotFileParser()
    rules.parse(fetch(host, address, "/robots.txt", 256 * 1024, robots=True).decode("utf-8").splitlines())
    if not rules.can_fetch(USER_AGENT, url):
        raise ExtractionFailure("URL is disallowed by robots rules")
    raw = fetch(host, address, urlsplit(url).path or "/", MAX_HTML_BYTES)
    kind = source_type(url)
    if kind:
        record = extract_document(url, raw)
        if record is None:
            raise ExtractionFailure("Page contains no usable descriptive text")
        title, text = record["title"], record["text"]
    else:
        soup = BeautifulSoup(raw, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else host
        main = soup.select_one("main") or soup.select_one("article") or soup.body
        if main is None:
            raise ExtractionFailure("Page contains no usable descriptive text")
        for node in main.select("script, style, nav, header, footer, form, button"):
            node.decompose()
        text = main.get_text(" ", strip=True)
    return {"text": bounded_text(text), "title": title[:500], "raw": base64.b64encode(raw).decode()}


def main() -> None:
    # Limits apply to PDF decompression, parsing, DNS, and URL reads. The parent
    # also kills this process after 30 seconds of wall-clock time.
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    try:
        request = json.loads(sys.stdin.buffer.read(8 * 1024 * 1024))
        if request["mode"] == "url":
            result = web_text(request["url"], request["hosts"])
        else:
            raw = base64.b64decode(request["raw"], validate=True)
            result = {"text": file_text(raw, request["kind"])}
    except ExtractionFailure as exc:
        result = {"error": str(exc)}
    except Exception:
        result = {"error": "Invalid document or URL unavailable; extraction failed"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
