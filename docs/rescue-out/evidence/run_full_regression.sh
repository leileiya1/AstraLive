#!/usr/bin/env bash
# Full local regression for the rescue/main integration. Usage:
#   docs/rescue-out/evidence/run_full_regression.sh <out-dir>
# Needs: .venv-guardian, .venv-gpusim (gpu_worker/requirements-simulation.txt +
# runtime/requirements.txt + pillow/aiohttp/pytest/psutil), PostgreSQL 17
# binaries, MediaMTX, redis-server, go, bun.
# Private PG/Redis are started on loopback and removed on exit. Redis must
# use 127.0.0.1:56382 (a Go test guard); the run refuses if it is busy.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
PY="$ROOT/.venv-guardian/bin/python"
PGBIN=${GUARDIAN_TEST_PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}
export GUARDIAN_TEST_MEDIAMTX=${GUARDIAN_TEST_MEDIAMTX:-/tmp/astralive-guardian-tools/mediamtx}
export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
WORK=$(mktemp -d /tmp/alreg.XXXX)
SUMMARY="$OUT/summary.txt"
cd "$ROOT"

cleanup() {
  "$PGBIN/pg_ctl" -D "$WORK/pg" stop -m fast >/dev/null 2>&1
  redis-cli -p 56382 shutdown nosave >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

step() { # name, command...
  local name=$1; shift
  local start=$(date +%s)
  "$@" >"$OUT/$name.txt" 2>&1
  local code=$?
  printf '%-22s exit=%-3s %4ss  %s\n' "$name" "$code" "$(( $(date +%s) - start ))" \
    "$(grep -E '(passed|failed|^OK|^FAILED|^PASS|^CHECK)' "$OUT/$name.txt" | tail -1)" | tee -a "$SUMMARY"
}

{ date -u +%FT%TZ; echo "head=$(git rev-parse HEAD) index-tree=$(git write-tree)"; } >"$SUMMARY"
step guardian   "$PY" -m pytest output_guardian/tests -p no:cacheprovider -q -rfEs
step contracts  "$PY" -m unittest tests.test_contracts tests.test_durable_live_contracts \
  tests.test_durable_answer_contracts tests.test_answer_contract_repairs \
  tests.test_receiver_contracts tests.test_receiver_stop_races
step adapter-wire "$PY" -m unittest tests.test_receiver1_wiring tests.test_durable_live_v2_wire
step journal    "$PY" -m pytest -p no:cacheprovider runtime/tests/test_durable_live_journal.py -q
step validator-v1 "$PY" scripts/validate-durable-live-contracts.py
step validator-v2 "$PY" scripts/validate-answer-contract.py
step generated  "$PY" scripts/durable-live/generate_v2_wire.py --check
step diff-check git diff --check HEAD
step runtime    env PYTHONPATH=runtime "$PY" -m unittest discover -s runtime/tests -p 'test_*.py'
step gpu-worker env PYTHONPATH=runtime "$ROOT/.venv-gpusim/bin/python" -m pytest gpu_worker/tests -p no:cacheprovider -q
step frontend   sh -c 'cd frontend && bun install --frozen-lockfile && bun run test && bun run build'

PORT=$("$PY" -c "import socket;s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1])")
"$PGBIN/initdb" -D "$WORK/pg" -A trust -U rescue_owner >/dev/null
"$PGBIN/pg_ctl" -D "$WORK/pg" -o "-h 127.0.0.1 -p $PORT -k ''" -l "$WORK/pg.log" start >/dev/null
sleep 1
for d in agent2_rescue agent2_v2_rescue rescue_cfg; do
  "$PGBIN/createdb" -h 127.0.0.1 -p "$PORT" -U rescue_owner "$d"
done
if lsof -nP -iTCP:56382 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "redis port 56382 busy; Go Redis case will fail" | tee -a "$SUMMARY"
else
  redis-server --port 56382 --bind 127.0.0.1 --save '' --appendonly no \
    --daemonize yes --dir "$WORK" >/dev/null
fi
U="postgres://rescue_owner@127.0.0.1:$PORT"
export DURABLE_LIVE_TEST_DATABASE_URL="$U/agent2_rescue?sslmode=disable"
export DURABLE_V2_TEST_DATABASE_URL="$U/agent2_v2_rescue?sslmode=disable"
export CONFIG_TEST_DATABASE_URL="$U/rescue_cfg?sslmode=disable"
export DURABLE_LIVE_TEST_REDIS_URL="redis://127.0.0.1:56382/1"
export DURABLE_LIVE_TEST_PYTHON="$PY"
cd backend
step go-vet go vet ./...
go test -p 1 -race -count=1 -json ./... >"$OUT/go-race.jsonl" 2>"$OUT/go-race.stderr.txt"
code=$?
"$PY" - "$OUT/go-race.jsonl" "$code" <<'EOF' | tee -a "$SUMMARY"
import collections, json, sys
c = collections.Counter(); fails = []
for line in open(sys.argv[1]):
    try: e = json.loads(line)
    except ValueError: continue
    if e.get("Test") and "/" not in e["Test"] and e.get("Action") in ("pass", "fail", "skip"):
        c[e["Action"]] += 1
        if e["Action"] == "fail": fails.append(e["Package"].split("/")[-1] + "." + e["Test"])
print(f"go-race                exit={sys.argv[2]:<3} {dict(c)} fails={fails}")
EOF
