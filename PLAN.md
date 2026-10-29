# Sardars AI Assistant — product and development plan

Last reviewed: 2026-10-29
Status: closed historical roadmap. The agreed English internal-prototype implementation is complete through Phase 12; Phase 13 deployment was not implemented. The extended implementation cycle is also closed in its measured scope; see `EXTENDED_PLAN.md`.
Implementation status: see `IMPLEMENTATION_STATUS.md`
Repository: `sardars-ai-assistant`

## Purpose and working agreement

Build a self-hosted assistant for Sardars & Co., initially for admins and internal staff only. It should answer relevant general product questions, answer Sardars-specific questions from internally authorized company sources, search and compare products, cite evidence, and eventually perform approved business actions. Public customer access can be planned later. Sardars is the first implementation; keep the underlying components reusable without building a multi-company platform prematurely.

This is also a learning project. Work in small, runnable steps. Before a significant AI component or architectural change, explain what it does, why it is needed, alternatives, and trade-offs. The developer wants to create the application themselves with guided commands and review. Give commands in manageable batches, inspect the result, and then move to the next checkpoint. Do not claim a milestone works until it has been checked.

Core rules:

- Use self-hosted/open-weight models; do not add paid LLM APIs without explicit approval.
- Keep changing company facts outside model weights. Do not fine-tune on prices, stock, promotions, or other frequently changing facts.
- Do not invent Sardars-specific products, brands, prices, availability, specifications, policies, addresses, or promises. Say when verified information is unavailable.
- Keep company knowledge, exact business records, and conversation memory separate.
- Give the model only relevant context from authorized sources and bounded tools. Authorized admin/staff uploads and admin-registered URLs are approved at the source level for internal retrieval; no document-by-document approval queue is required for the first release. Authorization is enforced in application code.
- Start locally. Add infrastructure and frameworks only when a working use case needs them. In particular, no Kubernetes, Kafka, Temporal, agent framework, Celery, Redis, or S3 in the initial foundation by default.
- Keep the application runnable, tested where the behavior matters, and documented after each milestone.

Engineering standards for every phase: use type hints, Pydantic v2 schemas, clear names, environment-based configuration, useful exceptions, and async code when I/O behavior warrants it. Keep API routes thin; put business logic in services and SQL in repositories when those boundaries improve clarity. Use Alembic for schema changes. Add unit tests for important rules and integration tests for core paths. Avoid giant files, duplicated logic, magic constants, premature abstractions, and changes to unrelated working code. Diagnose the failing layer before redesigning it. Explain unfamiliar infrastructure commands before asking the developer to run them.

## Implementation tracking

`IMPLEMENTATION_STATUS.md` is the record of current behavior, phase status, completed major features, and verification evidence. This file preserves the original roadmap and acceptance criteria through Phase 12. `EXTENDED_PLAN.md` records the now-closed follow-up cycle and its explicitly deferred items. New features or acceptance work will use a new plan rather than changing historical checkpoints. If status text here and the implementation status file disagree, inspect the code and use `IMPLEMENTATION_STATUS.md` as the current-status record.

## Decisions to settle before they affect implementation

These questions do not block the remaining Phase 1 work. Record the chosen answer and date here when resolved.

| Decision | Why it matters | Current state |
| --- | --- | --- |
| First audience: public customers, staff, or both | Determines authentication, permitted sources, and feature scope | Admins and internal staff only for the first release (changed 2026-10-13); public customer access deferred. Local admin/staff login is implemented. Both roles may access the approved public-site seed; admins can list account metadata. Phase 5 Step 4 adds authenticated ingestion with public/staff/admin source visibility; actual broader internal company documents still need importing/evaluation. |
| First 10–20 user questions and success criteria | Defines the first useful AI slice and evaluation set | An English internal-prototype suite of 26 cross-route cases plus the retained 40-case full-site and seven-case seed suites is recorded in Phase 11. Provisional engineering gates are in `docs/phase11_evaluation_completion.md`; business acceptance and additional languages remain open. |
| Product catalogue, price, and stock authority | Determines which structured facts the assistant may report and what synchronization is needed | For the internal proof of concept, the developer designated price/SKU values in `public.products` as valid on 2026-10-16 and populated variant stock quantities on 2026-10-18, explicitly accepting those values as valid. The app reads them from PostgreSQL at request time. Shopify/ERP synchronization, external IDs, currency, stock reservations/location, sellable availability and external freshness remain open; do not claim external-system authority. |
| Source approval for the internal release | Determines which material may enter internal retrieval | On 2026-10-13 the project owner approved the supplied Sardars sitemap/site links and pasted company profile, and chose source-level approval for future files, documents, and URLs supplied or registered by authorized admins/staff. Do not require per-document manual review for the first release. The developer has no staff-only documents yet; see `data/source_inventory.md`. |
| Local CPU, RAM, GPU, and VRAM | Determines model size, quantization, and expected latency | Observed 2026-10-12: Ryzen 3 3250U (2 cores/4 threads), 13 GiB RAM with about 2.6 GiB available and 3.2 GiB swap used, integrated Radeon Vega, no NVIDIA GPU; start with a small CPU model and measure latency |
| Required languages: English, Urdu, Roman Urdu | Determines model and retrieval evaluation | Open |
| Intended hosting, traffic, privacy, and data-retention requirements | Determines later production design | Open |

## System boundaries and data ownership

| Component | Responsibility |
| --- | --- |
| LLM | Reasoning, language generation, general educational knowledge, and requests for allowed tools |
| PostgreSQL/company systems | Exact structured records such as products, variants, prices, inventory, users, permissions, conversations, and jobs |
| Qdrant | Searchable index of approved descriptive content; it is derived data, not the source of truth |
| Embedding model | Converts queries and text to vectors using a recorded model/version |
| RAG | Selects relevant unstructured company evidence for a question |
| Tools | Narrow, validated access to structured facts and later confirmed actions |
| Guardrails | Enforce permissions, constrain actions and claims, and handle missing evidence |
| Evaluation and observability | Measure correctness, retrieval, tool use, safety, latency, and failures |

Information policy:

- A general question such as “What is a thermostatic mixer?” may use the model's general knowledge.
- A Sardars-specific claim must be supported by an internally authorized company source. Store a stable source reference and, where relevant, an update/as-of time. Source approval permits retrieval; it does not establish that a changing fact is current or that a retrieved chunk answers the question.
- Price, stock, availability, promotions, and other changing facts must come from the authoritative system or a freshness-checked copy. If the source or freshness is unknown, say the value cannot be verified.
- Product and variant identity must be consistent across source data, PostgreSQL, and Qdrant. Preserve source-system IDs and SKUs; do not assume a product title uniquely identifies an item.
- Staff-only data must be filtered by application permissions before it reaches retrieval results, tools, prompts, or logs for an unauthorized role. No public user access is in the first release; a later public release needs a separate visibility policy and review.
- If sources conflict, follow an explicit source-priority rule approved by the business owner; log conflicts rather than silently choosing a value.

## Intended request and ingestion flows

Chat request: frontend → FastAPI → authentication/rate limit → input and scope checks → query routing → direct domain answer, RAG, structured tool, or a combination → evidence/context assembly → LLM generation → output checks → answer with citations and provenance. Keep the inference layer behind `generate()` and later `stream()`/tool-request operations so Ollama can be replaced with vLLM without changing business logic. Bound tool iterations (initial limit: five), context size, output tokens, timeouts, and errors. Do not send all documents or the full conversation on every request.

Ingestion: authorized admin/staff source or registered URL → extract → clean and normalize → logical documents → document-aware chunks → embeddings → Qdrant points plus metadata. The source registry records who supplied the source, its allowed audience, and its URL/domain or file identity; records inherit internal retrieval eligibility without a per-document approval queue. Track source identity, document ID, chunk ID, title, URL, source type, visibility, product/variant IDs where relevant, brand/category, checksum, timestamps, embedding version, and indexing status. Compact product records should stay intact when practical; long text can start around 400–600 tokens with 50–80 overlap, then be tuned through evaluation. Unchanged content should skip re-embedding. Changed or deleted content must replace or remove its old vectors. Track pending, processing, completed, and failed jobs with useful error details. Treat every imported page, PDF, row, and tool result as untrusted data, never as instructions.

Store imported source files on the local filesystem while developing. Move to S3-compatible object storage only when production needs require it. Keep original files or source references available for reprocessing and citation audits.

Retrieval should combine semantic search with exact lookup or metadata filters when queries contain SKUs, brands, categories, product IDs, finishes, or price bounds. Reranking, hybrid search, and compression are options after basic retrieval is measured. Do not treat a raw similarity score as universal proof that an answer is safe.

## Repository layout as the project grows

Create folders when the first feature needs them; this is a destination, not a request to generate empty scaffolding now.

```text
sardars-ai-assistant/
├── README.md
├── PLAN.md
├── .env.example
├── compose.yaml
├── backend/
│   ├── app/
│   │   ├── api/             # versioned HTTP routes
│   │   ├── core/            # settings, security, logging
│   │   ├── db/              # database session, models, repositories
│   │   ├── schemas/         # Pydantic API and tool data shapes
│   │   ├── services/        # business logic
│   │   ├── llm/             # runtime interface and adapters
│   │   ├── ingestion/       # source import and synchronization
│   │   ├── retrieval/       # embeddings, Qdrant, search, reranking
│   │   ├── tools/           # explicit registry and handlers
│   │   ├── guardrails/      # policy checks and validation
│   │   └── main.py
│   ├── alembic/             # created by Alembic when configured
│   └── tests/
└── frontend/                # added in Phase 10
```

## Phase 0 — Product scope and source decisions

Goal: turn the broad vision into one testable first user journey.

- [x] Record the product vision, architectural boundaries, and phased approach.
- [x] Choose the V1 audience: admins and internal staff only; defer public customer access.
- [x] Define admin/staff roles and application-enforced source visibility for the internal prototype.
- [x] Collect representative questions, including cases whose correct answer is “not verified,” in the recorded evaluation suites.
- [x] Authorize the supplied public sitemap/site links and company profile for the internal retrieval prototype; use source-level approval for authorized admin/staff uploads and registered URLs.
- [x] Choose PostgreSQL as the authorized source for internal SKU, price and stock snapshots; external business-system ownership and synchronization remain deferred.
- [x] Scope the prototype to English and inspect the available local hardware; other languages remain deferred.
- [x] Record provisional engineering checks for correctness, groundedness and latency after a baseline; a business response-time target remains deferred.

Exit: the first AI use case and its authoritative sources are written down. Phase 1 originally proceeded while some decisions were pending.

Phase 0 is closed for the agreed English internal prototype. The deferred external-system, language and business-target decisions above are not implied to be settled by this closure.

## Phase 1 — Foundation

Goal: a reproducible local API with PostgreSQL and migrations; no AI orchestration yet.

- [x] Create the repository and basic backend package structure.
- [x] Create a Python 3.12 virtual environment, ignore it in Git, and install FastAPI/Uvicorn.
- [x] Run and verify `GET /api/v1/health` as an application liveness endpoint.
- [x] Add typed settings and `.env.example`; keep secrets out of Git.
- [x] Add PostgreSQL in Docker Compose with a persistent local volume and documented startup/shutdown commands.
- [x] Add SQLAlchemy session/configuration and a database readiness check separate from liveness.
- [x] Initialize Alembic and apply the first small migration; avoid speculative tables.
- [x] Add a meaningful API/database smoke test and document setup in `README.md`.
- [x] Record dependency versions for reproducible installation.

Exit: a fresh developer setup can start PostgreSQL, run migrations, start the API, verify liveness and database readiness, and run the tests.

## Phase 2 — Local LLM

Goal: user question → FastAPI → local model → response, with no claim that company facts are verified.

- [x] Install/run Ollama locally and test a small quantized Qwen3 model on this laptop; evaluate the 8B candidate later on hardware with enough free memory and compute.
- [x] Define a small inference interface and an Ollama adapter, including model/config selection, timeouts, failure handling, and token/latency reporting where available.
- [x] Add a versioned simple chat request/response endpoint and test the path end to end.
- [x] Keep the inference interface independent of Ollama so a production vLLM adapter can be added later; verify vLLM behavior in Phase 13.

Exit: local chat works reliably and can report model errors clearly. Company-specific factual answers remain outside this milestone.

## Phase 3 — Embeddings and Qdrant

Goal: index a small sample from the owner-authorized sources and retrieve relevant chunks without generation.

- [x] Select and record `qwen3-embedding:0.6b` in local Ollama; its `/api/embed` output measured 1,024 dimensions on 2026-10-12.
- [x] Add Qdrant locally, with persistent storage and the empty `sardars_public_qwen3_embedding_06b_v1` collection matching 1,024-dimensional cosine embeddings.
- [x] Implement extraction, cleaning, per-document chunking, embedding, vector upsert, and metadata for two sample website documents. The current word-window chunker is a prototype; improve boundaries when evaluation shows a need.
- [x] Implement query embedding, semantic search, public-source/approval filtering, and inspectable retrieval results for the seed collection. Role-specific staff filtering belongs to the later internal access path.
- [x] Test the seed retrieval against bathroom-storage, brand, and missing return-policy questions; document the model and chunk settings. Answerability remains a Phase 4 concern.

Exit: questions retrieve the expected internally authorized chunks, with source identity preserved. The two-document seed now meets this retrieval-only milestone; grounded answers and internal access controls are Phase 4 work.

## Phase 4 — Grounded RAG

Goal: answer company questions from retrieved evidence and cite it.

- [x] Route clearly general educational questions to the local model and company/ambiguous questions to registered-source retrieval using an inspectable conservative rule.
- [x] Bound retrieved excerpts and total evidence, select matching source sentences, and return a grounded response or exact sourced fallback.
- [x] Return numbered citations with source IDs, titles, safe Sardars URLs, and source fetch time; normalize citation markers to the returned entries.
- [x] Abstain when evidence is missing, changing facts lack an authoritative source, or matched excerpts have obvious numeric/negation conflicts.
- [x] Check roles and registered source identity before prompt assembly; exercise staff/admin boundaries with a synthetic admin-only source and filter obvious retrieved instructions.
- [x] Run a repeatable seed evaluation covering retrieval, missing evidence, unsupported price/policy claims, prompt injection, and conflicting evidence.

Exit met for the two-document approved seed on 2026-10-13: the six evaluation cases passed, and authenticated general/company routes were checked live. Citations refer to the selected evidence. Real private-document ingestion, broader company coverage, and more robust answerability are Phase 5 and later work.

## Phase 5 — Real Sardars data and synchronization

Goal: authorized descriptive website content and supported internal documents are usable and maintainable. On 2026-10-14 the developer deferred company-database price/stock integration to the later tools phase; exact structured catalogue/variant records follow that authoritative-source decision rather than blocking this descriptive ingestion checkpoint.

Learning checkpoints (added 2026-10-14): implement and verify small runnable checkpoints, let the developer run command batches, and inspect the outcome. On request, 3B and 3C were completed together after the developer accepted 3A. Keep the existing company-answer seed runnable throughout.

| Step | Deliverable | Checkpoint acceptance | Status |
| --- | --- | --- | --- |
| 1 | Validated website import preparation | Explicitly select saved crawler records; validate URLs, identity, exact text checksums, timezone-aware fetch dates, and processing limits; preview or save chunks without accessing live services | Verified offline and by developer screenshot: 31 tests, two documents, three saved chunks |
| 2 | Controlled source registration and indexing | Import a selected authorized website source with preserved provenance, registry-enforced permissions, bounded embeddings, and an inspectable processing result | Verified for existing seed by developer screenshot: completed import, zero new registrations, three indexed chunks, cited Bongio answer |
| 3 | Source synchronization | Skip unchanged content; replace changed content and remove obsolete chunks; handle removal/disablement, processing failures, and safe retries without exposing stale evidence | Complete for the local public-site CLI: isolated real-service lifecycle and failure/retry tests passed; existing seed skipped unchanged |
| 4 | Authenticated URL and file ingestion | Authorized admin/staff can submit supported source formats through the API with local file storage, source visibility, bounded extraction, and processing status; add parsers as needed | Complete for supported formats: real URL/PDF/Markdown API and private cited retrieval verified, TXT/failures/limits tested; upload screen belongs to frontend work |
| 5 | Broader data coverage and evaluation | Import additional authorized descriptive sources in bounded batches; check extraction and answers; defer structured product/variant records until ownership, IDs, source priority, and freshness rules are defined | Complete for V1 descriptive scope: eight website documents/twelve chunks; 25-case evaluation passed; company database work deferred by developer to tools |
| 6 | Full saved-crawl descriptive coverage | Account for every saved record; preserve originals and derived-text provenance; import suitable content in resumable serial batches; verify repeat imports, permissions and representative answers against the enlarged corpus | Ingestion/replay completed 2026-10-15: 999 eligible sources/3,739 chunks, nine exclusions; expanded 28/40 and seed 4/7 leave retrieval/answer follow-up open |

Step 1 reuses the 100-word/15-word-overlap chunker to isolate validation from later synchronization changes. It does not authorize or index sources, parse PDFs, or add an upload endpoint. The extractor's legacy `pending` field remains in prepared files; source authorization will be enforced separately when importing, with no per-document approval queue. These checkpoints divide the work; the Phase 5 exit criteria below still apply.

Step 2 introduced a trusted local-operator CLI for the already owner-authorized public Sardars site. It revalidates original extraction records, previews registry changes by default, and applies registration/embedding/upserts only with `--apply`. Its original implementation refused changed records and committed new registrations after writes. Step 3 supersedes that workflow with staged publication and durable jobs, preserving permissions and authorization basis while supporting updates and cleanup. No migration or upload API was added in Step 2. The developer's existing-seed replay is verified; Step 3's real new-source/update/removal lifecycle was demonstrated with isolated synthetic data, not additional company coverage.

Step 3 learning substeps:

| Substep | Deliverable | Acceptance | Status |
| --- | --- | --- | --- |
| 3A | Skip correctly indexed unchanged sources | PostgreSQL source identity/checksum/permissions match, and a bounded Qdrant scan verifies expected chunks, payloads, recorded model, and valid vectors. Healthy sources skip embedding/writes; incomplete/mismatched chunks are repaired; 3B cleans obsolete points. | Verified: live seed skipped two sources/three chunks, with zero embeddings or deletions |
| 3B | Changed/removed source synchronization and cleanup | Replace changed content without stale evidence reaching answers; remove obsolete chunks and handle explicit source removal/disablement with bounded cleanup. Use isolated test data for update/removal demonstrations. | Verified: isolated PostgreSQL/Qdrant/Ollama lifecycle; permission and failure tests passed |
| 3C | Persistent job status and retries | Record pending/processing/completed/failed states, safe errors and processing timestamps; support bounded, recoverable retries and track unfinished cleanup. | Verified: durable completed job live; forced failures, snapshot retries, expiry/fencing, and three-attempt limit tested |

Skipped vectors keep their last indexed fetch timestamp; scanning saved content is not a fresh website fetch or verification of current price/stock. Registry-only preview does not scan Qdrant and reports each `index_action` as `unchecked`. Alembic revision `a52f01d98e73` adds durable jobs and source publication/timestamp fields for 3B/3C. Selected sources are hidden during indexing; publication requires replacement verification and obsolete-ID cleanup. Source IDs stay stable; generation-specific point IDs and worker leases prevent expired attempts from publishing or overwriting later chunks. Explicit removal disables before cleanup and never implicitly reactivates a source. Retries use stored snapshots, at most three attempts; no background worker or automatic website scheduler is added. Failed batches remain unavailable until recovery. Step 3 is complete in its public-site scope; Step 4 extends these rules to authenticated submissions.

Step 4 uses the existing synchronous job runner instead of introducing Celery/Redis before measuring a background-processing need. One authenticated ingestion request runs per API process, with HTTP 429 for concurrent submissions. Staff may create/manage their own staff-visible sources; admins can manage all sources and choose public/staff/admin visibility. Existing visibility/owner/authorization are preserved. Supported uploads are UTF-8 TXT/Markdown and text-based PDFs, with local originals, stable source identities, protected citation downloads, and original/text checksums. URL imports are single-page HTTPS HTML on configured exact hosts, with robots checks, public-IP validation/pinning, and redirect refusal. Resource-limited parser subprocesses bound PDF/DNS/network work; they are not background workers. Migration `b61c9e42d703` adds submitter and original-file metadata. Source-level authorization has no per-document queue and does not establish accuracy/freshness. Originals and snapshots are retained after replacement/removal; retention cleanup, OCR, DOCX/CSV/Excel, automatic synchronization, and the frontend upload screen remain outside this supported-format checkpoint. See README for limits and commands.

- [x] Register authorized website/URL/upload sources with provenance and internal access scopes. Exact company-database/export ownership and source priority remain prerequisites for later structured tools; the supplied sitemap/site links and company profile are source-authorized.
- [x] Add bounded HTML, UTF-8 TXT/Markdown, and text-based PDF parsers for authenticated imports; add other formats only when needed.
- [x] Preserve stable descriptive source IDs/URLs, source type, checksums, fetch/index times, and visibility across PostgreSQL and Qdrant. Keep raw article/product references in source text; authoritative product/variant ID normalization belongs to later database/tool integration.
- [x] Implement checksums, re-indexing, deletions, job status, retries/error reporting, and source update timestamps for local public-site and authenticated Step 4 sources.
- [x] Reuse bounded whitespace chunk cleanup and identical-record deduplication; add offline normalized duplicate/paragraph, changing-claim, short-content, instruction, and suspicious-specification checks plus selected-source spot checks. Preserve exact source checksums; do not rewrite uncertain specifications or require per-page approval.
- [x] Import an explicit checksum-pinned descriptive coverage batch and evaluate retrieval, grounded citations, unsupported/current facts, trust boundaries, representative phrasing, and latency.

Exit met for the V1 descriptive scope on 2026-10-14: updates/removals and recoverable jobs were verified in Steps 3/4; the Step 5 batch expanded company coverage to eight documents/twelve chunks with source IDs, checksums, fetch dates, and role checks. Repeat import skipped all eight sources/twelve chunks; the broader evaluation passed 25/25 and the original seed baseline 7/7. This is a bounded prototype corpus, not full-site indexing or general answer-quality proof. See `docs/phase5_step5_report.md`. The developer's separate staff-visible interview PDF adds 26 test chunks and is not authoritative company information. Phase 5 is complete within this scope; current price/stock and exact structured records remain deferred to Phases 6/7.

Historical scope clarification, 2026-10-15: Phase 5 full-site ingestion was required before Phase 6. Step 6 extends the verified pipeline rather than reopening its earlier lifecycle milestones. Full coverage requires every one of the 1,008 saved records to have an inspectable disposition, all suitable prepared sources to be active/ready with matching verified generations, a repeat import that skips unchanged content, and larger-corpus retrieval/answer results with failures investigated and limits recorded. Prepared files or a successful small batch do not meet that exit. Whole-source and passage exclusions must have reasons; heuristic flags are not a document approval queue or proof of incorrect facts. Preserve verbatim descriptive excerpts, original checksums/fetch dates, and omission offsets; never repair uncertain specifications by inference. Keep batches serial, embedding requests small, job deadlines bounded, and explicit retries on the existing durable jobs. The 999 suitable sources were later ingested and replayed; larger-corpus answer-quality failures remain open.

## Phase 6 — Safe read-only product tools

Goal: an authenticated staff product-price or SKU question reaches a registered, role-filtered PostgreSQL read tool and returns the current values in `public.products`, with source and database observation time. The developer designated the table's manually assigned prices and SKUs as valid internal-assistant data on 2026-10-16. Their original creation remains recorded in provenance fields. The application does not claim verified Shopify/ERP synchronization, currency, or stock.

### Completed checkpoints

| Step | Behavior | Evidence |
| --- | --- | --- |
| 1 | Import and classify the Shopify CSV rows | 4,983 rows / 2,009 handles; 3,090 original variant rows and 1,893 image-only rows. Original file hash and classification replay verified. |
| 2 | Accept current table values as the chosen internal product source | All rows have SKU and price; no case-insensitive duplicate SKU or oversized identifier/display field. Source authority is `developer_authorized_products_table`; `external_sync_verified` remains false. |
| 3 | Build a narrow PostgreSQL read tool | `get_product_details` accepts an exact identifier or bounded product question. Exact SKU returns its row, including an image-row label when relevant. Handle/name returns variants; multiple name matches return bounded choices. SQL is parameterized and visibility-filtered. |
| 4 | Enforce tool boundaries | Strict Pydantic arguments/results, authentication, role checks, field allowlist, 8 KiB result limit, PostgreSQL statement/lock limits, safe errors and redacted tool logs. Cost, HTML, inventory and arbitrary SQL are never exposed. |
| 5 | Route price/SKU chat reliably | The application recognizes product-price/SKU intent and invokes the registered tool directly. The earlier Ollama tool-call adapter remains available, but a small model's probabilistic tool choice is not required for exact database facts. General questions and descriptive company RAG keep their existing routes. |
| 6 | Render grounded answers and clarify ambiguity | The answer uses only returned database fields, marks query-time PostgreSQL values as current for this internal source, keeps unknown currency explicit, and distinguishes image-only rows. Missing/ambiguous/unauthorized/unavailable values fail safely. |
| 7 | Verify the end-to-end staff flow | Focused tests, authenticated real PostgreSQL/API checks, unauthenticated 401, model-independent behavior, catalog-wide result audit, full backend regressions and Alembic consistency are recorded in `docs/phase6_product_tool.md`. |

### Boundaries and phase exit

The retained CSV hash identifies the original import; it does not hash later manual price/SKU edits. `observed_at` is the time the application read PostgreSQL, not a Shopify export or ERP synchronization time. A later ERP connection must establish source IDs, update/deletion behavior, synchronization and freshness rules before making claims about an external system. Internet search is a separate tool. Phase 7 combines structured lookup with descriptive RAG; Phase 5 full-corpus answer-quality regressions remain open.

Phase 6 exits when staff can reliably ask for a SKU or product price from the authorized table through `/api/v1/chat` without depending on the model to decide to call the tool, and the response matches visible database rows or safely requests clarification. The source-status tool and Ollama tool-call adapter remain supported preliminary work.

## Phase 7 — RAG and tools together

Goal: answer queries needing both structured filtering and descriptive evidence.

- [x] Route category/brand/finish/price/SKU filters through the registered PostgreSQL `search_products` read tool before fetching descriptions by exact Shopify handle/product-page URL. Match only visible active rows and recheck registered Qdrant sources.
- [x] Return the lowest qualifying variant's exact database SKU, price, recorded currency and catalog-listed options; show short citations from matching product pages for supported recommendations and comparisons. Unknown or hidden descriptions do not become recommendations.
- [x] Give PostgreSQL precedence for structured facts; ignore changing price/stock claims in webpage excerpts. Show database observation time, source fetch time and explicit uncertainty for currency, inventory and external synchronization.
- [x] Exercise numeric bounds, SKU/variant comparisons, role boundaries, missing or conflicting descriptions, and a follow-up using returned `product_handles`. Each follow-up reauthorizes and rereads its products; long-term conversation memory remains Phase 9.

Exit: a request such as “recommend black wall-mounted basin mixers under 1000” applies the numeric price limit to the matching variant and only recommends verified matches with supported descriptions. The response must state when currency is unrecorded; a request naming PKR or another currency must not treat an unlabelled price as that currency.

Phase 7 complete for this internal proof of concept (2026-10-17). The developer chose a numeric, currency-unspecified exit while the current manually assigned prices have no verified currency. Combined lookup, description join and follow-up flow passed isolated and authenticated local checks; the full backend suite passed 404 tests with three skipped, and Alembic reported no schema drift. Explicit-currency filtering remains conditional on a recorded currency for the matching row, outside this phase's exit. See `docs/phase7_combined_product_search.md` and `IMPLEMENTATION_STATUS.md` for evidence and limits.

## Phase 8 — Guardrail hardening

Goal: expand and test protections already present in earlier phases.

- [x] Refine scope handling for Sardars, related product knowledge, unrelated requests, and unsafe requests without rejecting useful domain questions.
- [x] Test prompt injection in pages, PDFs, tool output, and user input; authorization and permissions must still be code-enforced.
- [x] Validate high-impact output claims (identity, price, stock, dimensions, warranty, delivery, links) against retrieved/tool evidence where deterministic checks are possible.
- [x] Check private-data disclosure, role boundaries, rate limits, request sizes, timeouts, and error-message hygiene.
- [x] Avoid unnecessary second-model validation calls; add one only if measured benefit justifies it.

Exit: adversarial and unsupported-fact cases fail safely without blocking ordinary product questions.

Phase 8 completed for the internal single-process prototype on 2026-10-17. Its verified checkpoints were:

| Checkpoint | Application behavior | Verification |
| --- | --- | --- |
| 1. Question boundary | Bearer authentication before bounded JSON reads; strict fields, 32 KiB body, 30-second read deadline and safe validation errors | 64 request-boundary tests plus earlier full-suite checkpoint |
| 2. Scope | Clear company, general product education, off-topic, unavailable-action and unsafe requests are handled before retrieval/model/tool dispatch; generic warranty definitions remain educational | 26 initial focused routing/chat/auth checks; final focused routing/answer run 57 passed |
| 3. Injection | Page/PDF excerpts, catalog fields, forged tool results and user override attempts cannot change code-enforced permissions or become answer instructions | 56 focused source/tool/answer checks; role-filtered private-PDF and useful-source tests added later |
| 4. Claims | PostgreSQL remains current price/SKU authority; unsupported current identity, warranty, policy, delivery and stock claims abstain; dimensions require matching cited text; prose URLs cannot become answer links | 73 focused answer/product/chat checks; later product-description and role tests passed |
| 5. Rate and deadline | Per-user question/tool windows, login IP/account windows, 429/Retry-After, 90-second answer budget, lower-level I/O/SQL limits and bounded Ollama output | 100 focused deadline/request/auth/rate checks; all final backend regressions passed |

The final backend suite passed **510 tests**, with three opt-in live tests skipped and one existing dependency warning. A read-only check of the current 2,009-handle/3,090-variant catalog found no title, vendor, option or specification fields blocked by the refined display guard; tests preserve ordinary product titles containing “Price” and general warranty education. No second-model validation call was added. This phase exit is for tested internal behavior, not production traffic or comprehensive adversarial coverage. The process-local limiter does not coordinate multiple API processes, and cancellation cannot forcibly stop synchronous threads; their I/O and database operations have separate limits. Phase 5 full-corpus retrieval/answer failures remain open. See `IMPLEMENTATION_STATUS.md` and README for observed behavior and limits.

## Phase 9 — Conversation memory

Goal: persist conversations and support follow-up questions with bounded context.

- [x] Reuse existing users/roles; add conversations, messages, ownership checks, and a migration.
- [x] Save completed turns, model metadata, timing/token counts when available, and only necessary source IDs/product handles.
- [x] Send bounded recent context for recognizable follow-ups; preserve product handles and reread current values through authorized tools.
- [x] Defer conversation summaries until measured usage requires them; never treat conversation history as company evidence.
- [x] Define a configurable 30-day rolling expiry, immediate owner deletion, and a bounded physical-purge command for staff conversation data.

Exit: users can continue and review their own conversations, and follow-ups resolve correctly without unbounded prompts.

Phase 9 completed for the internal prototype on 2026-10-17. An authenticated `/chat` turn creates or continues an owned PostgreSQL conversation; list, paged review and delete endpoints enforce ownership and current role. Recognizable general follow-ups use at most eight recent messages and 1,600 history characters; company follow-ups can expand the search query without treating prior chat as evidence, and product follow-ups reuse handles only for fresh authorized PostgreSQL searches. Independent topics drop old prompt context. Source and product visibility are rechecked when reviewing historical answers, and failed or timed-out turns are not saved. The additive migration applied to local PostgreSQL and `alembic check` found no drift; an authenticated PostgreSQL API smoke check passed. The final backend suite passed **537 tests**, with three opt-in live tests skipped and one existing dependency warning. No summary was added because there is no measured need; the keyword-based follow-up boundary and 30-day physical purge scheduling remain prototype limitations. See `IMPLEMENTATION_STATUS.md` and README.

## Phase 10 — Frontend and streaming

Goal: a usable, responsive chat experience for Sardars admins and internal staff.

- [x] Choose React or Next.js based on actual hosting and product needs.
- [x] Build new chat, history/sidebar, Markdown display, source links, loading/error/retry states, and mobile layouts.
- [x] Add streaming, initially via SSE if it fits the API; keep streaming separate from retrieval and generation logic.
- [x] Make source references clear and show them only to roles authorized for those sources.
- [x] Ensure high-impact company claims are verified before they are shown, including during streaming.
- [x] Apply suitable accessibility and visual polish without delaying backend correctness.

Exit: an authorized staff user can ask, read cited answers, recover from errors, and return to earlier conversations on desktop and mobile.

Phase 10 completed for the internal prototype on 2026-10-18. React/Vite/TypeScript and Zustand support owned conversation history, safe Markdown, authorized citations and source-file downloads, retryable errors, and responsive desktop/mobile layouts. `POST /api/v1/chat/stream` sends SSE answer chunks only after the existing answer checks and PostgreSQL save complete; this is buffered delivery streaming, not raw model-token streaming. Backend tests covered the stream, ownership, source revocation and role changes; frontend tests, production build and mocked-API Chrome desktop/mobile flows covered login, retry, answer delivery, citations, refresh, history, keyboard focus and layout. Production hosting/auth hardening remains Phase 13; full-corpus retrieval regressions remain open from Phase 5. See `IMPLEMENTATION_STATUS.md` for verification details.

## Phase 11 — Full evaluation

Goal: measure the complete assistant rather than judging it by casual chats.

- [x] Expand realistic cases for company info, brands, discovery, exact product facts, prices, availability, technical questions, comparisons, RAG, tools, combined flows, irrelevant questions, injection, and unavailable information.
- [x] Measure retrieval relevance/coverage, answer correctness, support for claims, hallucinations, tool selection, permission handling, refusal quality, latency, and token/context use separately.
- [x] Inspect failures at the correct layer: source data, extraction, chunking, retrieval, routing, tools, prompt, model, or UI.
- [x] Record baselines and acceptance thresholds before tuning.

Exit: an evaluation run is repeatable and shows whether a change improved or harmed the assistant.

Phase 11 evaluation work completed for the English internal prototype on 2026-10-18. The pre-stock baseline, stock-aware 26-case suite, comparator, full-site/seed rechecks, isolated authenticated stock API tests, and provisional engineering gates are recorded in `docs/phase11_evaluation_completion.md`. The initial stock-aware pair passed 23/26 with stable failures. A later targeted quality checkpoint passed the stricter 26-case gate twice with matching case/evaluator/database fingerprints. This is a measured pass for that bounded suite, not universal answer quality: the wider full-site regression suite still has open failures, semantic checks are limited proxies, the browser smoke is mocked, and production/business thresholds and multilingual evaluation remain open. The deferred Phase 5 full-corpus retrieval regression work is not cleared or folded into this phase. Phase 12 can begin with the recorded baseline and remaining failures.

## Phase 12 — Optimization after measurement

Goal: improve quality, latency, concurrency, and resource use where data shows a problem.

- [x] Evaluate retrieval options: adopt bounded 32-to-eight, authorization-first lexical reranking for specific subjects; retain the existing profile hint and broad-discovery semantic order. Defer a new hybrid index, extra deduplication and contextual compression until the remaining failures justify their complexity.
- [x] Review context and response budgets: the existing eight-message/1,600-character history, three-excerpt/1,800-character RAG evidence and 256-token output caps remain appropriate for the measured internal cases; no summarizer is needed yet.
- [x] Assess caching, batching and model routing: use a measured, bounded five-minute chat-model residency; retain current two-chunk embedding batches and deterministic routing. Defer answer/embedding caches, Redis and further routing without repeated-query benefit and safe invalidation rules.
- [x] Record applicable local inference resources: CPU-only model residency, zero VRAM, a small two-request queueing probe and token/runtime cost proxies. Separate KV-cache use and monetary cost require future deployment telemetry and hosting assumptions.

Exit: each optimization has a measured benefit and does not reduce answer correctness or freshness.

Phase 12 completed for the English internal prototype on 2026-10-18. Against the retained Phase 11 full-site baseline, the same 40-case suite improved from **31/40** to **34/40** and expected-source hits from **18/24** to **21/24**, with no previously passing case regressing. The 26-case chat gate and seven-case seed suite remained fully passing. The local model reload probe measured roughly three seconds of avoidable loading for warm repeated calls at a cost of about 1.02 GB resident RAM; final serial full-site median/p95 were **2,965.8/12,641.5 ms**. The six remaining full-corpus failures and production-scale concurrency/cost questions remain open; Phase 12 does not clear the deferred Phase 5 backlog. See `docs/phase12_optimization_report.md` for evidence, limits and reproducible checks.

## Phase 13 — Transferred, not completed

Production deployment is not currently planned. Its local containerization portion was verified in E1; production-readiness requirements were recorded as E9 and remain unimplemented. The original roadmap is complete **for its English internal-prototype scope through Phase 12 only**; closing this plan does not certify production readiness.

## API, security, and observability conventions

Candidate versioned endpoints include `GET /api/v1/health`, a separate readiness endpoint, `POST /api/v1/chat`, conversation list/detail routes, and protected ingestion/job routes. Final route names can evolve with implementation. Use Pydantic request/response schemas. Keep staff and admin operations separate. A later streaming endpoint may use SSE.

Read-only tools can execute automatically after permission checks. Actions such as quote submission, lead creation, booking, email, orders, cancellations, or product changes require stronger authorization and explicit confirmation of the exact pending action. The model may request an action; it never grants itself permission. Do not expose raw database credentials, unrestricted SQL, shell execution, internal services, or secrets to the model. Keep retrieved content and tool results in a lower-trust boundary than application instructions.

Capture structured logs/metrics for request and conversation IDs, model/embedding versions, retrieval candidates and selected sources, retrieval/tool/model/total latency, tool failures, token/context size, guardrail decisions, and fallback behavior. Do not log passwords, keys, unnecessary customer details, or entire private documents. Define retention and access for logs before production.

## Later options, outside the initial working product

- Fine-tune for tone, formatting, recommendation style, classification, or tool selection only after a quality dataset exists. LoRA/QLoRA are possible techniques. Keep changing facts in external sources.
- Add write/action tools only with confirmed workflows and audit trails.
- Add multi-company configuration after Sardars has proven the shared boundaries; do not hardcode core infrastructure to one brand, but do not build tenancy before it is needed.
- Add Redis, rerankers, advanced orchestration, S3, or broader deployment infrastructure only when evidence justifies them.

## Closure and deferred work

The extended cycle subsequently verified E1–E7, including the developer-requested model-first E6 follow-up, in their stated internal-prototype scopes. On 2026-10-29 the project owner closed the current implementation cycle. E8 live internal acceptance, independent human sign-off, self-registration/approval, and E9 production readiness were not completed; they are deferred until a new plan is opened. Closing the roadmap changes no data or verification result.

