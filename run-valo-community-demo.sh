#!/usr/bin/env bash
set -euo pipefail

test -f requirements.txt && test -f web/package.json || { echo "Run from the valo-community repository root."; exit 1; }

python -m pip install -r requirements.txt
test -d web/node_modules || npm --prefix web ci

if ! curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
  nohup env APP_EDITION=community APP_ENFORCEMENT_MODE=monitor APP_LOG_LEVEL=INFO \
    APP_RATE_LIMIT=100/minute APP_CORRELATION_ENGINE_ENABLED=false \
    APP_EXECUTIVE_METRICS_ENABLED=false APP_REPORTS_ENABLED=false \
    APP_PLAYBOOKS_ENABLED=false APP_LEARNING_LOOP_ENABLED=false \
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
    >/tmp/valo-community-api.log 2>&1 &
  echo $! >/tmp/valo-community-api.pid
fi

for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break; sleep 1; done
curl -fsS http://127.0.0.1:8000/health >/dev/null || { tail -n 200 /tmp/valo-community-api.log; exit 1; }

if ! curl -fsS http://127.0.0.1:8080 >/dev/null 2>&1; then
  nohup env VITE_BACKEND_URL=http://127.0.0.1:8000 VITE_VALO_EDITION=community \
    npm --prefix web run dev -- --host 127.0.0.1 --port 8080 \
    >/tmp/valo-community-web.log 2>&1 &
  echo $! >/tmp/valo-community-web.pid
fi

for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:8080 >/dev/null 2>&1 && break; sleep 1; done
curl -fsS http://127.0.0.1:8080 >/dev/null || { tail -n 200 /tmp/valo-community-web.log; exit 1; }
python scripts/community_smoke.py
echo "Valo Community demo ready: UI http://localhost:8080 | API docs http://localhost:8000/docs"

