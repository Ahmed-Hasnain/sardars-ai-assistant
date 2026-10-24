# E4 real-data evaluation — 2026-10-21

This checkpoint measures the admin-ingested corpus without importing, retrying, removing, restoring or reindexing sources. It adds an operator evaluation CLI and frozen questions, not a new application answer path. E5 answer/chunking changes and E1 restart/restore checks have not been performed.

## Reproducible scope

The starting Git revision was `7b01dce92d9292ec2916ac1ac740e362bfbc9420`, with a clean working tree. The running image's application Python files (excluding evaluation utilities) match the workspace. The current local model is `qwen3:4b-instruct-2507-q4_K_M` (digest `cf900a341a8dbe441efee29eafb80d74e8b65e1295ebe8c1da37fa6d7b50e747`); embeddings remain `qwen3-embedding:0.6b`, 1,024 dimensions. The API uses a 300-second answer budget and 330-second Ollama limit. API, worker, web, PostgreSQL, Qdrant and Ollama were inspected live; migration revision is `f2c4b811a6d0`. The 4,983 product rows remain intact.

Detailed internal reports are under Git-ignored `data/extracted/e4_20261021/`. They contain source identities and answers and should remain internal. Each evaluation saves case hashes, model settings, SQL fact/authorization fingerprints and complete Qdrant payload/vector fingerprints before and after. Later runs also record the application Python hash. All completed runs must report `data_stable: true`. `runtime.json` records model digests and the running-image/workspace comparison.

## Sources, provenance and job outcomes

All **991 registrations are active, ready and staff-visible**: 950 product pages, 13 company/project pages, 25 articles and three text uploads. Qdrant contains **5,825 points**. Every source's original-file checksum, published snapshot checksum and expected chunk text/count matched. No orphan or registry-rejected points were found; no two registered sources have identical full-text checksums. This does not rule out overlapping passages or semantically duplicated research.

| Uploaded source | Chunks | Authority and limits |
| --- | ---: | --- |
| Sardars Complete KB | 293 | Admin-supplied research, mixing observed records and inherited references; not blanket verification of every claim or date |
| Sardars Social Media Research | 54 | Admin-supplied attributed observations dated 2026-10-20; no authenticated account export or current commercial authority implied |
| Sardars Customer Q and A | 285 | 250 curated anticipated questions and qualified response seeds, not measured customer frequency or an approved policy system |

Website and upload source authorization permits internal retrieval. PostgreSQL remains the application authority for exact SKU, price and database stock, with observation/provenance metadata; currency, external synchronization, reservations and sellable availability remain unverified. Research warnings and inherited-record status are currently text within chunks, not record-level eligibility/freshness filters. Returned file citations identify the supplied file; they do not independently certify its embedded external references.

There are **1,161 jobs: 997 completed and 164 failed**, with none pending/processing. The completed root crawl discovered 1,150 pages and queued 1,150 children: **988 completed, 162 failed**. It took 26,021.5 seconds (7 h 13 min 41 s) from parent creation to final child completion. Failure groups are:

- 141 child pages: no usable descriptive text;
- 19 child pages: fetch failed or redirected;
- two child pages: other extraction/input failures;
- two earlier sitemap parents: rejected ranged XML references, with zero children.

These are stored failure outcomes, not fresh refetch diagnoses. Representative references include `/products/1784` (no text), `/products/oclock-long-spout-basin-mixer-clic-clac` (fetch/redirect), and `/products/logic-standing-kitchen-mixer-pull-out-spray-pakistan` (other extraction failure). No failed job was retried during this checkpoint. The parser deliberately refuses empty descriptions and redirects; a failure does not prove that a page contains useful missing evidence.

Across 995 completed import jobs, latest-attempt execution median/p95 was **8.26/119.15 seconds**, and creation-to-latest-start queue delay median/p95 was **7,394.75/24,684.46 seconds**. Queue delay includes pauses/restarts and prior attempts; it is not continuous worker wait measured by a scheduler. The serial worker sustained this workload, but the seven-hour crawl is a real throughput limitation. These observations do not establish that adding Celery would accelerate CPU embeddings.

The earlier remove/restore jobs and FAQ replacement remain in the durable ledger. The FAQ refresh preserved source identity, indexed 285 chunks and deleted 270 old chunks. This checkpoint verified the resulting state, rather than replaying those mutations.

## Answer baseline and upload comparison

The original frozen 21-case file is retained as `backend/app/evaluation/e4_cases_baseline.json`; the original `answers.json` also stores its definitions and hash. It covers each upload, exact FAQ questions and paraphrases, website evidence, both roles, and six unsupported/current claims. These are engineering probes, including research-document questions, not a representative sample of observed staff traffic. The default `e4_cases.json` was later revised for the qualified current-rating answer described below; the table remains the original pre-change baseline.

| Measurement | Current corpus | Same corpus with the three uploads excluded before ranking |
| --- | ---: | ---: |
| Strict case passes | 13/21 | 8/21 |
| Expected source in selected evidence | 15/15 | 3/15 |
| Requested answer phrases | 8/15 | 3/15 |
| Expected cited source | 8/15 | 2/15 |
| Marker/authorized-source consistency | 21/21 | 21/21 |
| Routing and service checks | 21/21 | 21/21 |
| Safe unsupported-claim abstentions | 6/6 | 6/6 |
| Live median/p95 | 0.930/49.832 s | 0.677/52.778 s |
| Chat-model calls | 3 | 3 |

The comparison is a **current-corpus exclusion experiment**, not a reconstructed historical pre-ingestion run. Exclusion happens inside Qdrant before its top-32 limit; permissions, reranking, prompts and model are preserved. No saved comprehensive pre-upload answer report exists, so no historical before/after score is claimed. The earlier documented five-question FAQ failure analysis is historical evidence only.

Five checks improve with uploads: alias identity for staff and admin, manufacture, disputed history and European-origin caution. This is four distinct questions plus a role repeat. Their returned FAQ answers preserve the qualifications. The current run's three model calls took 51.68, 14.43 and 49.26 seconds; the overall subsecond median hides that generation cost. These serial laptop observations are not business latency targets.

All six unsupported cases abstain without citations: current hours, current rating, return policy, delivery promise, charity hospital and CEO. Citation consistency checks provenance/markers, not semantic entailment. The following failures remain frozen, without relaxing assertions to improve scores:

| Case | Observed outcome | Diagnosis |
| --- | --- | --- |
| Professionals FAQ | Abstention with the source retrieved | Claim guard treats the verb `address` in “materials address homeowners” as an address fact |
| Complete-bathroom FAQ | Abstention with source retrieved | Guard rejects the answer's qualified discussion of availability |
| Slogan FAQ | Cites the KB slogan sentence but omits the requested qualification | FAQ guard rejects `stock`/`warranty`; fallback gives a partial answer from another source |
| Alias paraphrase | Abstention despite source hit | Exact FAQ match fails; conservative sentence prerequisite finds no evidence |
| History paraphrase | Returns `CORRECTED ANSWER SEEDS How old is Sardars?` | Unlabelled KB question heading passes lexical selection; generation/fallback preserves a non-answer |
| Social craftsmanship | Abstention despite source hit | Sentence-level term gate misses the relevant passage |
| Social authenticated export | Abstention despite source hit | Relevant evidence is available, but no acceptable sentence survives selection; the safe non-export statement is not composed |
| Storage | Useful Shower Niche 8283 description from another authorized product page | Strict expected-URL mismatch, distinct from a fabricated product or absent evidence |

The FAQ audit finds **250 pairs, 136 complete answers passing answer-text guards, and 131 passing both question and answer guards**. All 136 indexed extractor candidates match complete snapshot answers; no partial answer candidate was found. This is an offline upper bound without ranking, scope routing or live answers for all 250 questions. It confirms the earlier 131/250 limitation rather than claiming broader FAQ coverage.

## Retained regression suites

The same retained case assertions were rerun against the **current E4 corpus**, not restored into the original E2 namespace. Corpus composition, later prompt changes and FAQ behavior differ from the historical reference; the cross-period comparison does not isolate one cause.

| Suite | Current result | Retrieval / trust / exact facts | Live median/p95 |
| --- | ---: | --- | ---: |
| Chat | **25/26** (17/18 live, 8/8 isolated controls) | 4/4 source hits; 6/6 independent price/SKU checks; 7/7 stock checks; all 18 route/tool checks pass | 0.245/20.954 s |
| Full-site | **31/40** (22/31 live, 8/8 controls, 1/1 routing) | **19/24** expected-source hits | 21.015/73.985 s |
| Seed, staff-role search | **6/7** | Same authorized alternative Shower Niche citation is the sole failure | Per-case times saved; no aggregate latency claim |

The historical E2 reference remains 26/26, 34/40 and 7/7 on its original corpus. **No six-case regression closure is claimed.** On the current corpus, `mirror` and `mirror_paraphrase` pass, while `seat_materials`, `fittings_materials_article`, `sustainable_toilets_article` and `maintenance_article` still fail. Newly failing versus that reference are `storage`, `garden_residences`, `omsa_hy410`, `omsa_hy524` and `compact_basin_spec`. Frozen source/phrase checks were not changed or rescored.

All 24 expected live full-site sources are registered/ready and contain the expected answer phrases in their stored snapshots. The 162 failed page imports therefore do not explain these particular failures. Additional layer diagnoses:

- `storage`: an authorized, relevant sibling Shower Niche page; strict URL mismatch in all three suites.
- `seat_materials`: the correct source is selected, but answer evidence comes from the sibling seat-with-legs product's generic durability sentence rather than the requested material list.
- `garden_residences`: expected page is not selected; a FAQ project list becomes a non-answer about the named project.
- Three article cases and `compact_basin_spec`: expected pages are not selected despite stored supporting text; the result safely abstains.
- `omsa_hy410` and `omsa_hy524`: correct source citations, but evidence selection returns a trailing dimension/variant fragment instead of the descriptive freestanding-tub sentence. These are answer usefulness/selection failures, not evidence that the returned numbers were invented.

A separate eight-case retrieval probe confirms the failing boundary (ranks count chunks, not distinct sources):

| Case | Expected page in authorized top 32 | In selected top eight |
| --- | ---: | ---: |
| Seat materials | 1 | 1 |
| Garden, three articles, compact basin size | Absent in every case | Absent |
| OMSA HY410 | 2 | 1 |
| OMSA HY524 | 3 | 1 |

The seat case has the complete correct materials sentence among three matching excerpts; the answer chooses the shorter sibling-product sentence. The bathtub matches contain only the trailing specification fragments. These require different evidence-selection fixes from the five semantic top-32 misses. Full matches and source identities are saved in `retrieval_diagnosis.json`; stored-source phrase presence is saved in `retained_source_coverage.json`.

### Focused FAQ guard follow-up, 2026-10-21

The exact FAQ question about a **current Google rating** had its complete answer in selected evidence, but the broad changing-fact question check returned the generic fallback before exact FAQ handling. The file itself says no matched live Google listing was refreshed and its earlier rating must not be quoted as current. The answer path now permits only an exact approved FAQ whose answer explicitly says a live value was not verified, contains no numeral, and makes no `currently`/`today`/`latest` assertion. It renders a fixed cited non-verification explanation rather than trusting source prose to state a value. Current price, stock, opening-hours and unsupported current claims remain guarded; this does not give the LLM authority over live facts.

The original case definition is preserved in `e4_cases_baseline.json`. The default `e4_cases.json` now expects the cited qualification for this one case. Authenticated local API checks passed for the rating question, the unchanged ratings-difference answer, and continued opening-hours abstention. The post-change 21-case replay in `post_qualified_faq.json` remained **13/21**, made three model calls, and reported unchanged SQL and Qdrant fingerprints. Compared case-by-case with the original `answers.json`, only `current_rating` changed answer text; every case kept its original pass/fail result. The eight other E4 failures remain open. One model call in the serial replay took 230.7 seconds, so its 0.819/55.932-second median/p95 does not represent a guaranteed response target. The backend suite passed **656 tests, four skipped**; this follow-up did not reindex sources or reset volumes.

## Authentication and browser evidence

Using temporary admin and staff accounts against the running API, anonymous `/ask` and protected-file reads returned **401**. Both roles logged in, received their actual role from `/auth/me`, got HTTP **200** for an alias question with the same qualified FAQ answer and an authorized citation, and downloaded the exact original FAQ file with its checksum intact. A forged `role` request field returned **422**; staff sitemap submission returned **403**; logout revoked the token (**401** on reuse). Temporary users and sessions were removed; no source, product or index data was changed. The two measured HTTP answer calls took 771 and 674 ms, respectively; they were FAQ fast-path calls, not model-generation samples.

A real Chrome session used the running web proxy and API, with no mocked requests. Temporary-admin login, the Knowledge sources list, completed sitemap progress (**988 completed, 162 failed**), protected FAQ download, an SSE cited answer, history restoration after refresh, and logout all passed. The browser reported zero horizontal overflow. Its displayed download filename came from the source title (`Sardars Customer Q and A.txt`). The temporary account and conversation/session records were cleaned up. This exercises actual application-enforced auth and role behavior; there was no admin-only source in this corpus to compare against staff visibility. Eight retained synthetic trust controls separately tested revocation and prompt-injection boundaries.

## Verification and replay

The final backend suite passed **654 tests, 4 skipped, 1 existing Starlette deprecation warning** in 98.78 seconds. The new E4 evaluation tests passed as part of that run. The read-only inventory and all completed answer suites reported unchanged SQL and vector fingerprints; no bulk source reindex or volume reset was performed. `http.json`, `browser.json`, `runtime.json`, `inventory_final.json`, `answers.json`, `without_uploads.json`, `retained_chat.json`, `retained_full_site.json`, `retained_seed_staff.json`, `retrieval_diagnosis.json`, `retained_source_coverage.json` and `backend_tests.txt` hold the detailed evidence.

From the repository root, with the existing local stack running, choose a new report directory/name:

```bash
mkdir -p data/extracted/e4_replay

docker compose -f compose.local.yaml run --rm --no-deps --user 0:0 \
  -v "$PWD/backend/app:/app/app:ro" \
  -v "$PWD/data/extracted/e4_replay:/reports" \
  api python -m app.evaluation.run_e4 --suite inventory --report /reports/inventory.json

docker compose -f compose.local.yaml run --rm --no-deps --user 0:0 \
  -v "$PWD/backend/app:/app/app:ro" \
  -v "$PWD/data/extracted/e4_replay:/reports" \
  api python -m app.evaluation.run_e4 --suite e4 --report /reports/answers.json
```

The container operator is used to verify protected originals and write the mounted report directory; API authentication is tested separately. The code mount is read-only. Reports refuse overwrite. Exit 1 means a measured case/integrity/stability failure, not an instruction to reset data. Repeat the answer command with `--exclude-uploads` and a different report name for the comparison; use `--suite chat`, `--suite full-site` and `--suite seed` for retained cases. `seed` explicitly adapts search to staff visibility: the original seed CLI searches only `public`, while this entire corpus is `staff`. Its original public-only score would measure a visibility mismatch rather than answer quality.

Run model evaluations serially, without ingestion or another model benchmark. The ordinary backend checks use the existing isolated database:

```bash
SARDARS_DB_PORT=15432 PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests
```

## Phase boundary

The E4 **measured real-data checkpoint is complete** for the current internal corpus: actual imports, failures, source integrity, authorized retrieval, answers, citations, HTTP/browser access and latency have recorded outcomes. This is the phase's practical acceptance with an explicit method substitution: comprehensive answers were not saved before the user uploaded sources, so the controlled same-corpus upload exclusion is the comparable answer baseline. It cannot establish a historical before/after effect. The previously implemented sitemap/update/removal controls were not replayed destructively against the user's data. An admin-only live source is absent; direct cross-role visibility for that tier remains covered by existing tests, not this real corpus.

E4 completion does **not** close the six retained retrieval/evidence failures. On the current corpus four of those six still fail, two now pass, and five other retained cases fail. It also does not establish independent human review of every answer, freshness of attributed research, multilingual quality, or a business latency target. The next small runnable checkpoint is the deferred **E1 data-backed container acceptance**: verify migrations and service health, then take a scoped backup of existing volumes and catalog identities before a controlled restart and restore rehearsal that preserves the live data. Record before/after checksums, auth/product/RAG/browser flows and latency. E5 can then compare structure-aware chunking and a bounded grounded model-answer path against this frozen E4 baseline, without speculative full reindexing.
