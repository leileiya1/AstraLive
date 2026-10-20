"""Peer-pinned private Unix HTTP transport; never a business DB client.

Deployment supplies the credential over an inherited private FD and pins the
Backend OS identity. No Runtime JSON can construct a trusted Backend Actor.
Only the three frozen Authority operations are exposed by AuthorityTransport.
"""
import asyncio
import ctypes
import dataclasses
import hashlib
import math
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import time
import threading

import psutil

from astralive_contracts import durable_live_v2 as dto
from .wire import mapping


class TransportFailure(RuntimeError):
    """Fixed codes only: no body, credential, ticket or underlying exception."""


@dataclasses.dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    uid: int
    birth: str


def identity(pid):
    p = psutil.Process(pid)
    if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
        raise TransportFailure("UNAUTHENTICATED")
    if sys.platform.startswith("linux"):
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        birth = Path("/proc/sys/kernel/random/boot_id").read_text().strip() + ":" + fields[19]
    elif sys.platform == "darwin":
        micros = round(p.create_time() * 1_000_000)
        birth = f"darwin:{micros // 1_000_000}:{micros % 1_000_000}"
    else:
        raise TransportFailure("OUTPUT_FENCE_UNPROVEN")
    return ProcessIdentity(pid, p.uids().real, birth)


def continuous():
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    if sys.platform == "darwin":
        class Timebase(ctypes.Structure):
            _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]
        lib = ctypes.CDLL(None)
        lib.mach_continuous_time.restype = ctypes.c_uint64
        tb = Timebase()
        if lib.mach_timebase_info(ctypes.byref(tb)) != 0 or not tb.denom:
            raise TransportFailure("DEPENDENCY_UNAVAILABLE")
        return lib.mach_continuous_time() * tb.numer / tb.denom / 1_000_000_000
    raise TransportFailure("OUTPUT_FENCE_UNPROVEN")


class Credential:
    __slots__ = ("_raw",)
    def __init__(self, raw):
        if not isinstance(raw, bytes) or len(raw) != 43 or not all(
                c in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in raw):
            raise TransportFailure("UNAUTHENTICATED")
        self._raw = raw
    def __repr__(self): return "Credential(<redacted>)"
    __str__ = __repr__


class _UnixTransport:
    def __init__(self, path, backend, credential, *, timeout=0.200):
        if not isinstance(backend, ProcessIdentity) or not isinstance(credential, Credential) or not 0 < timeout <= 0.250:
            raise TransportFailure("INVALID_ARGUMENT")
        self.path, self.backend, self.credential, self.timeout = str(path), backend, credential, timeout
        self._pending = threading.BoundedSemaphore(16)

    async def _invoke(self, operation, document):
        if not self._pending.acquire(blocking=False):
            raise TransportFailure("OVERLOADED")
        try:
            started = (time.monotonic(), continuous())
        except BaseException:
            self._pending.release()
            raise
        def invoke():
            try:
                return self._call(operation, document, _sent=started)
            finally:
                self._pending.release()
        # Cancellation cannot strand admission or make unbounded worker tasks.
        task = asyncio.create_task(asyncio.to_thread(invoke))
        task.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        return await asyncio.shield(task)

    def _peer(self, sock):
        if sys.platform.startswith("linux"):
            pid, uid, _ = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        elif sys.platform == "darwin":
            pid = struct.unpack("i", sock.getsockopt(0, 2, 4))[0]
            uid = identity(pid).uid
        else:
            raise TransportFailure("OUTPUT_FENCE_UNPROVEN")
        if identity(pid) != self.backend or uid != self.backend.uid:
            raise TransportFailure("UNAUTHENTICATED")

    def _call(self, operation, document, *, _sent=None):
        sent, suspended = _sent or (time.monotonic(), continuous())
        op = dto.OPERATIONS[operation]
        request = dto.decode(op.request_schema, dto.canonical_json(document))
        raw = dto.encode_request(operation, request, role="OUTPUT_GUARDIAN", target=op.target,
                                 method=op.method, route_template=op.path)
        def remaining():
            return self.timeout - max(time.monotonic() - sent, continuous() - suspended)
        try:
            if remaining() <= 0: raise TransportFailure("DEPENDENCY_UNAVAILABLE")
            parent = Path(self.path).parent.lstat()
            entry = Path(self.path).lstat()
            if not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o077 or parent.st_uid != self.backend.uid or not stat.S_ISSOCK(entry.st_mode) or entry.st_mode & 0o077 or entry.st_uid != self.backend.uid:
                raise TransportFailure("UNAUTHENTICATED")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(max(0.001, remaining()))
                sock.connect(self.path)
                self._peer(sock)
                if remaining() <= 0: raise TransportFailure("DEPENDENCY_UNAVAILABLE")
                sock.settimeout(remaining())
                header = (b"POST " + op.path.encode("ascii") + b" HTTP/1.1\r\nHost: private\r\nContent-Type: application/json\r\nAuthorization: Bearer " + self.credential._raw + b"\r\nContent-Length: " + str(len(raw)).encode() + b"\r\nConnection: close\r\n\r\n")
                sock.sendall(header + raw)
                received = bytearray()
                while b"\r\n\r\n" not in received:
                    if len(received) >= 8192 or remaining() <= 0:
                        raise TransportFailure("DEPENDENCY_UNAVAILABLE")
                    sock.settimeout(remaining())
                    chunk = sock.recv(1)
                    if not chunk: raise TransportFailure("CONSUMPTION_UNKNOWN")
                    received.extend(chunk)
                lines = bytes(received).split(b"\r\n")
                parts = lines[0].split(b" ", 2)
                if len(parts) != 3 or parts[0] != b"HTTP/1.1":
                    raise TransportFailure("INVALID_ARGUMENT")
                status = int(parts[1])
                headers = {}
                for line in lines[1:-2]:
                    k, v = line.split(b":", 1); k = k.lower()
                    if k in headers: raise TransportFailure("INVALID_ARGUMENT")
                    headers[k] = v.strip()
                length = headers.get(b"content-length", b"")
                if b"transfer-encoding" in headers or not length.isdigit() or not 0 < int(length) <= op.max_body_bytes:
                    raise TransportFailure("INVALID_ARGUMENT")
                body = bytearray()
                while len(body) < int(length):
                    if remaining() <= 0: raise TransportFailure("DEPENDENCY_UNAVAILABLE")
                    sock.settimeout(remaining())
                    chunk = sock.recv(min(65536, int(length) - len(body)))
                    if not chunk: raise TransportFailure("CONSUMPTION_UNKNOWN")
                    body.extend(chunk)
                # A server may close immediately after its bounded response.
                # The kernel-bound peer cannot change on an existing socket;
                # LOCAL_PEERPID on a closed Darwin socket can return ENOTCONN.
                if identity(self.backend.pid) != self.backend:
                    raise TransportFailure("UNAUTHENTICATED")
            if remaining() <= 0: raise TransportFailure("CONSUMPTION_UNKNOWN")
            response = dto.decode_response(operation, bytes(body), status=status)
            if status != op.success_status: raise TransportFailure(str(response.code))
            if response.requestId != request.requestId: raise TransportFailure("CONSUMPTION_UNKNOWN")
            out = mapping(response)
            # Consume elapsed time before returning. Guardian applies its own
            # original outer anchor/final gate again; double subtraction is safe.
            elapsed = math.ceil(max(time.monotonic() - sent, continuous() - suspended) * 1000)
            timing = out.get("consumeTiming")
            first = out.get("consumeAuthorized") is True
            if "snapshot" in out: timing = out["snapshot"]["timing"]
            if timing is not None:
                for k in ("remainingGrantMs", "remainingProofMs"):
                    timing[k] = max(0, timing[k] - elapsed)
                budget = min(timing["remainingGrantMs"], timing["remainingProofMs"]) if first else timing["remainingProofMs"]
                if budget <= timing["safetyMarginMs"]:
                    raise TransportFailure("CONSUMPTION_UNKNOWN")
            return out
        except (TransportFailure, dto.WireError):
            raise
        except Exception as e:
            error = TransportFailure("DEPENDENCY_UNAVAILABLE")
            error.cause_type = type(e).__name__  # class only; no message/payload
            error.os_errno = getattr(e, "errno", None)
            raise error from None


class AuthorityTransport(_UnixTransport):
    async def query_receiver_authority(self, request):
        return await self._invoke("QueryReceiverAuthority", request)

    async def commit_receiver_consume(self, request):
        # Exactly one call; no retry, true-response cache or ticket retention.
        return await self._invoke("CommitReceiverConsume", request)

    async def query_receiver_consumption(self, request):
        return await self._invoke("QueryReceiverConsumption", request)


class InstallationReader(_UnixTransport):
    async def read(self, request):
        return await self._invoke("ReadReceiverPhysicalInstallation", request)
