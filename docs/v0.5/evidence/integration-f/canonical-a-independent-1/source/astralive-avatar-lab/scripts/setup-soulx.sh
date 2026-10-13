#!/bin/bash
set -euo pipefail
export PIP_INDEX_URL=https://pypi.org/simple
LAB=/root/autodl-tmp/astralive-avatar-lab
export PIP_CONSTRAINT="$LAB/scripts/soulx-constraints.txt"
/root/miniconda3/bin/python -m venv --system-site-packages "$LAB/environments/astralive-soulx"
P="$LAB/environments/astralive-soulx/bin/python"
"$P" -m pip install 'diffusers==0.34.0' 'transformers==4.57.3' 'accelerate==1.8.1' 'einops==0.8.1' 'numpy==1.26.4' 'opencv-contrib-python==4.11.0.86' 'mediapipe==0.10.21' 'protobuf==4.25.8' 'imageio' 'imageio-ffmpeg' 'easydict' 'ftfy' 'scikit-image' 'loguru' 'pyloudnorm' 'decord' 'librosa' 'soundfile' 'ninja' 'yunchang==0.6.2'
"$P" -m pip install 'distvae' 'pytest' 'sentencepiece' 'opencv-python==4.11.0.86'
"$P" -m pip install --no-deps 'xfuser==0.4.3'
"$P" -m pip install --no-deps "$LAB/artifacts/wheelhouse/flash_attn-2.8.3+cu12torch2.8cxx11abiTRUE-cp312-cp312-linux_x86_64.whl"
"$P" -m pip freeze > "$LAB/reports/soulx-pip-freeze.txt"
"$P" -m pip check > "$LAB/reports/soulx-pip-check.txt"
