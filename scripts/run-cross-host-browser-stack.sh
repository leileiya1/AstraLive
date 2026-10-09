#!/usr/bin/env bash
# Isolated acceptance stack; run from the repository root.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
source backend/.env.integration
set +a
evidence="$(pwd)/integration/evidence/${ASTRALIVE_TOOL_EVIDENCE_NAME:-browser-connected-runtime-tool.jsonl}"
: > "$evidence"

cleanup() {
  for pid in "${frontend_pid:-}" "${backend_pid:-}" "${runtime_proxy_pid:-}" "${tool_proxy_pid:-}" "${runtime_ssh_pid:-}" "${ubuntu_tunnel_pid:-}" "${school_tunnel_pid:-}"; do
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; fi
  done
  ssh -o BatchMode=yes ubuntu-server 'if test -f /tmp/astralive-browser-soak-runtime.pid; then kill "$(cat /tmp/astralive-browser-soak-runtime.pid)" 2>/dev/null || true; rm -f /tmp/astralive-browser-soak-runtime.pid; fi' 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT

ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -N -L 15432:127.0.0.1:5432 -L 16391:127.0.0.1:6379 school-linux & school_tunnel_pid=$!
ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -N -L 18000:127.0.0.1:18000 -R 16391:127.0.0.1:16391 -R 18083:127.0.0.1:18083 ubuntu-server & ubuntu_tunnel_pid=$!
python3 -m integration.observe_proxy --listen 18082 --upstream http://127.0.0.1:18000 --evidence "$evidence" > /private/tmp/astralive-browser-runtime-proxy.log 2>&1 & runtime_proxy_pid=$!
python3 -m integration.observe_proxy --listen 18083 --upstream http://127.0.0.1:18080 --evidence "$evidence" > /private/tmp/astralive-browser-tool-proxy.log 2>&1 & tool_proxy_pid=$!
sleep 2
printf '%s\n' "$INTERNAL_API_TOKEN" | ssh -o BatchMode=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 ubuntu-server 'read -r TOOL_TOKEN; export TOOL_TOKEN REDIS_URL=redis://127.0.0.1:16391/14 TOOL_BASE_URL=http://127.0.0.1:18083 MOCK_LLM=true MOCK_TTS=false MOCK_AVATAR=false MOCK_MEDIA=false TTS_MODEL_DIR=/home/sapiece/astralive-browser-acceptance-20261007/runtime/.local/vits-piper-zh_CN-xiao_ya-medium PYTHONPATH=/home/sapiece/astralive-browser-acceptance-20261007/runtime; cd /home/sapiece/astralive-browser-acceptance-20261007; echo $$ > /tmp/astralive-browser-soak-runtime.pid; exec runtime/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18000' > /private/tmp/astralive-browser-runtime.log 2>&1 & runtime_ssh_pid=$!
AI_RUNTIME_URL=http://127.0.0.1:18082 /private/tmp/astralive-v11-backend > /private/tmp/astralive-browser-backend.log 2>&1 & backend_pid=$!
python3 scripts/preview_proxy.py > /private/tmp/astralive-browser-frontend.log 2>&1 & frontend_pid=$!

for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:18080/health/ready >/dev/null 2>&1 && curl -fsS http://127.0.0.1:18081/ >/dev/null 2>&1; then
    echo "Cross-host browser stack ready"
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:18080/health/ready >/dev/null
wait "$runtime_ssh_pid"
