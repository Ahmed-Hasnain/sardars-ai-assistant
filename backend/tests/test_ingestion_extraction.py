"""Parser limits and URL network boundary, without fetching arbitrary hosts."""

from io import BytesIO
import socket
import subprocess
from unittest.mock import Mock

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest

from app.ingestion import extract_worker as worker
from app.ingestion import extraction
from app.ingestion.documents import SuppliedDocument, valid_source, valid_web_url


def pdf(text=None, *, pages=1, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("test-only")
    target = BytesIO()
    writer.write(target)
    return target.getvalue()


def test_real_pdf_and_markdown_subprocess_extraction():
    assert "Sardars catalogue" in extraction.extract_file(pdf("Sardars catalogue"), "pdf")
    assert extraction.extract_file(b"# Sardars\n\nInternal guide.", "markdown") == "# Sardars\n\nInternal guide."


@pytest.mark.parametrize("raw", [pdf(), pdf("encrypted", encrypted=True), pdf(pages=51), b"%PDF-1.4\nmalformed"])
def test_reject_scanned_encrypted_oversized_and_broken_pdfs(raw):
    with pytest.raises(extraction.ExtractionError):
        extraction.extract_file(raw, "pdf")


def test_text_resource_limit_and_subprocess_timeout(monkeypatch):
    with pytest.raises(extraction.ExtractionError, match="text limit"):
        extraction.extract_file(b"a" * 50_001, "text")
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired("test", 30)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(extraction.ExtractionError, match="30-second"):
        extraction.extract_file(b"text", "text")


def test_parser_environment_does_not_inherit_credentials(monkeypatch):
    monkeypatch.setenv("SARDARS_DB_PASSWORD", "private-test-value")
    def run(command, **kwargs):
        assert "SARDARS_DB_PASSWORD" not in kwargs["env"]
        assert kwargs["env"]["PYTHONPATH"].endswith("backend")
        return subprocess.CompletedProcess(command, 0, stdout=b'{"text": "safe text"}')
    monkeypatch.setattr(subprocess, "run", run)
    assert extraction.extract_file(b"safe text", "text") == "safe text"


def test_unexpected_parser_errors_do_not_expose_document_data(monkeypatch, capsys):
    import json
    import sys
    monkeypatch.setattr(worker.resource, "setrlimit", lambda *args: None)
    monkeypatch.setattr(sys, "stdin", Mock(buffer=BytesIO(b'{"mode": "file", "raw": "dGVzdA==", "kind": "pdf"}')))
    def bad_parser(*args):
        raise ValueError("PRIVATE_DOCUMENT_TEXT")
    monkeypatch.setattr(worker, "file_text", bad_parser)
    worker.main()
    result = json.loads(capsys.readouterr().out)
    assert "PRIVATE" not in result["error"]


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "::ffff:127.0.0.1"])
def test_dns_private_address_rejected(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
    with pytest.raises(ValueError, match="public addresses"):
        worker.public_addresses("configured.example")


def test_dns_mixed_public_private_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in ("8.8.8.8", "127.0.0.1")])
    with pytest.raises(ValueError):
        worker.public_addresses("configured.example")


def test_connection_pins_checked_ip_and_preserves_tls_hostname(monkeypatch):
    connect = Mock(return_value=Mock())
    monkeypatch.setattr(socket, "create_connection", connect)
    connection = worker.PinnedHTTPSConnection("configured.example", "8.8.8.8")
    context = Mock()
    connection._context = context
    connection.connect()
    connect.assert_called_once_with(("8.8.8.8", 443), 10)
    context.wrap_socket.assert_called_once_with(connect.return_value, server_hostname="configured.example")


def test_web_extract_respects_robots_and_strips_active_content(monkeypatch):
    monkeypatch.setattr(worker, "public_addresses", lambda host: ["8.8.8.8"])
    monkeypatch.setattr(worker, "fetch", lambda *args, **kwargs: b"User-agent: *\nDisallow: /private" if kwargs.get("robots") else b"<html><title>Guide</title><main>Useful descriptive text.<script>secret active script</script><form>ignored</form></main></html>")
    result = worker.web_text("https://configured.example/guide", ["configured.example"])
    assert result["text"] == "Useful descriptive text."
    with pytest.raises(ValueError, match="robots"):
        worker.web_text("https://configured.example/private", ["configured.example"])


@pytest.mark.parametrize("url", ["https://a.example:443/", "https://a.example/\n", "https://a.example/?secret=x", "https://a.example/#x", "https://a.example\\@localhost/", "https://user@a.example/", "file:///tmp/test"])
def test_web_url_identity_rejects_ambiguous_or_secret_bearing_urls(url):
    assert not valid_web_url(url)


def test_stored_key_cannot_escape_storage_root():
    with pytest.raises(ValueError):
        extraction.storage_path(Mock(), "../../secret")
    assert not valid_source("/anything", "text")
    assert not valid_source("https://a.example/", {})


@pytest.mark.parametrize("status,headers,content", [
    (302, {"Content-Type": "text/html"}, b"redirect"),
    (200, {"Content-Type": "application/pdf"}, b"pdf"),
    (200, {"Content-Type": "text/html", "Content-Encoding": "gzip"}, b"compressed"),
    (200, {"Content-Type": "text/html"}, b"x" * (worker.MAX_HTML_BYTES + 1)),
])
def test_fetch_rejects_redirects_wrong_types_compression_and_size(monkeypatch, status, headers, content):
    response = Mock(status=status)
    response.getheader.side_effect = lambda key, default=None: headers.get(key, default)
    response.read.side_effect = [content, b""]
    connection = Mock()
    connection.getresponse.return_value = response
    monkeypatch.setattr(worker, "PinnedHTTPSConnection", lambda *args: connection)
    with pytest.raises(ValueError):
        worker.fetch("configured.example", "8.8.8.8", "/guide", worker.MAX_HTML_BYTES)
    connection.close.assert_called_once()
