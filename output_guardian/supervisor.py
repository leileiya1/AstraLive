"""Trusted parent: a Guardian crash kills its entire owned process group.

Run under systemd KillMode=control-group or as container PID 1. Never point this
supervisor at a shared/existing ingest server: it owns the configured instance.
"""

import argparse
import errno
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil


def group_is_quiescent(pgid):
    """Prove no live group member after EPERM; an unreadable census is unknown.

    Darwin can return EPERM for a group containing only unreaped zombies.
    Zombies cannot publish or fork. Never infer this from errno alone, and
    never signal individual PIDs discovered by the census.
    """
    try:
        for process in psutil.process_iter(["pid"]):
            try:
                if (
                    os.getpgid(process.pid) == pgid
                    and process.status() != psutil.STATUS_ZOMBIE
                ):
                    return False
            except (ProcessLookupError, psutil.NoSuchProcess):
                continue
            except (OSError, psutil.Error):
                return False
    except (OSError, psutil.Error):
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    state = Path(config["stateDir"])
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (state / "supervisor.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    children = []
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    result, cleanup_unproven = 70, False
    try:
        # MediaMTX logs can include query strings: discard at the source.
        ingest = subprocess.Popen(
            [config["mediaMTXBinary"], config["mediaMTXConfig"]],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        children.append(ingest)
        time.sleep(0.15)
        guardian = subprocess.Popen(
            [sys.executable, "-m", "output_guardian", "--config", args.config],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
        )
        children.append(guardian)
        while not stopped and all(p.poll() is None for p in children):
            time.sleep(0.02)
        result = 0 if stopped else 70
    except Exception:
        # Static diagnostics only: never print configuration or exception text.
        print("OUTPUT_FENCE_UNPROVEN: supervisor child failure", file=sys.stderr)
    finally:
        for p in reversed(children):
            try:
                # Kill group even after its leader exited (retained FFmpeg).
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                if exc.errno != errno.EPERM or not group_is_quiescent(p.pid):
                    cleanup_unproven = True
                    print(
                        "OUTPUT_FENCE_UNPROVEN: group cleanup errno=" + str(exc.errno),
                        file=sys.stderr,
                    )
        for p in children:
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                cleanup_unproven = True
                p.kill()
                p.wait()
    return 74 if cleanup_unproven else result


if __name__ == "__main__":
    raise SystemExit(main())
