#!/usr/bin/env bash
# Provisions and destroys ONLY its own temporary cluster. No shared services/Redis/GPU are touched.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
pg_bin="${DURABILITY_PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}"
python_bin="${DURABILITY_TEST_PYTHON:-$repo_root/runtime/.venv/bin/python}"
if [[ ! -x "$pg_bin/initdb" || ! -x "$python_bin" ]]; then
  echo 'Set DURABILITY_PG_BIN and DURABILITY_TEST_PYTHON to installed PostgreSQL and Runtime Python binaries.' >&2
  exit 1
fi
pg_data="$(mktemp -d "${TMPDIR:-/tmp}/astralive-pg-chaos.XXXXXX")"
owner="$("$python_bin" -c 'import uuid;print(uuid.uuid4().hex)')"
port="$("$python_bin" -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"
cleanup() {
  if [[ -f "$pg_data/.astralive-durability-owned" && "$(cat "$pg_data/.astralive-durability-owned")" == "$owner" ]]; then
    "$pg_bin/pg_ctl" -D "$pg_data" -m fast stop >/dev/null 2>&1 || true
    rm -rf "$pg_data"
  fi
}
trap cleanup EXIT
"$pg_bin/initdb" -D "$pg_data" -A trust --no-locale -E UTF8 >/dev/null
printf "\nport = %s\nlisten_addresses = '127.0.0.1'\n" "$port" >> "$pg_data/postgresql.conf"
printf '%s' "$owner" > "$pg_data/.astralive-durability-owned"
"$pg_bin/pg_ctl" -D "$pg_data" -l "$pg_data/postgres.log" start >/dev/null
"$pg_bin/createdb" -h 127.0.0.1 -p "$port" astralive_durability
export DURABILITY_TEST_DATABASE_URL="postgres://$(id -un)@127.0.0.1:$port/astralive_durability?sslmode=disable"
export DURABILITY_TEST_PYTHON="$python_bin"
cd "$repo_root"
CONFIG_TEST_DATABASE_URL="$DURABILITY_TEST_DATABASE_URL" go -C backend test -p 1 ./... -count=1
CONFIG_TEST_DATABASE_URL="$DURABILITY_TEST_DATABASE_URL" go -C backend test -race -p 1 ./... -count=1
DURABILITY_OWNED_PGDATA="$pg_data" DURABILITY_PG_CTL="$pg_bin/pg_ctl" DURABILITY_PG_OWNER="$owner" go -C backend test ./internal/durability -run '^TestOwnedPostgresOutage$' -count=1 -v
PYTHONPATH=runtime "$python_bin" -m unittest discover -s runtime/tests -p test_durability.py -v
uv run --no-project --python "$python_bin" --with openapi-spec-validator --with jsonschema --with pyyaml contracts/validate_v1_1.py
