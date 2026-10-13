"""Read-only 60-second host resource sampling for the one-hour acceptance."""
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time


out = Path(sys.argv[1])
duration = int(sys.argv[2])
samples = json.loads(out.read_text())["samples"] if out.exists() else []
start = time.monotonic()


def run(*args):
    return subprocess.run(args, text=True, capture_output=True, timeout=12, check=True).stdout.strip()


while True:
    sample = {"at": datetime.now(timezone.utc).isoformat(), "elapsed_s": round(time.monotonic() - start, 1)}
    try:
        pid = run("pgrep", "-f", "^/private/tmp/astralive-v11-backend$").splitlines()[0]
        line = run("ps", "-p", pid, "-o", "pid=,rss=,%cpu=")
        parts = line.split()
        sample["backend"] = {"pid": int(parts[0]), "rss_kib": int(parts[1]), "cpu_pct": float(parts[2])}
        sample["backend_goroutines"] = "NOT AVAILABLE"
    except Exception as exc:
        sample["backend_error"] = str(exc)
    try:
        remote = run("ssh", "-o", "BatchMode=yes", "ubuntu-server", "nvidia-smi --query-gpu=memory.used,utilization.gpu,temperature.gpu --format=csv,noheader,nounits; ps -C python -o pid=,rss=,%cpu=,nlwp=,args= | grep 'uvicorn app.main:app' | head -1")
        gpu, process = remote.splitlines()[:2]
        vram, util, temp = [int(part.strip()) for part in gpu.split(",")]
        pid, rss, cpu, threads, *_ = process.split()
        sample["gpu"] = {"vram_mib": vram, "util_pct": util, "temperature_c": temp}
        sample["runtime"] = {"pid": int(pid), "rss_kib": int(rss), "cpu_pct_cumulative": float(cpu), "threads": int(threads), "tasks": "NOT AVAILABLE"}
    except Exception as exc:
        sample["runtime_error"] = str(exc)
    samples.append(sample)
    out.write_text(json.dumps({"samples": samples}, ensure_ascii=False, indent=2) + "\n")
    if time.monotonic() - start >= duration:
        break
    time.sleep(min(60, max(0, duration - (time.monotonic() - start))))
