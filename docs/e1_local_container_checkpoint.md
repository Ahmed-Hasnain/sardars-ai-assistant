# E1 local container checkpoint

This is an **isolated E1 development stack**, not a deployment. `compose.local.yaml` runs a separate `sardars-e1` project on localhost ports 15173 (web) and 18000 (API). Its PostgreSQL, Qdrant, Ollama and upload volumes have distinct names; starting it does not migrate or erase the volumes used by `compose.yaml` and `scripts/dev.sh`. Do not use `docker compose down --volumes` for either project unless a reviewed data-reset procedure calls for it.

## Start and inspect

On a new machine, install Docker Engine with the Compose plugin, copy `.env.example` to `.env`, and set a private `SARDARS_DB_PASSWORD`. Docker Compose reads `.env` for the database credentials and application model choice. The image build context excludes `.env`, local uploads and extracted data. From the repository root:

```bash
docker compose -f compose.local.yaml config --quiet
docker compose -f compose.local.yaml up -d --build
docker compose -f compose.local.yaml ps
curl -fsS http://127.0.0.1:18000/api/v1/ready
curl -fsS http://127.0.0.1:15173/api/v1/health
```

Open `http://127.0.0.1:15173/`. The web container serves the built frontend and proxies `/api` to the API over the private Compose network. PostgreSQL is published to **localhost only** on port 15432 for local database clients such as DataGrip; Qdrant's API root is `http://127.0.0.1:16333` and its browser dashboard is `http://127.0.0.1:16333/dashboard`. Ollama has no published host port in this stack. Use database/user from `.env` and enter `SARDARS_DB_PASSWORD` privately in the client. The one-shot `migrate` service applies Alembic migrations. The one-shot `vector_init` service creates the empty 1,024-dimensional cosine Qdrant collection if missing and rejects an incompatible existing collection; it never resets existing points. The one-shot `models` service pulls the configured `SARDARS_OLLAMA_MODEL` and the fixed `qwen3-embedding:0.6b` into Ollama's named volume before the API starts. The first `up` can take a long time because it downloads the Ollama image and both models; later starts reuse the volume. Check `docker compose -f compose.local.yaml logs --tail=100 ollama models vector_init migrate api web` if readiness fails. API `/ready` checks PostgreSQL; use an authenticated chat request to verify the model path.

E3 adds a dedicated `worker` service using the same API image and upload volume. In this Compose stack, ingestion requests return HTTP 202 with a job ID while the worker performs bounded extraction and indexing. E4 adds the admin browser workspace and worker-backed sitemap import; see [the E4 checkpoint](e4_admin_ingestion_checkpoint.md). Inspect `docker compose -f compose.local.yaml logs --tail=100 worker` and poll the authenticated job endpoint. The host-only development workflow remains inline unless separately configured. See [the E3 runner report](e3_ingestion_runner.md).

The isolated stack originally started with an empty database and Qdrant collection. The developer later copied **only the 4,983-row product catalog** from the original PostgreSQL database into this E1 database. E1 still has no copied users, conversations, source registrations or full-site corpus, and Qdrant remains empty. A Sardars company question should therefore return an evidence-based abstention until data is ingested, not a list of brands. Copying source code and `.env` to another machine will not transfer these records; export and restore the persistent data separately when that is needed. The Ollama model files persist in `sardars-e1_e1_ollama_data` and can be checked with:

```bash
docker compose -f compose.local.yaml exec ollama ollama list
```

CPU execution is the portable default. On a machine with an NVIDIA GPU and the NVIDIA Container Toolkit configured for Docker, add the GPU override to **every** Compose command for that stack, for example:

```bash
docker compose -f compose.local.yaml -f compose.local.nvidia.yaml up -d --build
```

The GPU override grants GPU access only to Ollama. It does not expose Ollama publicly or change the application-to-model URL. See the [official Ollama Docker guide](https://docs.ollama.com/docker) for host driver/toolkit prerequisites. E2 measured a 4B chat model and the developer selected it for the current local Docker stack through `SARDARS_OLLAMA_MODEL`; a fresh stack pulls the configured standard Ollama tag when missing.

### Mac mini with 16 GB memory

Check `uname -m`: `arm64` means Apple Silicon; `x86_64` means an Intel Mac mini. Install the matching Docker Desktop build and use the optional Mac override with **every** Compose command for this stack. It keeps the complete stack in containers and sets a modest Ollama workload: one request per model, at most two loaded models (chat and embedding), and at most eight queued requests. Additional requests wait or fail when the queue fills. The app's own rate and deadline limits still apply.

```bash
docker compose -f compose.local.yaml -f compose.local.mac.yaml config --quiet
docker compose -f compose.local.yaml -f compose.local.mac.yaml up -d --build
docker compose -f compose.local.yaml -f compose.local.mac.yaml ps
docker compose -f compose.local.yaml -f compose.local.mac.yaml exec ollama ollama ps
```

Start with `SARDARS_OLLAMA_MODEL=qwen3:0.6b` in `.env`. The pinned Compose images advertise Linux ARM64 variants and Docker should select them automatically on Apple Silicon; do not force `linux/amd64` or add the NVIDIA override on this Mac. Docker Desktop allocates a limited-memory Linux VM (normally half of host RAM by default, about 8 GB on a 16 GB Mac). Begin with that default, then check Docker Desktop **Settings → Resources** and `docker stats` while using chat and ingestion. Increase the VM memory only if measured pressure or out-of-memory failures require it, while leaving enough memory for macOS and other apps. Keep the model data volume and adequate free disk space for images, model pulls and uploaded data. No fixed container memory cap is imposed because the later E2 model comparison needs measured headroom.

The important trade-off is speed: [Ollama states that Docker Desktop on macOS has no GPU passthrough](https://docs.ollama.com/faq#how-do-i-use-ollama-with-gpu-acceleration-in-docker), so this all-container mode uses the Mac's CPU rather than its Metal GPU on Apple Silicon. A 4B or 8B model may fit in memory yet respond slowly; measure latency and memory in E2 before choosing one. [Native macOS Ollama supports Apple GPU acceleration through Metal](https://docs.ollama.com/gpu#metal-apple-gpus), but adopting a host-Ollama mode would change the all-container setup and should follow that measurement. The Mac profile has been Compose-validated on the current Linux machine; it has not yet been run on the target Mac mini.

Create a first admin in the isolated database when testing authenticated flows; the CLI prompts privately for a password:

```bash
docker compose -f compose.local.yaml exec -it api python -m app.auth.create_user --email you@example.com --role admin
```

The current upload path is a named volume mounted at `/app/data/uploads`. Normal `stop`, `start`, `up --build` and `down` retain existing E1 volumes. Use `docker compose -f compose.local.yaml stop` when finished; `docker compose -f compose.local.yaml start` resumes existing containers. This stack is separate from `scripts/dev.sh` and can coexist with the original database/vector services because its published app ports differ.

## Verified first checkpoint, 2026-10-19

After the first complete Ollama/model pull on this laptop, the API, database and Ollama were healthy, and the web proxy returned success. Both model names appeared in `ollama list`. A signed-in browser request for Sardars brands returned HTTP 503 because the fresh Qdrant volume had no collection; the Qdrant log showed HTTP 404 on the collection scroll request. The new `vector_init` job created the empty collection before API startup. Its live rerun reported `already compatible` without deleting it. A read-only brand search returned zero approved chunks; both the grounded-answer CLI and the exact admin company-answer service returned `I can't verify that from the available sources.` Focused collection/chat tests passed **37**. The user's authenticated browser retry is still needed; this does not establish ingestion, product lookup, citations or full E1 completion.

The signed-in browser then confirmed that company questions safely abstained, but also showed two wording gaps: `ok tell me what is mixer` and a question about the world's countries were incorrectly routed to company retrieval. Narrow router rules now send the former to general product education and the latter to `out_of_scope`; a reviewed bathroom-mixer definition covers the exact bare phrasing, and the general-model instruction supplies the bathroom sense for close phrasings. After rebuilding, read-only live answer-path probes of the screenshot's four questions and `What is a mixer?` returned the expected routes and bathroom meaning. Focused tests passed **92** after the last prompt change. The full backend suite passed **609**, with three opt-in skips, inside the isolated API with `SARDARS_IMPORT_TIMEOUT_SECONDS=300` before that final prompt wording; it was not rerun after the wording change. No new company evidence was ingested. Earlier saved answers remain historical, and the user's browser has not been retried after this routing fix.

`docker compose ... config --quiet` passed. The API and web images built successfully, including the frontend TypeScript/Vite production build. The isolated stack started and Alembic reached revision `e91c0a84f5d2 (head)`. The API readiness endpoint and the frontend's `/api/v1/health` proxy returned success; the frontend returned HTML 200. The API ran as non-root UID 999, wrote a temporary upload-volume marker, and read it after a full stop/start before removing it. The migration revision and web-proxied readiness also survived restart. Three existing health tests passed inside the API image. Their two warnings were an existing Starlette/httpx deprecation and pytest's inability to write cache under read-only `/app` as the non-root user. The original `sardars-ai-assistant` PostgreSQL/Qdrant containers stayed up throughout.

The original optional Ollama image pull was started but stopped because this pinned image has a roughly 1.9 GB layer and the local download was slow. After that observation, the roadmap was changed to make Ollama a default Compose service with automatic model initialization. The new Ollama/model-init path has not yet been exercised on this machine. No model files were pulled and no authenticated chat, product or RAG result was checked in this isolated stack. These checks are still required before E1 is complete.

## Verification still needed for the E1 exit

The developer has deferred these data-backed checks until after E4's existing-admin source-ingestion journey. Internal account registration and approval are later work. E2 used the retained original evaluation corpus and workflow; the empty isolated E1 index is not an equivalent E2 baseline. This is not E1 completion. Do not copy or clear the existing corpus merely to make this new stack appear populated.

- Complete the authenticated general-chat and controlled upload/retrieval/citation flow in the isolated stack; image/model pulls and a signed-in safe-abstention browser path have already been observed.
- Verify product lookup against controlled rows in the isolated database; empty catalog answers alone are insufficient.
- Restart every service and verify login, data, model files, upload originals and vector points persist.
- Compare the basic chat/retrieval latency with the existing host workflow, including CPU and any available GPU machine.
- Document a tested backup/restore procedure for the isolated volumes before calling E1 complete. No production HTTPS, shared rate limiting or public hosting is implied.
