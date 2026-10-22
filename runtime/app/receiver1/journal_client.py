"""RUNTIME_JOURNAL client for the durable-live-2 Backend Journal.

One peer-pinned AF_UNIX request per call (the Backend closes each connection).
Official SDK codec only; the Runtime never connects to SQL. Every call returns
the two local clocks captured BEFORE the request, because a first START or
continuation response carries a one-time consumeTicket whose deadline must be
anchored before the RPC (receiver-1 contract). A lost or ambiguous response is
JournalUnknown: callers must not retry a START or invent a ticket.

Importing this module opens no socket and grants nothing.
"""

import asyncio
import socket
import struct
import sys
import time

from astralive_contracts import durable_live_v2 as dto

from .transport import (
    Credential,
    ProcessIdentity,
    TransportFailure,
    continuous,
    identity,
)
from .wire import mapping

ROLE = "RUNTIME_JOURNAL"
OPERATIONS = frozenset(
    {
        "JournalAccept",
        "JournalStart",
        "AcquireOutputPermit",
        "ConfirmRunFence",
        "JournalPrepareAnswer",
        "JournalStartAnswerSegment",
        "JournalConfirmAnswerSegment",
        "JournalSealAnswer",
        "JournalQueryAnswer",
        "ConfirmCheckpoint",
        "QueryExecutionStatus",
    }
)


class JournalUnknown(RuntimeError):
    """The Backend may or may not have applied the request."""

    def __init__(self, code="DEPENDENCY_UNAVAILABLE"):
        super().__init__(code)
        self.code = code


class JournalRefused(RuntimeError):
    """The Backend answered with a frozen error code; nothing was granted."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class JournalClient:
    def __init__(self, path, backend, credential, *, timeout=1.0, connect=None):
        if not isinstance(backend, ProcessIdentity) or not isinstance(
            credential, Credential
        ):
            raise JournalRefused("INVALID_ARGUMENT")
        if not 0 < timeout <= 2.0:
            raise JournalRefused("INVALID_ARGUMENT")
        self.path, self.backend, self.credential, self.timeout = (
            str(path),
            backend,
            credential,
            timeout,
        )
        self._connect = connect or asyncio.open_unix_connection

    def _verify(self, writer):
        sock = writer.get_extra_info("socket")
        if sys.platform.startswith("linux"):
            pid, _, _ = struct.unpack(
                "3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
        elif sys.platform == "darwin":
            pid = struct.unpack("i", sock.getsockopt(0, 2, 4))[0]
        else:
            raise TransportFailure("OUTPUT_FENCE_UNPROVEN")
        if pid != self.backend.pid or identity(pid) != self.backend:
            raise TransportFailure("UNAUTHENTICATED")

    async def call(self, operation, document):
        """Return (response mapping, sent) where sent=(monotonic, suspend)."""
        if operation not in OPERATIONS:
            raise JournalRefused("FORBIDDEN")
        op = dto.OPERATIONS[operation]
        if ROLE not in op.roles or op.target != "BACKEND":
            raise JournalRefused("FORBIDDEN")
        request = dto.decode(op.request_schema, dto.canonical_json(document))
        raw = dto.encode_request(
            operation,
            request,
            role=ROLE,
            target=op.target,
            method=op.method,
            route_template=op.path,
        )
        path = op.path.replace("{runId}", str(request.runId))
        sent = (time.monotonic(), continuous())
        try:
            status, body = await asyncio.wait_for(
                self._exchange(op, path, raw), self.timeout
            )
            response = dto.decode_response(operation, body, status=status)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - any transport doubt is UNKNOWN
            raise JournalUnknown() from None
        if status != op.success_status:
            raise JournalRefused(str(response.code))
        if response.requestId != request.requestId:
            raise JournalUnknown()
        return mapping(response), sent

    async def _exchange(self, op, path, raw):
        reader, writer = await self._connect(self.path)
        try:
            self._verify(writer)
            writer.write(
                b"POST " + path.encode("ascii") + b" HTTP/1.1\r\nHost: backend\r\n"
                b"Content-Type: application/json\r\nAuthorization: Bearer "
                + self.credential._raw
                + b"\r\nContent-Length: "
                + str(len(raw)).encode()
                + b"\r\n\r\n"
                + raw
            )
            await writer.drain()
            header = await reader.readuntil(b"\r\n\r\n")
            if len(header) > 8192:
                raise TransportFailure("INVALID_ARGUMENT")
            lines = header.split(b"\r\n")
            version, status, _ = lines[0].split(b" ", 2)
            if version != b"HTTP/1.1":
                raise TransportFailure("INVALID_ARGUMENT")
            headers = {}
            for line in lines[1:-2]:
                key, value = line.split(b":", 1)
                key = key.strip().lower()
                if key in headers:
                    raise TransportFailure("INVALID_ARGUMENT")
                headers[key] = value.strip()
            length = headers.get(b"content-length", b"")
            if b"transfer-encoding" in headers or not length.isdigit():
                raise TransportFailure("INVALID_ARGUMENT")
            if not 0 < int(length) <= op.max_body_bytes:
                raise TransportFailure("INVALID_ARGUMENT")
            body = await reader.readexactly(int(length))
            if identity(self.backend.pid) != self.backend:
                raise TransportFailure("UNAUTHENTICATED")
            return int(status), body
        finally:
            writer.close()
