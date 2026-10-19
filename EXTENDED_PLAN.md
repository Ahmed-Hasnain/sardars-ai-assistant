# Sardars AI Assistant — extended plan

Last reviewed: 2026-10-19
Status: active roadmap; E1 isolated stack is runnable, with final data-backed acceptance deferred until after E4; E2 is next
Implementation evidence: `IMPLEMENTATION_STATUS.md`
Original prototype roadmap and decisions: `PLAN.md`

## Purpose and order

The English internal prototype completed Phases 1–12 of `PLAN.md`. The original Phase 13 deployment work and its deferred follow-up backlog move here because deployment is not currently planned. The isolated E1 stack now starts and answers safely with an empty corpus; the developer does not want to insert Sardars data merely to close E1. Proceed with E2's unchanged model comparison using the retained original evaluation corpus, then decide the ingestion runner in E3 and build the account-registration-to-RAG journey in E4. After Sardars data is entered through that journey, return to the remaining E1 end-to-end, restart and backup/restore checks **before** advancing to E5. Reassess retrieval and tool choice with that richer corpus before adding optional capabilities. Production deployment is a separate, later decision. This resequencing does **not** mark E1 or E3/E4 complete or clear the six remaining full-site evaluation failures. If the retained original corpus is unavailable for E2, restore or otherwise verify its baseline rather than comparing models on the empty E1 index.

Work in small, runnable checkpoints. Before each substantial change, explain the concept, alternatives and trade-offs. Keep a measured baseline and run the relevant regression suites after changes. Update `IMPLEMENTATION_STATUS.md` only after a verified major checkpoint, and update this plan when an exit criterion or order changes. The sequence below may change when measurements or developer decisions justify it.

The current reference is the Phase 12 English internal-prototype result: **26/26 chat**, **7/7 seed**, **34/40 full-site**, and **21/24 expected-source hits**. The full-site failures are `mirror`, `seat_materials`, `mirror_paraphrase`, `fittings_materials_article`, `sustainable_toilets_article`, and `maintenance_article`. See `docs/phase12_optimization_report.md`. These automated suites are useful regression checks, not independent human approval of answer quality.

Across every checkpoint: keep self-hosted inference; preserve authentication, application-enforced role/source visibility and bounded allowlisted tools; treat retrieved and tool text as untrusted; use PostgreSQL at request time for authorized SKU, price and stock values. Do not treat Qdrant or an internet result as authority for changing Sardars facts. Do not reset the corpus, product table, accounts or conversations as a routine setup step.

## E1 — Complete local containerization

Goal: run the existing application reproducibly on one development machine without publishing it. The runnable empty-data stack is an intermediate checkpoint; final E1 acceptance follows E4's real data entry.

- [ ] Add pinned, buildable API and frontend images and a local Compose workflow for API, frontend, PostgreSQL, Qdrant and containerized Ollama by default. Preserve data/model volumes; offer an optional NVIDIA GPU override for compatible hosts.
- [ ] Configure service-name networking, health/readiness checks, startup and migration commands, secrets from local environment rather than images, and localhost-only user-facing ports. Keep database, vector and inference services private to the Compose network by default.
- [ ] Document initial model pulls, first admin creation, startup, shutdown, updates and safe backup/restore of local volumes. Existing developer data must survive normal restarts and image rebuilds.
- [ ] Verify a clean-volume start and a restart with retained data; run authenticated chat, product lookup, authorized retrieval, frontend login and the relevant backend/frontend checks. Compare basic latency with the current host setup before deciding whether to retire `scripts/dev.sh`.

Exit, checked **after E4**: a developer can start the complete internal application locally, use its core flows with data entered through the new journey, and restart or restore it without losing data. Verify authenticated chat, authorized cited retrieval, frontend login, persistence, backup/restore and basic latency against the existing workflow. Verify product lookup separately against a controlled authorized PostgreSQL row or a safely restored catalog; RAG documents do not populate the product table. E1 stays open until that evidence is recorded. This is **local infrastructure**, not the production-deployment exit.

## E2 — Measure and improve model answer quality

Goal: test whether a larger local chat model produces better grounded answers on this hardware.

- [ ] Freeze the current prompts, retrieval corpus, tool rules and case definitions; record the active model, quantization, memory use and repeatable `qwen3:0.6b` baseline.
- [ ] Compare an available 4B-class Qwen instruct model first, then an 8B-class or other open-weight option only if hardware and latency permit. Keep the embedding model/collection unchanged during the chat-model comparison.
- [ ] Run the same 26-case chat, seven-case seed and 40-case full-site suites, plus a small blinded human review of real staff questions. Compare factual support, citations, abstentions, unsafe claims, phrasing, follow-ups, tool-choice outcomes, median/p95 latency, timeouts and memory/swap pressure. Recheck model response and tool-call formats through the Ollama adapter.
- [ ] Adopt a new default only when its measured quality gain is worth the resource cost and security/authorization checks remain passing; otherwise retain the current model and record why.

Exit: a documented model choice based on comparable results. A larger model alone does not fix missing retrieval evidence or the application's rule-based tool routing.

## E3 — Decide how ingestion work runs

Goal: make larger uploads and sitemap imports reliable before building the registration/ingestion UI. The current API records durable jobs but still waits for extraction and indexing in the request; measure whether a separate worker is needed.

- [ ] Measure current durable-job runtime, request blocking, queueing, retry/recovery and CPU/memory use on controlled files and sitemap samples representative of the Sardars data to be ingested.
- [ ] Compare the existing synchronous runner, a small dedicated worker and Celery with a broker. Choose the least complex option that meets the measured workload.
- [ ] If Celery is selected, add a broker and worker to the local Compose stack in a small runnable checkpoint. Pass job IDs rather than document text through the broker; let the API return an accepted job ID and let the UI poll the existing authorized job endpoint. Verify restart/retry behavior before relying on the worker for bulk imports.
- [ ] Preserve owner/role checks, leases, idempotency, bounded retries, progress, update/deletion and safe publication between PostgreSQL and Qdrant. A failed job must not expose partial or unauthorized content.

Exit: a documented runner choice and tested recovery for the selected workload. Celery/Redis are strong candidates for lengthy imports, but remain conditional until the E3 comparison demonstrates the need and verifies their failure behavior.

## E4 — Fresh-account-to-ingestion journey

Goal: complete the path from a newly approved internal account through Sardars company-data submission, RAG ingestion and authorized answers.

- [ ] Add an internal registration request that creates an inactive/pending account; an existing admin must approve and assign staff access before login or ingestion. The first admin remains operator-created. Rate-limit registration and prevent role self-assignment. Define whether submitted sources are staff-shared or admin-only; public customer access remains deferred.
- [ ] Inventory the available Sardars files, URLs and sitemap; identify descriptive claims, source authority, visibility, formats, duplicates and update/freshness rules. Save representative questions and the current answers before ingestion so improvements can be measured. Company documents do not replace PostgreSQL for current price, SKU or stock.
- [ ] Add registration and pending/approval UI, then file/URL/sitemap submission UI for approved admins and staff, plus source list, job status, retry and removal controls. Reuse the existing authenticated ingestion and job endpoints where possible; adapt submission to the E3 runner. Extend the bounded single-URL importer into an authenticated crawl with domain, robots, size and page limits; durably stage crawl references before indexing. Decide DOCX/OCR separately.
- [ ] Use the selected runner to ingest a small Sardars sample first, inspect extraction/chunks/citations and role visibility, then import the remaining authorized sources in bounded batches. Preserve stable source IDs, provenance, progress, retries and update/deletion. Use external original-document storage only if measured size/operational needs justify it.
- [ ] Reask the saved questions after each batch; compare grounded answer quality, retrieval/source hits, unsupported claims and latency with the pre-ingestion results and the retained chat/seed/full-site suites. Diagnose any remaining failures by layer rather than assuming more data guarantees better answers.
- [ ] For any requested fresh-start exercise, first inventory and back up RAG tables, originals and Qdrant; write a reversible, exact reset scope and verify restore before clearing data. Preserve users, conversations and authoritative products unless explicitly included in an approved reset.

Exit: a newly approved internal account can submit supported Sardars content, observe completion and retrieve only visible indexed sources; failures, revocation and updates behave correctly. Before/after evaluation shows where the new data improved answers and what still fails.

After this exit, finish and record the deferred E1 data-backed checks above. Do not infer E1 completion from E4's UI or job status alone.

## E5 — Close full-corpus retrieval and evidence regressions

Goal: resolve the six retained full-site failures and any newly measured retrieval/evidence failures after Sardars data ingestion, without weakening source checks.

- [ ] Reproduce each saved-crawl and seed failure, recording whether the case is evaluated against the original or newly expanded corpus. Classify source extraction and coverage, ranking, evidence selection, citation identity, answer generation and service errors separately.
- [ ] Change the failing layer in bounded increments; compare relevance and abstention, and distinguish another authorized citation from absent evidence. Consider hybrid retrieval or another reranking method only if the measured failures justify it.
- [ ] Rerun the same full-site, chat and seed suites after each accepted change; check role/source revocation, prompt injection, unsupported changing facts and latency.

Exit: the retained saved evaluations pass under explicitly reviewed criteria, with no regression in the chat and seed gates. Document any unresolved limitation and keep E5 and the Phase 5 backlog open; do not label those regressions fixed without a passing rerun.

## E6 — Evaluate model-assisted tool discovery

Goal: handle realistic product questions that do not match today's simple routing terms while keeping tool execution safe.

- [ ] Add representative missed-phrasing, mixed RAG/tool, irrelevant, ambiguous and adversarial cases with baseline route and tool-choice outcomes.
- [ ] Compare the current inspectable application router against a model-assisted choice using only a small authorized evidence set and an explicit read-only tool allowlist. Do not send the full corpus or arbitrary function names to the model.
- [ ] Keep Pydantic validation, role checks, source rechecks, bounded call count/time/results and PostgreSQL reads in application code. Missing or invalid model tool requests must fail safely; the model cannot authorize access or override current product records.
- [ ] Measure tool-choice precision/recall, exact-fact correctness, unsupported claims, abstentions and latency on the same cases; adopt only if it improves the measured result without security regression.

Exit: a tested routing decision, whether that is an improved deterministic router, a guarded model-assisted router, or the existing approach.

## E7 — Bounded internet search, if needed

Goal: add external information only for questions that benefit from it, with distinct provenance.

- [ ] Decide whether the use case needs internet search; compare a self-hosted search service with an approved provider, including privacy/network implications.
- [ ] If adopted, allowlist the search tool, cap queries/results/time, apply domain safety and safe errors, and define citation provenance and cache expiry. Treat result text as untrusted.
- [ ] Test injection, authorization, unavailable results and citations. Never use web results alone to assert current Sardars price, stock, policy or other controlled facts.

Exit: either a tested bounded search path with clear source labels or a documented decision to defer it.

## E8 — Live internal acceptance

Goal: test the actual integrated flow beyond mocked browser and isolated backend checks.

- [ ] With a disposable account and controlled files/sitemap, test approval, login, upload, job progress, retrieval, citations, source revocation, failed-job recovery, browser refresh and cleanup across PostgreSQL, originals and Qdrant.
- [ ] Compare real staff questions with the Phase 11/12 baselines; include independent human groundedness review and additional languages only after their required scope is decided.
- [ ] Record remaining data, quality, latency, accessibility and operational gaps without claiming production readiness.

Exit: a repeatable live internal acceptance record with known gaps and verified cleanup.

## E9 — Production readiness, only when deployment is chosen

Goal: make the selected internal release secure, observable and recoverable for its intended users. **Do not start this phase solely because local containerization is complete.**

- [ ] Decide hosting, expected traffic, privacy/retention rules and business response-time targets; size GPU/CPU, memory, concurrency, queues and timeouts from load tests.
- [ ] Verify an Ollama-to-vLLM adapter with the selected model, tool format, output limits and streaming behavior if vLLM is selected. Preserve the application inference interface.
- [ ] Add a reverse proxy, HTTPS, environment-specific secrets/configuration, private service networking, hardened internal authentication, shared rate limits when multiple API workers are used, and no public-customer access by default.
- [ ] Add structured metrics/logs, alerts and access/retention rules without logging secrets or unnecessary document/customer data. Plan durable PostgreSQL/Qdrant/original/model storage, backups and a tested restore; use S3-compatible storage only if justified.
- [ ] Run deployment smoke/load/failure drills and document operations and rollback before opening access to intended users.

Exit: authorized internal users can access the service, private services stay private, important data can be restored, and failures can be diagnosed and rolled back. This is intentionally open until deployment is requested and verified.
