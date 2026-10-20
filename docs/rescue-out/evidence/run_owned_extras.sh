#!/usr/bin/env bash
# Runs the four Go tests that need an Agent2-style *owned* layout:
#   TestPostgresIsolatedServerOutage   (stops/restarts its own PG on :55462)
#   TestRedisIsolatedDisconnectAndSQLFallback (owned Redis :56382 db 0)
#   TestInteractionFormalCPU           (real Python Runtime child, SQL+Redis)
#   TestEventDedupAndStateUpdateWithPostgres (plain DATABASE_URL)
# Everything lives in a fresh /tmp/astralive-agent2-rescue-* directory that is
# removed on exit; existing /tmp/astralive-agent2-* directories are not touched.
# Usage: docs/rescue-out/evidence/run_owned_extras.sh <out-dir>
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
PGBIN=${GUARDIAN_TEST_PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}
export PATH="$PGBIN:$PATH" LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
for port in 55462 56382; do
  if lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port busy; refusing to share it" >&2; exit 2
  fi
done
WORK=$(mktemp -d /tmp/astralive-agent2-rescue-XXXX)
cleanup() {
  pg_ctl -D "$WORK/pg" stop -m fast >/dev/null 2>&1
  redis-cli -p 56382 shutdown nosave >/dev/null 2>&1
  rm -rf "$WORK" "$WORK/pg.log"
}
trap cleanup EXIT
initdb -D "$WORK/pg" -A trust -U rescue_owner >/dev/null
touch "$WORK/pg/AGENT2_OWNED"
pg_ctl -D "$WORK/pg" -l "$WORK/pg.log" -o "-h 127.0.0.1 -p 55462 -k /tmp" -w start >/dev/null
for d in agent2_owned agent2_cfg agent2_legacy; do
  createdb -h 127.0.0.1 -p 55462 -U rescue_owner "$d"
done
# The legacy dedup test expects an already migrated schema.
for m in "$ROOT"/backend/db/migrations/*.sql; do
  psql -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 55462 -U rescue_owner -d agent2_legacy -f "$m" >/dev/null || exit 3
done
mkdir -p "$WORK/redis" && touch "$WORK/redis/AGENT2_OWNED"
redis-server --port 56382 --bind 127.0.0.1 --save '' --appendonly no \
  --daemonize yes --dir "$WORK/redis" >/dev/null
sleep 0.5
U="postgres://rescue_owner@127.0.0.1:55462"
export DURABLE_LIVE_TEST_DATABASE_URL="$U/agent2_owned?sslmode=disable"
export DURABLE_LIVE_TEST_REDIS_URL="redis://127.0.0.1:56382/0"
export DURABLE_LIVE_ISOLATED_PGDATA="$WORK/pg"
export DURABLE_LIVE_ISOLATED_REDISDIR="$WORK/redis"
export DURABLE_LIVE_TEST_PYTHON="$ROOT/.venv-guardian/bin/python"
export CONFIG_TEST_DATABASE_URL="$U/agent2_cfg?sslmode=disable"
export INTERACTION_TEST_REDIS_URL="redis://127.0.0.1:56382/2"
export INTERACTION_TEST_PYTHON="$ROOT/.venv-gpusim/bin/python"
export RUN_INTERACTION_CPU=1
export DATABASE_URL="$U/agent2_legacy?sslmode=disable"
cd "$ROOT/backend"
{ date -u +%FT%TZ; echo "head=$(git rev-parse HEAD) work=$WORK"; } >"$OUT/summary.txt"
run() { # label package regex
  go test -race -count=1 -v "$2" -run "$3" >"$OUT/$1.txt" 2>&1
  printf '%-16s exit=%s  %s\n' "$1" "$?" "$(grep -E '^(--- |ok|FAIL)' "$OUT/$1.txt" | tr '\n' ' ' | cut -c1-200)" | tee -a "$OUT/summary.txt"
}
run pg-outage    ./internal/durablelive '^TestPostgresIsolatedServerOutage$'
run redis-owned  ./internal/durablelive '^TestRedisIsolatedDisconnectAndSQLFallback$'
run interaction  ./internal/httpapi     '^TestInteractionFormalCPU$'
run legacy-dedup ./tests                '^TestEventDedupAndStateUpdateWithPostgres$'
