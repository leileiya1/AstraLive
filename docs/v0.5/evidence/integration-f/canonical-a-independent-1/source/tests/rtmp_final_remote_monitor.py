"""Independent 60-second process/resource/media monitor for RTMP acceptance."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time


ROOT = Path.home() / "AstraLive"
OUT = ROOT / "integration/evidence/rtmp-final"
RESOURCE = OUT / "resource-stats.jsonl"
RUNTIME_LOG = OUT / "runtime.log"
DONE = OUT / "soak-complete.json"
TIMER = OUT / "timer-start.json"
UNITS = {
    "runtime": "astralive-runtime-rtmp.service",
    "backend": "astralive-backend-rtmp.service",
    "frontend": "astralive-frontend-rtmp.service",
    "mediamtx": "astralive-mediamtx.service",
}


def command(*args):
    return subprocess.run(args, text=True, capture_output=True, check=False)


def unit_fields(unit):
    result = command("systemctl", "--user", "show", unit,
                     "-p", "MainPID", "-p", "ActiveState", "-p", "SubState",
                     "-p", "Result", "-p", "ExecMainCode", "-p", "ExecMainStatus")
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def process(pid):
    if not pid or not Path(f"/proc/{pid}").exists():
        return {"pid": pid, "status": "MISSING"}
    status = {}
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            if key in {"Name", "State", "VmRSS", "Threads"}:
                status[key] = value.strip()
    fields = Path(f"/proc/{pid}/stat").read_text().split()
    ticks = int(fields[13]) + int(fields[14])
    return {"pid": pid, "status": status, "stat_start_ticks": int(fields[21]),
            "cpu_ticks": ticks, "fd_count": len(list(Path(f"/proc/{pid}/fd").iterdir()))}


def oldest_pid(pattern):
    result = command("pgrep", "-o", "-f", pattern)
    value = result.stdout.strip()
    return int(value) if value else 0


def latest_media_metrics():
    if not RUNTIME_LOG.exists():
        return None
    for line in reversed(RUNTIME_LOG.read_text(errors="replace").splitlines()[-5000:]):
        if "acceptance_media_metrics " not in line:
            continue
        try:
            outer = json.loads(line)
            return json.loads(outer["message"].split("acceptance_media_metrics ", 1)[1])
        except (ValueError, KeyError):
            continue
    return None


def sample(started):
    units = {name: unit_fields(unit) for name, unit in UNITS.items()}
    pids = {name: int(data.get("MainPID", "0")) for name, data in units.items()}
    pids["ffmpeg"] = oldest_pid(r"[f]fmpeg .* -f flv rtmp://")
    inspect = command("docker", "inspect", "-f", "{{.State.Pid}}", "astralive-rtmp-test-mediamtx-1")
    pids["mediamtx_container"] = int(inspect.stdout.strip()) if inspect.returncode == 0 else 0
    meminfo = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in {"MemAvailable", "SwapTotal", "SwapFree"}:
            meminfo[key] = int(value.split()[0])
    row = {
        "at": datetime.now(timezone.utc).isoformat(),
        "monitor_elapsed_s": round(time.monotonic() - started, 1),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "host": {"mem_available_kib": meminfo["MemAvailable"],
                 "swap_used_kib": meminfo["SwapTotal"] - meminfo["SwapFree"],
                 "loadavg": Path("/proc/loadavg").read_text().strip()},
        "units": units,
        "processes": {name: process(pid) for name, pid in pids.items()},
        "media": latest_media_metrics(),
    }
    if TIMER.exists():
        timer = json.loads(TIMER.read_text())
        timer_at = datetime.fromisoformat(timer["at"].replace("Z", "+00:00"))
        row["soak_elapsed_s"] = round((datetime.now(timezone.utc) - timer_at).total_seconds(), 1)
        row["session_id"] = timer.get("session_id")
    return row


def investigate(row):
    unit = UNITS["runtime"]
    journal = command("journalctl", "--user", "-u", unit, "--no-pager", "-n", "120").stdout
    kernel = command("journalctl", "-k", "--no-pager", "-n", "120").stdout
    runtime_tail = "\n".join(RUNTIME_LOG.read_text(errors="replace").splitlines()[-120:]) if RUNTIME_LOG.exists() else "UNAVAILABLE"
    text = f"""# RTMP Runtime exit investigation

- Exact timestamp: {row['at']}
- Runtime PID: {row['processes']['runtime']['pid']}
- systemd fields: `{json.dumps(row['units']['runtime'], ensure_ascii=False)}`
- boot_id: `{row['boot_id']}`
- last resource/media sample: `{json.dumps(row, ensure_ascii=False)}`

## User journal

```text
{journal}
```

## Kernel evidence

```text
{kernel}
```

## Runtime log tail

```text
{runtime_tail}
```
"""
    (OUT / "RTMP-RUNTIME-EXIT-INVESTIGATION.md").write_text(text)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    while True:
        row = sample(started)
        with RESOURCE.open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        runtime_active = row["units"]["runtime"].get("ActiveState") == "active"
        if not runtime_active and not DONE.exists():
            investigate(row)
            return
        if DONE.exists():
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
