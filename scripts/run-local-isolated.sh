#!/usr/bin/env bash
# Fully local AstraLive default-mode stack for browser checks (no school-linux,
# no shared database, no GPU, no RTMP push, Durable LIVE stays disabled).
#   Backend (Go)        127.0.0.1:18080   private PostgreSQL + Redis
#   Runtime (Python)    127.0.0.1:18000   real Runtime, mock AI, WebRTC media
#   Frontend + proxy    http://127.0.0.1:18081
# Everything lives in a fresh temp directory and is stopped/removed on exit.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
PGBIN=${PGBIN:-/opt/homebrew/opt/postgresql@17/bin}
RUNTIME_PY=${RUNTIME_PY:-runtime/.venv/bin/python}
export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
for port in 18000 18080 18081; do
  if lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port is busy; stop the other process first" >&2; exit 2
  fi
done
free_port() { python3 -c "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1])"; }
WORK=$(mktemp -d /tmp/astralive-local-XXXX)
PIDS=()
cleanup() {
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
  "$PGBIN/pg_ctl" -D "$WORK/pg" stop -m fast >/dev/null 2>&1 || true
  [ -n "${REDIS_PORT:-}" ] && redis-cli -p "$REDIS_PORT" shutdown nosave >/dev/null 2>&1 || true
  rm -rf "$WORK"
  echo "local stack stopped and removed"
}
trap cleanup EXIT INT TERM

PG_PORT=$(free_port); REDIS_PORT=$(free_port)
"$PGBIN/initdb" -D "$WORK/pg" -A trust -U astralive >/dev/null
"$PGBIN/pg_ctl" -D "$WORK/pg" -l "$WORK/pg.log" -o "-h 127.0.0.1 -p $PG_PORT -k ''" -w start >/dev/null
"$PGBIN/createdb" -h 127.0.0.1 -p "$PG_PORT" -U astralive astralive
redis-server --port "$REDIS_PORT" --bind 127.0.0.1 --save '' --appendonly no \
  --daemonize yes --dir "$WORK" >/dev/null
TOKEN=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))")

(cd backend && go build -o "$WORK/backend" ./cmd/server)
(cd frontend && VITE_API_BASE_URL= bun run build >"$WORK/frontend-build.log" 2>&1)

APP_ENV=development HTTP_ADDR=127.0.0.1:18080 \
  DATABASE_URL="postgres://astralive@127.0.0.1:$PG_PORT/astralive?sslmode=disable" \
  REDIS_URL="redis://127.0.0.1:$REDIS_PORT/0" REDIS_RUNTIME_EVENT_STREAM=dh.runtime.events.v1 \
  AI_RUNTIME_URL=http://127.0.0.1:18000 INTERNAL_API_TOKEN="$TOKEN" \
  "$WORK/backend" >"$WORK/backend.log" 2>&1 & PIDS+=($!)
REDIS_URL="redis://127.0.0.1:$REDIS_PORT/0" TOOL_BASE_URL=http://127.0.0.1:18080 \
  TOOL_TOKEN="$TOKEN" MOCK_MEDIA=false RTMP_ENABLED=false PYTHONPATH=runtime \
  "$RUNTIME_PY" -m uvicorn app.main:app --host 127.0.0.1 --port 18000 \
  >"$WORK/runtime.log" 2>&1 & PIDS+=($!)
FRONTEND_PORT=18081 python3 scripts/preview_proxy.py >"$WORK/proxy.log" 2>&1 & PIDS+=($!)

for _ in $(seq 1 100); do
  curl -fsS http://127.0.0.1:18081/health/ready >/dev/null 2>&1 && break
  sleep 0.2
done
curl -fsS http://127.0.0.1:18081/health/ready && echo
echo "AstraLive local stack ready: http://127.0.0.1:18081  (logs: $WORK)"
wait
