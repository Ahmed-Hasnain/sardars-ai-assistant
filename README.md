# Sardars AI Assistant

A self-hosted AI assistant for Sardars staff. It combines a local language model with approved company documents, a PostgreSQL product catalog, and bounded web search so answers can use the right source for the question.

**Status:** The internal-prototype implementation cycle is closed. E1–E7 checkpoints are complete in their measured scopes; [E8 live acceptance](EXTENDED_PLAN.md) and production deployment are deferred. This is not a public customer service or a production deployment.

## What it does

- Answers company questions using role-visible documents and webpages, with citations to the sources used.
- Reads SKU, price, and stock facts from PostgreSQL rather than treating retrieved pages as current catalog data.
- Lets an admin upload text-based PDF, TXT, or Markdown files, add approved URLs, and crawl a bounded sitemap. A worker reports job progress and supports retries, updates, and source removal.
- Offers a read-only web search tool for recent public questions. Web results are labelled separately from company sources.
- Keeps authenticated conversations and rechecks source visibility when historical citations are viewed.

The assistant runs locally with **FastAPI, React/TypeScript, PostgreSQL, Qdrant, Ollama, and SearXNG**. Ollama provides the chat and embedding models; Qdrant indexes descriptive source chunks; PostgreSQL stores accounts, conversations, ingestion jobs, source registrations, and catalog facts. SearXNG runs locally, but public search queries still reach external search engines.

## Quick start

You need Docker with the Compose plugin and Python 3 for the one-time secret setup. Run these commands from the repository root.

### 1. Clone and configure

```bash
git clone https://github.com/Ahmed-Hasnain/sardars-ai-assistant.git
cd sardars-ai-assistant
cp .env.example .env
python3 - <<'PY'
from pathlib import Path
from secrets import token_urlsafe

path = Path(".env")
settings = path.read_text()
for key in ("SARDARS_DB_PASSWORD", "SARDARS_SEARXNG_SECRET"):
    settings = settings.replace(
        f"{key}=replace-with-random-value",
        f"{key}={token_urlsafe(48)}",
    )
path.write_text(settings)
path.chmod(0o600)
PY
```

The generated `.env` is ignored by Git. For an existing installation, keep its current database password and volumes instead of replacing `.env`.

### 2. Start the stack

```bash
docker compose -f compose.local.yaml up -d --build
docker compose -f compose.local.yaml ps
```

The first start downloads container images and the Ollama chat/embedding models, so it can take a while. Compose also applies database migrations and creates the compatible empty Qdrant collection. Wait for `api` to become healthy and `web` to start.

### 3. Create the first admin

```bash
docker compose -f compose.local.yaml exec api \
  python -m app.auth.create_user --email you@example.com --role admin
```

Enter a password when prompted. The first user must be an admin; you can use the same command with `--role staff` for later staff accounts.

Open the [web app](http://127.0.0.1:15173/) and sign in. The [API docs](http://127.0.0.1:18000/docs) and [readiness check](http://127.0.0.1:18000/api/v1/ready) are available locally.

A fresh clone does **not** contain the private uploaded knowledge base or product catalog. After signing in, use **Knowledge sources** to add approved documents or URLs. The separate [Shopify CSV import guide](docs/phase6_shopify_products.md) explains how a trusted operator loads catalog rows; without those rows, exact product answers have no catalog facts to read.

### Stop and restart

```bash
docker compose -f compose.local.yaml down
docker compose -f compose.local.yaml up -d
```

`down` keeps the named volumes for PostgreSQL, Qdrant, uploads, and Ollama models. Do not add `--volumes` if you want to keep your data. The tested [backup and restore guide](docs/e1_backup_restore.md) covers those volumes.

For a 16 GB Apple Silicon Mac, see the [Mac profile](docs/e1_local_container_checkpoint.md#mac-mini-with-16-gb-memory). Hosts with an NVIDIA Container Toolkit can add `-f compose.local.nvidia.yaml`.

## Try it

Once you have imported suitable data, ask:

- “What is Sardars?” for a cited company answer.
- “Show me basin mixers” for catalog-backed product suggestions.
- “What is the latest Python release?” for a labelled web-search answer.

Company and catalog answers depend on what you have imported and what your role can see. Web snippets are not authority for Sardars prices, stock, or policies. The current product catalog may lack verified currency and external synchronization timestamps, so a database snapshot is not a live store guarantee.

## Development and tests

The Docker quick start needs no host Python packages or Node.js. To run the test suites locally, install Python 3.12+ and Node.js 20.19+ or 22.12+, then keep the Docker database running:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.lock
SARDARS_DB_PORT=15432 PYTHONPATH=backend backend/.venv/bin/python -m pytest -q backend/tests

npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

For startup problems, inspect `docker compose -f compose.local.yaml logs --tail=100 models migrate vector_init api web`. The [local-stack checkpoint](docs/e1_local_container_checkpoint.md) explains the services and ports. The older host-run workflow remains in `scripts/dev.sh`.

## Project layout

| Path | Purpose |
| --- | --- |
| `backend/app` | API, authentication, retrieval, model orchestration, tools, and ingestion worker |
| `backend/tests` | Backend behavior and integration tests |
| `frontend` | React chat and admin knowledge-source UI |
| `compose.local.yaml` | Local Docker stack |
| `docs` | Detailed design decisions, evaluations, and operating guides |

The [original prototype plan](PLAN.md) records the early phases. The [current roadmap](EXTENDED_PLAN.md) defines the extended checkpoints, and [implementation status](IMPLEMENTATION_STATUS.md) records verified behavior and open limits. [AGENTS.md](AGENTS.md) gives repository-specific development rules.
