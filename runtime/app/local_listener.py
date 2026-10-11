"""Opt-in single-host HTTP listener. Separate process, unchanged Runtime routes.

Use: PYTHONPATH=runtime python -m app.local_listener
Private UDS lifecycle uses flock + an inode record; no PID-based stale guessing.
"""
import argparse
from dataclasses import dataclass
from contextlib import contextmanager
import errno
import hmac
import importlib
import ipaddress
import json
import logging
import os
from pathlib import Path
import socket
import signal
import threading
import stat
import sys
from urllib.parse import urlsplit
from uuid import uuid4

LOG = logging.getLogger('astralive.local_listener')

@dataclass(frozen=True)
class ListenerSettings:
    mode: str
    path: str
    fallback: str
    host: str
    port: int

    @classmethod
    def from_env(cls, default_tcp_url='http://127.0.0.1:8000', platform=None):
        platform = platform or sys.platform
        mode = os.getenv('ASTRALIVE_LOCAL_TRANSPORT', 'tcp')
        fallback = os.getenv('ASTRALIVE_LOCAL_FALLBACK', 'disabled')
        path = os.getenv('ASTRALIVE_RUNTIME_UDS_PATH', '')
        if mode not in {'tcp', 'uds'} or fallback not in {'disabled', 'tcp'}:
            raise ValueError('local transport must be tcp|uds; fallback must be disabled|tcp')
        if mode == 'uds' and platform not in {'linux', 'darwin'}:
            if fallback != 'tcp':
                raise ValueError('UDS unsupported; configure authenticated loopback TCP')
            LOG.warning('UDS unsupported on %s; explicit startup TCP fallback', platform)
            mode = 'tcp'
        if mode == 'uds':
            if not os.path.isabs(path) or os.path.normpath(path) != path or len(os.fsencode(path)) > 103 or path == '/':
                raise ValueError('UDS path must be clean, absolute and <=103 bytes')
        target = urlsplit(os.getenv('AI_RUNTIME_URL', default_tcp_url))
        try:
            if target.scheme != 'http' or target.username or target.password or target.path or target.query or target.fragment or not target.port:
                raise ValueError
            host = target.hostname
            if host != 'localhost' and not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError('single-host TCP origin must be loopback HTTP with a port') from None
        return cls(mode, path, fallback, '127.0.0.1' if host == 'localhost' else host, target.port)


def private_parent(path, create=False):
    parent = Path(path).parent
    if create:
        try:
            parent.mkdir(mode=0o700) # never create an unchecked directory tree
        except FileExistsError:
            pass
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError('UDS parent must be an owned0700 directory')
    for directory in (parent, *parent.parents):
        s = directory.lstat()
        if not stat.S_ISDIR(s.st_mode):
            raise PermissionError('UDS parent chain contains symlink/non-directory')
        if s.st_mode & 0o022 and not (s.st_mode & stat.S_ISVTX and s.st_uid == 0):
            raise PermissionError('UDS parent chain is writable by other users')
    return info


def socket_info(path):
    info = Path(path).lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise PermissionError('UDS must be an owned0600 socket (no symlinks)')
    return info


def same_inode(a, b):
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


class PrivateSocket:
    """Only remove a socket recorded under this exclusive lifecycle lock."""
    def __init__(self, path):
        self.path, self.fd, self.sock, self.identity = path, None, None, None

    def __enter__(self):
        import fcntl # imported only in Unix path; Windows TCP has no dependency
        parent = private_parent(self.path, create=True)
        lock_path = self.path + '.lock'
        try:
            self.fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            lock = os.fstat(self.fd)
            if not stat.S_ISREG(lock.st_mode) or lock.st_uid != os.geteuid() or stat.S_IMODE(lock.st_mode) != 0o600 or lock.st_nlink != 1:
                raise PermissionError('UDS lock must be an owned private regular file')
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Runtime UDS lifecycle lock already held') from None
            if not same_inode(parent, private_parent(self.path)):
                raise PermissionError('UDS parent replaced')
            try:
                existing = socket_info(self.path)
            except FileNotFoundError:
                existing = None
            if existing:
                try:
                    record = json.loads(os.pread(self.fd, 4096, 0))
                    ours = record['device'] == existing.st_dev and record['inode'] == existing.st_ino
                except (ValueError, KeyError, TypeError):
                    ours = False
                if not ours:
                    raise PermissionError('refusing to remove socket without matching lifecycle record')
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(.2)
                    try:
                        probe.connect(self.path)
                    except OSError as e:
                        if e.errno != errno.ECONNREFUSED:
                            raise RuntimeError('stale UDS liveness uncertain; refusing cleanup') from e
                    else:
                        raise RuntimeError('existing UDS is live; refusing cleanup')
                if not same_inode(existing, socket_info(self.path)):
                    raise PermissionError('UDS replaced before stale cleanup')
                os.unlink(self.path)
                LOG.info('removed stale owned UDS inode after exclusive lock and liveness check')
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            previous = os.umask(0o077)
            try:
                self.sock.bind(self.path)
                os.chmod(self.path, 0o600)
            finally:
                os.umask(previous)
            self.identity = socket_info(self.path)
            os.ftruncate(self.fd, 0)
            os.pwrite(self.fd, json.dumps({'device':self.identity.st_dev, 'inode':self.identity.st_ino}).encode(), 0)
            os.fsync(self.fd)
            self.sock.listen(2048)
            self.sock.setblocking(False)
            return self.sock
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.sock:
            self.sock.close()
        if self.identity:
            try:
                if same_inode(self.identity, socket_info(self.path)):
                    os.unlink(self.path)
            except (FileNotFoundError, PermissionError):
                LOG.warning('UDS cleanup preserved missing/replaced/unsafe path')
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def protected_app(target):
    from .session_binding import service_token, enabled
    from .events import utc_now
    from fastapi.responses import JSONResponse
    token_path = os.environ.get('RUNTIME_CONTROL_TOKEN_FILE', '')
    service_token(token_path) # startup failure; never run without a private control token
    module, name = target.split(':', 1)
    app = getattr(importlib.import_module(module), name)
    if not enabled():
        # Binding-disabled experimental deployments still authenticate every route.
        @app.middleware('http')
        async def trusted_local_control(request, call_next):
            try:
                valid = hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + service_token(token_path))
            except Exception:
                valid = False
            if not valid:
                return JSONResponse(status_code=401, content={'code':'INVALID_ARGUMENT','message':'Trusted control required','details':{'integrationCode':'UNAUTHENTICATED'},'requestId':f'req_{uuid4().hex}','timestamp':utc_now()})
            return await call_next(request)
    return app


def run(target='app.main:app', default_tcp_url='http://127.0.0.1:8000'):
    import uvicorn
    settings = ListenerSettings.from_env(default_tcp_url)
    app = protected_app(target)
    config = uvicorn.Config(app, host=settings.host, port=settings.port, loop='asyncio',
                            timeout_graceful_shutdown=25, proxy_headers=False, access_log=False)
    class LifecycleServer(uvicorn.Server):
        @contextmanager
        def capture_signals(self):
            # Uvicorn>=0.29 re-raises shutdown signals after ASGI cleanup.
            # Retain orderly handle_exit but let our socket context clean up first.
            if threading.current_thread() is not threading.main_thread():
                yield
                return
            handlers = {sig: signal.signal(sig, self.handle_exit) for sig in (signal.SIGINT, signal.SIGTERM)}
            try:
                yield
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
    server = LifecycleServer(config)
    LOG.warning('Runtime local control transport=%s fallback=%s', settings.mode, settings.fallback)
    if settings.mode == 'uds':
        with PrivateSocket(settings.path) as sock:
            server.run(sockets=[sock]) # server owns ASGI lifecycle, wrapper owns path lifecycle
    else:
        server.run()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--app', default='app.main:app'); args = parser.parse_args()
    try:
        run(args.app)
    except (ValueError, OSError, RuntimeError) as error:
        LOG.error('Runtime local listener startup failed: %s', error)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
