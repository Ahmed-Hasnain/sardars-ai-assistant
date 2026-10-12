# Sardars AI Assistant

A self-hosted AI assistant for Sardars. The current implementation has a FastAPI backend, PostgreSQL, Alembic migrations, health checks, and local-model chat through Ollama.

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
