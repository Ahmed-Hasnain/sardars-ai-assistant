# Sardars AI Assistant

A self-hosted AI assistant for Sardars, initially intended for admins and internal staff. This monorepo contains the FastAPI backend and a React/Vite/TypeScript frontend. The backend provides PostgreSQL-backed conversations, revocable internal login, local-model chat through Ollama, and authorized Qdrant retrieval.

The original prototype roadmap through Phase 12 is recorded in [PLAN.md](PLAN.md). Current work follows [EXTENDED_PLAN.md](EXTENDED_PLAN.md); verified behavior and open limitations are recorded in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). E1–E4 local checkpoints are complete; E5 is next. The [E1 data-backed container exit](docs/e1_local_container_checkpoint.md), [E2 model comparison](docs/e2_model_comparison.md), [E3 ingestion-runner selection](docs/e3_ingestion_runner.md), and [E4 real-data evaluation](docs/e4_real_data_baseline.md) are recorded. E4 used a current-corpus upload-exclusion comparison because comprehensive pre-upload answers were not saved; retained retrieval/evidence failures remain open. The 4B model's loaded-laptop latency and guarded non-answer remain an open quality/performance limitation. Internal self-registration, approval and production deployment are deferred.

The [E1 local stack](docs/e1_local_container_checkpoint.md) uses `compose.local.yaml` for the API, frontend, PostgreSQL, Qdrant and containerized Ollama, with a persistent model store, automatic pulls of missing models, a compatible collection initializer, and separate volumes/ports. The [tested local backup/restore procedure](docs/e1_backup_restore.md) covers all four persistent volumes. For a 16 GB Apple Silicon Mac mini, use `compose.local.mac.yaml` as described there; Ollama remains containerized and runs on CPU because Docker Desktop on macOS cannot pass through the Apple GPU. The existing `compose.yaml` and `scripts/dev.sh` workflow remains available; the historical host latency comparison changes model size and does not isolate container overhead.

On the current Linux development machine, Git-ignored `.env` selects `SARDARS_OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M` for `compose.local.yaml`. The selected 4B tag is installed in that stack's Ollama volume, and the API adapter has returned a live 4B response. A fresh machine must set the same variable if it should use 4B; the Compose model initializer will pull a missing standard Ollama tag. The older host-Ollama `scripts/dev.sh` workflow needs its own copy of a selected model and was not switched or retested in E2. See [the E2 comparison](docs/e2_model_comparison.md) for the measured quality and latency tradeoff.

## Start and stop the complete Docker stack

From the project root, with Docker running and `.env` configured, use these two commands for the local API, web app, PostgreSQL, Qdrant, Ollama and ingestion worker:

Start everything (builds changed app images and shows all service logs in this terminal):

```bash
docker compose -f compose.local.yaml up --build
```

Stop everything:

```bash
docker compose -f compose.local.yaml down
```

Open `http://127.0.0.1:15173/` after startup. The `up` command stays open and shows combined logs; press **Ctrl+C** to stop the services. Run `down` afterward to remove the stopped containers. `down` **keeps the named volumes** containing PostgreSQL data, Qdrant data, uploads and Ollama models. Do not add `--volumes` when you want to keep that data. The first startup may take longer while Docker pulls images and Ollama downloads missing models.

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

Run the frontend in a second terminal (Node.js 20.19+ or 22.12+):

    cd frontend
    npm ci
    npm run dev

Open http://127.0.0.1:5173 and sign in with an existing admin or staff account. Vite proxies `/api` to the local FastAPI server on port 8000; the browser does not need a separate CORS allowance. The frontend supports sign-in, new and follow-up chats, safe Markdown, returned citations, retry after an API error, and a sidebar of owned conversations. The list shows a short preview of each conversation's first question. Open one to read its latest 50 messages and load older pages; earlier answers are marked as historical because business facts may have changed. Historical citations are reconstructed only while each source is currently active, indexed and visible to your role. Uploaded source links download through the authenticated API. Answer text may link only to URLs in its returned citations.

The browser keeps the bearer token and active conversation ID in this tab's `sessionStorage` so refresh can restore the chat. On startup, the frontend checks the token with `/auth/me` before showing any saved conversation; logout or HTTP 401 clears it. Closing the tab ends this browser-side session, and the backend still enforces its eight-hour token expiry and role/source visibility. Browser storage is accessible to JavaScript, so a later production authentication design should use an HTTP-only cookie and its CSRF controls. The browser uses `POST /api/v1/chat/stream` for SSE delivery. The API authenticates, checks and saves the whole answer before sending any text, so it cannot leak an unverified intermediate company claim; the first chunk arrives after generation finishes. `POST /api/v1/chat` remains a JSON option. Production static hosting is deferred to E9; E1 already serves the local frontend in a container.

### Admin knowledge imports in the local stack

Start the isolated stack with the `up --build` command above and sign in at `http://127.0.0.1:15173/` as an existing admin. The **Knowledge sources** workspace submits a text PDF, UTF-8 TXT/Markdown file (up to 5 MiB), one allowed HTTPS HTML page, or a direct HTTPS `.xml` sitemap URL. Use **Visible to** to choose staff-and-admin or admin-only retrieval before submitting. Jobs return immediately with an ID; the separate worker extracts and indexes them. The screen polls job status, shows sitemap page progress and failures, lists registered sources, and offers retry, removal, same-source document replacement, and **Restore** for a previously removed website page. A replacement must retain the source's format and visibility. Staff may still use the pre-existing authorized API paths for their own individual submissions, but the new browser workspace and sitemap submission require admin access.

Removing a page keeps its registration as a revoked record. To add that same URL again, wait for its removal job to complete and click **Restore** beside the removed page in **Registered sources**; submitting it through **Add page** remains blocked. Restore is an explicit admin-only action that fetches the current page, keeps its source ID and visibility, and publishes it only after the worker verifies fresh indexing. If restoration fails, the page remains hidden and the job can be retried. A failed removal must finish cleanup through its job retry before restoration. The matching API is `POST /api/v1/ingestion/sources/{source_id}/restore`.

Sitemap discovery reads an allowed host's robots rules, follows only same-host XML indexes and descriptive page URLs, and queues one durable child job per eligible page. Sitemap XML links may use only the same-host numeric `?from=...&to=...` range found in Sardars' Shopify sitemap; ordinary page URLs still cannot have queries. Its limits are 1,500 pages, 16 XML files, two nested XML levels, 5 MiB per XML, and 12 MiB total XML bytes. **Maximum eligible pages is a safety ceiling, not a request to import the first N pages**: if a sitemap has more pages, discovery fails before queueing. For a small first run, submit a narrower child XML instead of the root. Child page extraction has its own size, time and robots limits; jobs may fail when a page cannot yield usable text. The parent job's `completed` status means discovery and queueing finished; check **Pages** for indexing progress. Repeating a sitemap creates another crawl job whose page imports update stable source IDs; it does not automatically remove pages no longer present on the site. A failed parent can be retried up to the existing three-attempt limit, reusing its saved page list after partial queueing. This is a serial local worker, so a large crawl can take a long time; there is no cancel control yet. Scanned PDFs need OCR, and DOCX is not supported. The current SKU, price and stock tool continues to read PostgreSQL rather than imported RAG text.

The authenticated API equivalents are `POST /api/v1/ingestion/files`, `/urls`, and admin-only `/sitemaps`; `GET /api/v1/ingestion/jobs`, `/jobs/{id}`, `/jobs/{id}/pages`, and `/sources`; `POST /jobs/{id}/retry`; and `DELETE /sources/{source_id}`. The browser routes through the web proxy. See [the E4 implementation checkpoint](docs/e4_admin_ingestion_checkpoint.md) for limits and [the real-data baseline](docs/e4_real_data_baseline.md) for measured outcomes. Do not run `docker compose down --volumes` when restarting: the database, Qdrant, uploads and models live in named volumes.

Frontend checks:

    cd frontend
    npm test
    npm run build
    npm run test:browser

The browser smoke uses installed Google Chrome and a mocked API to exercise desktop/mobile login, retry, streaming, source links and downloads, refresh, history, focus and layout. It does not require a staff password or Ollama; use the local app for a live credentialed check.

Run the smoke tests while PostgreSQL is running:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests

Stop PostgreSQL with `docker compose stop db`; its data is retained. Keep `.env` and `backend/.venv/` out of Git.

For daily development, run one command from the project root:

    ./scripts/dev.sh

It starts PostgreSQL and Qdrant through Docker Compose, applies pending database migrations, starts the installed Ollama system service if needed, and runs FastAPI and the Vite frontend together. Open http://127.0.0.1:5173/ for the assistant or http://127.0.0.1:8000/docs for the API. If the frontend dependencies are missing, the script installs the locked packages with `npm ci`; the Python environment and first admin account still require the initial setup above. If Ollama is stopped, `sudo` may ask for your password. Press Ctrl+C to stop both app servers and the log followers; the Docker containers and Ollama service remain running. Stop the containers later with `docker compose stop db qdrant`.

## Internal login and roles

The first account must be an admin. A local operator can create additional accounts with the same command and `--role staff` or `--role admin`; the command always prompts for a password. Passwords are stored as salted scrypt hashes. Login issues a random bearer token valid for eight hours; PostgreSQL stores only its hash. Logout deletes that session, and disabling a user or changing a role takes effect on the next request. Both roles may query the current approved public-site seed; only admins may call `GET /api/v1/admin/users`. Retrieval enforces source visibility for each role, but no real staff-only document has been indexed yet.

In Postman, send `POST http://127.0.0.1:8000/api/v1/auth/login` with JSON `{"email":"you@example.com","password":"your-password"}`. Copy the returned `access_token` into Postman's **Authorization → Bearer Token** field. You can then call `GET /api/v1/auth/me`, `POST /api/v1/chat`, and `POST /api/v1/ask`; `POST /api/v1/auth/logout` revokes the token. Do not put passwords or bearer tokens into a committed file. Keep the API bound to localhost during development; HTTPS, login rate limiting, and broader role-scoped source rules remain deployment work.

If a password or token is exposed, reset that account locally. This prompts twice for a new password and deletes all of the account's existing login sessions; log in again afterward. It does not put the password in shell history:

    PYTHONPATH=backend backend/.venv/bin/python -m app.auth.reset_password --email you@example.com

## Local-model chat

All application chat-model calls use the shared behavioral instructions in `backend/app/llm/prompts.py`, followed by route-specific instructions for general answers or cited company evidence. This is a compact adaptation of the developer-supplied Sardars prompt: it does not embed unverified contact details, brand lists, policies, or a claim that the product tool reads live website pages. Exact SKU, price and stock results still come from PostgreSQL through application-controlled tools. Routes that answer directly in code do not call an LLM, so no model context is sent for those turns. Changing these instructions requires rebuilding/restarting the API image in the Docker workflow.

Recognizable medical and fertility questions return `route: out_of_scope` without a model or retrieval call; `/ask` abstains. This English keyword check prevents the observed conception-advice failure but is not comprehensive medical-intent detection.

For the older host-Ollama workflow, install Ollama using its [Linux instructions](https://docs.ollama.com/linux), then download the original small baseline model. The current Docker stack on this machine selects 4B as described above:

    ollama pull qwen3:0.6b

With Ollama and the API running, send a request from Postman using the bearer token above. For a terminal request, paste the token into a silent prompt first so it is not recorded in shell history:

    read -rs -p 'Bearer token: ' SARDARS_TOKEN; printf '\n'
    curl -sS http://127.0.0.1:8000/api/v1/chat -H "Authorization: Bearer $SARDARS_TOKEN" -H 'Content-Type: application/json' -d '{"message":"Explain what a database is in one sentence."}'

`POST /api/v1/chat` sends clear educational questions such as “What is a database?” to local Ollama. Product-price, SKU and exact-stock questions use a registered PostgreSQL read tool; combined product searches add authorized product-page descriptions; other Sardars questions use registered-source retrieval. The response has `route: general`, `product`, `product_search`, or `company`. Exact product answers use the developer-authorized current database values, include `product_source` and set `company_data_verified: true` after a successful read. Combined product answers return a `products` array and matching descriptive `sources`. Variant stock quantities are read from `public.products` at request time; zero means zero in that database snapshot. Currency, stock reservations and external Shopify/ERP synchronization remain unknown. Other company answers include numbered `sources` with `source_id`, title, Sardars URL, and `fetched_at`; unsupported questions have no citations. General answers have no company sources and may include model token counts and duration. The Ollama settings in `.env.example` default to `qwen3:0.6b` on localhost. Chat keeps that model resident for up to five minutes between requests; ingestion still uses `keep_alive=0`. No answer or company-fact cache is used.

For a company-overview example, send `{"message":"What is the category of business in which Sardars deal?"}`. The application keeps the registered About Us page within the final eight authorized evidence candidates, rechecks source permissions, and gives short source sentences plus the question to local Ollama. When exact-word matching finds no answer, the model may select a supporting sentence or abstain; the application returns only the selected source sentence and its validated citation. Natural About Us questions such as “Tell me about Sardars” and broad brand-offering questions now select directly supporting About Us sentences without requiring every question word to appear in the same sentence. A two-part “what is Sardars and what brands do they offer?” question can cite both source sentences. Single-name brand definitions such as “What is Bongio?” inspect authorized company-page evidence before the three-sentence answer cap, so matching product descriptions cannot crowd out that definition. This relaxation applies to descriptive company overview and brand lists; policy, price, stock, and product-feature claims retain stricter evidence requirements because the small model selected unrelated evidence when allowed to judge all company questions. If no authorized company-page evidence remains, the answer abstains without a citation.

Both `/api/v1/chat` and `/api/v1/ask` authenticate before reading the question body. Send `Content-Type: application/json` with a `message` of up to 2,000 characters and optionally up to three `product_handles`. Unknown fields, including client-supplied roles or system prompts, are rejected. The actual streamed body is capped at 32 KiB with a total 30-second read deadline; the byte budget accommodates escaped Unicode within the character limit. Missing/invalid/revoked authentication returns HTTP 401, oversized bodies 413, unsupported media types 415, invalid JSON or fields 422, stalled body reads 408, and interrupted reads 400. Validation errors return a short message without echoing submitted text.

Phase 8 also gives `/chat` a narrow scope decision: general product education remains available, Sardars-specific questions use authorized sources or registered PostgreSQL tools, and clear off-topic, instruction-override, private-data and unsupported-action requests return a short response without calling an answer service. `/ask` abstains on the latter requests. Retrieved page/PDF sentences and product tool fields are checked for instruction text before they reach a prompt or answer. Current CEO, policy, warranty, delivery and similar changing claims are not verified by descriptive pages; stock quantities use the later-authorized PostgreSQL product snapshot, while live sellable availability remains unverified. Dimensions need exact matching cited evidence. Direct URLs in descriptive excerpts are excluded; returned citation links still follow source authorization. The general model's answer is discarded if it adds a Sardars-specific claim.

Broad browsing phrases such as `{"message":"What products can I get under 10000?"}` and `{"message":"Show me basin mixers"}` now use the bounded PostgreSQL product search. Requests without a category return at most three active, visible products and indicate when more matches exist. Price limits without an explicit currency compare the stored numeric values; the response labels currency as unrecorded rather than assuming PKR or USD. Broad catalog ordering is by handle for now, so add a category, brand, or finish for more useful results.

Process-local limits allow 20 combined `/chat` and `/ask` requests per user per minute and 60 registered tool calls per user per minute. Login allows 60 attempts per socket IP and six per normalized account per minute; successful login clears that account's failure window. A limit returns HTTP 429 and `Retry-After`. Login JSON is bounded to 2 KiB and the same 30-second body-read deadline. Answer generation has a configurable five-minute total deadline (`SARDARS_ANSWER_TIMEOUT_SECONDS=300`, allowed range 5–300). The Ollama HTTP limit is 330 seconds and the web proxy waits 330 seconds, leaving a small margin beyond the answer deadline; the shorter product-route limits remain in place. The Ollama adapter requests no more than 256 generated tokens and rejects responses over 64 KiB. Answer timeouts return HTTP 504 without partial citations. Limits are held in each API process; shared deployment limits and proxy IP handling belong to production work. Cancellation cannot forcibly stop an already running synchronous thread, so retrieval HTTP calls and PostgreSQL statements have their own timeouts.

Run the focused request/guardrail checks with:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_question_requests.py backend/tests/test_rate_limits.py backend/tests/test_answer_deadlines.py backend/tests/test_ollama_limits.py backend/tests/test_chat.py backend/tests/test_auth.py

## Conversation memory

The first authenticated `POST /api/v1/chat` turn creates a conversation and returns `conversation_id`. Send that ID with a later message to continue it, for example `{"message":"How does it work?","conversation_id":"<returned-id>"}`. Omitting the ID starts a new conversation. `/api/v1/ask` remains stateless and rejects `conversation_id`. Use `GET /api/v1/conversations` to list your conversations, `GET /api/v1/conversations/{id}` to review a bounded page of messages, and `DELETE /api/v1/conversations/{id}` to remove one immediately. History pages accept `limit` (1–50) and `before_message_id`; list requests accept `limit` (1–50) and `offset` (0–1000). Conversation history requests allow 60 calls per user per minute and require the same revocable bearer login.

In Swagger `/docs`, send only `{"message":"What is a mixer?"}` for the first turn. Copy the returned `conversation_id` into the next `/chat` request. Do not submit generated placeholder values for `conversation_id` or `product_handles`; Swagger does not track chat sessions automatically.

The application includes at most eight recent general-route messages and 1,600 history characters for a recognizable follow-up, stopping at the most recent independent question. Company follow-ups may add the previous question to the *retrieval query* but still answer the current question from freshly authorized evidence. Product follow-ups carry only the immediately previous product handles and rerun the authorized PostgreSQL search; old prices and SKUs are never treated as current facts. Conversation text is separate from company knowledge. There is no rolling model summary yet because the current use case has no measured need for one.

Conversations expire 30 days after their last completed turn by default (`SARDARS_CONVERSATION_RETENTION_DAYS`, 1–365). Expired conversations are unavailable through the API; run the following command periodically to physically delete expired rows. The local prototype does not include a background scheduler, so deployment must schedule this command if automatic physical deletion is required:

    PYTHONPATH=backend backend/.venv/bin/python -m app.services.purge_conversations

History shows when an answer was created and warns that old business facts may be stale. Answers backed by a now-revoked source or hidden product are redacted on read. A conversation used while an account has admin access becomes admin-only; if that account is later downgraded, its owner can delete the conversation but cannot read or continue it. Successful turns store messages, model/timing/token metadata when present, source IDs and product handles. Failed and timed-out turns are not saved.

Run the focused memory checks with:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_conversations.py

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

Step 3 is complete for the local public-site workflow. Step 4 below extends it to authenticated submissions. The limited descriptive pipeline checkpoint was completed in Step 5 below; full saved-crawl coverage is active in Step 6. At that earlier checkpoint, structured company-database work and price/stock authority were deferred; the later product-tool and Phase 11 sections describe the current PostgreSQL proof of concept. Automatic website synchronization remains unimplemented. That checkpoint had eight website documents/twelve chunks, plus the separate staff-visible interview test PDF with twenty-six chunks; Step 6 records the later corpus.

## Phase 5 learning checkpoint — Step 4

At the Phase 5 checkpoint, admins and staff could submit one URL or file per request. The API authenticated before reading the upload body, extracted bounded descriptive text, retained the original in local storage, recorded the authenticated submitter, and ran the existing durable job. Processing was synchronous: the response waited for completion or a safe error containing the job ID. One ingestion request ran per API process; another received HTTP 429 with `Retry-After`. Job status remained available after a request ended or failed. The extraction subprocess enforced resource limits.

**Current E3 behavior:** `compose.local.yaml` runs a dedicated worker with `SARDARS_INGESTION_RUNNER=worker`. File and URL submissions, retries and removals return HTTP 202 with a pending `job_id`; poll the authenticated job endpoint for the result. Files are staged in the shared uploads volume, while URL fetching, extraction and indexing run in the worker. Removal becomes invisible before vector cleanup. The host-only `scripts/dev.sh` workflow remains inline by default. See [the E3 runner decision](docs/e3_ingestion_runner.md) for measurements, recovery, and limitations; Celery/Redis were not added.

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

The upload limit is 5 MiB and the multipart body limit includes 64 KiB of overhead. UTF-8 TXT/Markdown uploads may contain up to 250,000 extracted characters and 30,000 words; PDFs and website pages remain capped at 50,000 characters and 10,000 words, and PDFs at 50 pages. Extraction has a 30-second wall-clock limit, a 20-second CPU limit, and a 512 MiB process memory limit on Linux. Encrypted, malformed, blank, and scanned/image-only PDFs fail safely; OCR, DOCX, spreadsheets, and multilingual evaluation remain later work. This is descriptive RAG ingestion, not a price/inventory import.

`SARDARS_INGESTION_STORAGE_DIR` defaults to Git-ignored `data/uploads`. Originals use generated UUID names with restrictive permissions; user filenames are metadata, never paths. This directory is not served as static content. File citations point to the protected download endpoint; the original checksum is verified before download and untrusted content is sent as an attachment. Replacements/removals retain previous originals and job snapshots for recovery/history; there is no retention cleanup or full-data erasure endpoint yet. Back up both PostgreSQL and the configured storage directory.

A successful submission returns `job_id`, counts, and `sources` containing stable source IDs and citation URLs. Validation/extraction failures before job creation return HTTP 400/413/422 without a job. Indexing failures return HTTP 503 with `detail.job_id`; inspect that job and resolve the reported cause before retrying. API retries are for authenticated internal jobs; local-operator jobs still use the CLI. Limits are three total attempts, and permissions/account activity are checked again during processing. Logs record job IDs, attempts, counts, safe error codes, and duration, without document text or credentials.

`SARDARS_EMBEDDING_BATCH_SIZE` defaults to two chunks and supports one through eight. Smaller batches bound each model request more tightly on a CPU laptop. `SARDARS_IMPORT_TIMEOUT_SECONDS` defaults to 300 seconds and is capped at 600; this local installation uses 600. In the Compose worker, a TXT/Markdown document over the ordinary 50,000-character/10,000-word cap receives a separate `SARDARS_LARGE_TEXT_IMPORT_TIMEOUT_SECONDS` budget (default and maximum 7,200 seconds) and a matching durable lease. This does not speed up embedding; a large upload can occupy the serial worker for a long time while other jobs wait. The host-only inline workflow keeps its ordinary request budget. Model requests keep their existing bounded timeout and model-unload setting. Errors distinguish the overall processing budget, embedding/vector request timeouts, connection failures, and HTTP statuses without returning service bodies. If indexing fails, the source remains unavailable until recovery; retry the existing job rather than uploading a duplicate. If it cannot finish within the larger budget, split it into smaller documents.

Run the new checks:

    PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_ingestion_api.py backend/tests/test_ingestion_extraction.py

The opt-in test command above also verifies real authenticated uploads and private retrieval in disposable namespaces. It requires the local services and access to the authorized About Us page. Uploaded test documents and temporary accounts are isolated from the project database/index; they are not real company knowledge. Step 5 below adds a measured coverage/evaluation checkpoint. General answerability, wider source quality/ranking, and current facts still need later work.

## Phase 5 learning checkpoint — Step 5

The selected Step 5 checkpoint completed the limited V1 descriptive ingestion and synchronization pipeline. Full saved-crawl ingestion was later completed, with answer-quality failures still open. The developer deferred current price/stock and authoritative structured data to later company-database tools. Product tool calling was implemented in the Phase 6 proof of concept below. The [Step 5 report](docs/phase5_step5_report.md) records changes, evidence, commands, and limitations.

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

Add `--report data/extracted/UNUSED_NAME.json` to an audit/import/evaluation command to save local JSON evidence; existing files are refused. Saved source data and detailed reports remain Git-ignored. Avoid parallel Ollama evaluations/indexing on this laptop. The developer-authorized PostgreSQL table supplies internal-assistant prices, SKUs and variant stock quantities as read. Claims about external Shopify/ERP synchronization, reservations or real-time sellable availability require separate sources and freshness rules.


## Phase 5 Step 6 — resumable full saved-crawl coverage

`app.ingestion.full_site` prepares a fixed descriptive snapshot of all 1,008 saved records, then runs small serial jobs through the existing publication, permissions, cleanup, and retry mechanisms. It does not fetch a newer website snapshot. Full-site ingestion and repeat verification completed on 2026-10-15: all 999 eligible sources/3,739 chunks finished across 309 batches, with nine recorded exclusions. The then-current expanded evaluation passed 28/40 and the seed regression 4/7; retrieval/answer quality remains open. See [the completion outcomes](docs/phase5_full_site_completion_status.md) and [the coverage report](docs/phase5_full_site_report.md). At that point, price and stock tools had not been implemented; the later product-tool and Phase 11 sections record the authorized PostgreSQL values. Contact/hours and guaranteed business promises remain outside verified current answers.

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


The detached serial continuation has finished with `indexed_with_evaluation_failures`. Import and complete-plan replay succeeded; all 999 sources were verified/skipped on replay. Expanded evaluation passed 28/40 (19/31 live, 8/8 trust controls, 1/1 routing; 15/24 supported-source hits), and the original seed passed 4/7. Inspect `data/extracted/full_site_continuation.json`, its `.log`, `data/extracted/full_site_completion_evaluation.json`, and `docs/phase5_full_site_completion_status.md` for outcomes. These supersede the partial checkpoint counts/scores above. Ingestion is complete; full-corpus answer-quality failures remain open. The separate Phase 6 CSV proof of concept is described below.

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.ingestion.full_site
tail -f data/extracted/full_site_continuation.log
```


## Phase 6 — read-only product tool

The Shopify CSV/PostgreSQL proof of concept uses `public.products` with all 88 named export columns and row provenance. The original 4,983 rows / 2,009 handles were imported before the developer assigned prices and SKUs to every row. The developer now designates the stored price, SKU and stock values as valid for this internal assistant. Product-price, SKU or exact-stock questions invoke the registered `get_product_details` tool through application code, using an exact SKU/handle or bounded product-name match. Results come from PostgreSQL at request time. An exact SKU on one of the 1,893 image-only CSV rows is identified as such; handle/name lookups show the 3,090 variant rows. `search_products` also supports bounded in-stock (`> 0`) and out-of-stock (`= 0`) variant filters. Currency, reservations, sellable availability and external synchronization remain unknown. See [the CSV validation report](docs/phase6_shopify_csv_validation.md), [the schema/import guide](docs/phase6_shopify_products.md), and [the Phase 6 tool guide](docs/phase6_product_tool.md).

The tool registry allowlists `get_source_status`, `get_product_details`, and `search_products` with strict Pydantic inputs/results and authenticated execution. The application chooses the product tools for price/SKU and catalog-search questions so the response does not depend on Ollama selecting a tool. The local Ollama tool-call adapter remains available; ERP integration and internet search are separate future integrations. The ERP access checklist and metadata-tool evidence are in [the Phase 6 source contract](docs/phase6_source_contract.md).

Phase 7 is complete for numeric price searches without a currency claim. Its `search_products` tool supports staff recommendations and comparisons. A combined query filters the PostgreSQL catalog first, then cites descriptive text from the matching registered product-page URL after the usual source authorization check. For example, send `{"message":"Recommend black wall mounted basin mixers under 1000"}` to `/api/v1/chat`. The response uses `route: "product_search"` and includes `products`, `sources`, and `product_handles`. To compare the shown items, send `{"message":"Which of these is cheaper?","product_handles":["first-handle","second-handle"]}` using handles from the first response. Each follow-up rechecks visibility and prices. See [the Phase 7 guide](docs/phase7_combined_product_search.md) for filters, citation rules and limits. Explicit PKR/USD price filters require a recorded database currency; current rows do not have one.

After logging in as staff or admin, send `POST /api/v1/chat` with `{"message":"Is SKU TEST-1 in stock?"}`. The `product` route returns its PostgreSQL SKU, price, variant stock quantity and `product_source.database_observed_at`; `current_stock_verified` means the database quantity was present at that read. A product-name question such as `{"message":"What is the price and SKU for Sculptural Flush Plate OLI Voronoi?"}` returns its variants. Ambiguous names ask for a SKU or handle. The tool does not guarantee a reservation or external-system freshness.

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

## Phase 11 — full evaluation

The [historical baseline](docs/phase11_evaluation_baseline.md) records the first 23-case pre-stock run. The [completion report](docs/phase11_evaluation_completion.md) records the 26-case stock-aware suite, identical repeat, full-site/seed rechecks, measured latency and token use, quality thresholds and remaining failures. The evaluator checks routes, actual tool calls, independent database price/SKU/stock facts, expected retrieval/citations, unsupported answers and latency. Isolated API tests cover authenticated stock answers, saved streaming/history and revocation. The frontend's browser smoke uses a mocked API; a live credentialed browser pass remains deferred.

With PostgreSQL, Qdrant and Ollama running, use a new report filename each time:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_chat --report data/extracted/phase11_chat_NEW_NAME.json
PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.compare_chat data/extracted/phase11_gate_final_b_20261018.json data/extracted/phase11_chat_NEW_NAME.json
PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests/test_chat_evaluation.py backend/tests/test_chat_comparison.py backend/tests/test_stock_api.py
```

Run live evaluations serially. Reports remain internal and Git-ignored; existing files are refused. The initial stock-aware pair passed **23/26**. After targeted corrections and a stronger bathroom-definition check, two same-definition runs passed the bounded **26/26** chat gate (18/18 live, 8/8 isolated controls), with a controlled repeat comparison. The retained seed suite passed **7/7**, while the full-site suite passed **31/40** and still has nine open retrieval/evidence failures. This small chat gate does not certify the whole corpus or production quality. The [completion report](docs/phase11_evaluation_completion.md) separates historical and latest results.

## Phase 12 — optimization after measurement

Retrieval now inspects up to 32 role-prefiltered Qdrant candidates, rechecks each against PostgreSQL source authorization, and passes at most eight to the bounded answer selector. Specific-subject questions get a small lexical title/text rerank; broad product discovery keeps semantic order. The registered About Us profile hint remains within the final eight. A separate five-minute chat-model keep-alive avoids repeated model loads while keeping the existing ingestion/embedding unload setting. `SARDARS_OLLAMA_CHAT_KEEP_ALIVE=0` disables the residency trade-off on a memory-constrained host. No response, embedding or business-fact cache is used.

The measured internal-prototype full-site score rose from **31/40** to **34/40**, with required-source hits from **18/24** to **21/24** and no passing case regressing; the chat and seed suites remained **26/26** and **7/7**. Six full-corpus cases remain open. See the [Phase 12 report](docs/phase12_optimization_report.md) for latency, memory, commands and limitations. Historical Phase 5 reports retain their original outcomes.
