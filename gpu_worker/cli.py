"""Fixed lifecycle actions. No arbitrary remote commands, PID signals or cloud APIs."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from .config import Config
from .probe import probe
from .supervisor import child_environment


def stop(cfg):
    control = Path(cfg.state_dir) / 'control.sock'
    if not control.exists():
        return
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(2)
        s.connect(str(control))
        s.sendall(b'STOP')
        if s.recv(16) != b'OK':
            raise RuntimeError('STOP_REJECTED')
    deadline = time.monotonic() + cfg.stop_timeout_s + 5
    while control.exists():
        if time.monotonic() > deadline:
            raise RuntimeError('SUPERVISOR_STOP_TIMEOUT')
        time.sleep(.1)


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['start', 'stop', 'restart', 'status', 'probe', 'check'])
    p.add_argument('--config', required=True)
    a = p.parse_args()
    cfg = Config.load(a.config)
    if a.action in {'stop', 'restart'}:
        stop(cfg)
    if a.action in {'start', 'restart'}:
        Path(cfg.state_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
        proc = subprocess.Popen([cfg.python, '-m', 'gpu_worker.supervisor', '--config', str(Path(a.config).resolve())],
                                cwd=Path(__file__).resolve().parent.parent, env=child_environment(), start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Start is an admission result; probe gates actual readiness separately.
        time.sleep(.2)
        if proc.poll() is not None:
            return 1
        print('SUPERVISOR_STARTED; use probe for READY')
    elif a.action == 'status':
        try:
            print(json.dumps(probe(cfg, '/v1/status')))
        except Exception:
            state = Path(cfg.state_dir) / 'supervisor.json'
            previous = json.loads(state.read_text()) if state.exists() else None
            last_exit = Path(cfg.state_dir) / 'worker-last-exit.json'
            failure = json.loads(last_exit.read_text()) if last_exit.exists() else None
            print(json.dumps(dict(status='UNREACHABLE', ready=False, health='UNKNOWN', workerRef=cfg.worker_ref, lastSupervisorState=previous, lastWorkerExit=failure)))
            return 1
    elif a.action == 'probe':
        try:
            print(json.dumps(probe(cfg)))
        except Exception:
            print('NOT_READY')
            return 1
    elif a.action == 'check':
        print(cfg.verify_assets())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
