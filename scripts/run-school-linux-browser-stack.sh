#!/usr/bin/env bash
# Full School-Linux stack with Mac TCP forwards; run from the repository root.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY is required}"

remote_root=/home/sapiece/AstraLive
evidence_dir="$remote_root/integration/evidence/school-linux"
final_evidence_dir="$remote_root/integration/evidence/school-linux-final"

cleanup() {
  for pid in "${frontend_pid:-}" "${backend_pid:-}" "${runtime_pid:-}" "${runtime_proxy_pid:-}" "${tool_proxy_pid:-}" "${tunnel_pid:-}"; do
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; fi
  done
  ssh -o BatchMode=yes school-linux '
    for pid_file in /tmp/astralive-school-{frontend,backend,runtime,runtime-proxy,tool-proxy}.pid; do
      if test -f "$pid_file"; then kill "$(cat "$pid_file")" 2>/dev/null || true; rm -f "$pid_file"; fi
    done
  ' 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

ssh -o BatchMode=yes school-linux "mkdir -p '$evidence_dir' '$final_evidence_dir'"
ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
  -N -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 -L 16391:127.0.0.1:6379 school-linux & tunnel_pid=$!

ssh -o BatchMode=yes school-linux '
  cd "$HOME/AstraLive"
  echo $$ > /tmp/astralive-school-runtime-proxy.pid
  exec runtime/.venv/bin/python -m integration.observe_proxy --listen 18082 --upstream http://127.0.0.1:18000 --evidence integration/evidence/school-linux-final/runtime-tool.jsonl
' > /private/tmp/astralive-school-runtime-proxy.log 2>&1 & runtime_proxy_pid=$!

ssh -o BatchMode=yes school-linux '
  cd "$HOME/AstraLive"
  echo $$ > /tmp/astralive-school-tool-proxy.pid
  exec runtime/.venv/bin/python -m integration.observe_proxy --listen 18083 --upstream http://127.0.0.1:18080 --evidence integration/evidence/school-linux-final/runtime-tool.jsonl
' > /private/tmp/astralive-school-tool-proxy.log 2>&1 & tool_proxy_pid=$!

printf '%s\n%s\n' "$DEEPSEEK_API_KEY" "${ASTRALIVE_RTMP_ACCEPTANCE:-0}" | ssh -o BatchMode=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 school-linux '
  set -euo pipefail
  read -r LLM_API_KEY
  read -r RTMP_ACCEPTANCE
  export LLM_API_KEY LLM_BASE_URL=https://api.deepseek.com LLM_MODEL=deepseek-flash LLM_MAX_TOKENS=1024
  set -a; source "$HOME/AstraLive/backend/.env.integration"; set +a
  export REDIS_URL=redis://127.0.0.1:6379/14 REDIS_RUNTIME_EVENT_STREAM=dh.runtime.events.v1
  export TOOL_BASE_URL=http://127.0.0.1:18083
  export TOOL_TOKEN="$INTERNAL_API_TOKEN"
  export MOCK_LLM=false MOCK_TTS=false MOCK_AVATAR=false MOCK_MEDIA=false
  export WEBRTC_ENABLED=true
  if [[ "$RTMP_ACCEPTANCE" == "1" ]]; then
    export RTMP_ENABLED=true RTMP_URL=rtmp://127.0.0.1:1935/live RTMP_STREAM_KEY=astralive-test
    export RTMP_WIDTH=720 RTMP_HEIGHT=1280 RTMP_FPS=25
    export RTMP_VIDEO_BITRATE=3000k RTMP_AUDIO_BITRATE=128k RTMP_AUDIO_SAMPLE_RATE=48000
    export RTMP_PRESET=veryfast RTMP_VIDEO_BUFFER_MS=400 RTMP_AUDIO_BUFFER_MS=400
  fi
  export TARGET_FPS=25 TARGET_VIDEO_BUFFER_MS=400 MAX_VIDEO_BUFFER_MS=1000
  export TARGET_AUDIO_BUFFER_MS=400 MAX_AUDIO_BUFFER_MS=1000 CAPTURE_TTS_TEXT_EVIDENCE=1
  export TTS_MODEL_DIR="$HOME/AstraLive/runtime/.local/vits-piper-zh_CN-xiao_ya-medium"
  export PYTHONPATH="$HOME/AstraLive/runtime"
  cd "$HOME/AstraLive"
  echo $$ > /tmp/astralive-school-runtime.pid
  exec runtime/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18000
' > /private/tmp/astralive-school-runtime.log 2>&1 & runtime_pid=$!

ssh -o BatchMode=yes school-linux '
  set -euo pipefail
  export PATH="$HOME/.local/bin:$PATH"
  cd "$HOME/AstraLive"
  set -a; source backend/.env.integration; set +a
  export HTTP_ADDR=127.0.0.1:18080
  export DATABASE_URL="${DATABASE_URL/15432/5432}"
  export REDIS_URL="${REDIS_URL/16391/6379}"
  export AI_RUNTIME_URL=http://127.0.0.1:18082
  echo $$ > /tmp/astralive-school-backend.pid
  exec /tmp/astralive-school-backend
' > /private/tmp/astralive-school-backend.log 2>&1 & backend_pid=$!

ssh -o BatchMode=yes school-linux '
  cd "$HOME/AstraLive"
  export ASTRALIVE_BASE_URL=http://127.0.0.1:18080 FRONTEND_PORT=18081
  echo $$ > /tmp/astralive-school-frontend.pid
  exec runtime/.venv/bin/python scripts/preview_proxy.py
' > /private/tmp/astralive-school-frontend.log 2>&1 & frontend_pid=$!

for _ in {1..45}; do
  if curl -fsS http://127.0.0.1:18080/health/ready >/dev/null 2>&1 && curl -fsS http://127.0.0.1:18081/ >/dev/null 2>&1; then
    echo "School-Linux browser stack ready"
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:18080/health/ready >/dev/null
wait "$runtime_pid"
