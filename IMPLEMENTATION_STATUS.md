# Sardars AI Assistant — implementation status

Last updated: 2026-10-12  
Current phase: Phase 3 — Public source extraction sample verified; embeddings and Qdrant next

This file records **what has actually been built and verified**. `PLAN.md` describes the full roadmap and exit criteria; `AGENTS.md` tells AI coding agents how to work in this repository. If this file differs from the code, inspect the code and correct this file at the next major feature update.

## Update rule

Update this file when a **major feature or phase milestone is complete and verified**: for example, a working PostgreSQL foundation, local LLM chat, document retrieval, grounded RAG, safe tools, conversation history, or the frontend. Record the behavior, key files/components, verification evidence, limitations, and next major milestone. Do not update it for each small file edit, refactor, routine bug fix, dependency adjustment, or command run. Update `PLAN.md` when roadmap scope or acceptance criteria change, or when a phase is formally completed.

“Complete” means the intended behavior works end to end, the relevant checks have passed, and another developer can run it using the documented setup. Files or folders existing by themselves do not count.

## Current working implementation

- The Python 3.12 backend has FastAPI/Uvicorn, typed environment settings, SQLAlchemy with psycopg, and a local virtual environment ignored by Git. `.env.example` documents required settings; `.env` is ignored.
- Docker Compose runs PostgreSQL 18 with a persistent volume, a health check, and port 5433 bound to localhost. `backend/app/db/session.py` creates the application engine and session factory.
- `GET /api/v1/health` checks API liveness. `GET /api/v1/ready` runs `SELECT 1` against PostgreSQL and returns HTTP 503 when the database is unavailable.
- Alembic is wired to the same database settings and has an applied baseline revision (`87b27fb5a926`). This baseline contains no business tables; it establishes schema version tracking.
- Ollama runs locally with `qwen3:0.6b` on the developer's Ubuntu laptop. `backend/app/llm/base.py` defines a small chat interface and result/error types; `backend/app/llm/ollama.py` implements it through Ollama's local HTTP API with a timeout, error handling, and available token/latency metrics. Configuration defaults to unloading the model after each request to conserve memory.
- `POST /api/v1/chat` validates the user's message and returns the model answer, model name, available metrics, and `company_data_verified: false`. It gives HTTP 503 when the model request fails. The system prompt tells the model not to invent Sardars-specific facts, but no company knowledge or deterministic claim verification exists yet.
- `backend/tests/test_health.py` and `backend/tests/test_chat.py` cover six health and chat cases. `backend/requirements-dev.lock` records exact installed development dependencies, and `README.md` describes local setup, tests, and chat.
- The project owner supplied the public website sitemap and company profile text. `data/source_inventory.md` records their provenance, `data/sources/company_profile.md` stores the pasted profile, and `backend/app/ingestion/public_site.py` discovers public sitemap links and extracts reviewable page, article, and product-description records. It checks robots rules, restricts URLs to the site and descriptive paths, limits each run, waits between requests, and leaves product offer data out of extracted text. Output records carry source identity, public visibility, fetch time, content checksum, and pending review status.
- There is no embedding, Qdrant index, retrieval, approved-for-answer company data, authentication/authorization, frontend, or business database schema yet. Some blog articles discuss prices or promotions and need freshness review before indexing. The `services` package is still a placeholder.

Current request flow:

```text
Browser or curl → Uvicorn → FastAPI → /health → liveness JSON
Browser or curl → Uvicorn → FastAPI → /ready → SQLAlchemy → PostgreSQL → readiness JSON or HTTP 503
Postman or curl → Uvicorn → FastAPI → /chat → chat interface → Ollama adapter → local Qwen3 0.6B → response JSON or HTTP 503
```

Verified evidence on 2026-10-12: PostgreSQL was healthy; Alembic `current` and PostgreSQL's `alembic_version` both reported `87b27fb5a926`; the initial smoke suite passed all three tests (with one dependency deprecation warning); `pip check` found no broken requirements; `docker compose config --quiet` passed; and Git ignored `.env` and `backend/.venv/`. The developer then showed a successful direct Ollama response and a successful `OllamaChatModel` response, reported six passing backend tests, and confirmed that the Postman chat request worked. These latter results are user-reported evidence, not a fresh test run for this documentation update. The README describes a fresh setup, but an independent clean-machine replay has not been performed.

Public-source checkpoint on 2026-10-12: the sitemap and robots rules were fetched from the site. The sitemap had 13 eligible public pages, 25 articles, and 1,112 product links. A first review run wrote 63 records; a subsequent full public run wrote 1,008 records (13 pages, 25 articles, 970 products) and skipped 142 product links. Sampled skipped pages loaded but had little or no descriptive text. All 1,008 source IDs are unique and every record is pending review. A local heuristic audit flagged 17 records for possible changing price, stock, or promotion language. A manual sample inspection found the About page's team-directory text in the initial extraction; page extraction was narrowed to content sections and checked against the downloaded page. No record has been approved or embedded. The developer has no staff-document access yet, so the first retrieval slice uses public sources only.

## Phase status

| Phase | Major outcome | Status |
| --- | --- | --- |
| 0 | Product scope and authoritative source decisions | In progress |
| 1 | Backend foundation and PostgreSQL | Complete |
| 2 | Local LLM through an inference interface | Complete |
| 3 | Embeddings, Qdrant, and retrieval | In progress: source extraction only |
| 4 | Grounded RAG with citations | Not started |
| 5 | Real Sardars data and synchronization | Not started |
| 6 | Safe read-only tools | Not started |
| 7 | Combined structured search and RAG | Not started |
| 8 | Guardrail hardening | Not started |
| 9 | Persistent conversations | Not started |
| 10 | Frontend and streaming | Not started |
| 11 | Full evaluation suite | Not started |
| 12 | Measured optimization | Not started |
| 13 | Production deployment | Not started |

## Major features completed

| Date | Feature | What works | Verification |
| --- | --- | --- | --- |
| 2026-10-12 | Backend shell and health endpoint | FastAPI serves `/api/v1/health` locally | HTTP 200, `{"status":"ok"}` |
| 2026-10-12 | PostgreSQL foundation and migrations | Readiness checks PostgreSQL; baseline schema revision applied | Healthy container; matching Alembic/PostgreSQL revision; three smoke tests passed |
| 2026-10-12 | Local-model chat | FastAPI accepts chat requests and calls local Ollama through an inference interface | Developer reported six passing tests and a successful Postman request; direct adapter response was shown |
| 2026-10-12 | Public source extraction | Bounded sitemap crawler writes reviewable records for public pages, articles, and product descriptions | Full run wrote 1,008 records; 142 links skipped; 10 backend tests passed; content remains pending review |

## Active work and next major milestone

The first usable assistant should serve both public customers and staff, but the developer has no staff-document access yet. Proceed with a public-only retrieval prototype using a small reviewed subset; defer staff-only indexing until a source and approver are available. Review the extracted text for stale claims, near duplicates, and page clutter. Define how a request is identified as public or staff and enforce that boundary in application code before staff-only text can enter retrieval results or prompts. Representative questions, the authoritative catalogue/price/stock source, required languages, and a measured response-time target remain open Phase 0 decisions in `PLAN.md`. Next, add a small local embedding model, Qdrant, and retrieval-only checks. No company-specific answer should be treated as verified until grounded retrieval and citation checks are built.
