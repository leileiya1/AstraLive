#!/usr/bin/env bash
set -euo pipefail
mode="${1:-mock}"
case "$mode" in
  mock) profile=mock; runtime=mock-runtime ;;
  real) profile=real; runtime=real-runtime ;;
  *) echo 'usage: integration-test.sh mock|real' >&2; exit 2 ;;
esac
cd "$(dirname "$0")/.."
RUNTIME_SERVICE="$runtime" docker compose -f infra/compose.yaml --profile "$profile" up -d --build postgres redis "$runtime" backend frontend
runtime/.venv/bin/python -m unittest tests.test_contracts -v
ASTRALIVE_BASE_URL="http://127.0.0.1:${BACKEND_PORT:-18080}" runtime/.venv/bin/python tests/e2e.py --heartbeat
