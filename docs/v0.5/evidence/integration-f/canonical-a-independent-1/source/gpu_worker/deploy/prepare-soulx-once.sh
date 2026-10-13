#!/usr/bin/env bash
# Explicit first provisioning only. Service start never invokes this script.
set -euo pipefail
umask 077
lab=${ASTRALIVE_GPU_LAB_ROOT:-/root/autodl-tmp/astralive-avatar-lab}
base=/root/miniconda3/bin/python
py="$lab/environments/astralive-soulx/bin/python"
wheel="$lab/artifacts/wheelhouse/flash_attn-2.8.3+cu12torch2.8cxx11abiTRUE-cp312-cp312-linux_x86_64.whl"
"$base" - <<'PY'
import sys, torch
assert sys.version_info[:3] == (3,12,3), 'PINNED_BASE_PYTHON_REQUIRED'
assert torch.__version__ == '2.8.0+cu128' and torch.version.cuda == '12.8', 'PINNED_BASE_TORCH_REQUIRED'
assert torch._C._GLIBCXX_USE_CXX11_ABI, 'PINNED_ABI_REQUIRED'
PY
"$base" - "$wheel" <<'PY'
import hashlib, sys
with open(sys.argv[1], 'rb') as f:
    assert hashlib.file_digest(f, 'sha256').hexdigest() == 'f25da18657a87fc83dc1bfb8b7751b82246e9db355510226b674fd437c34b5fb', 'FLASH_WHEEL_SHA256_MISMATCH'
PY
if [[ ! -x "$py" ]]; then
  "$base" -m venv --system-site-packages "$lab/environments/astralive-soulx"
fi
export PIP_INDEX_URL=https://pypi.org/simple
deployment=$(cd "$(dirname "$0")" && pwd)
export PIP_CONSTRAINT="${ASTRALIVE_GPU_CONSTRAINTS:-$deployment/constraints-pinned.txt}"
requirements=${ASTRALIVE_GPU_REQUIREMENTS:-$deployment/requirements-soulx.txt}
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1
if [[ "${ASTRALIVE_GPU_OFFLINE_INSTALL:-0}" == 1 ]]; then
  export PIP_NO_INDEX=1
  export PIP_FIND_LINKS="$lab/artifacts/soulx-wheelhouse"
fi
# Reuse the exact existing binary; never compile or change CUDA/Torch.
timeout 300 "$py" -m pip install --no-deps "$wheel"
timeout 900 "$py" -m pip install --retries 2 --timeout 30 -r "$requirements"
timeout 180 "$py" -m pip install --no-deps 'DistVAE==0.1.0' 'xfuser==0.4.3'
"$py" -m pip freeze > "$lab/reports/environment-installed.txt"
"$py" - <<'PY'
import sys, torch, flash_attn, av
assert sys.version_info[:3] == (3,12,3)
assert torch.__version__ == '2.8.0+cu128' and torch.version.cuda == '12.8'
assert flash_attn.__version__ == '2.8.3' and av.__version__ == '17.1.0'
print('PINNED_INFERENCE_ENVIRONMENT_INSTALLED')
PY
