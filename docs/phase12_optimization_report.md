# Phase 12 — measured optimization for the internal prototype

Recorded 2026-10-18. The Phase 11 baseline passed 26/26 cross-route chat cases and 7/7 seed cases, but only 31/40 full-site cases, with 18/24 required authorized sources retrieved. Full-site serial live median/p95 were 17,572.6/44,310.5 ms. Reports contain the saved case outcomes; the full-site evaluator does not fingerprint every Qdrant point between runs, so treat timing comparisons as local observations, not a production service-level result.

## Authorized retrieval selection

The read-only top-32 probe found three missed sources at semantic ranks 12, 14 and 21; three article targets were still outside the top 32. Retrieval now fetches at most 32 role-prefiltered Qdrant points, checks every candidate against the current PostgreSQL source registry, and selects at most eight authorized points. A small lexical reranker favors query terms in titles and descriptive text for specific-subject questions. The registered About Us profile remains pinned for the existing company/brand hint. Broad product-discovery questions keep semantic order because reranking generic storage terms displaced the useful Shower Niche evidence in an early live test. Final model evidence remains capped at three excerpts and 1,800 characters. Exact SKU, price and stock answers still use PostgreSQL tools at request time.

The final 40-case run passed **34/40**, with **21/24** expected-source retrieval hits. `corner_overflow`, `drain_paraphrase` and `garden_residences` changed from failed to passed, with no case passing before and failing afterward. The separate 26-case chat suite stayed **26/26** and the seed suite stayed **7/7**; eight isolated trust controls also passed in the full-site run. The six remaining full-site failures are `mirror`, `seat_materials`, `mirror_paraphrase`, `fittings_materials_article`, `sustainable_toilets_article` and `maintenance_article`. The first three concern evidence selection or a strict expected-source reference; the three articles remain absent from the authorized top-32 semantic pool. The deferred Phase 5 full-corpus work is still open.

## Model residency and resource trade-off

The local Ollama adapter previously sent `keep_alive=0` for every chat call. In a five-call reload probe, two cold calls each spent about 2.9–3.1 seconds loading the 0.6B chat model; a repeated call with a five-minute keep-alive spent 6.6 ms loading it. Ollama reported about **1.02 GB** resident model size and **0 bytes VRAM** while loaded on this CPU-only machine. The final probe call unloaded it again. Chat now defaults to a bounded 300-second keep-alive; the existing embedding/ingestion setting remains zero, and operators can set `SARDARS_OLLAMA_CHAT_KEEP_ALIVE=0` if RAM is constrained. This retains model weights, not answers, prompts, permissions or company facts.

With reranking alone, the full-site serial live median/p95 were **8,528.7/17,588.3 ms**; with chat keep-alive they were **2,965.8/12,641.5 ms**, with the same 34/40 case outcomes and 21/24 expected-source hits. Run-to-run model and host variance also affect these small samples; the isolated load-duration probe supports the narrower conclusion that warm repeated model calls avoid about three seconds of reload work.

Existing budgets already cap general conversation history at eight messages and 1,600 characters, RAG evidence at three excerpts and 1,800 characters, and model generation at 256 tokens. No observed case showed a context-growth problem, so no summarizer or prompt cache was added. Embedding ingestion already batches two chunks; no new batching or model routing was justified by this answer-focused baseline. Redis, embedding/result caching and an additional lexical index were deferred: repeated-query benefit and safe invalidation across source updates, revocations and exact changing facts have not been measured. The remaining three out-of-pool article cases provide a specific future test for hybrid or indexed keyword retrieval.

A tiny warm-model concurrency probe took **2,545.8 ms** for two serial requests and **1,967.5 ms** for two overlapping requests; the second overlapping request took **1,966.5 ms** versus **1,180.6 ms** for the first. This suggests some local queueing/competition, but two direct Ollama calls do not establish API throughput, multi-user behavior or a production concurrency target. No GPU or VRAM was present in the probe. The final 26-case chat report recorded one model call, 179 prompt tokens, 14 output tokens, 790 maximum model-context characters and 8,130.2 ms model-call time; these are local compute-cost proxies, not a monetary hosting estimate. Ollama did not expose separate KV-cache consumption in this probe. Full load, queue capacity and monetary cost planning remain Phase 13 work once deployment hardware and traffic are chosen.

Verification: the final complete backend suite passed **604 tests**, with three opt-in skips and one existing Starlette/httpx warning. The focused retrieval/adapter group passed **92 tests**, `git diff --check` passed, and the live final suites passed 26/26 chat and 7/7 seed while the retained full-site suite remained 34/40. Frontend code and database schema were unchanged, so the prior frontend checks and Alembic result were not rerun for this checkpoint.

Reproduce the local checks with PostgreSQL, Qdrant and Ollama running; use a new report filename each time:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.probe_retrieval
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.probe_ollama_keepalive
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.probe_ollama_concurrency
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_chat --report data/extracted/phase12_chat_NEW_NAME.json
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_seed
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_coverage --cases backend/app/evaluation/full_site_cases.json --report data/extracted/phase12_fullsite_NEW_NAME.json
```

Run live evaluations serially. The local reports are Git-ignored and refuse overwrite. No corpus reset, ingestion-worker system, model-assisted tool chooser, answer cache or external paid model was introduced.
