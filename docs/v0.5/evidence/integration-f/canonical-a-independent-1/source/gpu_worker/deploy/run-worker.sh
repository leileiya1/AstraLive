#!/usr/bin/env bash
set -euo pipefail
: "${ASTRALIVE_GPU_CONFIG:?Set the absolute operator configuration file}"
: "${ASTRALIVE_GPU_PYTHON:?Use the existing validated Python executable}"
cd "$(dirname "$0")/../.."
exec "$ASTRALIVE_GPU_PYTHON" -m gpu_worker.supervisor --config "$ASTRALIVE_GPU_CONFIG"
