"""Conservative, auditable verbatim excerpts from the authorized saved crawl.

This is a content-scope filter, not fact verification or source approval.
Original records remain intact; offsets refer to their exact extracted text.
"""

from hashlib import sha256
import re

from app.ingestion.coverage import CHANGING_CLAIMS, TRANSACTION_CLAIMS, normalize
from app.ingestion.site_documents import WebsiteDocument
from app.rag.text_safety import contains_prompt_instruction

METHOD = "descriptive_spans_v1"
BOUNDARY = re.compile(
    r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z0-9])|"
    r"\s+(?=(?:Available [Cc]olou?rs?|Warr[ae]nty|Art(?: No)?|Size|Dimensions|"
    r"Model number|Material|Brand)\s*[:：])|"
    r"\s+(?=Warr[ae]nty\s+\d)", re.I,
)
ADDITIONAL_CLAIMS = re.compile(
    r"\b(?:available|availability|in[- ]store|warr[ae]nt(?:y|ies)|guarantee[ds]?|"
    r"guaranteeing|refund|deliver(?:y|ies)|payments?|order(?:s|ed|ing)?|"
    r"buy|shop|purchase|quote|contact|phone|tel|email|whatsapp|"
    r"showroom|opening hours|aries tower|murree r(?:oa)?d|shamsabad)\b|"
    r"\b(?:PKR|Rs\.?)\s*\d|\b\d[\d,]*\s*(?:PKR|rupees)\b", re.I,
)
MISLABELED = re.compile(r"Applicable Water Pressure.{0,30}\b\d[\d -]*\s*V\b", re.I)
DEDICATED_SCOPE = re.compile(r"\b(?:prices?|sale|discounts?|refunds?|returns?|shipping|warrant(?:y|ies))\b", re.I)


def omission_reason(text: str) -> str | None:
    if CHANGING_CLAIMS.search(text):
        return "changing_claim"
    if TRANSACTION_CLAIMS.search(text) or ADDITIONAL_CLAIMS.search(text):
        return "transaction_contact_or_promise"
    return None


def descriptive_document(original: WebsiteDocument) -> tuple[WebsiteDocument | None, dict]:
    record = {"source_id": original.source_id, "url": original.url,
              "original_title": original.title,
              "source_type": original.source_type, "fetched_at": original.fetched_at.isoformat(),
              "original_content_sha256": original.content_sha256,
              "original_words": len(original.text.split()), "retained_spans": [], "omitted_spans": []}
    if original.derivation is not None:
        raise ValueError("Prepare from original crawler records, not previous excerpts")
    reason = None
    if contains_prompt_instruction(original.title + "\n" + original.text):
        reason = "instruction_patterns"
    elif MISLABELED.search(original.text):
        reason = "possibly_mislabeled_specification"
    elif (original.source_type != "products" and DEDICATED_SCOPE.search(original.url.rsplit("/", 1)[-1].replace("-", " "))) or original.url.endswith(("/contact", "/faqs", "/our-projects")):
        reason = "dedicated_changing_transaction_contact_or_navigation_source"
    title = original.title
    if not reason and omission_reason(title):
        # Retain an exact descriptive title clause, never invent a product name.
        candidates = [part.strip() for part in re.split(r"\s+[|—–]\s+", title)]
        title = next((part for part in candidates if len(part.split()) >= 3 and not omission_reason(part)), "")
        if not title:
            reason = "no_descriptive_title_clause"
        else:
            start = original.title.index(title)
            record["retained_title_span"] = {"start": start, "end": start + len(title)}
    if reason:
        return None, {**record, "status": "rejected", "reason": reason}

    spans = []
    cursor = 0
    for boundary in BOUNDARY.finditer(original.text):
        spans.append((cursor, boundary.start()))
        cursor = boundary.end()
    spans.append((cursor, len(original.text)))
    seen = set()
    retained = []
    for start, end in spans:
        part = original.text[start:end]
        start += len(part) - len(part.lstrip())
        end -= len(part) - len(part.rstrip())
        if start >= end:
            continue
        part = original.text[start:end]
        normalized = normalize(part)
        reason = omission_reason(part)
        if normalized in seen:
            reason = "repeated_verbatim_segment"
        seen.add(normalized)
        if reason:
            record["omitted_spans"].append({"start": start, "end": end, "reason": reason})
        else:
            retained.append(part)
            record["retained_spans"].append({"start": start, "end": end})
    # Do not publish just a heading after removing the whole description.
    body = [part for part in retained if normalize(part) != normalize(original.title)]
    structured_identity = any(re.search(r"\b(?:art|model|size|dimensions)\s*[:：]\s*\S", part, re.I) for part in body)
    if not body or (sum(len(part.split()) for part in body) < 3 and not structured_identity):
        return None, {**record, "status": "rejected", "reason": "no_descriptive_body"}
    # Unmodified documents retain their checksum, chunk IDs and existing seed behavior.
    text = "\n\n".join(retained) if record["omitted_spans"] else original.text
    raw = original.model_dump(mode="json")
    raw.update(text=text, content_sha256=sha256(text.encode()).hexdigest())
    raw["title"] = title
    if text != original.text or title != original.title:
        raw["derivation"] = {"method": METHOD, "original_content_sha256": original.content_sha256}
    document = WebsiteDocument.model_validate(raw)
    return document, {**record, "status": "pending", "reason": None,
                      "content_sha256": document.content_sha256,
                      "retained_words": len(text.split()), "derived": document.derivation is not None}
