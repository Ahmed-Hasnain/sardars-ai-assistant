# Sardars AI Assistant — product and development plan

Last reviewed: 2026-10-14
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

`IMPLEMENTATION_STATUS.md` is the record of current behavior, phase status, completed major features, and verification evidence. This file defines the roadmap and acceptance criteria. Its checkboxes describe individual planned tasks; update them when a major feature or phase is formally verified, not after every small change. If status text here and the implementation status file disagree, inspect the code and use `IMPLEMENTATION_STATUS.md` as the current-status record.

## Decisions to settle before they affect implementation

These questions do not block the remaining Phase 1 work. Record the chosen answer and date here when resolved.

| Decision | Why it matters | Current state |
| --- | --- | --- |
| First audience: public customers, staff, or both | Determines authentication, permitted sources, and feature scope | Admins and internal staff only for the first release (changed 2026-10-13); public customer access deferred. Local admin/staff login is implemented. Both roles may access the approved public-site seed; admins can list account metadata. Source registrations support public, staff, and admin visibility; real private-source ingestion remains for Phase 5. |
| First 10–20 user questions and success criteria | Defines the first useful AI slice and evaluation set | Open |
| Authoritative product catalogue, price, and stock source | Determines SQL sync and what can be called current | Open; the [public website](https://sardarandco.com/) identifies Shopify as its store platform, but access and data ownership must be confirmed |
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
- [ ] Define admin/staff roles and which internal sources each role may access.
- [ ] Collect representative user questions, including questions whose correct answer is “not verified.”
- [x] Authorize the supplied public sitemap/site links and company profile for the internal retrieval prototype; use source-level approval for authorized admin/staff uploads and registered URLs.
- [ ] Identify owners and authoritative sources for product, price, and stock data.
- [ ] Decide required languages and inspect local hardware.
- [ ] Define initial acceptance measures for correctness, groundedness, and acceptable response time after a baseline is measured.

Exit: the first AI use case and its authoritative sources are written down. Phase 1 can continue while these decisions are pending.

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

Goal: authorized website, catalogue, and structured product sources are usable and maintainable.

Learning checkpoints (added 2026-10-14): implement and verify one checkpoint, let the developer run its command batch, and inspect the outcome before the next checkpoint. Keep the existing company-answer seed runnable throughout.

| Step | Deliverable | Checkpoint acceptance | Status |
| --- | --- | --- | --- |
| 1 | Validated website import preparation | Explicitly select saved crawler records; validate URLs, identity, exact text checksums, timezone-aware fetch dates, and processing limits; preview or save chunks without accessing live services | Verified offline and by developer screenshot: 31 tests, two documents, three saved chunks |
| 2 | Controlled source registration and indexing | Import a selected authorized website source with preserved provenance, registry-enforced permissions, bounded embeddings, and an inspectable processing result | Verified for existing seed by developer screenshot: completed import, zero new registrations, three indexed chunks, cited Bongio answer |
| 3 | Source synchronization | Skip unchanged content; replace changed content and remove obsolete chunks; handle removal/disablement, processing failures, and safe retries without exposing stale evidence | In progress: 3A implemented/tested offline; live skip replay pending; 3B/3C remain |
| 4 | Authenticated URL and file ingestion | Authorized admin/staff can submit supported source formats through the API with local file storage, source visibility, bounded extraction, and processing status; add parsers as needed | Planned; upload screen belongs to frontend work |
| 5 | Broader data coverage and evaluation | Import additional authorized descriptive sources in bounded batches; check extraction and answers; integrate structured product/variant records only once ownership, IDs, source priority, and freshness rules are defined | Planned; authoritative catalogue/price/stock decisions remain open |

Step 1 reuses the 100-word/15-word-overlap chunker to isolate validation from later synchronization changes. It does not authorize or index sources, parse PDFs, or add an upload endpoint. The extractor's legacy `pending` field remains in prepared files; source authorization will be enforced separately when importing, with no per-document approval queue. These checkpoints divide the work; the Phase 5 exit criteria below still apply.

Step 2 is a trusted local-operator CLI for the already owner-authorized public Sardars site. It revalidates original extraction records, previews registry changes by default, and applies registration/embedding/upserts only with `--apply`. It preserves existing source permissions and authorization basis, refuses disabled/restricted/conflicting/changed records, and commits new registrations only after confirmed Qdrant writes. The original Step 2 implementation re-embedded on repeat imports; the Step 3A extension below now skips verified indexed sources. No migration or upload API was added in Step 2. The developer's existing-seed live replay is verified; new-source creation has offline test coverage but has not been demonstrated live with an additional website document.

Step 3 learning substeps:

| Substep | Deliverable | Acceptance | Status |
| --- | --- | --- | --- |
| 3A | Skip correctly indexed unchanged sources | PostgreSQL source identity/checksum/permissions match, and a bounded Qdrant source scan finds exactly the expected chunk IDs, payloads, recorded model, and valid vectors. Healthy sources skip embedding/writes; incomplete/mismatched expected chunks are repaired. Unexpected extra points are refused until cleanup exists. | Implemented and tested offline; developer replay next |
| 3B | Changed/removed source synchronization and cleanup | Replace changed content without stale evidence reaching answers; remove obsolete chunks and handle explicit source removal/disablement with bounded cleanup. Use isolated test data for update/removal demonstrations. | Next after 3A replay |
| 3C | Persistent job status and retries | Record pending/processing/completed/failed states, safe errors and processing timestamps; support bounded, recoverable retries and track unfinished cleanup. | Planned |

3A keeps the last indexed fetch timestamp when content is skipped; scanning saved content is not a fresh website fetch or verification of current price/stock. Registry-only preview does not scan Qdrant and reports each `index_action` as `unchecked`. No schema change is needed for 3A. Full Step 3 remains incomplete until updates, removals, cleanup, and persistent retry tracking are verified.

- [ ] Register authorized source domains, uploads, and access scopes; confirm source priority and authoritative ownership for Shopify/company exports, internal documents, PDF catalogues, CSV/Excel lists, and later ERP/CRM sources. The supplied sitemap/site links and company profile are already approved for the internal prototype.
- [ ] Add parsers only for approved formats actually needed (for example HTTPX/BeautifulSoup for HTML and PyMuPDF for PDFs).
- [ ] Normalize product and variant identities, descriptions, specifications, brand/category, and source URLs.
- [ ] Put exact structured data in PostgreSQL only with a defined owner and sync/freshness policy; keep descriptive documents in the retrieval index.
- [ ] Implement checksums, re-indexing, deletions, job status, retries/error reporting, and source update timestamps.
- [ ] Apply automated cleaning/deduplication and spot checks for boilerplate or inaccurate extraction; flag changing claims for authoritative lookup or a clear as-of caveat. Do not require individual approval of every imported page or file for internal retrieval.

Exit: a changed or removed source is reflected correctly in both records and retrieval results, and each answerable fact has traceable provenance.

## Phase 6 — Safe read-only tools

Goal: the model can request narrow application functions for exact facts.

- [ ] Add an explicit tool registry with strict Pydantic argument and result schemas; never execute arbitrary SQL, Python, shell commands, or function names from model text.
- [ ] Route tools through service and repository methods, with authorization outside the model and safe error responses.
- [ ] Start with only needed read tools, such as product search, product details, price, stock/availability, showroom details, and catalogue search.
- [ ] Implement bounded tool-call iterations (initial maximum five), timeouts, structured results, and tool-call logs that exclude secrets.
- [ ] Test malformed arguments, unknown tools, permission denial, stale values, and model failures.

Exit: exact fact questions use the authoritative read tool and fail safely if the tool cannot verify the answer.

## Phase 7 — RAG and tools together

Goal: answer queries needing both structured filtering and descriptive evidence.

- [ ] Route category/brand/finish/price/SKU filters to structured search before retrieving descriptions for matching product IDs.
- [ ] Support grounded product comparison and recommendation with exact prices/specifications and cited descriptive evidence.
- [ ] Define precedence when tool data and documents disagree; show uncertainty or as-of information where appropriate.
- [ ] Evaluate combined queries, including follow-up questions referring to previously shown products.

Exit: a request such as “black wall-mounted basin mixers under PKR 100,000” uses exact filters and only recommends verified matches with supported descriptions.

## Phase 8 — Guardrail hardening

Goal: expand and test protections already present in earlier phases.

- [ ] Refine scope handling for Sardars, related product knowledge, unrelated requests, and unsafe requests without rejecting useful domain questions.
- [ ] Test prompt injection in pages, PDFs, tool output, and user input; authorization and permissions must still be code-enforced.
- [ ] Validate high-impact output claims (identity, price, stock, dimensions, warranty, delivery, links) against retrieved/tool evidence where deterministic checks are possible.
- [ ] Check private-data disclosure, role boundaries, rate limits, request sizes, timeouts, and error-message hygiene.
- [ ] Avoid unnecessary second-model validation calls; add one only if measured benefit justifies it.

Exit: adversarial and unsupported-fact cases fail safely without blocking ordinary product questions.

## Phase 9 — Conversation memory

Goal: persist conversations and support follow-up questions with bounded context.

- [ ] Add users/roles as needed, conversations, messages, ownership checks, and migrations.
- [ ] Save messages, model metadata, timing/token counts when available, and only necessary tool/source references.
- [ ] Send a bounded recent history; preserve product references needed for follow-ups.
- [ ] Add conversation summaries only if actual usage requires them; never confuse a summary with company evidence.
- [ ] Define retention and deletion behavior for staff conversation data.

Exit: users can continue and review their own conversations, and follow-ups resolve correctly without unbounded prompts.

## Phase 10 — Frontend and streaming

Goal: a usable, responsive chat experience for Sardars admins and internal staff.

- [ ] Choose React or Next.js based on actual hosting and product needs.
- [ ] Build new chat, history/sidebar, Markdown display, source links, loading/error/retry states, and mobile layouts.
- [ ] Add streaming, initially via SSE if it fits the API; keep streaming separate from retrieval and generation logic.
- [ ] Make source references clear and show them only to roles authorized for those sources.
- [ ] Ensure high-impact company claims are verified before they are shown, including during streaming.
- [ ] Apply suitable accessibility and visual polish without delaying backend correctness.

Exit: an authorized staff user can ask, read cited answers, recover from errors, and return to earlier conversations on desktop and mobile.

## Phase 11 — Full evaluation

Goal: measure the complete assistant rather than judging it by casual chats.

- [ ] Expand realistic cases for company info, brands, discovery, exact product facts, prices, availability, technical questions, comparisons, RAG, tools, combined flows, irrelevant questions, injection, and unavailable information.
- [ ] Measure retrieval relevance/coverage, answer correctness, support for claims, hallucinations, tool selection, permission handling, refusal quality, latency, and token/context use separately.
- [ ] Inspect failures at the correct layer: source data, extraction, chunking, retrieval, routing, tools, prompt, model, or UI.
- [ ] Record baselines and acceptance thresholds before tuning.

Exit: an evaluation run is repeatable and shows whether a change improved or harmed the assistant.

## Phase 12 — Optimization after measurement

Goal: improve quality, latency, concurrency, and resource use where data shows a problem.

- [ ] Consider reranking, hybrid keyword/vector retrieval for exact terms, dynamic top-K, deduplication, and contextual compression.
- [ ] Trim or summarize conversation context only when needed; set explicit per-request context and response budgets.
- [ ] Consider embedding/result caching, prompt caching, Redis, batching, and model routing only with measured value and clear invalidation rules.
- [ ] Track GPU compute, VRAM/KV-cache use, queueing, and cost of self-hosted inference.

Exit: each optimization has a measured benefit and does not reduce answer correctness or freshness.

## Phase 13 — Production deployment

Goal: a secure, observable deployment that can be operated and recovered.

- [ ] Verify Ollama-to-vLLM adapter behavior with the selected model, tool format, streaming, and load profile.
- [ ] Containerize services appropriately; keep PostgreSQL, Qdrant, and inference private behind the application network.
- [ ] Add reverse proxy, HTTPS, internal-user authentication/authorization, rate limiting, secret handling, and environment-specific configuration; do not expose the first release to public customers.
- [ ] Plan GPU capacity, concurrency, request queues, timeouts, backups, database/vector persistence, restore tests, logging, monitoring, and alerts.
- [ ] Use S3-compatible document storage only if deployment/storage needs justify it.
- [ ] Run deployment smoke tests and failure/recovery drills; document operations and rollback.

Exit: the service is accessible to its intended users, private services are protected, data can be restored, and failures can be diagnosed.

## API, security, and observability conventions

Candidate versioned endpoints include `GET /api/v1/health`, a separate readiness endpoint, `POST /api/v1/chat`, conversation list/detail routes, and protected ingestion/job routes. Final route names can evolve with implementation. Use Pydantic request/response schemas. Keep staff and admin operations separate. A later streaming endpoint may use SSE.

Read-only tools can execute automatically after permission checks. Actions such as quote submission, lead creation, booking, email, orders, cancellations, or product changes require stronger authorization and explicit confirmation of the exact pending action. The model may request an action; it never grants itself permission. Do not expose raw database credentials, unrestricted SQL, shell execution, internal services, or secrets to the model. Keep retrieved content and tool results in a lower-trust boundary than application instructions.

Capture structured logs/metrics for request and conversation IDs, model/embedding versions, retrieval candidates and selected sources, retrieval/tool/model/total latency, tool failures, token/context size, guardrail decisions, and fallback behavior. Do not log passwords, keys, unnecessary customer details, or entire private documents. Define retention and access for logs before production.

## Later options, outside the initial working product

- Fine-tune for tone, formatting, recommendation style, classification, or tool selection only after a quality dataset exists. LoRA/QLoRA are possible techniques. Keep changing facts in external sources.
- Add write/action tools only with confirmed workflows and audit trails.
- Add multi-company configuration after Sardars has proven the shared boundaries; do not hardcode core infrastructure to one brand, but do not build tenancy before it is needed.
- Add Redis, rerankers, advanced orchestration, S3, or broader deployment infrastructure only when evidence justifies them.

