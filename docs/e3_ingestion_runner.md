# E3 — ingestion runner decision

Recorded 2026-10-19. E3 selected **one dedicated PostgreSQL-polling worker** for the local Compose stack. The existing inline runner remains available for `scripts/dev.sh` and historical CLI workflows through `SARDARS_INGESTION_RUNNER=inline`; `compose.local.yaml` sets `worker` for both API and worker. No Redis or Celery dependency was added.

## Baseline and choice

Before E3, authenticated file and URL submissions extracted in a bounded subprocess, saved an `ingestion_jobs` snapshot, and indexed before the HTTP response. One request per API process could ingest; another received HTTP 429. The extractor had a 30-second wall limit and the indexer a configured 300-second budget, so the request could remain open through both. Retries were explicit and used a three-attempt fenced lease. There was no API sitemap crawl; E4 owns that feature.

Controlled local probes, without inserting data into E1 RAG:

| Probe | Observation |
| --- | --- |
| 2.4 KiB company-profile Markdown extraction | 455 ms, 2,372 text characters |
| 153 KiB, ten-page saved PDF extraction | 2,273 ms, 14,891 text characters; parser child peak RSS about 52 MiB |
| Synthetic 1,000/20,000-byte text extraction | 404/498 ms; 100 KiB sample was correctly rejected by extracted-text limits |
| Saved-crawl sample of ten descriptive records | 19 chunks, 14.6 KiB bounded job snapshot, 1.1 ms local preparation; no embeddings |
| Direct local Ollama embed, one/four controlled excerpts with unloading | 5.7/17.6 seconds; model load and CPU variance affect these single observations |
| Resident embedding-model resource sample | Worker idle about 63 MiB, API about 80 MiB, Ollama about 1.26 GiB container memory; `ollama ps` reported a 1.4 GB model. The sampled CPU percentages were taken after the request and are not peak utilization. |

Synchronous processing keeps an HTTP request open across the model work and rejects a second overlapping ingestion request. A dedicated worker removes this bottleneck for the current single-API, single-worker local workload. Celery would provide broker-based dispatch and broader scaling but would add Redis, another durability boundary and operational failure modes without a measured need. Reassess if E4's real batch throughput, multiple workers, or recovery requirements exceed this runner. The saved-crawl preparation result is not a live sitemap benchmark; E4 must measure the new crawl separately.

## Resulting flow

The API authenticates and validates the submission. For a file it writes a bounded original to the shared uploads volume; for a URL it records the validated reference. It commits a `pending` PostgreSQL job and returns HTTP **202** with `job_id`. The worker polls for the oldest pending or expired-lease job, claims it with a row lock and run token, extracts the file or URL, and stores the resulting fixed document snapshot in the job before indexing. A failed URL job with a stored snapshot retries that same content. The worker then reuses the existing staged PostgreSQL/Qdrant publication, source visibility checks, generation fencing, point verification and bounded cleanup. One worker processes one job at a time. The API's authenticated `GET /api/v1/ingestion/jobs/{job_id}` shows progress and safe errors; `POST .../retry` requeues a permitted failed or expired job, retaining the three-attempt limit. Source removal is hidden from retrieval before asynchronous vector cleanup starts.

The database is the durable queue. A stopped worker leaves pending jobs for restart; an interrupted processing job is reclaimable after its lease expires. An old run token cannot publish after replacement. An account or source permission change is checked before extraction and before publication. No raw document text, credentials or run token appear in the job-status response. Product SKU, price and stock continue to come from PostgreSQL at request time.

## Verification and limits

- Focused ingestion and saved-crawl tests: **102 passed, one opt-in skipped**. The final complete backend suite: **617 passed, four opt-in skipped** with `SARDARS_DB_PORT=15432`; an initial full run had one readiness failure because `.env` points to the deliberately stopped old database on port 5433. Subsequent full reruns passed without changing `.env`.
- An opt-in test against a disposable PostgreSQL schema passed queueing, expired-lease recovery, update and immediate removal visibility; it deleted the schema afterward. Ollama and Qdrant calls in that test were mocked.
- Compose rebuilt the API image and started the new worker. Both containers received `SARDARS_INGESTION_RUNNER=worker`; the API and database were healthy and the worker stayed running. The E1 database retained **0 ingestion jobs, 0 source registrations and 4,983 products**, and E1 Qdrant retained **0 points**. No Sardars document was ingested into E1.

The worker has process-local single-job concurrency and polls once a second. It does not yet expose an aggregate batch-progress view or crawl a sitemap; E4 will provide the submission UI and bounded crawl. A worker crash during a job waits for the lease to expire before automatic recovery. URL fetching creates the fixed snapshot on its first worker attempt; a crash before that snapshot is saved may fetch the URL again on retry, while a saved snapshot is reused. Original-file retention and orphan cleanup need operational review as the E4 upload volume grows. The opt-in PostgreSQL test used mocked vector/model services, so it does not establish live end-to-end answer quality or E1 completion.

To inspect the local runner:

```bash
docker compose -f compose.local.yaml ps api worker
docker compose -f compose.local.yaml logs --tail=100 worker
```

After a permitted file/URL request returns `job_id`, poll `GET /api/v1/ingestion/jobs/{job_id}` with the same Bearer token. The host-only `scripts/dev.sh` workflow still uses inline processing unless `SARDARS_INGESTION_RUNNER` is changed and a worker is started against its database.
