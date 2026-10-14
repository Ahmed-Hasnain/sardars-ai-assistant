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

Each JSONL record includes a stable source ID, public visibility, pending review status, source type, URL, title, fetch time, content checksum, and extracted text. The output directory is ignored by Git. Inspect the records before increasing `--limit-per-type` (maximum 1500 per type). Chat uses only the registered and indexed seed, not the full extracted file. Staff-only material must wait until a private-document ingestion path exists.

A full public crawl was run on 2026-10-12 with `--limit-per-type 1500 --delay-seconds 0.5 --output data/extracted/public_site_full.jsonl`. It produced 1,008 review records; 142 product links did not yield useful text. The local audit is `data/extracted/public_site_audit.md`. Both files remain ignored by Git. Some descriptions and articles include changing claims despite excluding structured offer fields, so review them before any indexing or answer generation.

## Vector-search runtime

Pull the small local embedding model with `ollama pull qwen3-embedding:0.6b`. Its `/api/embed` response was measured at 1,024 dimensions on this laptop. Qdrant runs through the `qdrant` Compose service at `http://127.0.0.1:6333` with persistent storage. Collection `sardars_public_qwen3_embedding_06b_v1` uses 1,024-dimensional cosine vectors and currently contains three approved seed points. On a new Qdrant volume, create the collection after starting the service:

    curl -sS -X PUT http://127.0.0.1:6333/collections/sardars_public_qwen3_embedding_06b_v1 -H 'Content-Type: application/json' -d '{"vectors":{"size":1024,"distance":"Cosine"}}'

The prototype selects the public About Us and Shower Niche records from `data/extracted/public_site_full.jsonl` into `data/extracted/rag_seed.jsonl`. After producing the full crawl described above, run from the project root:

    grep -F -e '"url": "https://sardarandco.com/pages/about-us"' -e '"url": "https://sardarandco.com/products/shower-niche-pakistan"' data/extracted/public_site_full.jsonl > data/extracted/rag_seed.jsonl
    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.chunking
    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.register_seed
    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.index_seed
    PYTHONPATH=backend backend/.venv/bin/python -m app.retrieval.search_seed --approved "What bathroom storage product does Sardars describe?"

`chunking.py` writes three 100-word-maximum chunks with 15-word overlap to `data/extracted/rag_seed_chunks.jsonl`. `register_seed.py` records the two already authorized URLs and their content checksums in PostgreSQL's `source_registrations` table; rerunning it does not reactivate disabled sources. `index_seed.py` requires active matching registrations, embeds the chunks, and upserts them with `review_status: approved`, `approval_basis: owner_authorized_source_for_internal_use`, and `prototype_only: false`. `search_seed.py --approved` embeds a question and prints ranked text, source URLs, and similarity scores. Its default mode is the old pending/prototype diagnostic filter and should now return no seed points. The local extracted files are ignored by Git and retain their original `pending` labels; authorization is applied when indexing. On 2026-10-13 the project owner authorized the supplied sources for internal use and chose source-level approval for future authorized admin/staff uploads and registered URLs. Company questions on `/chat` and explicit `/ask` use this small approved public-site seed. The CLI scripts are a learning prototype, not a source synchronization workflow.

Before answering, `/ask`, routed company `/chat`, and the grounded-answer CLI compare each retrieved Qdrant point with its PostgreSQL source registration: source ID, URL, type, visibility, active status, and content checksum must match. Unknown or disabled sources are excluded. Qdrant also prefilters visibility by the authenticated role. Both internal roles can use the current public seed. The registry can express staff and admin visibility, but real private-document indexing is not built yet. In DataGrip, inspect `public.source_registrations` to see the two authorized sources.

## Grounded-answer CLI seed

With Ollama and Qdrant running and the three seed points indexed, try:

    PYTHONPATH=backend backend/.venv/bin/python -m app.rag.answer_seed "Which brands does Sardars mention?"
    PYTHONPATH=backend backend/.venv/bin/python -m app.rag.answer_seed "What is Sardars' return policy?"

The first question should show an exact brand sentence from the About Us source with its URL; the second should say it cannot verify the policy and show no citation. This CLI filters for approved Sardars website chunks and uses a conservative question-term match to find source sentences before calling the local chat model. The evidence is capped at 1,800 characters. If the small model's answer or citation is unusable, it prints an exact matching source sentence. This is a two-document learning checkpoint: the term match can miss paraphrases and does not prove general answerability. The protected `POST /api/v1/ask` route uses the same company seed flow and accepts `{"message":"Which brands does Sardars mention?"}`. `/api/v1/chat` selects the company flow for that question and uses general Ollama chat for clear educational questions.

Run the RAG baseline after starting Ollama and Qdrant and indexing the approved seed:

    PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_seed

It checks five live questions: supported brand-list, Bongio definition, and storage answers against their source URLs, and uncited abstentions for missing return-policy and current-price facts. Two synthetic cases check prompt injection and conflicting warranty evidence without indexing either in Qdrant. The case file is `backend/app/evaluation/seed_cases.json`. The direct Bongio answer states only what the approved About Us source supports; it does not establish further facts about the brand. This small baseline does not establish general answer accuracy, adversarial robustness, or coverage of the full website.

## Phase 5 learning checkpoint — Step 1

Phase 5 is being built in small runnable checkpoints; `PLAN.md` records their sequence. Step 1 prepares selected website documents from an existing crawler JSONL file. It needs no PostgreSQL, Qdrant, Ollama, login, or network access. It validates record integrity, not factual accuracy, source permissions, or freshness. Only explicitly selected documents are validated; the rest of the bounded extraction file is scanned for selection, not imported.

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

Expect the direct brand answer and its About Us citation. File validation/registry conflicts fail before embedding, and an invalid collection fails before embeddings or writes. Disabled sources stay disabled, restricted visibility cannot be changed by this public-site importer, and changed source checksums are refused until synchronization is implemented. Existing authorization records are preserved; new registrations record the owner's site authorization rather than claiming an authenticated uploader identity.

PostgreSQL and Qdrant do not share a transaction. New registrations commit only after index writes complete; failures roll them back and return a safe JSON error/nonzero exit code. A partial failure can leave unregistered vectors: retrieval excludes them, but they can consume candidate slots until later cleanup. The console result is not a persistent ingestion job record. Step 2's existing-seed import and cited answer were verified by the developer screenshot on 2026-10-14. New-source creation remains tested offline; Step 3B/3C add updates/removals, cleanup, and durable failure/retry tracking.

## Phase 5 learning checkpoint — Step 3A

Step 3 is divided into 3A (skip unchanged indexed sources), 3B (changed/removed sources and cleanup), and 3C (persistent jobs and retries). The existing `import_site` command now implements 3A. No new dependency or migration is needed. Registry-only preview retains its read-only behavior and reports `index_action: unchecked`; applying the import also checks Qdrant before deciding to skip or index each source.

Run the import/index tests:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_site_import.py backend/tests/test_site_index.py

With the existing local stack running, repeat the same seed import:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.import_site --input data/extracted/public_site_full.jsonl --url https://sardarandco.com/pages/about-us --url https://sardarandco.com/products/shower-niche-pakistan --apply

For the seed already written by Step 2, expect these fields:

```json
{
  "phase": 5,
  "step": 3,
  "checkpoint": "3A",
  "status": "completed",
  "new_sources": 0,
  "indexed_chunks": 0,
  "skipped_sources": 2,
  "skipped_chunks": 3
}
```

Each source should report `index_action: skipped`. The command reads PostgreSQL and Qdrant but sends no embedding requests or vector writes for skipped sources. It should be much quicker than the developer's approximately 30-second Step 2 re-embedding run, although no precise latency target is established.

A matching registry checksum alone is not enough to skip. The importer uses [Qdrant source-filtered scroll](https://api.qdrant.tech/api-reference/points/scroll-points), reads at most eight points/vectors per page under the existing response/time budgets, and verifies the complete expected ID set, source metadata, exact chunk text, approval basis, recorded embedding-model tag, and finite 1,024-dimensional vectors. A missing or mismatched expected chunk causes its document to be reindexed; healthy neighboring documents still skip. Malformed checks fail rather than silently skipping or falling through to a write. Extra/unexpected IDs require Step 3B cleanup and are refused before writes. Index checks validate stored vector shape/values and recorded model metadata; they do not regenerate embeddings or prove the model weights behind a mutable tag are unchanged.

Skipped content retains its actual last indexed fetch timestamp. An unchanged checksum does not prove that changing business facts are current, and this saved-file command does not fetch the website again. Changed document checksums are still refused until 3B; removal, obsolete/orphan cleanup, and persistent jobs/retries are not implemented by 3A. Tests simulate missing/corrupt points without altering the live seed.

Verify the cited answer and live regression baseline after the skip replay:

    PYTHONPATH=backend backend/.venv/bin/python -m app.rag.answer_seed "What is Bongio?"
    PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_seed

Expect the About Us citation and seven passing seed cases. This is still a two-document coverage baseline. Inspect the developer's 3A replay before moving to the update/removal checkpoint.
