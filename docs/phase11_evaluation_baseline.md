# Phase 11 checkpoint 1: read-only chat-service baseline

Recorded 2026-10-18. This is the historical **first checkpoint**, taken before the stock-tool change. The final Phase 11 evaluation and its remaining product-quality failures are in [the completion report](phase11_evaluation_completion.md). This checkpoint added measurement without changing routing, prompts, retrieval, tools, model settings, or stored company data.

## Purpose and remaining steps

Phase 11 replaces judgments from casual chats with repeatable questions and explicit checks. A baseline records the current result before tuning. Layer-specific results help distinguish a bad expected answer, missing source, retrieval miss, evidence-selection problem, incorrect tool, wrong database value, or service failure.

This first checkpoint measures the answer dispatcher used by `/chat`, real local PostgreSQL/Qdrant/Ollama calls, and separate disposable trust controls. Later checkpoints should expand representative staff questions, human review of semantic correctness/groundedness and refusal quality, authenticated API/conversation/stream/browser evaluation, adversarial and language coverage, and repeated performance measurements. Business quality and response-time thresholds still require decisions after reviewing the baseline. Phase 11 exits when evaluations can reliably show whether a change improves or harms the assistant; this checkpoint alone does not complete that phase.

## Run it

From the repository root, with the existing PostgreSQL, Qdrant collection, Ollama chat model and embedding model available:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_chat --report data/extracted/phase11_chat_NEW_NAME.json
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_chat_evaluation.py
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests
```

Use a new report filename for every run. `--cases PATH` selects another bounded JSON case file; unknown fields, invalid cases, duplicate IDs and oversized files are refused. The CLI exits **1** when a case fails, after saving the results. Evaluation failures are expected baseline findings, distinct from failing harness tests.

Run the CLI serially in its own process. Avoid overlapping Ollama ingestion/evaluations. Temporary observers wrap the existing dispatcher dependencies only in that process. Each live case uses a PostgreSQL `REPEATABLE READ READ ONLY` transaction and the ordinary role/source filters. Exact prices/SKUs are compared with an independent SQL read in the same snapshot. Continuation variants may have NULL status; their active, visible product identity is checked under the same handle. Source controls use in-memory SQLite and never enter PostgreSQL or Qdrant. No account, conversation, source, job or vector is inserted, updated or deleted.

This is a trusted local operator command using staff/admin evaluation actors. It does **not** authenticate over HTTP or measure login, request validation, rate limits, conversation ownership, history, SSE or the browser. Existing tests for those features remain separate evidence.

## Fixed checks and observations

The 23 cases contain fifteen live-service questions and eight isolated controls. They cover company overview, brands, descriptive evidence, exact SKU prices, missing products, discovery, price-filtered descriptions, comparisons, unknown currency, unsupported policy/stock, general technical education, unrelated input, user/source injection, conflicting evidence, source roles, registration, readiness, disablement and generation.

Reports distinguish:

- Expected route and **observed tool calls**, including safe tool errors; a matching route does not prove correct tool selection.
- Expected source in authorized retrieval versus the source actually cited; another authorized citation is reported separately from a retrieval miss.
- Citation marker/authorized-source consistency and product-description joins, bounded price filters, required answer phrases and exact abstentions.
- Returned and rendered SKU/price values, source-file identity and currency against role-visible database rows.
- End-to-end live-service latency, route-specific median/nearest-rank p95, retrieval/tool/model call duration, model-call context character/message counts and available token counts. Missing token counts remain null. Failed services cannot pass as legitimate abstentions; caught description-index outages also fail the service check even if exact database results remain usable.

Checks with no applicable expectation remain unmeasured. Citation consistency and phrase checks are limited automated proxies, **not** universal semantic correctness, groundedness or hallucination scores. Raw candidate text, prompts, tool arguments and exception messages are not recorded; local reports contain answers and authorized citation metadata and should remain internal/Git-ignored.

Report metadata includes UTC run time, case definitions/checksum, evaluator checksum, Git revision/dirty state, model tags, collection and answer timeout. It does not freeze mutable model-weight digests or the whole live corpus. Repeat comparisons require the same protocol/cases and a controlled corpus/model/workload; database values intentionally remain current reads.

## Measured baseline

The corrected protocol-v2 report is `data/extracted/phase11_chat_baseline_v2_20261018.json`, against Git base `01a0114` with this checkpoint uncommitted. It completed with the expected exit code 1:

| Measure | Result |
| --- | --- |
| Whole cases | **20/23** |
| Live-service cases | **12/15** |
| Isolated trust controls | **8/8** |
| Expected routing / tool selection | **14/15 each** |
| Observed tool outcomes | **7/7** matched declared success/missing-product expectations |
| Independent exact-fact checks | **4/4** cases |
| Expected source retrieved | **3/4** |
| Expected source cited | **2/4** |
| Citation consistency | **15/15**, including cases correctly returning no citations |
| Description joins | **3/3** |
| Required answer phrase checks | **12/13** |
| Exact unsupported-fact abstentions | **1/2** |
| Service checks | **15/15** |
| Live median / nearest-rank p95 | **470.1 / 24,520.4 ms** |
| Chat-model calls | **3** |

The mixed latency median is dominated by fast database/scope routes. Company-route median/p95 were 1,257.6/24,520.4 ms (five cases); the one general-model case took 15,092.9 ms. These are a small serial laptop sample, not a load benchmark or response-time target. The ordinary backend regression suite overlapped part of this run; performance comparisons need a more controlled workload.

## Findings by layer

| Case | Observation | Diagnosis / next measurement |
| --- | --- | --- |
| `brand_list` | Required names appear and About Us was retrieved, but the answer cites the authorized `best-sanitary-company-in-pakistan` article | Strict expected-source mismatch/evidence selection. Do not label it a source-authorization failure or missing retrieval evidence; review whether the alternative source answers the intended question. Preserve the strict baseline assertion. |
| `storage_evidence` | Shower Niche is absent from the authorized candidate set; the answer cites generic bathroom-storage article prose | Retrieval/coverage investigation first, then evidence usefulness. The supported product answer is missing. This does not establish whether extraction or ranking caused the miss. |
| `unknown_stock` | A guarantee-of-stock question runs `search_products` and returns a generic no-match response | Routing and refusal-quality mismatch. It does not invent stock, but does not give the expected explicit unsupported-stock abstention. |

No application fixes or tuning were made for these findings. The historical Phase 5 expanded **28/40** and latest seed **5/7** records remain open. Neither complete legacy evaluation was rerun here, and this new overlapping case set does not supersede or fix them.

The initial evaluator-development run is preserved as `data/extracted/phase11_chat_baseline_20261018.json` (**16/23**) with its case file `phase11_chat_cases_initial_20261018.json`. Its extra failures included an incorrect per-variant status requirement, a needless company-name phrase requirement, and an unjustified single-product citation expectation on a broad recommendation. Protocol v2 corrects those checks and requires a citation joined to the actual recommended product. **The score difference is an evaluator correction, not an assistant quality improvement.**

## Verification and scope limits

The focused harness checks passed **24 tests**, including wrong rendered prices, wrong tool calls, forged citations, continuation variants, missing required descriptions, service/model failures, caught description-index outages, report overwrite protection, case validation, isolated trust controls and latency separation. A sandboxed threaded test run stalled; that process was stopped, and the focused run passed outside the sandbox. Full backend verification is recorded in `IMPLEMENTATION_STATUS.md`.

The deferred backlog remains untouched: no corpus reset, ingestion worker, model-assisted tool selection, registration/upload UI, internet-search tool or fresh live end-to-end journey was implemented. There are no schema, dependency or production API changes.
