# Sardars AI Assistant — extended plan

Last reviewed: 2026-10-22
Status: active roadmap; E1–E6 and the developer-requested E6 model-first prototype follow-up are complete on this laptop. E7 is the next optional checkpoint. Human claim review and production readiness remain later work.
Implementation evidence: `IMPLEMENTATION_STATUS.md`
Original prototype roadmap and decisions: `PLAN.md`

## Purpose and order

The English internal prototype completed Phases 1–12 of `PLAN.md`. The original Phase 13 deployment work and its deferred follow-up backlog move here because deployment is not currently planned. E1's data-backed local-container restart and restore exit was verified after E4; see `docs/e1_local_container_checkpoint.md`. E2 compared the retained original corpus on the same Ollama server; the developer selected 4B for the current local Docker application despite slower measured responses and unchanged automated scores. See `docs/e2_model_comparison.md`. E3 selected a dedicated PostgreSQL-polling ingestion worker for the local Compose stack; see `docs/e3_ingestion_runner.md`. E4 completed the **existing-admin-to-RAG** journey and measured the uploaded corpus; see `docs/e4_real_data_baseline.md`. E5 resolved the retained retrieval/evidence cases on the uploaded corpus and measured the 4B latency limitation; see `docs/e5_quality_checkpoint.md`. E6 screened bounded 4B read-tool choice, rejected live model-requested follow-ups on correctness/latency evidence, and verified an application-router improvement; see `docs/e6_routing_checkpoint.md`. Self-registration and admin approval are deferred. Production deployment is a separate, later decision. E1 infrastructure completion alone did **not** clear the retained full-site failures or certify model answer quality; the later E5 replay supplies the correctness evidence.

Work in small, runnable checkpoints. Before each substantial change, explain the concept, alternatives and trade-offs. Keep a measured baseline and run the relevant regression suites after changes. Update `IMPLEMENTATION_STATUS.md` only after a verified major checkpoint, and update this plan when an exit criterion or order changes. The sequence below may change when measurements or developer decisions justify it.

The current reference is the Phase 12 English internal-prototype result: **26/26 chat**, **7/7 seed**, **34/40 full-site**, and **21/24 expected-source hits**. The full-site failures are `mirror`, `seat_materials`, `mirror_paraphrase`, `fittings_materials_article`, `sustainable_toilets_article`, and `maintenance_article`. See `docs/phase12_optimization_report.md`. These automated suites are useful regression checks, not independent human approval of answer quality.

Across every checkpoint: keep self-hosted inference; preserve authentication, application-enforced role/source visibility and bounded allowlisted tools; treat retrieved and tool text as untrusted; use PostgreSQL at request time for authorized SKU, price and stock values. Do not treat Qdrant or an internet result as authority for changing Sardars facts. Do not reset the corpus, product table, accounts or conversations as a routine setup step.

## E1 — Complete local containerization

Goal: run the existing application reproducibly on one development machine without publishing it. The runnable empty-data stack was an intermediate checkpoint; the data-backed E1 exit was verified on 2026-10-21 after E4's real data entry.

- [x] Add pinned, buildable API and frontend images and a local Compose workflow for API, frontend, PostgreSQL, Qdrant and containerized Ollama by default. Preserve data/model volumes; offer an optional NVIDIA GPU override for compatible hosts.
- [x] Configure service-name networking, health/readiness checks, startup and migration commands, secrets from local environment rather than images, and localhost-only user-facing ports. Keep database, vector and inference services private to the Compose network by default.
- [x] Document initial model pulls, first admin creation, startup, shutdown, updates and safe backup/restore of local volumes. Existing developer data must survive normal restarts and image rebuilds.
- [x] Verify a clean-volume start and a restart with retained data; run authenticated chat, product lookup, authorized retrieval, frontend login and the relevant backend/frontend checks. Compare basic latency with the current host setup before deciding whether to retire `scripts/dev.sh`.

Exit, checked **after E4** on 2026-10-21: the complete internal stack started and restarted with the entered corpus, authenticated chat, authorized cited retrieval, PostgreSQL product lookup and frontend login passed, and a four-volume cold backup booted in an isolated restore. SQL/vector fingerprints and source originals matched before/after; backend/frontend checks passed. Basic latency was compared with the historical host workflow; the different chat models prevent attributing that gap to containers, so `scripts/dev.sh` remains available. On this memory-constrained laptop a 4B model request timed out and a retry took 207 seconds before a guarded non-answer. E1 is the **local infrastructure** exit, not a model-quality, hardware-capacity or production-deployment sign-off. Evidence: [E1 checkpoint](docs/e1_local_container_checkpoint.md) and [backup/restore procedure](docs/e1_backup_restore.md).

## E2 — Measure and improve model answer quality

Goal: test whether a larger local chat model produces better grounded answers on this hardware.

- [x] Freeze the current prompts, retrieval corpus, tool rules and case definitions; record the active model, quantization, memory use and repeatable `qwen3:0.6b` baseline.
- [x] Compare an available 4B-class Qwen instruct model first, then an 8B-class or other open-weight option only if hardware and latency permit. Keep the embedding model/collection unchanged during the chat-model comparison. The observed 4B latency on this CPU ruled out an 8B run here.
- [x] Run the same 26-case chat, seven-case seed and 40-case full-site suites, plus a blinded comparison of real staff questions. All eight staff answer/citation pairs were exactly identical, so they were scored as objective ties without separate subjective human grading. Compare factual support, citations, abstentions, unsafe claims, phrasing, follow-ups, tool-choice outcomes, median/p95 latency, timeouts and memory/swap pressure. Recheck model response and tool-call formats through the Ollama adapter. Independent human review after E4's richer data remains open.
- [x] Make a documented local model choice from measured quality, resource cost and developer preference while keeping security/authorization checks passing. The developer selected 4B for the current Docker application despite its higher latency; the shared code fallback remains 0.6B for other environments.

Exit: a documented model choice based on comparable results. A larger model alone does not fix missing retrieval evidence or the application's rule-based tool routing.

E2 completed on 2026-10-19 for the retained corpus/current CPU. Both models passed 26/26 chat and 7/7 seed cases, and each passed 34/40 full-site cases with the same six failures. Eight blinded staff pairs had identical text and citations; the developer confirmed recording these as exact ties in place of subjective human scoring, a change to the review method rather than a claim of independent human approval. The developer selected 4B for the current local Docker application despite slower model-invoking turns and no measured correctness gain; retest it after E4 or on stronger hardware if useful. See `docs/e2_model_comparison.md` for the full evidence and limits.

## E3 — Decide how ingestion work runs

Goal: make larger uploads and sitemap imports reliable before building the ingestion UI. Before this checkpoint, the API recorded durable jobs but still waited for extraction and indexing in the request; measure whether a separate worker was needed.

- [x] Measure current durable-job runtime, request blocking, queueing, retry/recovery and CPU/memory use on controlled files and saved-crawl samples. A live sitemap API/crawl does not yet exist and remains E4 work.
- [x] Compare the existing synchronous runner, a small dedicated worker and Celery with a broker. Select one PostgreSQL-polling worker for the local workload; defer Celery/Redis until E4 measurements demonstrate a need.
- [x] Apply the selected runner in the local Compose stack. The API returns HTTP 202 with a job ID, and the UI can poll the existing authorized job endpoint. Celery's broker-specific step is not applicable to this selection.
- [x] Preserve owner/role checks, leases, idempotency, bounded retries, status, update/deletion and safe publication between PostgreSQL and Qdrant. A failed job must not expose partial or unauthorized content.

Exit: a documented runner choice and tested recovery for the selected workload. Celery/Redis are strong candidates for lengthy imports, but remain conditional until the E3 comparison demonstrates the need and verifies their failure behavior.

E3 completed on 2026-10-19 for the current single-worker local workload. Controlled file, saved-crawl and embedding probes established the request-blocking baseline; the dedicated worker passed focused tests, the full backend regression suite, and a disposable-PostgreSQL recovery/update/removal check. The API and worker started in Compose without adding any source or Qdrant points to E1. See `docs/e3_ingestion_runner.md` for measurements and limits. E4 must measure its new sitemap crawl and real bulk-submission workload before deciding whether broker-based scaling is needed.

## E4 — Admin-to-ingestion journey

Goal: let an existing admin submit Sardars company data through the browser, have the E3 worker index it, and receive authorized cited answers. Account self-registration and approval are later work; the first admin remains operator-created.

- [x] Inventory the uploaded Sardars files, URLs, sitemap, source authority, visibility, formats, duplicate checks and freshness limits. Freeze representative questions. A comprehensive pre-upload answer snapshot was not saved; the measured comparison excludes uploads before retrieval ranking on the same current corpus. Company documents do not replace PostgreSQL for current price, SKU or stock.
- [x] Add an admin-only browser screen for PDF/TXT/Markdown file and single-URL submission, source list, job status, retry and removal controls. Reuse the authenticated ingestion and job endpoints and preserve role/source checks. DOCX/OCR remains a separate decision.
- [x] Add bounded admin-submitted sitemap crawling through the worker, with aggregate progress, child failures, stable source identity and provenance. Preserve configured domain, robots, response-size, page-count, crawl-delay and retry limits.
- [x] Inspect real uploaded files and sitemap jobs, extracted chunks, citations, role visibility and replacement behavior. The user entered the live data before this evaluation; no historical small-sample-first procedure is claimed. Originals remain in existing storage; no external store was justified.
- [x] Measure current questions with and without uploaded sources, plus retained chat/seed/full-site suites; record answer quality, source hits, unsupported claims, latency and layer diagnoses. This is a controlled current-corpus ablation, not a historical before/after replay.
- [x] No fresh-start exercise was requested or performed. Preserve users, conversations, sources, products and index; require a scoped backup and verified restore before any later reset.

Exit: an existing admin can submit supported files, individual URLs and a bounded sitemap through the browser, observe worker completion, and retrieve only visible indexed sources; failures, revocation and updates behave correctly. Where no pre-upload snapshot exists, a same-corpus source-exclusion evaluation measures what the uploaded data contributes and what still fails. Registration and account approval are outside this exit.

E4 implementation checkpoint (2026-10-19): the admin browser workflow, worker-backed sitemap parent/child jobs, bounded discovery, progress and retry were implemented and covered by backend/frontend/mocked-browser tests. At that point, real-data evaluation remained open; see `docs/e4_admin_ingestion_checkpoint.md`.

E4 measured exit (2026-10-21): the live corpus, durable job outcomes, original/snapshot/vector integrity, real authenticated HTTP/browser journey, 21-case answer set and retained suites were evaluated. Current-corpus upload exclusion improved strict cases from 8/21 to 13/21 and selected expected-source hits from 3/15 to 15/15; six unsupported-claim cases abstained. The historical before-upload answers and per-batch questions were not saved, so this substituted ablation cannot claim a historical effect. Four of the original six full-site cases still fail on the current corpus, and five other retained cases now fail. These remain E5 work, not E4 successes. See `docs/e4_real_data_baseline.md` and `IMPLEMENTATION_STATUS.md`.

E4 qualified-FAQ follow-up (2026-10-21): A later answer-layer refinement permits an exact approved FAQ to explain that a requested live value was not verified, with a citation and without asserting any current value. The original 21-case expectations are preserved in `e4_cases_baseline.json`; the active case file expects this qualification for the Google-rating question. The replay remained 13/21 with stable data. This does not change E5's separate plan to measure a grounded model path for descriptive questions, or the rule that current SKU, price and stock come from PostgreSQL.

After this exit, finish and record the deferred E1 data-backed checks above. Do not infer E1 completion from E4's UI or job status alone.

## E5 — Close full-corpus retrieval and evidence regressions

Goal: resolve the six retained full-site failures and any newly measured retrieval/evidence failures after Sardars data ingestion, and improve how the model turns sufficient evidence into a useful cited answer without weakening source checks.

- [x] Reproduce each saved-crawl and seed failure, recording whether the case is evaluated against the original or newly expanded corpus. Add real Sardars brand, company-overview and other descriptive questions with current answer, retrieved source, model use, citation and latency baselines. Classify source extraction and coverage, ranking, evidence selection, citation identity, answer generation and service errors separately.
- [x] Change the failing layer in bounded increments; compare relevance and abstention, and distinguish another authorized citation from absent evidence. Consider hybrid retrieval or another reranking method only if the measured failures justify it.
- [x] Evaluate a shared, structure-aware chunking policy before changing the index: keep FAQ question/answer pairs intact, split longer documents and articles at heading or paragraph boundaries, keep short product descriptions together, and use bounded overlap only when a section is too long. Compare it with the current 100-word/15-word-overlap baseline on the same saved questions, including source hits, answer support, indexing cost and latency; adopt and reindex sources only if the evidence warrants it. The offline gate found unchanged answer locality and 6.2% more chunks, so no shadow vector index or live reindex was justified; vector ranking and answer latency under that rejected policy remain unmeasured.
- [x] For descriptive company questions, replace the all-question-terms-in-one-sentence prerequisite with a measured relevance check over a small evidence set; a relevant authorized passage may reach the model even when no individual sentence repeats every query term. Give the selected local model the shared system instructions, user question and numbered excerpts **after** application-enforced source authorization. Let it compose a clear answer with citations instead of returning an isolated source sentence by default. Treat excerpts as untrusted; verify cited source identity and support for company claims, and abstain or use a safe extractive fallback when evidence or output is inadequate. Preserve deterministic handling of explicit changing facts from PostgreSQL.
- [x] Rerun the same full-site, chat and seed suites after each accepted change; check answer usefulness, citation support, role/source revocation, prompt injection, unsupported changing facts and latency, including the cost of another 4B model call.

Exit: the retained saved evaluations pass under explicitly reviewed criteria, with no regression in the chat and seed gates; supported company questions receive useful cited answers, while missing evidence still produces a safe abstention. Document unresolved limitations in the Phase 5 quality backlog. Keep E5 open if those correctness gates fail; do not label retained regressions fixed without a passing rerun. This checkpoint has no response-time threshold or independent-human sign-off gate.

E5 exit, verified 2026-10-22: On the uploaded E4 corpus and unchanged frozen checks, **40/40 full-site** cases passed with **24/24** expected-source hits, including all six retained failures; chat passed **26/26**, staff-role seed **7/7**, and uploaded-source cases **21/21**. Unsupported-claim, citation, role/source and exact-fact controls passed; SQL/vector fingerprints stayed stable. The final backend suite passed **670, four skipped**, and authenticated `/ask` returned cited answers from the rebuilt API. The chunking shadow policy was rejected without reindexing. The 4B CPU full-site p95 was **72.424 seconds** with a **162.420-second** outlier, and independent human claim review remains open quality backlog. Those limitations were measured and documented, but no E5 response-time threshold or independent-human sign-off was set as an exit criterion. E6 can begin. See [E5 checkpoint](docs/e5_quality_checkpoint.md).

## E6 — Evaluate hybrid routing and model-assisted investigation

Goal: handle realistic company and product questions that do not match today's simple routing terms by comparing application-first routing with bounded model-requested retrieval and read tools, while keeping tool execution safe. This routing hybrid is distinct from Qdrant's semantic-plus-keyword hybrid search.

- [x] Add representative missed-phrasing, mixed RAG/product-tool, irrelevant, ambiguous and adversarial cases with baseline route, retrieval, tool-choice and answer outcomes.
- [x] Keep application-enforced authentication, scope exclusions and an initial authorized RAG search for clear or uncertain Sardars questions; do not depend on the model remembering to search. Keep an application-triggered PostgreSQL lookup for explicit SKU, price or stock requests if the model omits it. Clear general product education need not search the company corpus.
- [x] Screen the guarded model-assisted candidate with explicit `search_company_sources` and approved read-only product-tool definitions before building a follow-up executor. The selected 4B model failed the bounded tool-choice/latency gate (3/5 correct; two 60-second errors), so no model-requested tool was executed or added to the API. This staged gate replaces the originally proposed full execution comparison for this laptop/model; a future candidate must pass it before application-validated execution and source rechecks are considered.
- [x] Preserve Pydantic validation, role checks, source rechecks, bounded result/time handling, safe failures and PostgreSQL reads in the unchanged production tool paths. Preserve source IDs/citations and verify exact product claims against database results; retrieved or tool text cannot grant permission or override current product records. Compare Ollama tool-call behavior and latency on the selected 4B model.
- [x] Measure current retrieval usefulness, tool-choice precision/recall, exact-fact correctness, unsupported claims, abstentions and latency on the same cases. Reject model-assisted follow-up before execution after its tool-choice gate failed; adopt the tested deterministic router improvement.

Exit: a tested hybrid-routing decision, whether that retains the initial application search with guarded model-requested follow-ups, improves the deterministic router alone, or keeps the existing behavior. Company evidence remains cited and role-visible; exact changing facts come from PostgreSQL, with safe behavior when the model misses or requests an invalid tool.

E6 exit, verified 2026-10-22: The 11-case baseline passed 6/11 and the final application-router path passed 11/11; the broad history case's unsupported expected citation was corrected to abstention after source audit, with the original response still failing. The 4B tool-choice screen returned 3/5 correct selections with two roughly 60-second errors, so the model-assisted executor was not built. Retained chat, uploaded-source, seed and full-site suites passed 26/26, 21/21, 7/7 and 40/40 with 24/24 expected source hits and stable data fingerprints. The backend suite passed 676 with four skipped; the rebuilt local API passed authenticated E6 routes and anonymous 401. The 4B full-site latency tail and independent broader claim review remain open. See [E6 checkpoint](docs/e6_routing_checkpoint.md).

## E6 prototype follow-up — Model-first answers

The developer requested a more open prototype flow after the E6 application router returned the safe fallback for greetings and several ordinary company questions. This follow-up supersedes the E6 router as the **current `/chat` and `/ask` behavior**, without changing the historical E6 evaluation result.

- [x] Send each normal information question to a local LLM. Retrieve and authorize a small initial RAG set first; empty or unavailable retrieval becomes empty context. Pure greetings skip needless retrieval but still reach the model. Offer a bounded model-selected follow-up search and read-only PostgreSQL product tools. Preserve application-enforced login, role/source checks, Pydantic tool validation, output bounds and database authority for SKU, price and stock.
- [x] Record a first live latency and answer sample on uploaded data, compare the chosen 4B model with the already-installed 0.6B model for this interactive path, and keep the embedding model, collection and corpus unchanged. See [prototype report](docs/e6_model_first_checkpoint.md).
- [x] Rebuild the current-flow case set and evaluator expectations. Measure greeting, company overview, FAQ qualification, review sentiment, categories, address, product discovery, exact SKU/price/stock, absent evidence, citations, role revocation, injection and latency under the new routing. The old E4/E5/E6 pass counts are historical and must not be presented as current-flow scores.
- [x] Separately audit a wider sample of company claims and citations against captured authorized excerpts, including the observed misqualified review answer. The bounded 0.6B path passed the prototype sample; independent human review and broader freeform quality remain E8/production backlog. See [current-flow exit](docs/e6_current_flow_exit.md).

E6 follow-up exit, verified 2026-10-28: The current-flow replay passed **14/14**, with **8/8** expected citation/source hits, **2/2** exact PostgreSQL fact checks, **2/2** stock checks and a stable source/product fingerprint; median/p95 latency was **3.82/26.39 seconds**. A separate five-case open-ended claim sample passed **5/5** after correcting unsupported Lahore, competitor, brand, installation and history answers; its median/p95 was **4.76/9.60 seconds**. An agent-performed citation audit found no unsupported Sardars or changing-fact assertion in the reviewed final cases. The full backend suite passed **679, four skipped**, and the rebuilt local API returned readiness 200 and anonymous `/ask` 401. This is a bounded prototype exit, not independent human sign-off or broad freeform grounding certification. See [current-flow exit](docs/e6_current_flow_exit.md).

## E7 — Bounded internet search, if needed

Goal: add external information only for questions that benefit from it, with distinct provenance.

- [ ] Decide whether the use case needs internet search; compare a self-hosted search service with an approved provider, including privacy/network implications.
- [ ] If adopted, allowlist the search tool, cap queries/results/time, apply domain safety and safe errors, and define citation provenance and cache expiry. Treat result text as untrusted.
- [ ] Test injection, authorization, unavailable results and citations. Never use web results alone to assert current Sardars price, stock, policy or other controlled facts.

Exit: either a tested bounded search path with clear source labels or a documented decision to defer it.

## E8 — Live internal acceptance

Goal: test the actual integrated flow beyond mocked browser and isolated backend checks.

- [ ] With an existing admin account and controlled files/sitemap, test login, upload, job progress, retrieval, citations, source revocation, failed-job recovery, browser refresh and cleanup across PostgreSQL, originals and Qdrant.
- [ ] Compare real staff questions with the Phase 11/12 baselines; include independent human groundedness review and additional languages only after their required scope is decided.
- [ ] Record remaining data, quality, latency, accessibility and operational gaps without claiming production readiness.

Exit: a repeatable live internal acceptance record with known gaps and verified cleanup.

## Deferred — Internal registration and approval

After the admin ingestion flow is working and when additional internal accounts are needed, add a rate-limited registration request that creates an inactive/pending account. An existing admin must approve it and assign staff access before login or ingestion; applicants cannot assign their own role. Add the corresponding admin review and applicant-status UI, then test pending/denied access and approval end to end. Public customer registration remains outside the internal release. This work is not an E4 or E8 exit criterion.

## E9 — Production readiness, only when deployment is chosen

Goal: make the selected internal release secure, observable and recoverable for its intended users. **Do not start this phase solely because local containerization is complete.**

- [ ] Decide hosting, expected traffic, privacy/retention rules and business response-time targets; size GPU/CPU, memory, concurrency, queues and timeouts from load tests.
- [ ] Verify an Ollama-to-vLLM adapter with the selected model, tool format, output limits and streaming behavior if vLLM is selected. Preserve the application inference interface.
- [ ] Add a reverse proxy, HTTPS, environment-specific secrets/configuration, private service networking, hardened internal authentication, shared rate limits when multiple API workers are used, and no public-customer access by default.
- [ ] Add structured metrics/logs, alerts and access/retention rules without logging secrets or unnecessary document/customer data. Plan durable PostgreSQL/Qdrant/original/model storage, backups and a tested restore; use S3-compatible storage only if justified.
- [ ] Run deployment smoke/load/failure drills and document operations and rollback before opening access to intended users.

Exit: authorized internal users can access the service, private services stay private, important data can be restored, and failures can be diagnosed and rolled back. This is intentionally open until deployment is requested and verified.
