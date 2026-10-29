# Phase 5 Step 5 — descriptive coverage and evaluation

Historical checkpoint: the results below describe the selected eight-document corpus on 2026-10-14. Full saved-crawl coverage was explicitly reopened on 2026-10-15 and remains separate from this limited pipeline milestone. See `PLAN.md` Step 6 and the full-site coverage commands in README; do not read this report as evidence that all 1,008 records were indexed.

Verified on 2026-10-14. Step 5 and Phase 5 are complete for the agreed internal descriptive ingestion/synchronization scope. The developer deferred company-database price and stock access to later tools; those values are not integrated or verified here.

## What changed

`app.ingestion.coverage` audits saved crawler records and imports one explicit, checksum-pinned manifest batch of at most ten sources. Default mode is offline audit, `--audit-all` never indexes the crawl, and `--apply` uses the existing durable job and permission/publication checks. The manifest pins a reproducible evaluation corpus; it is not a document approval queue. Changed content requires a deliberate manifest/check update for this benchmark workflow; the ordinary URL/file synchronization paths remain available.

The full 1,008-record extraction was audited offline. Checks identified 302 records with at least one flag: 252 changing-claim flags, 208 transaction/policy flags, 39 short-content flags, and one possible mislabeled specification. Counts overlap. These conservative heuristics can produce false positives and miss defects; they are not factual verification. Normalized duplicate-document/paragraph checks, identical-record deduplication, and existing word-window whitespace cleanup preserve source identity and exact text checksums. Selected risky/duplicate content is refused before job creation rather than rewritten into assumed facts.

Six descriptive website sources were added:

| Source | Purpose | New chunks |
| --- | --- | --- |
| [Cosmetic Mirror](https://sardarandco.com/products/cosmetic-mirror-in-pakistan) | Bathroom accessory description | 1 |
| [Wall-Mounted Seat Lift-Up](https://sardarandco.com/products/wall-mounted-seat-lift-up-support-pakistan) | Accessibility fitting materials and folding description | 2 |
| [Tile Floor Drain](https://sardarandco.com/products/tile-floor-drain-in-stainless-steel-6x6-inch) | Drain material and installation description | 2 |
| [Square E Corner Basin](https://sardarandco.com/products/square-e-ceramic-wall-mounted-or-vessel-corner-sink) | Basin, faucet-hole, and overflow description | 1 |
| [Round Over Counter Basin](https://sardarandco.com/products/over-counter-wash-basin-round) | Basin material description | 1 |
| [Elan Tower](https://sardarandco.com/pages/elan-tower) | Company project and supplied fittings description | 2 |

About Us and Shower Niche remain unchanged. Company coverage is now **eight website documents/twelve chunks**. The developer's staff-visible interview test PDF remains separate at 26 chunks. PostgreSQL reports nine active/ready registrations; Qdrant contains **38 points**. The full website and the separate supplied profile have not been indexed in their entirety; profile overlap and additional coverage need future measured selection.

The import job was `d2f2ff84-ca34-43cb-ba5a-e6287fb9b2f4`: six new sources, nine indexed chunks, two unchanged sources/three skipped chunks. Replay job `1cbddcb6-3d80-4570-8a7b-2d9b76fdcf5d` skipped all eight sources/twelve chunks with no embeddings, vector writes, or deletions. Source-level approval, existing PDF permissions, and publication generations are preserved. Imported descriptions retain their actual 2026-10-12 snapshot dates; replay is not a new fetch or freshness guarantee.

## Findings and focused fixes

The earlier lexical gate found zero usable sentences for three ordinary questions even when their correct documents were supplied. It now handles auxiliary phrases such as “tell me about,” and product headings can identify the subject while the requested feature must still match an actual source sentence. Heading-only matches cannot make an unrelated body answerable.

The first live evaluation passed 23/25. Bongio's correct source ranked sixth, outside the former three-candidate cutoff. Retrieval now checks at most eight candidates, with PostgreSQL authorization before evidence use. The final selection still allows only three excerpts and 1,800 evidence characters; every source chunk is bounded to 1,500 inspected characters. A second failure selected title-heavy vendor prose for a round-basin question. Product sentences describing features, materials, construction, or included parts now receive priority. The original narrow Bongio rule still skips the chat model when supported; other supported company questions generally call Ollama.

These are focused lexical/selection improvements, not a general semantic answerability or polished-language solution. No reranker, hybrid index, paid model, training, or background queue was added.

## Verification

| Check | Result |
| --- | --- |
| Full backend suite | **274 passed**, two opt-in live tests skipped, one existing dependency deprecation warning |
| Focused coverage/evaluation/answer/index tests | **116 passed** |
| Expanded evaluation before final fixes | 23/25; supported source hits 11/12 |
| Expanded evaluation after fixes | **25/25**; supported source hits **12/12** |
| Live company cases | **16/16** |
| Isolated trust controls | **8/8** |
| General education routing-only check | **1/1** |
| Original seed baseline | **7/7** |
| Repeat coverage import | All eight sources/twelve chunks skipped |
| Final corpus inspection | Eight public company sources, one staff test source; all ready; 38 points |

The expanded runner uses the role-filtered retrieval, PostgreSQL authorization, and answer components used by the company API. It checks expected source/content, citation provenance and markers, unsupported policy/current price/current stock/delivery abstentions, and records safe service failures as failures. Synthetic SQL controls cover injection, contradictory evidence, admin visibility, unregistered/disabled/failed sources, and stale generations; they never enter live Qdrant. The routing-only case does not measure general-model answer quality.

Across the sixteen live cases, median latency was **8.70 seconds**, and nearest-rank p95 was **18.69 seconds**. Eleven live cases called the chat model; supported direct-brand cases and abstentions may skip it. These are one-run observations on this CPU laptop, not a traffic benchmark or agreed response-time target. Existing real-service update/removal/upload lifecycle evidence comes from Steps 3/4; the two opt-in lifecycle tests were not rerun for this checkpoint.

Local, Git-ignored JSON evidence:

- `data/extracted/phase5_full_quality_audit.json`
- `data/extracted/phase5_coverage_import.json`
- `data/extracted/phase5_coverage_repeat.json`
- `data/extracted/phase5_coverage_evaluation.json` (before final candidate/priority fixes)
- `data/extracted/phase5_coverage_evaluation_after.json` (final)

## Reproduction

From the project root:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.coverage
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.coverage --audit-all
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.coverage --apply
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_coverage
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests
```

The first two commands are offline audits. Apply creates a durable job and normally skips the current batch. Evaluation needs local PostgreSQL/Qdrant/Ollama; run it separately from other model workloads. Optional `--report` writes a new JSON file and refuses overwrites. Saved crawler data is ignored by Git; use the extraction instructions in README on a fresh environment, then audit a changed snapshot and update its manifest/checks deliberately.

## Limits and next phase

The approved descriptive corpus is a selected eight-document slice of 1,008 saved records. It excludes FAQ transaction/policy promises, changing price/stock material, contact/address assertions, and unverified problematic specification examples from this batch. The automatic checks do not certify other data as accurate. The interview PDF is test data, not Sardars product knowledge. Company-specific claims still need relevant authorized evidence, and `company_data_verified` remains false.

The evaluation is developer-authored, in English, and covers known examples. Paraphrases, multi-product comparisons, contradiction handling, instruction attacks, lexical false abstentions, style, multilingual behavior, and larger-corpus ranking still need broader measurement. Scanned PDFs/OCR, DOCX/spreadsheets, retention cleanup, automatic synchronization, and the frontend upload screen remain future work. Clear general education still routes to model knowledge instead of automatically consulting uploaded files.

Next is Phase 6: an explicit validated read-only tool registry and controlled company-database access. Define authoritative ownership, IDs, permissions, and freshness before claiming current prices/stock. LLM tool calling is **not implemented** by Step 5.
