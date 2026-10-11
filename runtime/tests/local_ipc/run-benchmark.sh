#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
python_bin="${ASTRALIVE_IPC_TEST_PYTHON:-$PWD/runtime/.venv/bin/python}"
output_dir="${1:-$PWD/docs/v0.5/evidence/local-ipc}"
mkdir -p "$output_dir"
go -C backend build -o ../runtime/tests/local_ipc/bench ./cmd/local-ipc-bench
for transport in baseline tcp uds; do
  "$python_bin" runtime/tests/local_ipc/benchmark.py --transport "$transport" --output "$output_dir/$(uname -s | tr '[:upper:]' '[:lower:]')-$transport.json"
done
