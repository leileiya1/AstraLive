"""Launch only isolated ports, schema, event stream and lab RTMP destination."""
import os,subprocess
script='''set -eu
read -r LLM_API_KEY
export LLM_API_KEY LLM_BASE_URL=https://api.deepseek.com LLM_MODEL=deepseek-flash LLM_MAX_TOKENS=1024
cd "$HOME/AstraLive"; set -a; . backend/.env.integration; set +a
export SOULX_EXPERIMENT_DIR="$HOME/AstraLive/experiments/real-avatar/soulx-final-one-hour-fallback-postcheck-20261009"
export SOULX_PAIRED_RTMP=1 AVATAR_PROVIDER=SOULX_LITE_REMOTE SOULX_LATENCY_MARKER=1
export AVATAR_IMAGE_PATH="$SOULX_EXPERIMENT_DIR/avatar.png"
export MOCK_LLM=false MOCK_TTS=false MOCK_AVATAR=false MOCK_MEDIA=false WEBRTC_ENABLED=true
export REDIS_URL=redis://127.0.0.1:6379/12 REDIS_RUNTIME_EVENT_STREAM=dh.runtime.events.soulx.lab.20261009
export TOOL_BASE_URL=http://127.0.0.1:18180 TOOL_TOKEN="$INTERNAL_API_TOKEN"
export TTS_MODEL_DIR="$HOME/AstraLive/runtime/.local/vits-piper-zh_CN-xiao_ya-medium"
export TARGET_FPS=25 TARGET_VIDEO_BUFFER_MS=400 MAX_VIDEO_BUFFER_MS=1000 TARGET_AUDIO_BUFFER_MS=400 MAX_AUDIO_BUFFER_MS=1000 RUNTIME_MEDIA_METRICS_INTERVAL_SECONDS=10
export RTMP_ENABLED="RTMP_TEST_ENABLED" RTMP_URL=rtmp://127.0.0.1:19355/live RTMP_STREAM_KEY=soulx-isolated-lab
export RTMP_WIDTH=512 RTMP_HEIGHT=512 RTMP_FPS=25 RTMP_PRESET=veryfast
export PYTHONPATH="$HOME/AstraLive/experiments/real-avatar/soulx-streaming-runtime:$HOME/AstraLive/experiments/real-avatar/soulx-streaming"
p="$SOULX_EXPERIMENT_DIR/integration"; mkdir -p "$p"
setsid nohup runtime/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18100 > "$p/runtime-public.log" 2>&1 < /dev/null & echo $! > "$p/runtime-public.pid"
export HTTP_ADDR=127.0.0.1:18180 AI_RUNTIME_URL=http://127.0.0.1:18100
export DATABASE_URL="$(runtime/.venv/bin/python - <<'INNER'
import os,urllib.parse
u=urllib.parse.urlsplit(os.environ['DATABASE_URL'].replace(':15432',':5432'));q=[(k,v) for k,v in urllib.parse.parse_qsl(u.query) if k!='search_path'];q.append(('search_path','soulx_streaming_lab_20261009'));print(urllib.parse.urlunsplit(u._replace(query=urllib.parse.urlencode(q))))
INNER
)"
setsid nohup /tmp/astralive-school-backend > "$p/backend-public.log" 2>&1 < /dev/null & echo $! > "$p/backend-public.pid"
cat "$p/runtime-public.pid" "$p/backend-public.pid"
'''.replace('RTMP_TEST_ENABLED',os.environ.get('SOULX_DUAL_SINK','false'))
p=subprocess.run(['ssh','-o','BatchMode=yes','school-linux',script],input=os.environ['DEEPSEEK_API_KEY']+'\n',text=True,capture_output=True);print(p.stdout,p.stderr);assert p.returncode==0
