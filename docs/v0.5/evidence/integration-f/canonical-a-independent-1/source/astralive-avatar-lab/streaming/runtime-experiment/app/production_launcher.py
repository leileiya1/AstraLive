"""Hold a service-user publisher lock across preflight and Runtime lifetime."""
import fcntl
import os
from pathlib import Path
import sys

from .rtmp_preflight import main as preflight_main


def main():
    lock_path = Path('/run/astralive/publisher.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        print('AstraLive publisher lock is already held', file=sys.stderr)
        return 1
    if preflight_main():
        os.close(fd)
        return 1
    os.environ["MAX_SESSIONS"] = "1"
    os.set_inheritable(fd, True)
    os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'app.main:app',
                             '--host', '127.0.0.1', '--port', '18000',
                             '--timeout-graceful-shutdown', '25'])


if __name__ == '__main__':
    raise SystemExit(main())
