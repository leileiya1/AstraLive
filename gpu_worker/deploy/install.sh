#!/usr/bin/env bash
set -euo pipefail
bundle=$(cd -- "$(dirname -- "$0")" && pwd)
# AutoDL may keep its base interpreter outside PATH. This is a bootstrap only.
bootstrap=${ASTRALIVE_INSTALL_PYTHON:-/root/miniconda3/bin/python}
if [[ ! -x "$bootstrap" ]]; then
  bootstrap=$(command -v python3 || true)
fi
if [[ -z "$bootstrap" || ! -x "$bootstrap" ]]; then
  echo 'BOOTSTRAP_PYTHON_MISSING: use a Python >=3.12 base image' >&2
  exit 78
fi
cd "$bundle"
exec "$bootstrap" -B -m gpu_worker.install --bundle "$bundle" "$@"
