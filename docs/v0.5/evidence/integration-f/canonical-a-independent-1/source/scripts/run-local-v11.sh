#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
source backend/.env.integration
set +a
mkdir -p integration/evidence
(cd backend && go build -o /tmp/astralive-v11-backend ./cmd/server)
ssh -o BatchMode=yes -N -L 15432:127.0.0.1:5432 -L 16391:127.0.0.1:6379 school-linux & tunnel=$!
cleanup() {
  for p in "${backend_pid:-}" "${runtime_pid:-}" "${runtime_proxy_pid:-}" "${tool_proxy_pid:-}" "$tunnel"; do
    if [[ -n "$p" ]]; then kill "$p" 2>/dev/null || true; fi
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT
sleep 1
for mode in ${1:-mock real light}; do
  evidence="integration/evidence/${mode}-v1.1.jsonl"
  : > "$evidence"
  export ASTRALIVE_FAULT_FILE="$(pwd)/integration/evidence/fault.json"
  rm -f "$ASTRALIVE_FAULT_FILE"
  python3 -m integration.observe_proxy --listen 18082 --upstream http://127.0.0.1:18000 --evidence "$evidence" > "/tmp/astralive-${mode}-runtime-proxy.log" 2>&1 & runtime_proxy_pid=$!
  python3 -m integration.observe_proxy --listen 18083 --upstream http://127.0.0.1:18080 --evidence "$evidence" > "/tmp/astralive-${mode}-tool-proxy.log" 2>&1 & tool_proxy_pid=$!
  if [[ "$mode" == mock ]]; then
    REDIS_URL="$REDIS_URL" runtime/.venv/bin/python -m uvicorn integration.mock_runtime.app:app --host 127.0.0.1 --port 18000 > "/tmp/astralive-${mode}-runtime.log" 2>&1 & runtime_pid=$!
  elif [[ "$mode" == light ]]; then
    REDIS_URL="$REDIS_URL" TOOL_BASE_URL=http://127.0.0.1:18083 TOOL_TOKEN="$INTERNAL_API_TOKEN" MOCK_TTS=false MOCK_AVATAR=false MOCK_MEDIA=false TTS_MODEL_DIR="$(pwd)/runtime/.local/vits-piper-zh_CN-xiao_ya-medium" PYTHONPATH=runtime runtime/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18000 > "/tmp/astralive-${mode}-runtime.log" 2>&1 & runtime_pid=$!
  else
    REDIS_URL="$REDIS_URL" TOOL_BASE_URL=http://127.0.0.1:18083 TOOL_TOKEN="$INTERNAL_API_TOKEN" MOCK_MEDIA=false PYTHONPATH=runtime runtime/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18000 > "/tmp/astralive-${mode}-runtime.log" 2>&1 & runtime_pid=$!
  fi
  AI_RUNTIME_URL=http://127.0.0.1:18082 /tmp/astralive-v11-backend > "/tmp/astralive-${mode}-backend.log" 2>&1 & backend_pid=$!
  if [[ "$mode" == real ]]; then
    ASTRALIVE_EVIDENCE_FILE="$evidence" runtime/.venv/bin/python tests/e2e.py --require-evidence --heartbeat --require-tool --webrtc --browser --failure --redis-failure
  elif [[ "$mode" == light ]]; then
    ASTRALIVE_EVIDENCE_FILE="$evidence" runtime/.venv/bin/python tests/e2e.py --require-evidence --heartbeat --require-tool --webrtc --browser
  else
    ASTRALIVE_EVIDENCE_FILE="$evidence" runtime/.venv/bin/python tests/e2e.py --require-evidence --heartbeat
  fi
  kill "$backend_pid" "$runtime_pid" "$runtime_proxy_pid" "$tool_proxy_pid" 2>/dev/null || true
  wait "$backend_pid" "$runtime_pid" "$runtime_proxy_pid" "$tool_proxy_pid" 2>/dev/null || true
  unset backend_pid runtime_pid runtime_proxy_pid tool_proxy_pid
  rm -f "$ASTRALIVE_FAULT_FILE"
  sleep 1
done
