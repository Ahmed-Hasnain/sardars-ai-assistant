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
