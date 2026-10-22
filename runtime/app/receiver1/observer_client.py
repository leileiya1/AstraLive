"""Client for a pinned OBSERVER process to record drain evidence (stage 3).

Used only by an independent Observer process with its own deployment
credential (load_inherited('OBSERVER')). It is not a Runtime or Guardian
capability and carries no ticket, grant or media. One peer-pinned AF_UNIX
request per call; any doubt is ObserverUnknown and is never retried blindly
(the Backend makes an identical record idempotent by evidenceRef).

Importing this module opens no socket.
"""

import asyncio
import json
import socket
import struct
import sys

from .transport import Credential, ProcessIdentity, TransportFailure, identity

PATH = "/registrar/receiver-1/observer/drain-evidence"


class ObserverRefused(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ObserverUnknown(RuntimeError):
    def __init__(self):
        super().__init__("DEPENDENCY_UNAVAILABLE")
        self.code = "DEPENDENCY_UNAVAILABLE"


class ObserverClient:
    def __init__(self, path, backend, credential, *, timeout=1.5):
        if not isinstance(backend, ProcessIdentity) or not isinstance(
            credential, Credential
        ):
            raise ObserverRefused("INVALID_ARGUMENT")
        self.path, self.backend, self.credential, self.timeout = (
            str(path),
            backend,
            credential,
            timeout,
        )

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

    async def record(self, command_id, artifact_id, evidence):
        body = json.dumps(
            {"commandId": command_id, "artifactId": artifact_id, "evidence": evidence},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            status, out = await asyncio.wait_for(self._exchange(body), self.timeout)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - any transport doubt is UNKNOWN
            raise ObserverUnknown() from None
        if status != 200:
            raise ObserverRefused(str(out.get("code", "DEPENDENCY_UNAVAILABLE")))
        if out.get("recorded") is not True or out.get("evidenceRef") != evidence.get(
            "evidenceRef"
        ):
            raise ObserverUnknown()
        return out

    async def _exchange(self, body):
        reader, writer = await asyncio.open_unix_connection(self.path)
        try:
            self._verify(writer)
            writer.write(
                b"POST "
                + PATH.encode()
                + b" HTTP/1.1\r\nHost: backend\r\nContent-Type: application/json"
                b"\r\nAuthorization: Bearer "
                + self.credential._raw
                + b"\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\n\r\n"
                + body
            )
            await writer.drain()
            header = await reader.readuntil(b"\r\n\r\n")
            lines = header.split(b"\r\n")
            status = int(lines[0].split(b" ", 2)[1])
            length = next(
                int(v)
                for k, _, v in (line.partition(b":") for line in lines[1:])
                if k.strip().lower() == b"content-length"
            )
            if not 0 < length <= 65536:
                raise TransportFailure("INVALID_ARGUMENT")
            out = json.loads(await reader.readexactly(length))
            if identity(self.backend.pid) != self.backend:
                raise TransportFailure("UNAUTHENTICATED")
            return status, out
        finally:
            writer.close()
