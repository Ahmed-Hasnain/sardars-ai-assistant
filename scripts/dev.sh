#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -x backend/.venv/bin/python ]]; then
  echo "Missing backend/.venv. Create the Python environment first." >&2
  exit 1
fi

for program in docker curl journalctl; do
  if ! command -v "$program" >/dev/null 2>&1; then
    echo "Missing required command: $program" >&2
    exit 1
  fi
done

echo "Starting PostgreSQL and Qdrant..."
COMPOSE_PROGRESS=plain docker compose up -d --wait db qdrant

echo "Applying database migrations..."
backend/.venv/bin/alembic upgrade head

if ! curl --fail --silent --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "Starting the host Ollama service (sudo may request your password)..."
  sudo systemctl start ollama
fi

for attempt in {1..20}; do
  if curl --fail --silent --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
    break
  fi
  if (( attempt == 20 )); then
    echo "Ollama did not become ready at 127.0.0.1:11434." >&2
    exit 1
  fi
  sleep 1
done

if curl --fail --silent --max-time 2 http://127.0.0.1:8000/api/v1/health >/dev/null; then
  echo "An API is already running on port 8000. Stop its terminal before using this command." >&2
  exit 1
fi

docker compose logs --follow --no-color --tail=10 db qdrant &
compose_logs_pid=$!
journalctl --follow --no-pager --lines=10 -u ollama &
ollama_logs_pid=$!

cleanup() {
  trap - EXIT
  kill "$compose_logs_pid" "$ollama_logs_pid" 2>/dev/null || true
  wait "$compose_logs_pid" "$ollama_logs_pid" 2>/dev/null || true
}
trap cleanup EXIT

echo "Starting FastAPI at http://127.0.0.1:8000 (Ctrl+C stops the API and log followers)."
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
