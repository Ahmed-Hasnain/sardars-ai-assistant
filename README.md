# Sardars AI Assistant

A self-hosted AI assistant for Sardars, initially intended for admins and internal staff. The current implementation has a FastAPI backend, PostgreSQL, Alembic migrations, revocable internal login, health checks, local-model chat through Ollama, and an approved-source Qdrant answer prototype.

## Local setup

Requires Python 3.12+ and Docker Compose. Local chat also requires Ollama. Run commands from the project root.

Copy `.env.example` to `.env` and replace `SARDARS_DB_PASSWORD` with a private random password before starting PostgreSQL.

Create the environment and install the recorded dependencies:

    python3 -m venv backend/.venv
    backend/.venv/bin/python -m pip install -r backend/requirements-dev.lock

Start PostgreSQL and apply migrations:

    docker compose up -d --wait db
    backend/.venv/bin/alembic upgrade head

Create the first admin account. The command prompts for the password twice without echoing it or putting it in shell history:

    PYTHONPATH=backend backend/.venv/bin/python -m app.auth.create_user --email you@example.com --role admin

Start the API in another terminal:

    backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

Check http://127.0.0.1:8000/api/v1/health for API liveness and http://127.0.0.1:8000/api/v1/ready for database readiness.

Run the smoke tests while PostgreSQL is running:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests

Stop PostgreSQL with `docker compose stop db`; its data is retained. Keep `.env` and `backend/.venv/` out of Git.

For daily development, run `./scripts/dev.sh` from the project root. It starts PostgreSQL and Qdrant through Docker Compose, applies pending database migrations, starts the installed Ollama system service if needed, runs FastAPI, and follows all four services' logs in one terminal. If Ollama is stopped, `sudo` may ask for your password. Press Ctrl+C to stop FastAPI and the log followers; the Docker containers and Ollama service remain running. Stop the containers later with `docker compose stop db qdrant`.

## Internal login and roles

The first account must be an admin. A local operator can create additional accounts with the same command and `--role staff` or `--role admin`; the command always prompts for a password. Passwords are stored as salted scrypt hashes. Login issues a random bearer token valid for eight hours; PostgreSQL stores only its hash. Logout deletes that session, and disabling a user or changing a role takes effect on the next request. Both roles may query the current approved public-site seed; only admins may call `GET /api/v1/admin/users`. Retrieval enforces source visibility for each role, but no real staff-only document has been indexed yet.

In Postman, send `POST http://127.0.0.1:8000/api/v1/auth/login` with JSON `{"email":"you@example.com","password":"your-password"}`. Copy the returned `access_token` into Postman's **Authorization → Bearer Token** field. You can then call `GET /api/v1/auth/me`, `POST /api/v1/chat`, and `POST /api/v1/ask`; `POST /api/v1/auth/logout` revokes the token. Do not put passwords or bearer tokens into a committed file. Keep the API bound to localhost during development; HTTPS, login rate limiting, and broader role-scoped source rules remain deployment work.

If a password or token is exposed, reset that account locally. This prompts twice for a new password and deletes all of the account's existing login sessions; log in again afterward. It does not put the password in shell history:

    PYTHONPATH=backend backend/.venv/bin/python -m app.auth.reset_password --email you@example.com

## Local-model chat

Install Ollama using its [Linux instructions](https://docs.ollama.com/linux), then download the small model used on this laptop:

    ollama pull qwen3:0.6b

With Ollama and the API running, send a request from Postman using the bearer token above. For a terminal request, paste the token into a silent prompt first so it is not recorded in shell history:

    read -rs -p 'Bearer token: ' SARDARS_TOKEN; printf '\n'
    curl -sS http://127.0.0.1:8000/api/v1/chat -H "Authorization: Bearer $SARDARS_TOKEN" -H 'Content-Type: application/json' -d '{"message":"Explain what a database is in one sentence."}'

`POST /api/v1/chat` uses a simple, conservative rule: clear educational questions such as “What is a database?” go to the general Ollama model; Sardars or ambiguous business questions use registered-source retrieval. The response has `route: general` or `route: company`. Company answers include numbered `sources` with `source_id`, title, Sardars URL, and `fetched_at`; unsupported company questions have no citations. General answers have no company sources and may include model token counts and duration. `company_data_verified` remains false because an authorized source does not prove that changing facts are current. The Ollama settings in `.env.example` default to `qwen3:0.6b` on localhost with `keep_alive=0` to unload the model after each request. This reduces memory use but adds model load time to each request.

## Public source extraction sample

The project owner supplied `https://sardarandco.com/sitemap.xml` and the text in `data/sources/company_profile.md` for the first public-source prototype. `data/source_inventory.md` tracks their provenance and the missing staff source. The sitemap extractor reads public pages, articles, and product descriptions. It skips quote/account paths, checks robots rules, stays on the Sardars host, waits between page requests, and omits product offer data such as price and availability. Its output is descriptive source material for review, not verified answers or a search index.

From the project root, extract one page, one article, and one product:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.public_site --limit-per-type 1 --output data/extracted/public_site_sample.jsonl

Each JSONL record includes a stable source ID, public visibility, pending review status, source type, URL, title, fetch time, content checksum, and extracted text. The output directory is ignored by Git. Inspect the records before increasing `--limit-per-type` (maximum 1500 per type). Chat uses only registered and indexed content, not the full extracted file. Step 4 below adds authenticated private-document ingestion.

A full public crawl was run on 2026-10-12 with `--limit-per-type 1500 --delay-seconds 0.5 --output data/extracted/public_site_full.jsonl`. It produced 1,008 review records; 142 product links did not yield useful text. The local audit is `data/extracted/public_site_audit.md`. Both files remain ignored by Git. Some descriptions and articles include changing claims despite excluding structured offer fields, so review them before any indexing or answer generation.

## Vector-search runtime

Pull the small local embedding model with `ollama pull qwen3-embedding:0.6b`. Its `/api/embed` response was measured at 1,024 dimensions on this laptop. Qdrant runs through the `qdrant` Compose service at `http://127.0.0.1:6333` with persistent storage. Collection `sardars_public_qwen3_embedding_06b_v1` uses 1,024-dimensional cosine vectors and contained twelve company website chunks plus twenty-six staff-visible interview-test chunks at the selected Step 5 checkpoint (38 total). See the full-site checkpoint below for later coverage. The collection name is retained from the original public seed; role/source permissions govern later content. On a new Qdrant volume, create the collection after starting the service:

    curl -sS -X PUT http://127.0.0.1:6333/collections/sardars_public_qwen3_embedding_06b_v1 -H 'Content-Type: application/json' -d '{"vectors":{"size":1024,"distance":"Cosine"}}'

The prototype selects the public About Us and Shower Niche records from `data/extracted/public_site_full.jsonl` into `data/extracted/rag_seed.jsonl`. After producing the full crawl described above, run from the project root:

    grep -F -e '"url": "https://sardarandco.com/pages/about-us"' -e '"url": "https://sardarandco.com/products/shower-niche-pakistan"' data/extracted/public_site_full.jsonl > data/extracted/rag_seed.jsonl
    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.chunking
    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.register_seed
    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.index_seed
    PYTHONPATH=backend backend/.venv/bin/python -m app.retrieval.search_seed --approved "What bathroom storage product does Sardars describe?"

`chunking.py` writes three 100-word-maximum chunks with 15-word overlap to `data/extracted/rag_seed_chunks.jsonl`. `register_seed.py` records the two already authorized URLs and their content checksums in PostgreSQL's `source_registrations` table; rerunning it does not reactivate disabled sources. `index_seed.py` requires active matching registrations, embeds the chunks, and upserts them with `review_status: approved`, `approval_basis: owner_authorized_source_for_internal_use`, and `prototype_only: false`. `search_seed.py --approved` embeds a question and prints ranked text, source URLs, and similarity scores. Its default mode is the old pending/prototype diagnostic filter and should now return no seed points. The local extracted files are ignored by Git and retain their original `pending` labels; authorization is applied when indexing. On 2026-10-13 the project owner authorized the supplied sources for internal use and chose source-level approval for future authorized admin/staff uploads and registered URLs. Company questions on `/chat` and explicit `/ask` now use the Phase 5 company coverage and other role-permitted indexed sources. The original two-document seed remains a regression baseline. The CLI scripts are a learning prototype, not a source synchronization workflow.

Before answering, `/ask`, routed company `/chat`, and the grounded-answer CLI compare each retrieved Qdrant point with its PostgreSQL source registration: source ID, URL, type, visibility, active/ready status, published generation, and content checksum must match. Unknown, disabled, or unpublished sources are excluded. Qdrant also prefilters visibility by the authenticated role. Both internal roles can use the current public seed; Step 4 supports staff/admin documents too. In DataGrip, inspect `public.source_registrations` to see authorized sources.

## Grounded-answer CLI seed

With Ollama and Qdrant running and the three seed points indexed, try:

    PYTHONPATH=backend backend/.venv/bin/python -m app.rag.answer_seed "Which brands does Sardars mention?"
    PYTHONPATH=backend backend/.venv/bin/python -m app.rag.answer_seed "What is Sardars' return policy?"

The first question should show an exact brand sentence from the About Us source with its URL; the second should say it cannot verify the policy and show no citation. This CLI filters for approved Sardars website chunks and uses a conservative question-term match to find source sentences before calling the local chat model. The evidence is capped at 1,800 characters. If the small model's answer or citation is unusable, it prints an exact matching source sentence. This is a two-document learning checkpoint: the term match can miss paraphrases and does not prove general answerability. The protected `POST /api/v1/ask` route uses the same company seed flow and accepts `{"message":"Which brands does Sardars mention?"}`. `/api/v1/chat` selects the company flow for that question and uses general Ollama chat for clear educational questions.

Run the RAG baseline after starting Ollama and Qdrant and indexing the approved seed:

    PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_seed

It checks five live questions: supported brand-list, Bongio definition, and storage answers against their source URLs, and uncited abstentions for missing return-policy and current-price facts. Two synthetic cases check prompt injection and conflicting warranty evidence without indexing either in Qdrant. The case file is `backend/app/evaluation/seed_cases.json`. The direct Bongio answer states only what the approved About Us source supports; it does not establish further facts about the brand. This small baseline does not establish general answer accuracy, adversarial robustness, or coverage of the full website.

## Phase 5 learning checkpoint — Step 1

Phase 5 was built in small runnable checkpoints; `PLAN.md` records their sequence. Step 1 prepares selected website documents from an existing crawler JSONL file. It needs no PostgreSQL, Qdrant, Ollama, login, or network access. It validates record integrity, not factual accuracy, source permissions, or freshness. Only explicitly selected documents are validated; the rest of the bounded extraction file is scanned for selection, not imported.

From the project root, preview the About Us document:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.prepare_site --input data/extracted/public_site_full.jsonl --url https://sardarandco.com/pages/about-us

The saved 2026-10-12 extraction should produce one document and two chunks. `--url` can be repeated for up to ten unique URLs. Preview both existing seed documents and save their prepared chunks to a new local file:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.prepare_site --input data/extracted/public_site_full.jsonl --url https://sardarandco.com/pages/about-us --url https://sardarandco.com/products/shower-niche-pakistan --output data/extracted/phase5_prepared_chunks.jsonl

Expect two documents and three chunks. Existing output files are refused rather than overwritten; omit `--output` to repeat a preview. The extracted text checksum and URL-derived source ID must match, timestamps must include a timezone, and selected records must use the current public crawler format. Identical duplicate records are deduplicated; conflicting records and missing requested URLs fail the preparation. Processing is limited to a 32 MiB input file, 5,000 lines, 256 KiB per line, 50,000 characters/10,000 words per selected document, and ten selected URLs.

The output stays in the Git-ignored extraction directory. Its legacy `pending` label does not impose a per-document approval queue or authorize retrieval. This command does not register sources or change the chat index. The next checkpoint adds controlled registration and indexing; file uploads and PDF parsing are later Phase 5 work. If the full saved extraction is unavailable, `data/extracted/rag_seed.jsonl` can be used as the input for these same two URLs; extraction commands above explain how to recreate the local data.

Run this checkpoint's focused tests:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_prepare_site.py

## Phase 5 learning checkpoint — Step 2

Step 2 adds a controlled import for the already owner-authorized public Sardars site. Run it as a trusted local operator with the project's `.env` and local-service access; it is not an authenticated upload endpoint. It revalidates the original extraction file and regenerates the same chunks as Step 1 so that whole-document checksums can be checked before writing. The saved prepared chunk file remains an inspectable staging artifact, not an authority for permissions or content integrity.

Start the development stack with `./scripts/dev.sh` in another terminal if it is stopped. Keep that terminal open. This starts the database, Qdrant, Ollama, and API and applies existing migrations. No new migration or dependency is needed for Step 2. The recorded Qdrant collection and embedding model must already exist as described above. `SARDARS_QDRANT_BASE_URL` defaults to localhost port 6333; `SARDARS_IMPORT_TIMEOUT_SECONDS` defaults to 300 seconds (maximum 600). Ingestion and retrieval share the recorded model/collection schema and service URLs.

Run the new tests from the project root:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_site_import.py backend/tests/test_site_index.py

Preview the registry checks for the same two documents:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.import_site --input data/extracted/public_site_full.jsonl --url https://sardarandco.com/pages/about-us --url https://sardarandco.com/products/shower-niche-pakistan

This reads PostgreSQL but makes no registrations, model calls, or vector writes. The JSON result should have `status: preview`, `indexed_chunks: 0`, and source chunk counts of two and one. On the existing seed database, `new_sources` should be zero and both registrations should say `existing`.

Apply the import:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.import_site --input data/extracted/public_site_full.jsonl --url https://sardarandco.com/pages/about-us --url https://sardarandco.com/products/shower-niche-pakistan --apply

The original Step 2 replay produced `status: completed`, `indexed_chunks: 3`, and `new_sources: 0` for the already registered seed. The Step 3A extension below now skips healthy indexed sources, so these same inputs normally produce `indexed_chunks: 0` and `skipped_chunks: 3`. The importer checks the Qdrant collection schema, embeds at most eight chunks per request when needed, validates vector counts/dimensions/numbers, and waits for completed upserts. An upsert inserts a new point or replaces the point with the same stable ID. Rerunning these exact inputs preserves the seed point IDs. Different selected authorized website records may create new registrations and broaden retrieval coverage.

Verify the cited answer through the PostgreSQL-authorized retrieval path:

    PYTHONPATH=backend backend/.venv/bin/python -m app.rag.answer_seed "What is Bongio?"

Expect the direct brand answer and its About Us citation. File validation/registry conflicts fail before embedding, and an invalid collection fails before embeddings or writes. Disabled sources stay disabled and restricted visibility cannot be changed by this public-site importer. Existing authorization records are preserved; new registrations record the owner's site authorization rather than claiming an authenticated uploader identity. Step 3B/3C below now supports changed content and durable jobs.

PostgreSQL and Qdrant do not share a transaction. The original Step 2 committed new registrations after index writes and could leave unregistered vectors after partial failures. Step 3B/3C supersedes that CLI workflow with staged publication, cleanup, and persistent failure/retry tracking. Step 2's existing-seed import and cited answer were verified by the developer screenshot on 2026-10-14.

## Phase 5 learning checkpoint — Step 3A

Step 3 is divided into 3A (skip unchanged indexed sources), 3B (changed/removed sources and cleanup), and 3C (persistent jobs and retries). All three now work through `import_site`. 3A itself needed no migration; the current 3B/3C workflow requires the migration below. Registry-only preview retains its read-only behavior and reports `index_action: unchecked`; applying the import also checks Qdrant before deciding to skip or index each source.

Run the import/index tests:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_site_import.py backend/tests/test_site_index.py

With the existing local stack running, repeat the same seed import:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.import_site --input data/extracted/public_site_full.jsonl --url https://sardarandco.com/pages/about-us --url https://sardarandco.com/products/shower-niche-pakistan --apply

For the seed already written by Step 2, expect these fields:

```json
{
  "phase": 5,
  "step": 3,
  "checkpoint": "3B/3C",
  "status": "completed",
  "new_sources": 0,
  "indexed_chunks": 0,
  "skipped_sources": 2,
  "skipped_chunks": 3
}
```

Each source should report `index_action: skipped`. The command reads PostgreSQL and Qdrant but sends no embedding requests or vector writes for skipped sources. It should be much quicker than the developer's approximately 30-second Step 2 re-embedding run, although no precise latency target is established.

A matching registry checksum alone is not enough to skip. The importer uses [Qdrant source-filtered scroll](https://api.qdrant.tech/api-reference/points/scroll-points), reads at most eight points/vectors per page under the existing response/time budgets, and verifies the expected ID set, source metadata, exact chunk text, approval basis, recorded embedding-model tag, and finite 1,024-dimensional vectors. A missing or mismatched expected chunk causes its document to be reindexed; healthy neighboring documents still skip. Malformed checks fail rather than silently skipping or falling through to a write. Step 3B also removes obsolete source points. Index checks validate stored vector shape/values and recorded model metadata; they do not regenerate embeddings or prove the model weights behind a mutable tag are unchanged.

Skipped vectors retain their last indexed fetch timestamp. The registry records the selected snapshot's fetch time and successful synchronization time separately from the last embedding time. An unchanged checksum does not prove that changing business facts are current, and this saved-file command does not fetch the website again. Tests simulate missing/corrupt points without altering the live seed.

Verify the cited answer and live regression baseline after the skip replay:

    PYTHONPATH=backend backend/.venv/bin/python -m app.rag.answer_seed "What is Bongio?"
    PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_seed

Expect the About Us citation and seven passing seed cases. This is still a two-document coverage baseline.

## Phase 5 learning checkpoints — Steps 3B and 3C

Step 3B keeps source IDs stable while replacing changed text and removing obsolete vectors. Before any network writes, PostgreSQL marks selected sources `indexing`; retrieval accepts only active `ready` sources and their published generation. Replacement point IDs include the indexing generation, so an expired worker cannot overwrite a later generation's chunks. The importer verifies replacements, deletes a bounded snapshot of obsolete IDs, verifies the remaining set, and then publishes `ready`. A failed batch remains unavailable until recovered. This trades temporary availability for avoiding mixed or stale evidence; even unchanged members of a batch are briefly held during processing.

Step 3C stores each validated request snapshot in PostgreSQL before processing. Jobs transition through `pending`, `processing`, `completed`, or `failed`, with attempt counts, timestamps, safe errors, and results. Explicit retries use the saved snapshot, with at most three total attempts. A worker lease and ownership checks prevent expired workers from publishing. Older snapshots and jobs queued before a newer conflicting publication cannot replace that version. Job inspection omits document text and worker tokens. This is a synchronous local CLI, with no scheduler or background queue; the latest attempt result is retained rather than a full attempt history.

Apply the schema migration (already applied in the verified project workspace):

    backend/.venv/bin/alembic upgrade head

Use the same `import_site --input ... --url ... --apply` command above for updates. A changed checksum triggers replacement; unchanged healthy documents skip embeddings. Omitting a URL from an import never deletes that source.

Inspect recent jobs or one job:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.jobs --limit 5
    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.jobs --job JOB_ID

Retry a failed, pending, or expired job after resolving its cause; replace `JOB_ID` with its UUID:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.import_site --retry JOB_ID --apply

Explicit removal uses `--remove --url URL`. Preview it without `--apply` first. Applying removal disables the registration before deleting its vectors; failure keeps it disabled. Import and retry do not reactivate disabled sources. Removal retains the source registration, local extraction file, and stored job snapshots; it is not deletion of all retained data. Cleanup scans at most 2,000 points per source, with ID reads/deletes in batches of 64, and fails safely if limits or response checks fail. The legacy `index_seed` command refuses sources managed by a generation or not ready; use this importer for synchronization.

Run the full backend suite:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests

The real-service integration test is opt-in and creates/removes a disposable PostgreSQL schema and Qdrant collection. Run it separately from other Ollama evaluations:

    SARDARS_RUN_SYNC_LIVE=1 PYTHONPATH=backend backend/.venv/bin/python -m pytest -q -s backend/tests/test_sync_live.py

It checks migration compatibility, real import, a two-chunk-to-one-chunk update, unchanged skip, explicit removal, authorization, and persisted job completion. Unit tests additionally force partial cleanup failures, retries, worker expiry, permission changes, and concurrent claims. No live seed source is updated or removed by that integration test.

Step 3 is complete for the local public-site workflow. Step 4 below extends it to authenticated submissions. The limited descriptive pipeline checkpoint was completed in Step 5 below; full saved-crawl coverage is active in Step 6. Authoritative structured company-database work is deferred to later tools by the developer. Automatic website synchronization and current-price/stock authority remain unimplemented. That checkpoint had eight website documents/twelve chunks, plus the separate staff-visible interview test PDF with twenty-six chunks; Step 6 records the later corpus.

## Phase 5 learning checkpoint — Step 4

Admins and staff can now submit one URL or file per request. The API authenticates before reading the upload body, extracts bounded descriptive text, retains the original in local storage, records the authenticated submitter, and runs the existing durable job. Processing is synchronous: the response waits for completion or a safe error containing the job ID. There is no Celery/Redis/background queue. One ingestion request runs per API process; another receives HTTP 429 with `Retry-After`. Job status remains available after a request ends or fails. The extraction subprocess exists to enforce resource limits, not to schedule background jobs.

Install the updated dependencies and apply the migration from the project root (both already done in the verified workspace):

    backend/.venv/bin/python -m pip install -r backend/requirements-dev.lock
    backend/.venv/bin/alembic upgrade head

Restart the API using `./scripts/dev.sh` if needed, then open `http://127.0.0.1:8000/docs`. Authenticate with your own account and use **Authorize** with your bearer token, or reuse Postman's Authorization tab. Keep credentials private. The OpenAPI page exposes the submission inputs, including a file picker; it is a developer interface, not the planned project upload screen.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/ingestion/files` | Multipart file submission or update |
| `POST /api/v1/ingestion/urls` | Fetch and import one configured HTTPS HTML page |
| `GET /api/v1/ingestion/jobs?limit=5` | Recent job metadata; staff see their own permitted jobs, admins see all |
| `GET /api/v1/ingestion/jobs/{job_id}` | Inspect one job without exposing its stored document snapshot |
| `POST /api/v1/ingestion/jobs/{job_id}/retry` | Explicit retry of a permitted internal job's saved snapshot |
| `GET /api/v1/ingestion/sources?limit=20&offset=0` | List source metadata permitted for the current role |
| `DELETE /api/v1/ingestion/sources/{source_id}` | Explicitly disable a managed source and delete its vectors |
| `GET /api/v1/ingestion/files/{file_id}` | Download a ready, active uploaded original after source authorization |

In Postman, choose `POST http://127.0.0.1:8000/api/v1/ingestion/files`, select **Body → form-data**, and add `file` with type **File**. Choose a UTF-8 `.txt`/`.md` or text-based `.pdf`. Optional text fields are `visibility` (default `staff`), `title`, and `source_id`. Blank optional `title`/`source_id` fields are treated as omitted, including empty values submitted from `/docs`; the filename supplies the default title. Invalid nonempty metadata identifies its field without echoing the submitted value. Let Postman generate the multipart Content-Type/boundary. To replace an existing uploaded document, supply its `source_id`, keep its visibility and format, and choose the new file; the source identity and citation link stay stable. Without `source_id`, each upload creates a new source, even for the same filename. Unknown/repeated fields and multiple files are rejected.

Staff may create staff-visible sources and update/remove their own staff-visible sources. Staff-visible material is readable by other staff and admins. Admins may create public, staff, or admin sources and manage any source. Import does not change an existing source's visibility, owner, or authorization basis, or reactivate a disabled source. In this internal release, `public` describes source classification; anonymous API access remains denied. Submissions are approved at source level with no page-by-page approval queue. This does not certify their accuracy or freshness.

For a URL, send JSON to `POST /api/v1/ingestion/urls`, for example:

```json
{
  "url": "https://sardarandco.com/pages/about-us",
  "visibility": "public"
}
```

Use an admin for this existing public source. Staff cannot take over its local-operator registration. Defaults permit only the exact host `sardarandco.com` and its descriptive pages/articles/products. An operator can configure additional approved hosts using `SARDARS_INGESTION_URL_HOSTS` as a JSON array; generic HTML uses a main/article/body extractor. This fetches one page, not the whole site, and does not execute JavaScript. URLs must use HTTPS with no credentials, query, fragment, or custom port. Robots restrictions apply; redirects and private/non-global DNS addresses are rejected. Connections pin a checked public IP while retaining TLS hostname verification, preventing a DNS change between checking and connecting from targeting internal services. URL responses are bounded to 3 MiB; PDF URLs must be uploaded as files instead.

The upload limit is 5 MiB and the multipart body limit includes 64 KiB of overhead. Extracted text is capped at 50,000 characters and 10,000 words; PDFs at 50 pages. Extraction has a 30-second wall-clock limit, a 20-second CPU limit, and a 512 MiB process memory limit on Linux. Encrypted, malformed, blank, and scanned/image-only PDFs fail safely; OCR, DOCX, spreadsheets, and multilingual evaluation remain later work. Ingestion/indexing has the existing configured processing budget. This is descriptive RAG ingestion, not a price/inventory import.

`SARDARS_INGESTION_STORAGE_DIR` defaults to Git-ignored `data/uploads`. Originals use generated UUID names with restrictive permissions; user filenames are metadata, never paths. This directory is not served as static content. File citations point to the protected download endpoint; the original checksum is verified before download and untrusted content is sent as an attachment. Replacements/removals retain previous originals and job snapshots for recovery/history; there is no retention cleanup or full-data erasure endpoint yet. Back up both PostgreSQL and the configured storage directory.

A successful submission returns `job_id`, counts, and `sources` containing stable source IDs and citation URLs. Validation/extraction failures before job creation return HTTP 400/413/422 without a job. Indexing failures return HTTP 503 with `detail.job_id`; inspect that job and resolve the reported cause before retrying. API retries are for authenticated internal jobs; local-operator jobs still use the CLI. Limits are three total attempts, and permissions/account activity are checked again during processing. Logs record job IDs, attempts, counts, safe error codes, and duration, without document text or credentials.

`SARDARS_EMBEDDING_BATCH_SIZE` defaults to two chunks and supports one through eight. Smaller batches bound each model request more tightly on a CPU laptop. `SARDARS_IMPORT_TIMEOUT_SECONDS` defaults to 300 and is capped at 600; this local installation was set to 600 after a 26-chunk PDF exceeded five minutes. An upload below the file/page limits can still exceed the processing budget, especially under memory/swap pressure. Model requests keep the existing bounded timeout and model-unload setting. Errors distinguish the overall processing budget, embedding/vector request timeouts, connection failures, and HTTP statuses without returning service bodies. If indexing fails, the source remains unavailable until recovery. Retry the existing job rather than uploading a duplicate; splitting a document may be necessary if it cannot finish within the maximum budget. These are synchronous requests, not an indication of background worker progress.

Run the new checks:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_ingestion_api.py backend/tests/test_ingestion_extraction.py

The opt-in test command above also verifies real authenticated uploads and private retrieval in disposable namespaces. It requires the local services and access to the authorized About Us page. Uploaded test documents and temporary accounts are isolated from the project database/index; they are not real company knowledge. Step 5 below adds a measured coverage/evaluation checkpoint. General answerability, wider source quality/ranking, and current facts still need later work.

## Phase 5 learning checkpoint — Step 5

The selected Step 5 checkpoint completed the limited V1 descriptive ingestion and synchronization pipeline. Full saved-crawl coverage remains active in Step 6. The developer deferred current price/stock and authoritative structured data to later company-database tools. Tool calling is not implemented yet. The [Step 5 report](docs/phase5_step5_report.md) records changes, evidence, commands, and limitations.

The explicit [coverage manifest](data/coverage/public_site_v1.json) selects eight checksum-pinned documents from the saved crawl. It preserves About Us and Shower Niche and adds Cosmetic Mirror, Wall-Mounted Seat Lift-Up, Tile Floor Drain, Square E Corner Basin, Round Over Counter Basin, and Elan Tower. The import completed with six new sources/nine new chunks and skipped the original three chunks. Repeat import skipped all eight documents/twelve chunks. The full 1,008-record website extraction remains local source data; it was audited, not fully indexed. The separate supplied profile remains unindexed, with overlap and further claims needing measured future selection.

Run these commands from the project root:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.coverage
    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.coverage --audit-all
    PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_coverage
    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests

The first command audits only the selected manifest without services. The second audits the bounded full extraction without indexing it. The legacy `coverage --apply` imports only the selected raw manifest. Use `full_site` below to manage the derived full-crawl snapshot; replaying the old raw manifest can replace a derived version with the original text. A manifest checksum mismatch or quality flag refuses the batch before job creation. This pins reproducible evaluation data and enforces automatic input-quality checks, not a per-document authorization queue. Ordinary authenticated URL/file imports still support updates. Audit checks include normalized duplicate content/paragraphs, identical-record deduplication, short text, obvious instructions, changing-fact/policy language, and possible mislabeled specification units; they preserve original source text/checksums rather than inventing corrections. Flags can be false positives and do not certify unflagged data as accurate.

The expanded evaluation runs sixteen live questions using the role-filtered company-answer components, eight isolated SQL trust controls, and one routing-only check. It checks expected sources and answer phrases, citation provenance/markers, supported product/project descriptions, unsupported/current-fact abstentions, instruction patterns, conflicts, admin visibility, disabled/unregistered/failed/stale sources, and live latency. Service failures remain failed cases. Synthetic controls never enter the live index. Reports distinguish live results, synthetic controls, and routing; they do not treat a routing check as a general-model answer test.

The first run passed 23/25, exposing a missing Bongio source and a vendor-prose answer. Retrieval now inspects at most eight candidates instead of three, with PostgreSQL authorization before evidence selection. Product headings can identify the subject, while requested features must still match body evidence. Product feature/material sentences receive priority, and common auxiliary phrases no longer cause false abstentions. Final model evidence remains capped at three excerpts/1,800 characters. These lexical changes do not provide general semantic answerability or guarantee polished prose.

The final run passed 25/25 with all twelve supported source hits; median live latency was 8.70 seconds and p95 18.69 seconds. The original baseline passed 7/7; the full backend suite passed 274 tests with two opt-in integration tests skipped. These are bounded English prototype checks on this laptop, not comprehensive accuracy, adversarial, multilingual, or traffic measurements. The technical interview PDF is test data, not authoritative Sardars information. Clear general educational questions still go directly to the model instead of automatically reading uploaded documents.

Add `--report data/extracted/UNUSED_NAME.json` to an audit/import/evaluation command to save local JSON evidence; existing files are refused. Saved source data and detailed reports remain Git-ignored. Avoid parallel Ollama evaluations/indexing on this laptop. After full descriptive coverage, Phase 6 adds controlled read-only tools backed by an identified company database, with permissions, stable product IDs, and freshness rules before returning exact/current values.


## Phase 5 Step 6 — resumable full saved-crawl coverage

`app.ingestion.full_site` prepares a fixed descriptive snapshot of all 1,008 saved records, then runs small serial jobs through the existing publication, permissions, cleanup, and retry mechanisms. It does not fetch a newer website snapshot. Full-site ingestion and repeat verification completed on 2026-10-15: all 999 eligible sources/3,739 chunks finished across 309 batches, with nine recorded exclusions. The final expanded evaluation passed 28/40 and the seed regression 4/7; retrieval/answer quality remains open. See [the completion outcomes](docs/phase5_full_site_completion_status.md) and [the coverage report](docs/phase5_full_site_report.md). Price, stock, availability, contact/hours, and guaranteed business promises remain outside verified current answers.

The final offline plan retains **999 documents / 3,739 chunks** and records **nine whole-source exclusions**. Of the eligible sources, 670 have derived excerpts. Mixed records retain verbatim descriptive spans while omitting changing claims, transaction/contact/promise text, and repeated segments. Short specifications and SKU-only records remain eligible; distinct product URLs are not merged because their prose matches. The suspicious Axent water-pressure specification is excluded without correction. Filtering is heuristic and does not certify factual accuracy.

The Git-ignored state directory contains:

- `plan.json`: checksums of the original crawl and prepared data, source dispositions, retained/omitted character offsets and reasons, original titles, and fixed batch membership.
- `documents.jsonl`: validated originals or derived text with stable source IDs, actual fetch dates, and original-content checksums for derived records.
- `ledger.json`: per-source pending/processing/imported/skipped/rejected/failed status and PostgreSQL job references/results. Atomic writes and a runner lock protect resumption.

Status/preparation are offline. On this existing workspace, preparation is already done; start with status and apply:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.full_site
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.full_site --apply --max-batches 1
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.full_site --apply --max-batches 6
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_coverage --cases backend/app/evaluation/full_site_cases.json
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests
```

On a fresh setup with the saved crawl present, first run `python -m app.ingestion.full_site --prepare` with the same `PYTHONPATH` and virtual-environment prefix. Preparation refuses an existing directory. A changed crawl or filter requires a **new** `--state data/extracted/NEW_NAME` directory; every later command must use that same state. Keep the original crawl at its recorded path for checksum and provenance checks. The local pilot directories `full_site_v1` and `full_site_descriptive_v1` retain earlier development snapshots; `full_site_descriptive` is the final plan used by default.

Each apply resumes unfinished batches and defaults to one job. The target is five sources/twenty-four chunks; a longer document runs alone, with a hard sixty-four-chunk source limit. This saved plan's largest job has twenty-six chunks. Every job gets a fresh configured processing deadline (600 seconds on this installation), and embedding requests use the configured small batch size (two here). One model stays warm for 120 seconds between serial ingestion requests. A larger `--max-batches` schedules more serial jobs; it does not increase request sizes or concurrency. Run evaluations separately from ingestion.

To check completed batches again, add `--verify --max-batches 6` to apply. This uses the lifecycle importer's vector/payload checks; it can repair missing points and remove obsolete generations. Simply resuming a completed ledger does not recheck live services. If a batch fails, the command stops, preserves its job ID, and leaves failed generations unavailable. Inspect `app.ingestion.jobs --job JOB_ID`, resolve the cause, then run `app.ingestion.full_site --apply --retry-failed`. Retries use the same saved job with the existing three-attempt limit; active leases must expire before recovery. A stopped process does not lose successful preceding batches. There is no automatic website synchronization or new queue infrastructure.

Citations now optionally include `content_derivation` and `original_content_sha256` for derived material, alongside the source ID, URL, title and actual fetch date. The original text remains in the saved crawl; the ledger's offsets explain the excerpt. Authorization and generation checks still precede evidence/prompt use. The forty-case English evaluation expands the earlier twenty-five cases with projects, articles, compact product records/specifications, removed warranty claims, and unsupported current facts. It measures the current indexed scope, not pending documents or general accuracy.


At the historical partial 2026-10-15 Step 6 checkpoint, 39 website sources/83 chunks plus the unchanged staff test PDF/26 chunks were ready (109 points). The final suite passed 302 tests; the original seed passed 7/7 and the original evaluation subset 25/25. The larger set passed **37/40**, with three documented article false abstentions; it is not a fully passing coverage evaluation. All 39 published website sources skipped on replay. See the report for the distinction between live sources, prepared versions and the final ledger. A narrow, configurable About Us hint preserves the existing direct Bongio definition within the eight-candidate limit; it does not establish a general brand lookup service. `SARDARS_BRAND_DEFINITION_PROFILE_URL` is documented in `.env.example`.


The detached serial continuation has finished with `indexed_with_evaluation_failures`. Import and complete-plan replay succeeded; all 999 sources were verified/skipped on replay. Expanded evaluation passed 28/40 (19/31 live, 8/8 trust controls, 1/1 routing; 15/24 supported-source hits), and the original seed passed 4/7. Inspect `data/extracted/full_site_continuation.json`, its `.log`, `data/extracted/full_site_completion_evaluation.json`, and `docs/phase5_full_site_completion_status.md` for outcomes. These supersede the partial checkpoint counts/scores above. Ingestion is complete; neither full-corpus answer quality nor Phase 6 is declared complete.

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.full_site
tail -f data/extracted/full_site_continuation.log
```


## Phase 6 — first read-only application tool

On 2026-10-16 the developer chose a Shopify CSV/PostgreSQL product-lookup proof of concept without ERP access. The first schema checkpoint adds `public.products`, with all 88 named export columns and eight identity/provenance fields. It preserves variant/image rows, exact decimal prices and leading-zero identifiers. `backend/.venv/bin/alembic upgrade head` applies migration `c83d7a16e902`. The supplied `products_export_1.csv` has been inspected read-only: all 88 headers match, with 4,983 records / 2,009 handles and no structural/basic type errors. Only 15 rows have SKUs, so handle/option lookup is the appropriate initial design. The validated file is now imported: 4,983 rows / 2,009 handles, with all exported values/provenance verified and repeat import skipping all rows. The original prices/SKUs remain unchanged; export time/currency remain unknown. No product lookup/model tool is implemented yet. See [the CSV validation report](docs/phase6_shopify_csv_validation.md). See [the Shopify schema and checkpoint guide](docs/phase6_shopify_products.md). The developer authorized this import; the product tool and model integration require the next agreed checkpoint. Price/stock values will be dated snapshot facts, with currency/export time left unknown until supplied. The existing source-status tool below remains a separate verified metadata checkpoint.

The first checkpoint adds an explicit allowlist containing `get_source_status`, strict Pydantic inputs/results and authenticated **single-tool execution**. Model tool calling and ERP integration are later checkpoints. The ERP access checklist and verification evidence are in [the Phase 6 source contract](docs/phase6_source_contract.md).

With the API running and a current admin/staff login in Postman:

1. Call `GET /api/v1/ingestion/sources` with Bearer authentication. Copy a visible source's `source_id`; answer citations also carry that ID.
2. Call `POST /api/v1/tools/execute` with the same Bearer authentication and `Content-Type: application/json`. Replace the placeholder below with that sixty-four-character lowercase hexadecimal ID:

```json
{
  "name": "get_source_status",
  "arguments": {"source_id": "<copy the source_id here>"}
}
```

A successful HTTP 200 response has `ok: true` and `data` containing the source's URL/title, visibility, active/index state, registry readiness, fetch/index/sync timestamps and an observation timestamp. The authority is `application_source_registry`; `company_facts_verified` stays false. The tool reports PostgreSQL metadata. It does not scan Qdrant, read document bodies, establish answerability, or verify current prices/stock. Null dates remain unknown. `retrieval_ready` reflects only the registered active/ready state.

Staff may read public/staff metadata; admins may also read admin metadata, following existing source-list visibility rules. Unknown and hidden sources both return `ok: false` with error code `source_not_found`, without leaking source details. Invalid arguments, unknown tool names, database errors and query timeouts return structured safe tool failures (HTTP 200); malformed request envelopes use HTTP 422. Authentication errors use HTTP 401, oversized request bodies HTTP 413, unsupported content types HTTP 415, and slow body reads HTTP 408. Client-supplied role/permission fields are refused.

Each request performs one lookup without model calls or retries. Body/argument/result limits are 8/4/8 KiB, the body read limit is thirty seconds, and PostgreSQL statement/lock limits are two/one seconds within the request transaction. These query limits do not establish a new end-to-end network timeout. Tool logs include allowlisted name, outcome and duration only. No arbitrary SQL, shell or model-supplied function name is executed.

Run the focused checks:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_tools.py backend/tests/test_ingestion_api.py backend/tests/test_chat.py
```

The full backend suite passed 339 tests with two opt-in integration tests skipped; the focused run passed 71 tests. A real local PostgreSQL/API smoke check verified both roles, timestamp preservation, session revocation, query limits/reset and unchanged source/job records; temporary test accounts were removed. ERP product IDs, ownership, price/stock semantics, permissions and freshness rules still need confirmation before implementing those business tools.
