"""Capture one-minute School-Linux resource samples for final acceptance."""
import json
from datetime import datetime, timezone
from pathlib import Path
import signal
import subprocess
import sys
import time


output = Path(sys.argv[1])
duration = int(sys.argv[2]) if len(sys.argv) > 2 else 3700
samples = []
stopping = False


def stop(*_):
    global stopping
    stopping = True


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)


def remote_sample(elapsed):
    code = r'''set -u
runtime_pid=$(pgrep -o -f '[u]vicorn app.main:app.*--port 18000' || true)
backend_pid=$(pgrep -o -f '[/]tmp/astralive-school-backend' || true)
printf 'BOOT|'; cat /proc/sys/kernel/random/boot_id
printf 'UPTIME|'; cat /proc/uptime
printf 'LOAD|'; cat /proc/loadavg
printf 'MEM|'; awk '/MemAvailable:/{ma=$2}/SwapTotal:/{st=$2}/SwapFree:/{sf=$2}END{print ma","st-sf}' /proc/meminfo
printf 'TEMP|'; awk '{printf "%s%s",sep,$1;sep=","}' /sys/class/thermal/thermal_zone*/temp 2>/dev/null || true; printf '\n'
printf 'GPU|'; nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu,utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -n1 || true
if [ -n "$runtime_pid" ]; then printf 'RUNTIME|'; ps -p "$runtime_pid" -o pid=,rss=,%cpu=,nlwp=; else echo 'RUNTIME|MISSING'; fi
if [ -n "$backend_pid" ]; then printf 'BACKEND|'; ps -p "$backend_pid" -o pid=,rss=,%cpu=,nlwp=; else echo 'BACKEND|MISSING'; fi
docker stats --no-stream --format 'CONTAINER|{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}' postgres redis-server 2>/dev/null || true
'''
    done = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "school-linux", code],
        text=True, capture_output=True, timeout=15, check=True,
    )
    row = {"at": datetime.now(timezone.utc).isoformat(), "elapsed_s": round(elapsed, 1)}
    for line in done.stdout.splitlines():
        key, _, value = line.partition("|")
        if key == "BOOT": row["boot_id"] = value
        elif key == "UPTIME": row["uptime_s"] = float(value.split()[0])
        elif key == "LOAD": row["loadavg"] = value
        elif key == "MEM":
            available, swap = value.split(",")
            row["ram_available_kib"] = int(available)
            row["swap_used_kib"] = int(swap)
        elif key == "TEMP":
            values = [int(item) / 1000 for item in value.split(",") if item]
            row["cpu_temperature_c"] = max(values) if values else None
        elif key == "GPU" and value:
            used, free, temp, util = [int(item.strip()) for item in value.split(",")]
            row["k2200_reference"] = {"used_mib": used, "free_mib": free, "temperature_c": temp, "util_pct": util}
        elif key in {"RUNTIME", "BACKEND"}:
            parts = value.split()
            row[key.lower()] = ({"status": "MISSING"} if value == "MISSING" else
                                {"pid": int(parts[0]), "rss_kib": int(parts[1]),
                                 "cpu_pct": float(parts[2]), "threads": int(parts[3])})
        elif key == "CONTAINER":
            name, memory, cpu = value.split("|", 2)
            row.setdefault("containers", {})[name] = {"memory": memory, "cpu": cpu}
    return row


started = time.monotonic()
while True:
    elapsed = time.monotonic() - started
    try:
        samples.append(remote_sample(elapsed))
    except Exception as exc:
        samples.append({"at": datetime.now(timezone.utc).isoformat(), "elapsed_s": round(elapsed, 1),
                        "error": f"{type(exc).__name__}: {exc}"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"samples": samples}, ensure_ascii=False, indent=2) + "\n")
    if stopping or elapsed >= duration:
        break
    deadline = time.monotonic() + 60
    while not stopping and time.monotonic() < deadline:
        time.sleep(min(1, deadline - time.monotonic()))
