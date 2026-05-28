#!/usr/bin/env bash
# Drive the Valo AI Firewall demo end-to-end:
#   1. start a fake OpenAI upstream on :9999
#   2. start Valo in enforce mode pointed at the fake upstream
#   3. wait for /health
#   4. drive the customer app through allow / warn / deny scenarios
#   5. print live audit trail
#   6. shut everything down
#
# Usage:
#   bash demo/firewall/run_demo.sh
#
# To run against the real OpenAI instead of the fake upstream:
#   USE_REAL_OPENAI=1 OPENAI_API_KEY=sk-... bash demo/firewall/run_demo.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DEMO_DIR="$ROOT_DIR/demo/firewall"
LOG_DIR="$DEMO_DIR/.logs"
mkdir -p "$LOG_DIR"

UPSTREAM_PORT=${UPSTREAM_PORT:-9999}
VALO_PORT=${VALO_PORT:-8000}
USE_REAL_OPENAI=${USE_REAL_OPENAI:-0}

cleanup() {
  set +e
  if [[ -n "${VALO_PID:-}" ]]; then kill "$VALO_PID" 2>/dev/null; fi
  if [[ -n "${UPSTREAM_PID:-}" ]]; then kill "$UPSTREAM_PID" 2>/dev/null; fi
  wait 2>/dev/null
}
trap cleanup EXIT

cd "$ROOT_DIR"

if [[ "$USE_REAL_OPENAI" = "1" ]]; then
  : "${OPENAI_API_KEY:?Set OPENAI_API_KEY when USE_REAL_OPENAI=1}"
  UPSTREAM_URL="https://api.openai.com/v1/chat/completions"
  echo "[demo] using real OpenAI upstream"
else
  echo "[demo] starting fake upstream on :$UPSTREAM_PORT"
  python3 "$DEMO_DIR/fake_openai.py" --port "$UPSTREAM_PORT" \
    > "$LOG_DIR/fake_openai.log" 2>&1 &
  UPSTREAM_PID=$!
  UPSTREAM_URL="http://127.0.0.1:$UPSTREAM_PORT/v1/chat/completions"
  for _ in $(seq 1 30); do
    sleep 0.2
    if curl -fsS -o /dev/null -X POST "http://127.0.0.1:$UPSTREAM_PORT" \
        -H 'Content-Type: application/json' -d '{}' 2>/dev/null; then break; fi
  done
fi

echo "[demo] starting Valo in enforce mode on :$VALO_PORT (upstream=$UPSTREAM_URL)"
APP_ENFORCEMENT_MODE=enforce \
APP_PROXY_UPSTREAM_URL="$UPSTREAM_URL" \
  uvicorn app.main:app --host 127.0.0.1 --port "$VALO_PORT" \
  > "$LOG_DIR/valo.log" 2>&1 &
VALO_PID=$!

echo -n "[demo] waiting for Valo health"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$VALO_PORT/health" >/dev/null 2>&1; then
    echo " ok"
    break
  fi
  echo -n "."
  sleep 0.5
done

echo "[demo] running customer scenarios"
OPENAI_BASE_URL="http://127.0.0.1:$VALO_PORT/v1/proxy" \
OPENAI_API_KEY="${OPENAI_API_KEY:-sk-test-anything}" \
VALO_API_URL="http://127.0.0.1:$VALO_PORT" \
  python3 "$DEMO_DIR/scenarios.py"

echo
echo "[demo] logs: $LOG_DIR"
echo "[demo] done. tearing down."
