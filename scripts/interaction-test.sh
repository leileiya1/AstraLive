#!/usr/bin/env bash
# Uses ONLY caller-provided disposable databases. Never starts GPU/real Providers.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${CONFIG_TEST_DATABASE_URL:?set an independent disposable PostgreSQL URL}"
: "${INTERACTION_TEST_REDIS_URL:?set an independent disposable Redis URL}"
export DATABASE_URL="$CONFIG_TEST_DATABASE_URL"
export RUN_INTERACTION_CPU=1
export INTERACTION_TEST_EVIDENCE="$PWD/docs/v0.4/evidence/formal-session-cpu.json"
python_bin="${INTERACTION_TEST_PYTHON:-$PWD/runtime/.venv/bin/python}"
export INTERACTION_TEST_PYTHON="$python_bin"
(cd backend && go test ./...)
(cd backend && go test -race ./...)
PYTHONPATH=runtime "$python_bin" -m unittest discover -s runtime/tests -v
"$python_bin" -m unittest tests.test_contracts tests.test_acceptance_guards -v
(cd frontend && bun run build && bun run test)
(cd backend && go run ./cmd/comment-load > ../docs/v0.4/evidence/comment-load.json)
(cd backend && go run ./cmd/comment-load -wall > ../docs/v0.4/evidence/comment-load-wall.json)
git diff --check
