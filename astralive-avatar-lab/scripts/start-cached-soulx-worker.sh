#!/usr/bin/env bash
# Reuse the verified GPU installation. Never install dependencies or download weights.
set -euo pipefail
lab=/root/autodl-tmp/astralive-avatar-lab
py="$lab/environments/astralive-soulx/bin/python"
run_dir="${SOULX_FINAL_RUN_DIR:-soulx-cached-deployment}"
[[ "$run_dir" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'Invalid evidence directory'; exit 1; }
test -x "$py"
test -f "$lab/reports/soulx-weight-manifest.json"
test -s "$lab/streaming/.private/token"
test -f "$lab/repositories/SoulX-FlashHead/flash_head/inference.py"
test -f "$lab/streaming/worker_final.py"
test -f "$lab/assets/soulx/original/official_girl.png"
out="$lab/streaming/evidence/$run_dir"
mkdir -p "$out"
if [[ -f "$out/worker.pid" ]]; then
  worker_pid=$(cat "$out/worker.pid")
  if [[ "$worker_pid" =~ ^[0-9]+$ ]] && kill -0 "$worker_pid" 2>/dev/null; then
    echo 'Existing worker PID is alive; refusing a duplicate launch.'
    exit 0
  fi
fi
"$py" - <<'PY'
import json,pathlib,torch,flash_attn
r=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab')
assert torch.__version__=='2.8.0+cu128'
assert flash_attn.__version__=='2.8.3'
for x in json.loads((r/'reports/soulx-weight-manifest.json').read_text()):
    folder='wav2vec2-base-960h' if x['repo'].startswith('facebook/') else 'SoulX-FlashHead-1_3B'
    assert (r/'models/soulx'/folder/x['file']).exists(), 'Model cache missing: restore once before launch'
print('Cached installation present. Worker will verify weight SHA256 before loading.')
PY
cd "$lab/streaming"
SOULX_FINAL_RUN_DIR="$run_dir" setsid nohup "$py" worker_final.py > "$out/worker.log" 2>&1 < /dev/null &
echo $! > "$out/worker.pid"
echo "Worker started; readiness and version evidence: $out/worker-ready.json"
