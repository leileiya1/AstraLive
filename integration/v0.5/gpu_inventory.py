#!/usr/bin/env python3
"""Read-only cached GPU installation inventory; never prints credential values."""
import json
import platform
from pathlib import Path
import subprocess


def main():
    lab = Path("/root/autodl-tmp/astralive-avatar-lab")
    service = Path("/root/autodl-tmp/astralive-services/soulx-lite-01")
    result = {"scope": "read-only installation inventory; no inference/start/install",
              "labPresent": lab.is_dir(), "servicePresent": service.is_dir(), "pythonBinaries": {}}
    result["platform"] = {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()}
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
    result["gpuQuery"] = {"exitCode": gpu.returncode, "columns": ["name", "driverVersion", "memoryTotalMiB", "memoryUsedMiB", "utilizationPercent"], "rows": [row.split(", ") for row in gpu.stdout.strip().splitlines()]}
    for path in (Path("/root/miniconda3/bin/python"), lab / "environments/astralive-soulx/bin/python"):
        result["pythonBinaries"][str(path)] = path.exists()
    cached_python = lab / "environments/astralive-soulx/bin/python"
    if cached_python.exists():
        code = "import importlib.metadata as m,json,platform; names=('torch','flash-attn','av','numpy'); print(json.dumps(dict(python=platform.python_version(),packages={n: next((d.version for d in m.distributions() if d.metadata.get('Name','').lower().replace('_','-')==n),None) for n in names})))"
        probe = subprocess.run([str(cached_python), "-c", code], capture_output=True, text=True, timeout=20)
        result["cachedEnvironmentExit"] = probe.returncode
        if probe.returncode == 0:
            result["cachedEnvironment"] = json.loads(probe.stdout)
    manifest = lab / "reports/soulx-weight-manifest.json"
    result["modelManifestPresent"] = manifest.is_file()
    if manifest.is_file():
        data = json.loads(manifest.read_text())
        result["modelFileCount"] = len(data)
        result["modelFilesPresent"] = [
            {"repo": item["repo"], "file": item["file"],
             "present": (lab / "models/soulx" / ("wav2vec2-base-960h" if item["repo"].startswith("facebook/") else "SoulX-FlashHead-1_3B") / item["file"]).is_file()}
            for item in data]
    config = service / "config/worker.json"
    if config.is_file():
        data = json.loads(config.read_text())
        # Strict allowlist. Inference/management token values and contents of
        # any credential file are deliberately never read or returned.
        allowed = ("worker_ref", "mode", "lab_root", "python", "port", "management_port", "model_revision", "state_dir")
        result["configuration"] = {key: data[key] for key in allowed if key in data}
    current = service / "current"
    result["currentRelease"] = current.resolve().name if current.exists() else None
    entry = service / "bin/astralive-worker"
    result["lifecycleEntryPresent"] = entry.is_file()
    result["cachedSupervisorStatePresent"] = (service / "state/supervisor.json").is_file()
    result["toolsPresent"] = {str(path): path.exists() for path in (Path("/usr/local/go/bin/go"), Path("/usr/bin/ffmpeg"), Path("/root/miniconda3/bin/ffmpeg"))}
    if entry.is_file():
        proc = subprocess.run([str(entry), "status"], capture_output=True, text=True, timeout=15)
        result["statusExit"] = proc.returncode
        try:
            state = json.loads(proc.stdout)
            allowed = ("status", "state", "ready", "health", "workerEpoch", "processPid")
            result["workerStatus"] = {key: state[key] for key in allowed if key in state}
        except (ValueError, TypeError):
            result["statusParsed"] = False
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
