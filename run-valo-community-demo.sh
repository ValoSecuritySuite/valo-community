#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
chmod +x "$0" 2>/dev/null || true

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install/start Docker, then rerun this script." >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is required." >&2
  exit 1
fi

"${COMPOSE[@]}" up --build -d
echo "Valo Community demo is starting."
echo "Frontend: http://localhost:8080"
echo "API:      http://localhost:8000"
echo "Docs:     http://localhost:8000/docs"
echo "Stop with: ${COMPOSE[*]} down"
