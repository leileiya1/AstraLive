"""Installed one-command lifecycle; start means warmup READY, not just a PID."""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time
from .config import Config
from .doctor import inspect
from .probe import probe
from .supervisor import child_environment


def operate(a):
    root = Path(a.root)
    config = root/'config/worker.json'
    cfg = Config(**json.loads(config.read_text()))
    cfg.validate()
    env = child_environment()
    # Managed installs always use persisted configuration, not shell path overrides.
    for key in tuple(env):
        if key.startswith('ASTRALIVE_GPU_'):
            del env[key]
    def cli(action):
        return subprocess.run([sys.executable, '-B', '-m', 'gpu_worker.cli', action, '--config', str(config)], env=env).returncode
    if a.action in {'doctor', 'start', 'restart', 'run'}:
        result = inspect(cfg)
        print(json.dumps(result), flush=True)
        if not result['preflightPassed']:
            return 78
        if a.action == 'doctor':
            return 0
    if a.action == 'run':
        import os
        os.execve(cfg.python, [cfg.python, '-B', '-m', 'gpu_worker.supervisor', '--config', str(config)], env)
    if a.action in {'start', 'restart'}:
        if a.action == 'start' and (Path(cfg.state_dir)/'control.sock').exists():
            print('ALREADY_RUNNING; inspect status or use restart')
            return 1
        if cli(a.action):
            return 1
        deadline = time.monotonic()+cfg.startup_timeout_s+5
        while time.monotonic() < deadline:
            try:
                status = probe(cfg)
                if status['ready']:
                    print(json.dumps(status))
                    return 0
            except Exception:
                pass
            state = Path(cfg.state_dir)/'supervisor.json'
            if state.exists() and json.loads(state.read_text()).get('status') == 'EXHAUSTED':
                return 70
            time.sleep(.25)
        cli('stop')
        print('READY_TIMEOUT; stopped this launch')
        return 70
    return cli(a.action)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True)
    p.add_argument('action', choices=['start', 'stop', 'restart', 'status', 'probe', 'doctor', 'run'])
    a = p.parse_args()
    with (Path(a.root)/'install.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('INSTALL_OR_LIFECYCLE_BUSY')
            return 78
        return operate(a)


if __name__ == '__main__':
    raise SystemExit(main())
