#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY is required}"

host=${ASTRALIVE_REMOTE_HOST:-school-linux}
remote_root=/home/sapiece/AstraLive

ssh -o BatchMode=yes "$host" 'mkdir -p "$HOME/AstraLive/.rtmp-final-stage"'
rsync -a runtime/app/main.py runtime/app/rtmp_media.py tests/gpu_partial_soak.py tests/rtmp_final_remote_monitor.py \
  scripts/rtmp-final-remote-service.sh "$host:$remote_root/.rtmp-final-stage/"
ssh -o BatchMode=yes "$host" '
set -euo pipefail
cd "$HOME/AstraLive"
install -m 0644 .rtmp-final-stage/main.py runtime/app/main.py
install -m 0644 .rtmp-final-stage/rtmp_media.py runtime/app/rtmp_media.py
install -m 0644 .rtmp-final-stage/gpu_partial_soak.py tests/gpu_partial_soak.py
install -m 0644 .rtmp-final-stage/rtmp_final_remote_monitor.py tests/rtmp_final_remote_monitor.py
install -m 0755 .rtmp-final-stage/rtmp-final-remote-service.sh scripts/rtmp-final-remote-service.sh
mkdir -p integration/evidence/rtmp-final
if test -f integration/evidence/rtmp-final/service-start.json; then
  echo "Existing final evidence must be archived before a new run" >&2
  exit 1
fi
for unit in astralive-monitor-rtmp astralive-frontend-rtmp astralive-backend-rtmp astralive-tool-proxy-rtmp astralive-runtime-proxy-rtmp astralive-runtime-rtmp astralive-mediamtx; do
  systemctl --user stop "$unit.service" 2>/dev/null || true
  systemctl --user reset-failed "$unit.service" 2>/dev/null || true
done
'

printf '%s\n' "$DEEPSEEK_API_KEY" | ssh -o BatchMode=yes "$host" '
set -euo pipefail
read -r key
secret=/run/user/$UID/astralive-rtmp-final.env
umask 077
printf "LLM_API_KEY=%s\nLLM_BASE_URL=https://api.deepseek.com\nLLM_MODEL=deepseek-flash\nLLM_MAX_TOKENS=1024\n" "$key" > "$secret"
chmod 600 "$secret"
'

ssh -o BatchMode=yes "$host" '
set -euo pipefail
cd "$HOME/AstraLive"
helper="$HOME/AstraLive/scripts/rtmp-final-remote-service.sh"
start() {
  local unit=$1 service=$2
  systemd-run --user --unit "$unit" --property=Type=exec --property=Restart=no \
    --property=KillMode=control-group --property=TimeoutStopSec=20s "$helper" "$service" >/dev/null
}
start astralive-mediamtx mediamtx
start astralive-runtime-proxy-rtmp runtime-proxy
start astralive-tool-proxy-rtmp tool-proxy
start astralive-runtime-rtmp runtime
start astralive-backend-rtmp backend
start astralive-frontend-rtmp frontend
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:18000/internal/v1/health >/dev/null 2>&1 &&
     curl -fsS http://127.0.0.1:18080/health/ready >/dev/null 2>&1 &&
     curl -fsS http://127.0.0.1:18081/ >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:18000/internal/v1/health >/dev/null
curl -fsS http://127.0.0.1:18080/health/ready >/dev/null
curl -fsS http://127.0.0.1:18081/ >/dev/null
systemd-run --user --unit astralive-monitor-rtmp --property=Type=exec --property=Restart=no \
  --property=KillMode=control-group "$HOME/AstraLive/runtime/.venv/bin/python" \
  "$HOME/AstraLive/tests/rtmp_final_remote_monitor.py" >/dev/null
runtime_pid=$(systemctl --user show astralive-runtime-rtmp.service -p MainPID --value)
backend_pid=$(systemctl --user show astralive-backend-rtmp.service -p MainPID --value)
frontend_pid=$(systemctl --user show astralive-frontend-rtmp.service -p MainPID --value)
mediamtx_pid=$(systemctl --user show astralive-mediamtx.service -p MainPID --value)
mediamtx_container_pid=$(docker inspect -f "{{.State.Pid}}" astralive-rtmp-test-mediamtx-1)
boot_id=$(cat /proc/sys/kernel/random/boot_id)
jq -n --arg at "$(date --iso-8601=seconds)" --arg boot "$boot_id" \
  --argjson runtime "$runtime_pid" --argjson backend "$backend_pid" --argjson frontend "$frontend_pid" --argjson mediamtx "$mediamtx_pid" --argjson mediamtxContainer "$mediamtx_container_pid" \
  "{at:\$at,boot_id:\$boot,units:[\"astralive-runtime-rtmp\",\"astralive-backend-rtmp\",\"astralive-frontend-rtmp\",\"astralive-mediamtx\"],pids:{runtime:\$runtime,backend:\$backend,frontend:\$frontend,mediamtx_unit:\$mediamtx,mediamtx_container:\$mediamtxContainer}}" \
  > integration/evidence/rtmp-final/service-start.json
runtime/.venv/bin/python - <<PY > integration/evidence/rtmp-final/processes-start.json
import json, pathlib, datetime
pids={"runtime":$runtime_pid,"backend":$backend_pid,"frontend":$frontend_pid,"mediamtx":$mediamtx_pid}
rows={}
for name,pid in pids.items():
    rows[name]={"pid":pid,"stat":pathlib.Path(f"/proc/{pid}/stat").read_text(),"status":pathlib.Path(f"/proc/{pid}/status").read_text()}
print(json.dumps({"at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"processes":rows},indent=2))
PY
'

mkdir -p integration/evidence/rtmp-final
if lsof -nP -iTCP:18080 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "An AstraLive final SSH tunnel is already running" >&2
  exit 1
fi
launchctl submit -l com.astralive.rtmp-final-tunnel \
  -o "$PWD/integration/evidence/rtmp-final/launchd-tunnel.log" \
  -e "$PWD/integration/evidence/rtmp-final/launchd-tunnel.err.log" -- \
  /usr/bin/ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
  -N -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 "$host"
for attempt in {1..30}; do
  if curl -fsS http://127.0.0.1:18080/health/ready >/dev/null 2>&1 && curl -fsS http://127.0.0.1:18081/ >/dev/null 2>&1; then
    echo "Persistent RTMP final stack ready"
    exit 0
  fi
  sleep 1
done
echo "Persistent tunnel did not become ready" >&2
exit 1
