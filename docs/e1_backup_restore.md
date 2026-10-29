# E1 local data backup and restore

The local Compose project is `sardars-e1`. Its PostgreSQL, Qdrant, uploads, and Ollama volumes hold different parts of one working assistant. Back up all four together while the stack is stopped. A normal `stop`, `start`, `up`, or `down` retains them; **never use `down --volumes` for a routine restart**. Store archives privately: they contain user records, source files, vectors, and model data. This is a local recovery procedure, not an off-machine backup policy.

## Cold backup

From the repository root, first finish or pause ingestion and inspect `docker compose -f compose.local.yaml ps`. Then:

```bash
set -e
mkdir -p data/extracted/e1_backup
chmod 700 data/extracted/e1_backup
docker compose -f compose.local.yaml stop
for component in postgres qdrant uploads ollama; do
  volume="sardars-e1_e1_${component}_data"
  if [ "$component" = uploads ]; then volume=sardars-e1_e1_uploads; fi
  docker run --rm --user 0:0 \
    -v "$volume:/source:ro" \
    -v "$PWD/data/extracted/e1_backup:/backup" \
    --entrypoint tar sardars-e1-api \
    -C /source -cf "/backup/${component}.tar" .
done
chmod 600 data/extracted/e1_backup/*.tar
(cd data/extracted/e1_backup && sha256sum *.tar > SHA256SUMS && chmod 600 SHA256SUMS && sha256sum -c SHA256SUMS)
docker compose -f compose.local.yaml up -d --wait
```

`data/extracted/` is Git-ignored. Copy the archive directory to a separate protected disk if machine loss is in scope. Keep the checksum file with the archives. Check free space before backing up; the 2026-10-21 Ollama archive alone was about 3.5 GB.

## Non-destructive restore rehearsal

The safest verification restores to **new names** on a private network, never over the live volumes. Pick a unique prefix and confirm `docker volume ls` contains no volume with that prefix. The following example uses `e1restore_test`; change it for each rehearsal:

```bash
set -e
(cd data/extracted/e1_backup && sha256sum -c SHA256SUMS)
docker volume ls --format '{{.Name}}' | grep '^e1restore_test_' || true
for component in postgres qdrant uploads ollama; do
  docker volume create "e1restore_test_${component}"
  docker run --rm --user 0:0 \
    -v "e1restore_test_${component}:/target" \
    -v "$PWD/data/extracted/e1_backup:/backup:ro" \
    --entrypoint tar sardars-e1-api \
    -C /target -xf "/backup/${component}.tar"
done
docker network create e1restore_test_net
docker run -d --name e1restore_test_db --network e1restore_test_net \
  -e POSTGRES_USER=sardars -e POSTGRES_DB=sardars -e POSTGRES_PASSWORD=scratch-unused \
  -v e1restore_test_postgres:/var/lib/postgresql postgres:18
docker run -d --name e1restore_test_qdrant --network e1restore_test_net \
  -v e1restore_test_qdrant:/qdrant/storage qdrant/qdrant:v1.19.2
docker run -d --name e1restore_test_ollama --network e1restore_test_net \
  -v e1restore_test_ollama:/root/.ollama ollama/ollama:0.12.6
docker run -d --name e1restore_test_api --network e1restore_test_net \
  --env-file .env \
  -e SARDARS_DB_HOST=e1restore_test_db -e SARDARS_DB_PORT=5432 \
  -e SARDARS_QDRANT_BASE_URL=http://e1restore_test_qdrant:6333 \
  -e SARDARS_OLLAMA_BASE_URL=http://e1restore_test_ollama:11434 \
  -e SARDARS_INGESTION_STORAGE_DIR=/app/data/uploads \
  -v e1restore_test_uploads:/app/data/uploads:ro \
  --entrypoint uvicorn sardars-e1-api app.main:app --host 0.0.0.0 --port 8000
docker exec e1restore_test_api python -c \
  'import httpx; print(httpx.get("http://127.0.0.1:8000/api/v1/ready", timeout=20).status_code)'
docker exec e1restore_test_api python -c \
  'from app.evaluation.run_chat import data_fingerprint; print(data_fingerprint())'
docker exec e1restore_test_api python -m app.evaluation.fingerprint_collection
docker exec e1restore_test_api python -c \
  'from app.evaluation.e4_inventory import inventory; from app.core.config import Settings; x=inventory(Settings()); print(x["source_count"], x["point_count"], x["job_count"], x["integrity_failures"]); assert not x["integrity_failures"] and all(s["original_checksum_ok"] and s["snapshot_checksum_ok"] and s["snapshot_chunks_match"] for s in x["sources"])'
docker exec e1restore_test_ollama ollama list
```

The restored API should return `200`; retry its read-only readiness command if it runs before Uvicorn is listening. Compare SQL and vector fingerprints, source/job counts, original checksums and Ollama model names with values recorded before backup. The restored API is deliberately not published to the host. Replace the sample `sardars` user/database names if `.env` differs. `POSTGRES_PASSWORD=scratch-unused` is only an initialization placeholder: an already initialized PostgreSQL volume retains its original database credential from `.env`.

After verification, remove **only these scratch names**:

```bash
docker rm -f e1restore_test_api e1restore_test_db e1restore_test_qdrant e1restore_test_ollama
docker network rm e1restore_test_net
for component in postgres qdrant uploads ollama; do docker volume rm "e1restore_test_${component}"; done
```

If the live stack ever needs recovery, stop it, preserve its current volumes as a second backup, verify archive checksums, and restore into newly named volumes first. Do not extract an archive into a nonempty live volume. Move the application to the verified restored copies only after checking their data and credentials.

On 2026-10-21, the four-volume cold backup, checksum verification, live restart, scratch restore, restored API readiness, and SQL/Qdrant/source/model comparisons passed. Evidence is in Git-ignored `data/extracted/e1_20261021/`; the scratch copies were removed after verification.
