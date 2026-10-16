# Phase 5 Step 6 — full saved-crawl coverage

Completion follow-up, 2026-10-15: **full-site ingestion and repeat verification finished** for all 999 eligible website sources/3,739 chunks across 309 batches. Nine whole-source exclusions account for the remaining saved records. Replay verified/skipped all 999 sources. A later PostgreSQL smoke check found all 999 public registrations active/ready. The expanded evaluation passed **28/40**, with **15/24** supported-source hits; the original seed regression passed **4/7**. This leaves retrieval/evidence/evaluation follow-up open and does not declare full answer quality complete. See [the observed completion outcomes](phase5_full_site_completion_status.md) and local `data/extracted/full_site_completion_evaluation.json` / `full_site_continuation.log`.

The twelve expanded failures include one service/input failure and expected-source/usable-evidence misses. The brand-list seed answer cited a different authorized article and failed its strict expected-source assertion; the Bongio definition abstained, and storage returned another article without the expected Shower Niche evidence. Distinguish alternate valid citations, evidence quality and service failures before changing retrieval architecture. The eight isolated trust controls passed. Phase 6's direct source-status tool is independent of these unresolved answer regressions.

The remainder records the **historical partial checkpoint** from 2026-10-15, before completion. Its 39-source counts and 37/40 score are not the final full-corpus outcomes. The earlier Step 5 completion described the limited descriptive pipeline and eight-document benchmark. Price/stock tools and current business promises remain pending authoritative ERP access and rules.

## Prepared scope and live coverage

| Measure | Verified checkpoint |
| --- | --- |
| Original saved crawl | 1,008 records: 13 pages, 25 articles, 970 products |
| Eligible final prepared descriptions | 999 documents / 3,739 chunks |
| Derived documents among eligible records | 670 |
| Whole-source exclusions | 9, each with a reason |
| Final plan | 309 serial batches; six completed, 303 not yet processed |
| Sources visited by the final ledger | 30 / 72 chunks; initial pass skipped 27 and indexed 3; repeat skipped all 30 |
| Live ready website corpus, including pilot/previous imports | **39 sources / 83 chunks**: 10 pages, 10 articles, 19 products |
| Separate staff interview test PDF | 1 source / 26 chunks, unchanged; not Sardars authority |
| Total live collection | **109 points**, 40 active/ready sources |
| Exact live payload/vector/generation/point-set verification | **40/40 sources** |
| Role authorization | Staff/admin: 109 permitted points; public/unknown: zero |

The final ledger's completion count differs from live coverage because earlier pilot imports and the original benchmark also registered sources. Thirty-six ready website sources match the final prepared checksum. Cosmetic Mirror, Square E Corner Basin and Wall-Mounted Seat Lift-Up still hold their original descriptive versions; their final-plan duplicate cleanup is pending. A pending ledger entry is not proof that its source is absent from Qdrant. Conversely, a prepared file is not indexed coverage. There are 960 eligible URLs with no registration yet, plus those three prepared-version replacements.

## Preparation and provenance

`app.ingestion.descriptive_site` retains exact original text spans. It omits changing claims, transaction/contact/promise passages and repeated segments, keeping descriptive materials, features, identifiers and specifications where available. Sentence and compact-field boundaries let a warranty label be omitted while retaining a following article number or dimension. Short/SKU-only descriptions remain eligible. Different product URLs keep separate identities even when their prose is identical. The original crawl is never rewritten, and uncertain specifications are never corrected by inference.

`plan.json` records the original/prepared checksums, original titles, exact retained/omitted character offsets, omission reasons and fixed batch membership. A derived title uses an exact descriptive clause from its original title. Prepared documents and Qdrant payloads carry `derivation.method: descriptive_spans_v1` and the original content checksum. Citations optionally expose `content_derivation` and `original_content_sha256`. Source IDs/URLs and original 2026-10-12 fetch times remain intact; import/replay does not establish freshness.

The nine exclusions are conservative processing decisions, not findings that entire sources are false or permanently unusable:

| Saved source | Reason |
| --- | --- |
| `/pages/contact` | Contact/hours source outside verified current facts |
| `/pages/faqs` | Transaction/policy/promises source |
| `/pages/our-projects` | Navigation-only source |
| `/blogs/news/jacuzzi-s-price-in-pakistan` | Dedicated price article |
| `/blogs/news/sardar-s-sanitary-fittings-sale-upto-50-off` | Dedicated promotion article |
| `/blogs/news/best-ceiling-fan-price-in-pakistan` | Dedicated price article |
| `/products/bathroom-cabinet-price-unit` | No safe descriptive title clause under this filter |
| `/products/bisk-pvc-bath-mat-35x70-cm` | No descriptive body remains beyond its repeated heading |
| `/products/axent-wall-hung-shower-toilet-for-modern-bathrooms-in-pakistan` | Suspected mislabeled water-pressure specification; retained original, no correction |

The previous 302-record flag audit was not used as a blanket exclusion list. Price-oriented product URLs can still contain usable descriptions. The rules can remove useful context or miss defects; retained text is source evidence, not certified product accuracy or current availability.

## Resumable execution

`app.ingestion.full_site` prepares offline and applies serial jobs through the existing source lifecycle. Small examples from pages/articles/products run first, followed by the rest. The target is five sources/twenty-four chunks per job; a longer source runs alone, with a sixty-four-chunk hard limit. The final plan's largest job is twenty-six chunks. Each job gets a fresh deadline; this installation uses 600 seconds and two chunks per embedding request. The CLI keeps one model warm for 120 seconds between requests. The runner makes serial model requests. No queue service, scheduler, schema migration or paid model was added.

The atomic ledger records pending/processing/imported/skipped/rejected/failed sources, durable job IDs and results. A file lock prevents concurrent runners on the same state. Job identity is saved before idempotent database admission, so interruption after enqueue or database completion can reconcile with the same snapshot. Completed ledger batches are not rerun on ordinary resume; `--verify` checks them through the lifecycle importer. Failure stops the run, preserves prior completed batches and hides unpublished generations. Explicit retry uses the existing job's bounded three-attempt policy and lease fencing. Changed snapshots/plans are refused; prepare a new state instead. Omitting a source from a new plan does not implicitly delete its existing registration; use the existing explicit removal workflow when needed.

The first five-source pilot job indexed eight chunks and skipped one source in 145.18 seconds. The next six pilot batches took 89.45, 57.77, 205.24, 206.84, 112.92 and 257.24 seconds. Final-plan reconciliation skipped twenty-seven sources and indexed three compact SKU sources. These observations establish a working bounded path on this laptop; they do not benchmark sustained throughput or prove the remaining 303 jobs will fit every deadline under other workloads.

## Answer/retrieval findings

The first forty-case run passed **33/40**, with supported-source hits **21/24**. All eight isolated trust controls and the general-routing check passed. Failures were investigated at retrieval/evidence/output level:

- Generic brand headings displaced concrete brand lists during evidence selection. Concrete listing sentences now receive priority.
- The model emitted only `[1]` for a storage answer. Empty text passed the old substring check; citation-only output now falls back to actual evidence. Product-discovery answers preserve product identity.
- Bongio's raw semantic query ranked eight unrelated short product records ahead of the company profile. A narrow profile lookup now reserves at most two of the existing eight candidate slots for the configured About Us source, with the same role/approval filters and PostgreSQL authorization. The direct rule still requires source text calling Bongio a brand; it stores no brand fact and does not bypass disabled/unpublished-source checks. `SARDARS_BRAND_DEFINITION_PROFILE_URL` configures this hint; blank disables it.
- Source-grouped search did not recover the missed sources and was not adopted. [Qdrant's grouped-query API](https://api.qdrant.tech/v-1-19-x/api-reference/search/query-points-groups) was used only for the diagnostic.
- Qwen's documented query-only instruction recovered Bongio's source but lost article hits in this diagnostic; no global query-format change was adopted. [Qwen model guidance](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) describes query instructions and unprefixed documents.
- Roman Grove had a valid sourced “refined character” description; the new test incorrectly insisted on “sophisticated.” Its final assertion accepts either documented description while still requiring Roman Grove's authorized source and citation.
- Three article questions still expose larger-corpus limitations: the materials/tips and dual-flush articles are outside the candidate set; the maintenance article is retrieved by source but its non-answering tail chunk wins. Source-level recall alone therefore overstates usable-evidence recall. These are safe false abstentions, not evidence that those documents were not indexed. They remain open retrieval/chunking work; no reranker, hybrid index or broad architecture change was added.

Final verified results:

| Check | Result |
| --- | --- |
| Final backend suite | **302 passed**, two opt-in integration tests skipped; existing dependency warning |
| Focused profile/answer/evaluation/authorization checks | **40 passed** |
| Final forty-case evaluation | **37/40**: 28/31 live, 8/8 trust controls, 1/1 routing-only |
| Original twenty-five-case subset in the final run | **25/25** |
| Supported-source hits | **22/24**, with the non-answering maintenance tail caveat above |
| Original seed regression | **7/7** |
| Completed final-plan batch replay | **30 sources/72 chunks skipped**; zero indexed/deleted chunks |
| Replay of all published website snapshots | **39 sources/83 chunks skipped**; zero indexed/deleted chunks |
| Exact live source/vector/generation/point-count checks | **40/40 sources**, including the unchanged test PDF |

The final live median was **30.93 seconds**, nearest-rank p95 **52.88 seconds**. The preceding run's median was 26.97 seconds and p95 39.80 seconds. CPU contention and different model outputs make these one-run observations, not proof of a latency regression or improvement. The final score includes the explicitly described Roman Grove assertion correction; it is not a comparison of identical assertions. Three article questions remain failures and Phase 5's full-site exit remains unmet.

 The forty-case set consists of 31 live cases, eight synthetic controls and one routing-only case; it is English and developer-authored. It does not measure pending records, general-model answer quality, multilingual behavior or comprehensive adversarial robustness. Live latency is sensitive to CPU contention and is not an agreed response-time target.

## Local evidence and continuation

Git-ignored evidence includes `data/extracted/full_site_checkpoint_registry.json`, `full_site_checkpoint_verification.json`, `full_site_checkpoint_evaluation.json`, `full_site_checkpoint_evaluation_after.json`, `full_site_grouping_diagnostic.json`, `full_site_instruction_diagnostic.json`, `full_site_checkpoint_repeat.json` and `full_site_all_published_repeat.json`. The final state is `data/extracted/full_site_descriptive`; earlier pilot directories are retained as execution history. The separate supplied company profile is still unindexed.

From the repository root:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.full_site
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.full_site --apply --max-batches 1
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.full_site --apply --max-batches 6
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_coverage --cases backend/app/evaluation/full_site_cases.json
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests
```

Default status is offline. On this workspace preparation already exists. On a fresh saved crawl, run `app.ingestion.full_site --prepare` first. Use a new `--state` directory for changed input/filter settings. Keep the original snapshot at its recorded path. `--apply --max-batches 1000` can advance the entire remaining plan serially, stopping on the first failure. Run model evaluations separately. Inspect a failed job with `app.ingestion.jobs --job JOB_ID`, resolve its cause, then explicitly use `app.ingestion.full_site --apply --retry-failed`. Do not replay the legacy raw eight-document manifest to manage this derived snapshot.

Full-site completion requires all suitable prepared versions to be ready and verified, repeat-import checks across that completed scope, and evaluation against the resulting corpus. This checkpoint does not meet that exit.


The remaining import was launched as a detached local serial command on 2026-10-15. Inspect `data/extracted/full_site_continuation.json` and `data/extracted/full_site_continuation.log` for its current status. It stops on import/verification failure, preserving durable job references; it does not retry failures automatically. After successful indexing it replays the completed plan and runs the expanded and original evaluations sequentially. Results go to `data/extracted/full_site_completion_evaluation.json` and, after those commands finish, `docs/phase5_full_site_completion_status.md`. These future outcomes are not included in the verified checkpoint counts above. Avoid starting another ingestion/evaluation workload while it runs.

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.full_site
tail -f data/extracted/full_site_continuation.log
```
