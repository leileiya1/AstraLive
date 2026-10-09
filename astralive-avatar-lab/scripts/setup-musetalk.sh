#!/bin/bash
set -euo pipefail
LAB=/root/autodl-tmp/astralive-avatar-lab
PY=$LAB/environments/astralive-musetalk/bin/python
export PATH="$LAB/tools/bin:$LAB/environments/astralive-musetalk/bin:$PATH"
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_DISABLE_PIP_VERSION_CHECK=1
cd "$LAB/repositories/MuseTalk"
"$PY" -m pip install setuptools==80.9.0
"$PY" -m pip install filelock typing_extensions sympy networkx jinja2 requests pillow==10.4.0 numpy==1.23.5 cmake lit
"$PY" -m pip install --no-deps triton==2.0.0
WHEEL="$LAB/wheelhouse/torch-2.0.1+cu118-cp310-cp310-linux_x86_64.whl"
if [ -f "$WHEEL" ]; then
    "$PY" -m pip install --no-deps "$WHEEL" torchvision==0.15.2+cu118 torchaudio==2.0.2+cu118 --index-url https://download.pytorch.org/whl/cu118
else
    "$PY" -m pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118
fi
"$PY" -m pip install -r "$LAB/scripts/requirements-musetalk-inference.txt"
"$PY" -m pip install mmengine==0.10.7
"$PY" -m pip install mmcv==2.0.1 --only-binary=mmcv -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html
"$PY" -m pip install --no-build-isolation chumpy==0.70
"$PY" -m pip install mmdet==3.1.0 mmpose==1.1.0 -c "$LAB/scripts/requirements-musetalk-inference.txt"
"$PY" -m pip freeze > "$LAB/reports/musetalk-pip-freeze.txt"
/root/miniconda3/bin/conda env export -p "$LAB/environments/astralive-musetalk" > "$LAB/reports/musetalk-conda.yaml"
"$PY" -m pip check
"$PY" -c 'import torch,torchvision,torchaudio,mmengine,mmcv,mmdet,mmpose; from mmcv.ops import nms; print("IMPORT PASS",torch.__version__,torch.version.cuda,torch.cuda.get_device_capability()); torch.rand(16,16,device="cuda").square(); torch.cuda.synchronize(); print("CUDA PASS")'
