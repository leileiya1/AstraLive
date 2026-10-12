"""Container-compatible bounded supervisor; Unix control socket replaces unsafe PID kill."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import random
import signal
import socket
import subprocess
import sys
import threading
import time
from .config import Config, secret
from .probe import probe
from .telemetry import atomic_json, logger


def child_environment():
    # Worker cannot inherit business credentials from its operator shell.
    names = ('PATH', 'LANG', 'LC_ALL', 'CUDA_VISIBLE_DEVICES', 'LD_LIBRARY_PATH', 'OMP_NUM_THREADS',
             'ASTRALIVE_GPU_STATE_DIR', 'ASTRALIVE_GPU_TOKEN_FILE', 'ASTRALIVE_GPU_MANAGEMENT_TOKEN_FILE',
             'ASTRALIVE_GPU_PYTHON', 'ASTRALIVE_GPU_LAB_ROOT', 'ASTRALIVE_WORKER_STAGING_ENABLED')
    env = {k: os.environ[k] for k in names if k in os.environ}
    env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUNBUFFERED='1')
    # HuggingFace local caches may need HOME, never credential files or runtime APIs.
    env['HOME'] = str(Path.home())
    return env


class Supervisor:
    def __init__(self, cfg, config_path):
        self.cfg, self.config_path = cfg, str(Path(config_path).resolve())
        self.stop = threading.Event()
        self.child = None
        self.log = logger(cfg, 'supervisor', (secret(cfg.token_file), secret(cfg.management_token_file)))
        self.state = Path(cfg.state_dir)

    def record(self, status, attempt, **kw):
        atomic_json(self.state / 'supervisor.json', dict(status=status, attempt=attempt, supervisorPid=os.getpid(), childPid=self.child.pid if self.child else None, **kw))

    def terminate(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(self.cfg.stop_timeout_s)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
                self.log.info(json.dumps({'event': 'GracePeriodExceeded'}))

    def run(self):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = (self.state / 'supervisor.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('SUPERVISOR_ALREADY_RUNNING') from None
        control_path = self.state / 'control.sock'
        control_path.unlink(missing_ok=True)
        control = socket.socket(socket.AF_UNIX)
        control.bind(str(control_path))
        control_path.chmod(0o600)
        control.listen(2)
        control.settimeout(.5)
        def command_loop():
            while not self.stop.is_set():
                try:
                    conn, _ = control.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                with conn:
                    conn.settimeout(1)
                    try:
                        if conn.recv(16) == b'STOP':
                            self.stop.set()
                            conn.sendall(b'OK')
                    except OSError:
                        pass
        thread = threading.Thread(target=command_loop, daemon=True)
        thread.start()
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        result = 0
        try:
            for attempt in range(self.cfg.retries + 1):
                if self.stop.is_set():
                    break
                self.child = subprocess.Popen([self.cfg.python, '-m', 'gpu_worker.service', '--config', self.config_path],
                                              cwd=Path(__file__).resolve().parent.parent,
                                              env=child_environment(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                self.record('STARTING', attempt)
                def drain(child):
                    # Bound a line even if a library emits malformed/unbounded output.
                    while True:
                        line = child.stdout.readline(8192)
                        if not line:
                            break
                        self.log.info(line.rstrip())
                    child.stdout.close()
                output = threading.Thread(target=drain, args=(self.child,), daemon=True)
                output.start()
                deadline = time.monotonic() + self.cfg.startup_timeout_s
                ready = False
                failures = 0
                while not self.stop.wait(.5) and self.child.poll() is None:
                    try:
                        status = probe(self.cfg)
                        if not status['ready'] or status.get('processPid') != self.child.pid or status['workerRef'] != self.cfg.worker_ref:
                            raise ValueError('not ready')
                        if not ready:
                            ready = True
                            self.record('READY', attempt, workerEpoch=status['workerEpoch'])
                        failures = 0
                    except Exception:
                        if ready:
                            failures += 1
                        if (not ready and time.monotonic() > deadline) or failures >= 3:
                            self.record('UNHEALTHY', attempt)
                            self.terminate()
                            break
                self.terminate()
                output.join(3)
                if self.stop.is_set():
                    break
                self.record('RETRY_WAIT' if attempt < self.cfg.retries else 'EXHAUSTED', attempt, exitCode=self.child.returncode)
                if attempt == self.cfg.retries:
                    result = 70
                    break
                delay = min(self.cfg.retry_max_s, self.cfg.retry_initial_s * 2**attempt)
                self.stop.wait(delay * random.uniform(.8, 1))
        finally:
            self.stop.set()
            self.terminate()
            control.close()
            thread.join(2)
            control_path.unlink(missing_ok=True)
            if result == 0:
                self.record('STOPPED', 0)
            lock.close()
        return result


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    args = p.parse_args()
    cfg = Config.load(args.config)
    return Supervisor(cfg, args.config).run()


if __name__ == '__main__':
    raise SystemExit(main())
