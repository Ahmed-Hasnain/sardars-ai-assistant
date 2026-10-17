#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -x backend/.venv/bin/python ]]; then
  echo "Missing backend/.venv. Create the Python environment first." >&2
  exit 1
fi

for program in docker curl journalctl node npm; do
  if ! command -v "$program" >/dev/null 2>&1; then
    echo "Missing required command: $program" >&2
    exit 1
  fi
done

if [[ ! -x frontend/node_modules/.bin/vite ]]; then
  echo "Installing frontend dependencies from frontend/package-lock.json..."
  npm --prefix frontend ci
fi

if curl --silent --max-time 2 http://127.0.0.1:8000/api/v1/health >/dev/null; then
  echo "An API is already running on port 8000. Stop its terminal before using this command." >&2
  exit 1
fi

if curl --silent --max-time 2 http://127.0.0.1:5173/ >/dev/null; then
  echo "A frontend is already running on port 5173. Stop its terminal before using this command." >&2
  exit 1
fi

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

compose_logs_pid=
ollama_logs_pid=
api_pid=
frontend_pid=

cleanup() {
  trap - EXIT
  for pid in "$api_pid" "$frontend_pid" "$compose_logs_pid" "$ollama_logs_pid"; do
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$api_pid" "$frontend_pid" "$compose_logs_pid" "$ollama_logs_pid"; do
    if [[ -n "$pid" ]]; then
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker compose logs --follow --no-color --tail=10 db qdrant &
compose_logs_pid=$!
journalctl --follow --no-pager --lines=10 -u ollama &
ollama_logs_pid=$!

echo "Starting FastAPI at http://127.0.0.1:8000..."
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000 &
api_pid=$!

echo "Starting the frontend at http://127.0.0.1:5173/ (Ctrl+C stops both app servers and log followers)."
(
  cd frontend
  exec ./node_modules/.bin/vite --host 127.0.0.1 --port 5173 --strictPort
) &
frontend_pid=$!

if wait -n "$api_pid" "$frontend_pid"; then
  echo "An app server stopped. Shutting down the other processes." >&2
  exit 1
else
  status=$?
  echo "An app server exited with status $status. Shutting down the other processes." >&2
  exit "$status"
fi
