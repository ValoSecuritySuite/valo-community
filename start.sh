#!/usr/bin/env bash
# One-command launcher for Valo Community Edition.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

API_URL="${VALO_API_URL:-http://localhost:8000}"
UI_URL="${VALO_UI_URL:-http://localhost:8080}"

if [[ -f .env.example && ! -f .env ]]; then
  echo "==> Creating .env from .env.example..."
  cp .env.example .env
fi

echo "==> Starting Valo Community Edition (Docker)..."
docker compose up --build -d

echo "==> Waiting for API health..."
for _ in $(seq 1 30); do
  if curl -sf "${API_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! curl -sf "${API_URL}/health" >/dev/null 2>&1; then
  echo "ERROR: API did not become healthy at ${API_URL}/health" >&2
  exit 1
fi

cat <<EOF

Valo Community Edition is ready.

  Web UI                     ${UI_URL}/
  API docs                   ${API_URL}/docs
  Health check               ${API_URL}/health

Stop:  docker compose down
Logs:  docker compose logs -f

EOF
