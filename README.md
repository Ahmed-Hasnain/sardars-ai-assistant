# Sardars AI Assistant

A self-hosted AI assistant for Sardars, initially intended for admins and internal staff. The current implementation has a FastAPI backend, PostgreSQL, Alembic migrations, health checks, local-model chat through Ollama, and a retrieval-only Qdrant prototype.

## Local setup

Requires Python 3.12+ and Docker Compose. Local chat also requires Ollama. Run commands from the project root.

Copy `.env.example` to `.env` and replace `SARDARS_DB_PASSWORD` with a private random password before starting PostgreSQL.

Create the environment and install the recorded dependencies:

    python3 -m venv backend/.venv
    backend/.venv/bin/python -m pip install -r backend/requirements-dev.lock

Start PostgreSQL and apply migrations:

    docker compose up -d --wait db
    backend/.venv/bin/alembic upgrade head

Start the API in another terminal:

    backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

Check http://127.0.0.1:8000/api/v1/health for API liveness and http://127.0.0.1:8000/api/v1/ready for database readiness.

Run the smoke tests while PostgreSQL is running:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests

Stop PostgreSQL with `docker compose stop db`; its data is retained. Keep `.env` and `backend/.venv/` out of Git.

For daily development, run `./scripts/dev.sh` from the project root. It starts PostgreSQL and Qdrant through Docker Compose, starts the installed Ollama system service if needed, runs FastAPI, and follows all four services' logs in one terminal. If Ollama is stopped, `sudo` may ask for your password. Press Ctrl+C to stop FastAPI and the log followers; the Docker containers and Ollama service remain running. Stop the containers later with `docker compose stop db qdrant`.

## Local-model chat

Install Ollama using its [Linux instructions](https://docs.ollama.com/linux), then download the small model used on this laptop:

    ollama pull qwen3:0.6b

With Ollama and the API running, send a request from Postman or the terminal:

    curl -sS http://127.0.0.1:8000/api/v1/chat -H 'Content-Type: application/json' -d '{"message":"Explain what a database is in one sentence."}'

`POST /api/v1/chat` returns an answer, model name, token counts, duration, and `company_data_verified: false`. It currently answers general questions without a Sardars source of truth; do not treat its Sardars-specific claims as verified. The Ollama settings in `.env.example` default to `qwen3:0.6b` on localhost with `keep_alive=0` to unload the model after each request. This reduces memory use but adds model load time to each request.

## Public source extraction sample

The project owner supplied `https://sardarandco.com/sitemap.xml` and the text in `data/sources/company_profile.md` for the first public-source prototype. `data/source_inventory.md` tracks their provenance and the missing staff source. The sitemap extractor reads public pages, articles, and product descriptions. It skips quote/account paths, checks robots rules, stays on the Sardars host, waits between page requests, and omits product offer data such as price and availability. Its output is descriptive source material for review, not verified answers or a search index.

From the project root, extract one page, one article, and one product:

    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.public_site --limit-per-type 1 --output data/extracted/public_site_sample.jsonl

Each JSONL record includes a stable source ID, public visibility, pending review status, source type, URL, title, fetch time, content checksum, and extracted text. The output directory is ignored by Git. Inspect the records before increasing `--limit-per-type` (maximum 1500 per type). The current chat endpoint does not use these records. Staff-only material must wait until staff authentication and source filtering exist.

A full public crawl was run on 2026-10-12 with `--limit-per-type 1500 --delay-seconds 0.5 --output data/extracted/public_site_full.jsonl`. It produced 1,008 review records; 142 product links did not yield useful text. The local audit is `data/extracted/public_site_audit.md`. Both files remain ignored by Git. Some descriptions and articles include changing claims despite excluding structured offer fields, so review them before any indexing or answer generation.

## Vector-search runtime

Pull the small local embedding model with `ollama pull qwen3-embedding:0.6b`. Its `/api/embed` response was measured at 1,024 dimensions on this laptop. Qdrant runs through the `qdrant` Compose service at `http://127.0.0.1:6333` with persistent storage. Collection `sardars_public_qwen3_embedding_06b_v1` uses 1,024-dimensional cosine vectors and currently contains three inspection-only points. On a new Qdrant volume, create the collection after starting the service:

    curl -sS -X PUT http://127.0.0.1:6333/collections/sardars_public_qwen3_embedding_06b_v1 -H 'Content-Type: application/json' -d '{"vectors":{"size":1024,"distance":"Cosine"}}'

The prototype selects the public About Us and Shower Niche records from `data/extracted/public_site_full.jsonl` into `data/extracted/rag_seed.jsonl`. After producing the full crawl described above, run from the project root:

    grep -F -e '"url": "https://sardarandco.com/pages/about-us"' -e '"url": "https://sardarandco.com/products/shower-niche-pakistan"' data/extracted/public_site_full.jsonl > data/extracted/rag_seed.jsonl
    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.chunking
    PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.index_seed
    PYTHONPATH=backend backend/.venv/bin/python -m app.retrieval.search_seed --approved "What bathroom storage product does Sardars describe?"

`chunking.py` writes three 100-word-maximum chunks with 15-word overlap to `data/extracted/rag_seed_chunks.jsonl`. `index_seed.py` validates that their URLs match the authorized Sardars site, embeds them, and upserts them with `review_status: approved`, `approval_basis: owner_authorized_source_for_internal_use`, and `prototype_only: false`. `search_seed.py --approved` embeds a question and prints ranked text, source URLs, and similarity scores. Its default mode is the old pending/prototype diagnostic filter and should now return no seed points. The local extracted files are ignored by Git and retain their original `pending` labels; authorization is applied when indexing. On 2026-10-13 the project owner authorized the supplied sources for internal use and chose source-level approval for future authorized admin/staff uploads and registered URLs. The current chat endpoint still does not use Qdrant, and no internal-user authentication or role filtering exists yet. The CLI scripts are a learning prototype, not a source synchronization workflow.
