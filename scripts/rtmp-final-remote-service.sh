#!/usr/bin/env bash
set -euo pipefail

service=${1:?service name is required}
root=${ASTRALIVE_ROOT:-$HOME/AstraLive}
evidence="$root/integration/evidence/rtmp-final"
secret_env=${ASTRALIVE_SECRET_ENV:-/run/user/$UID/astralive-rtmp-final.env}
mkdir -p "$evidence"
cd "$root"

case "$service" in
  runtime)
    exec >>"$evidence/runtime.log" 2>&1
    set -a
    source "$secret_env"
    source backend/.env.integration
    set +a
    export REDIS_URL=redis://127.0.0.1:6379/14 REDIS_RUNTIME_EVENT_STREAM=dh.runtime.events.v1
    export TOOL_BASE_URL=http://127.0.0.1:18083 TOOL_TOKEN="$INTERNAL_API_TOKEN"
    export MOCK_LLM=false MOCK_TTS=false MOCK_AVATAR=false MOCK_MEDIA=false WEBRTC_ENABLED=true
    export RTMP_ENABLED=true RTMP_URL=rtmp://127.0.0.1:1935/live RTMP_STREAM_KEY=astralive-test
    export RTMP_WIDTH=720 RTMP_HEIGHT=1280 RTMP_FPS=25 RTMP_VIDEO_BITRATE=3000k
    export RTMP_AUDIO_BITRATE=128k RTMP_AUDIO_SAMPLE_RATE=48000 RTMP_PRESET=veryfast
    export RTMP_VIDEO_BUFFER_MS=400 RTMP_AUDIO_BUFFER_MS=400
    export TARGET_FPS=25 TARGET_VIDEO_BUFFER_MS=400 MAX_VIDEO_BUFFER_MS=1000
    export TARGET_AUDIO_BUFFER_MS=400 MAX_AUDIO_BUFFER_MS=1000 CAPTURE_TTS_TEXT_EVIDENCE=1
    export ACCEPTANCE_MEDIA_METRICS_INTERVAL_SECONDS=60
    export TTS_MODEL_DIR="$root/runtime/.local/vits-piper-zh_CN-xiao_ya-medium"
    export PYTHONPATH="$root/runtime"
    exec runtime/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18000
    ;;
  runtime-proxy)
    exec >>"$evidence/runtime-proxy.log" 2>&1
    exec runtime/.venv/bin/python -m integration.observe_proxy --listen 18082 --upstream http://127.0.0.1:18000 --evidence "$evidence/runtime-tool.jsonl"
    ;;
  tool-proxy)
    exec >>"$evidence/tool-proxy.log" 2>&1
    exec runtime/.venv/bin/python -m integration.observe_proxy --listen 18083 --upstream http://127.0.0.1:18080 --evidence "$evidence/runtime-tool.jsonl"
    ;;
  backend)
    exec >>"$evidence/backend.log" 2>&1
    export PATH="$HOME/.local/bin:$PATH"
    set -a
    source backend/.env.integration
    set +a
    export HTTP_ADDR=127.0.0.1:18080
    export DATABASE_URL="${DATABASE_URL/15432/5432}"
    export REDIS_URL="${REDIS_URL/16391/6379}"
    export AI_RUNTIME_URL=http://127.0.0.1:18082
    exec /tmp/astralive-school-backend
    ;;
  frontend)
    exec >>"$evidence/frontend.log" 2>&1
    export ASTRALIVE_BASE_URL=http://127.0.0.1:18080 FRONTEND_PORT=18081
    exec runtime/.venv/bin/python scripts/preview_proxy.py
    ;;
  mediamtx)
    exec >>"$evidence/mediamtx.log" 2>&1
    exec docker compose -f infra/rtmp/compose.yaml up --no-color mediamtx
    ;;
  *)
    echo "unknown service: $service" >&2
    exit 2
    ;;
esac
