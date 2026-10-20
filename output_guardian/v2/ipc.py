"""Protected HTTP/1.1 over AF_UNIX, frozen receiver-1 routes only.

No token-only identity, JSON enrolment, custom Authority wire, v1 fallback or
production listener. Agent4 provisions pins and supplies the sole strict codec.
Nonblocking socket writes revalidate at EVERY transport delivery edge.
"""

import asyncio
import hashlib
import hmac
import os
import secrets
import socket
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import psutil

from output_guardian.model import Closed

from .gate import require

# Exactly the seven Guardian-owned operations of the frozen thirteen. Backend
# and Registrar operations are NOT registered on this listener.
OPERATIONS = {
    "/guardian/durable-live-2/bootstrap/stage": (
        "stage",
        "ReceiverStage",
        "CONTROL_REGISTRAR",
    ),
    "/guardian/durable-live-2/consume": (
        "consume",
        "ReceiverConsume",
        "REGISTERED_RUNTIME",
    ),
    "/guardian/durable-live-2/renew": ("renew", "ReceiverRenew", "REGISTERED_RUNTIME"),
    "/guardian/durable-live-2/consumption/query": (
        "query",
        "ReceiverQueryConsumption",
        "REGISTERED_RUNTIME",
    ),
    "/guardian/durable-live-2/media": ("media", "ReceiverMedia", "REGISTERED_RUNTIME"),
    "/guardian/durable-live-2/unit/finish": (
        "finish",
        "ReceiverFinishUnit",
        "REGISTERED_RUNTIME",
    ),
    "/guardian/durable-live-2/stop": ("stop", "ReceiverStop", "CONTROL_REGISTRAR"),
}


@dataclass(frozen=True)
class ProcessPin:
    """Trusted Registrar input, not an HTTP/JSON DTO; never self-enrolled."""

    principal_id: str
    role: str
    incarnation: str
    scope: tuple
    pid: int
    uid: int
    created: float
    credential_hash: bytes


@dataclass(frozen=True)
class Peer:
    principal_id: str
    role: str
    incarnation: str
    scope: tuple
    channel_binding: str


def credentials(sock):
    if sys.platform.startswith("linux"):
        pid, uid, _ = struct.unpack(
            "3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
    elif sys.platform == "darwin":
        # LOCAL_PEERPID is available on accepted AF_UNIX stream sockets. UID is
        # independently checked on the kernel-selected PID creation identity.
        pid = struct.unpack("i", sock.getsockopt(0, 2, 4))[0]
        uid = psutil.Process(pid).uids().real
    else:
        raise Closed("OUTPUT_FENCE_UNPROVEN")
    return pid, uid


class PrivateIPC:
    def __init__(self, receiver, directory, pins, *, access_groups=None):
        self.receiver, self.directory = receiver, Path(directory)
        self.pins = tuple(pins)
        self.listeners, self.tasks, self.connections = [], set(), set()
        self.paths = []
        self.role_directories = []
        self.access_groups = dict(access_groups or {})
        require(
            not self.access_groups
            or set(self.access_groups) == {"CONTROL_REGISTRAR", "REGISTERED_RUNTIME"},
            "INVALID_ARGUMENT",
        )
        self.max_connections = 16

    async def start(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = self.directory.lstat()
        require(
            stat.S_ISDIR(st.st_mode)
            and st.st_uid == os.geteuid()
            and not st.st_mode & (0o066 if self.access_groups else 0o077)
        )
        if self.access_groups:
            # Trusted deployment supplies two distinct role groups; Guardian
            # must belong to both. Runtime never gets the CONTROL group.
            require(len(set(self.access_groups.values())) == 2, "FORBIDDEN")
            os.chmod(self.directory, 0o711)  # traverse only, no list/read/write
        try:
            for role, name in (
                ("CONTROL_REGISTRAR", "control.sock"),
                ("REGISTERED_RUNTIME", "runtime.sock"),
            ):
                role_directory = self.directory
                if self.access_groups:
                    role_directory = self.directory / role.lower()
                    role_directory.mkdir(mode=0o710)
                    self.role_directories.append(role_directory)
                    os.chown(role_directory, -1, self.access_groups[role])
                    os.chmod(role_directory, 0o710)
                path = role_directory / name
                require(not path.exists() and not path.is_symlink())
                listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.listeners.append(listener)
                listener.setblocking(False)
                listener.bind(str(path))
                self.paths.append(path)
                if self.access_groups:
                    os.chown(path, -1, self.access_groups[role])
                os.chmod(path, 0o660 if self.access_groups else 0o600)
                listener.listen(16)
                self._task(self._accept(listener, role))
        except BaseException:
            await self.close()
            raise

    def _task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def _accept(self, listener, role):
        loop = asyncio.get_running_loop()
        while True:
            client, _ = await loop.sock_accept(listener)
            if len(self.connections) >= self.max_connections:
                client.close()
                continue
            client.setblocking(False)
            self.connections.add(client)
            self._task(self._connection(client, role))

    def _peer(self, sock, role, token, channel):
        pid, uid = credentials(sock)
        created = psutil.Process(pid).create_time()
        digest = hashlib.sha256(token).digest()
        matches = [
            p
            for p in self.pins
            if p.pid == pid
            and p.uid == uid
            and p.created == created
            and p.role == role
            and hmac.compare_digest(p.credential_hash, digest)
        ]
        require(len(matches) == 1, "UNAUTHENTICATED")
        p = matches[0]
        return Peer(p.principal_id, p.role, p.incarnation, p.scope, channel)

    async def _request(self, sock):
        loop = asyncio.get_running_loop()
        header = bytearray()
        # No pipelining/ambiguous lengths, Transfer-Encoding, duplicate headers,
        # query tokens or arbitrary paths. A request never buffers a lookahead.
        while not header.endswith(b"\r\n\r\n"):
            require(len(header) < 8192, "INVALID_ARGUMENT")
            part = await loop.sock_recv(sock, 1)
            require(bool(part), "UNAUTHENTICATED")
            header.extend(part)
        lines = bytes(header).split(b"\r\n")
        method, path, version = lines[0].decode("ascii").split(" ")
        require(
            method == "POST" and version == "HTTP/1.1" and path in OPERATIONS,
            "INVALID_ARGUMENT",
        )
        headers = {}
        for line in lines[1:-2]:
            key, value = line.split(b":", 1)
            key = key.strip().lower()
            require(key not in headers, "INVALID_ARGUMENT")
            headers[key] = value.strip()
        require(b"transfer-encoding" not in headers, "INVALID_ARGUMENT")
        size = headers.get(b"content-length", b"")
        require(size.isdigit() and len(size) <= 8, "INVALID_ARGUMENT")
        length = int(size)
        limit = 9 * 1024 * 1024 if OPERATIONS[path][0] == "media" else 256 * 1024
        require(0 < length <= limit, "INVALID_ARGUMENT")
        authorization = headers.get(b"authorization", b"")
        require(
            authorization.startswith(b"Bearer ") and len(authorization) <= 256,
            "UNAUTHENTICATED",
        )
        body = bytearray()
        while len(body) < length:
            part = await loop.sock_recv(sock, min(65536, length - len(body)))
            require(bool(part), "INVALID_ARGUMENT")
            body.extend(part)
        return path, authorization[7:], bytes(body)

    async def _connection(self, sock, role):
        channel = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        authenticated, response_started, request_id = False, False, "ipc_error"
        try:
            while True:
                response_started = False
                path, token, raw = await asyncio.wait_for(self._request(sock), 2)
                peer = self._peer(sock, role, token, channel)
                authenticated = True
                method, operation, allowed = OPERATIONS[path]
                require(role == allowed, "FORBIDDEN")
                try:
                    q = self.receiver.wire.decode(operation + "Request", raw)
                except Exception:
                    raise Closed("INVALID_ARGUMENT") from None
                request_id = q["requestId"]
                result = await getattr(self.receiver, method)(peer, q)
                self.receiver.wire.validate(operation + "Response", result)
                body = self.receiver.wire.canonical(result)
                response = (
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\n\r\n"
                    + body
                )
                lineage, grant_budget = None, None
                gate = self.receiver.gate
                with gate.lock:
                    if method == "consume" and result["consumeAuthorized"]:
                        require(bool(gate.acks))
                        lineage, queued, grant_budget = gate.acks.popleft()
                        require(queued is result)
                    elif method in {"media", "renew"}:
                        lineage = gate.active
                        require(lineage is not None)
                pending = memoryview(response)
                while pending:
                    # Kernel process pins rechecked outside gate. Channel is
                    # unique to this accepted connection, not a JSON field.
                    self._peer(sock, role, token, channel)
                    with gate.lock:
                        if lineage is not None:
                            gate.execution_locked(lineage)
                        if grant_budget is not None:
                            grant_budget.check()
                        try:
                            count = sock.send(pending[:16384])
                        except BlockingIOError:
                            count = 0
                        if count:
                            response_started = True
                            pending = pending[count:]
                    if not count:
                        await asyncio.sleep(0.001)  # no network wait in gate
        except Exception as exc:
            # No replay/retry of a partial true ACK. Closed stream is ambiguous.
            # Do not expose raw decode/body/process exceptions or credentials.
            if authenticated and not response_started:
                code = exc.code if isinstance(exc, Closed) else "DEPENDENCY_UNAVAILABLE"
                status = {
                    "UNAUTHENTICATED": 401,
                    "FORBIDDEN": 403,
                    "INVALID_ARGUMENT": 422,
                    "OVERLOADED": 429,
                    "DEPENDENCY_UNAVAILABLE": 503,
                }.get(code, 409)
                try:
                    document = dict(requestId=request_id, code=code)
                    self.receiver.wire.validate("ReceiverErrorResponse", document)
                    body = self.receiver.wire.canonical(document)
                    error = (
                        f"HTTP/1.1 {status} Rejected\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {len(body)}\r\n\r\n".encode()
                        + body
                    )
                    # Error metadata grants no output permission. Bounded send
                    # outside the admission gate; failure simply closes stream.
                    await asyncio.wait_for(
                        asyncio.get_running_loop().sock_sendall(sock, error), 0.1
                    )
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            # Disconnect of the owning execution cannot leave reusable output.
            gate = self.receiver.gate
            try:
                with gate.lock:
                    record = self.receiver.record
                    owned = (
                        record is not None
                        and record["channelBinding"] == channel
                        and gate.active is not None
                    )
                    if owned:
                        self.receiver.audit[record["binding"]["grantId"]] = "UNKNOWN"
                        gate.unknown_locked()
            except Closed:
                owned = True  # poisoned mutex: independent cleanup still runs
            if owned:
                await self.receiver.outputs.close()
            self.connections.discard(sock)
            sock.close()

    async def close(self):
        for listener in self.listeners:
            listener.close()
        self.listeners.clear()
        for sock in tuple(self.connections):
            sock.close()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for path in self.paths:
            path.unlink(missing_ok=True)
        self.paths.clear()
        for directory in self.role_directories:
            directory.rmdir()
        self.role_directories.clear()
