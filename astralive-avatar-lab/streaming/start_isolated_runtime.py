import os,subprocess
script='''set -eu
read -r LLM_API_KEY
export LLM_API_KEY LLM_BASE_URL=https://api.deepseek.com LLM_MODEL=deepseek-flash LLM_MAX_TOKENS=1024
export MOCK_LLM=false MOCK_TTS=false MOCK_AVATAR=false MOCK_MEDIA=false WEBRTC_ENABLED=true RTMP_ENABLED=false
export AVATAR_PROVIDER=SOULX_LITE_REMOTE SOULX_LATENCY_MARKER=1
export SOULX_EXPERIMENT_DIR="$HOME/AstraLive/experiments/real-avatar/soulx-streaming"
export TTS_MODEL_DIR="$HOME/AstraLive/runtime/.local/vits-piper-zh_CN-xiao_ya-medium"
export PYTHONPATH="$HOME/AstraLive/experiments/real-avatar/soulx-streaming-runtime:$SOULX_EXPERIMENT_DIR"
export TARGET_FPS=25 TARGET_VIDEO_BUFFER_MS=400 MAX_VIDEO_BUFFER_MS=1000 TARGET_AUDIO_BUFFER_MS=400 MAX_AUDIO_BUFFER_MS=1000 RUNTIME_MEDIA_METRICS_INTERVAL_SECONDS=5
unset REDIS_URL
cd "$HOME/AstraLive"
mkdir -p "$SOULX_EXPERIMENT_DIR/integration"
: > "$SOULX_EXPERIMENT_DIR/integration/avatar-events.jsonl"
nohup runtime/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18100 > "$SOULX_EXPERIMENT_DIR/integration/runtime.log" 2>&1 < /dev/null &
echo $! > "$SOULX_EXPERIMENT_DIR/integration/runtime.pid"
cat "$SOULX_EXPERIMENT_DIR/integration/runtime.pid"
'''
p=subprocess.run(['ssh','-o','BatchMode=yes','school-linux',script],input=os.environ['DEEPSEEK_API_KEY']+'\n',text=True,capture_output=True);print(p.stdout,p.stderr);assert p.returncode==0
