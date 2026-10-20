"""Runtime side of receiver-1: one consume, one TTS, lineage-bound media.

Implements the REGISTERED_RUNTIME role of the frozen receiver-1 contract
(RECEIVER-BOOTSTRAP-CONTRACT.md, examples/python/receiver.py RuntimeActor):

* The one-time ``consumeTicket`` from the FIRST true START/continuation
  response is held privately, sent once over the Guardian private IPC and
  erased after success, refusal or any ambiguity. It is never logged.
* Only the first true ACK for a still-pending nonce on the same persistent
  channel is accepted, inside the original START deadline intersected with
  the consume-ACK deadline, and again after the fresh proof exchange.
* TTS for the committed exact Artifact runs at most once per execution.
* Media carries the immutable lineage captured at submission and one outer
  ordinal that stays continuous across units. A delayed item of an older
  execution is rejected, never relabelled with the current execution.
* Any transport doubt makes the execution UNKNOWN. Nothing retries a consume,
  reconnects an execution or turns a query result back into an execution.

Importing this module opens no socket and grants nothing.
"""

import asyncio
import base64
import contextlib
import dataclasses
import secrets
import socket
import struct
import sys
import time

from astralive_contracts import durable_live_v2 as dto
from astralive_contracts.durable_live_v2.codec import SecretString

from .transport import (
    Credential,
    ProcessIdentity,
    TransportFailure,
    continuous,
    identity,
)
from .wire import mapping

ROLE = "REGISTERED_RUNTIME"
REVISIONS = {"contractRevision": "durable-live-2", "receiverRevision": "receiver-1"}
HEADER_LIMIT = 8192


class ReceiverUnknown(RuntimeError):
    """Execution or consume outcome is unknowable; reconcile via CONTROL only."""

    def __init__(self, code="CONSUMPTION_UNKNOWN"):
        super().__init__(code)
        self.code = code


class ReceiverRefused(RuntimeError):
    """Guardian or local rules refused the request; nothing was authorized."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _require(condition, code):
    if not condition:
        raise ReceiverRefused(code)


def request_id(prefix="req"):
    return prefix + "_" + secrets.token_hex(16)


class Deadline:
    """Both local clocks anchored BEFORE the RPC; fixed safety margin."""

    def __init__(self, timing, sent, *, grant=True, clocks=None):
        self.clocks = clocks or (time.monotonic, continuous)
        remaining = timing["remainingProofMs"]
        if grant:
            remaining = min(timing["remainingGrantMs"], remaining)
        duration = remaining / 1000 - timing["safetyMarginMs"] / 1000
        self.mono, self.suspended = sent[0] + duration, sent[1] + duration

    def check(self, code="GRANT_EXPIRED"):
        mono, suspended = self.clocks
        if not (mono() < self.mono and suspended() < self.suspended):
            raise ReceiverRefused(code)


@dataclasses.dataclass(frozen=True)
class Lineage:
    """Immutable owner captured when PCM/GPU work is submitted."""

    execution_id: str
    artifact_id: str
    artifact_hash: str


@dataclasses.dataclass
class Execution:
    lineage: Lineage
    consumption: dict
    channel: "GuardianChannel"
    proof: Deadline
    state: str = "ACTIVE"  # ACTIVE -> FINISHED | UNKNOWN; never back to ACTIVE
    tts_started: bool = False

    def request(self, **extra):
        return dict(
            REVISIONS,
            requestId=request_id(),
            executionId=self.lineage.execution_id,
            artifactId=self.lineage.artifact_id,
            artifactHash=self.lineage.artifact_hash,
            **extra,
        )


class GuardianChannel:
    """One persistent, peer-pinned AF_UNIX HTTP/1.1 connection = one channel.

    Guardian binds a consumed execution to the accepted connection. Requests
    are strictly sequential; after any failure the channel is dead forever.
    """

    def __init__(self, path, guardian, credential, *, timeout=0.200, connect=None):
        if not isinstance(guardian, ProcessIdentity) or not isinstance(
            credential, Credential
        ):
            raise ReceiverRefused("INVALID_ARGUMENT")
        if not 0 < timeout <= 0.250:
            raise ReceiverRefused("INVALID_ARGUMENT")
        self.path, self.guardian, self.credential = str(path), guardian, credential
        self.timeout = timeout
        self._connect = connect or asyncio.open_unix_connection
        self._lock = asyncio.Lock()
        self._streams = None
        self.dead = False

    def _verify_socket_peer(self):
        # The kernel-bound peer of a connected AF_UNIX socket cannot change,
        # so it is read once per connection (Darwin LOCAL_PEERPID returns
        # ENOTCONN after the peer closes, like transport.py documents).
        sock = self._streams[1].get_extra_info("socket")
        if sys.platform.startswith("linux"):
            pid, _, _ = struct.unpack(
                "3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
        elif sys.platform == "darwin":
            pid = struct.unpack("i", sock.getsockopt(0, 2, 4))[0]
        else:
            raise TransportFailure("OUTPUT_FENCE_UNPROVEN")
        if pid != self.guardian.pid or identity(pid) != self.guardian:
            raise TransportFailure("UNAUTHENTICATED")

    def _verify_pinned_process(self):
        if identity(self.guardian.pid) != self.guardian:
            raise TransportFailure("UNAUTHENTICATED")

    async def call(self, operation, document, *, deadline=None):
        op = dto.OPERATIONS[operation]
        if ROLE not in op.roles or op.target != "GUARDIAN":
            raise ReceiverRefused("FORBIDDEN")
        async with self._lock:
            if self.dead:
                raise ReceiverUnknown("CHANNEL_CLOSED")
            try:
                request = dto.decode(op.request_schema, dto.canonical_json(document))
                raw = dto.encode_request(
                    operation,
                    request,
                    role=ROLE,
                    target=op.target,
                    method=op.method,
                    route_template=op.path,
                )
                status, body = await asyncio.wait_for(
                    self._exchange(op, raw),
                    self.timeout if deadline is None else deadline,
                )
                response = dto.decode_response(operation, body, status=status)
            except ReceiverRefused:
                raise
            except asyncio.CancelledError:
                await self._kill()  # outcome unknown; propagate cancellation
                raise
            except Exception:  # noqa: BLE001 - any doubt is UNKNOWN by contract
                # Partial write/read, peer change, timeout or decode doubt: the
                # outcome may have happened. Never reuse this channel.
                await self._kill()
                raise ReceiverUnknown() from None
            if status != op.success_status:
                await self._kill()  # Guardian closes the stream after an error
                raise ReceiverRefused(str(response.code))
            if response.requestId != request.requestId:
                await self._kill()
                raise ReceiverUnknown()
            return mapping(response)

    async def _exchange(self, op, raw):
        if self._streams is None:
            self._streams = await self._connect(self.path)
            self._verify_socket_peer()
        self._verify_pinned_process()
        reader, writer = self._streams
        writer.write(
            b"POST " + op.path.encode("ascii") + b" HTTP/1.1\r\nHost: guardian\r\n"
            b"Content-Type: application/json\r\nAuthorization: Bearer "
            + self.credential._raw
            + b"\r\nContent-Length: "
            + str(len(raw)).encode()
            + b"\r\n\r\n"
            + raw
        )
        await writer.drain()
        header = await reader.readuntil(b"\r\n\r\n")
        if len(header) > HEADER_LIMIT:
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
        self._verify_pinned_process()
        return int(status), body

    async def _kill(self):
        self.dead = True
        streams, self._streams = self._streams, None
        if streams is not None:
            streams[1].close()
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                await asyncio.wait_for(streams[1].wait_closed(), 0.1)

    async def close(self):
        async with self._lock:
            await self._kill()


class ReceiverRuntime:
    """REGISTERED_RUNTIME actor. One instance per Runtime process incarnation."""

    def __init__(self, open_channel, wire, *, clocks=None):
        self._open_channel = open_channel  # () -> GuardianChannel
        self.wire = wire
        self.clocks = clocks or (time.monotonic, continuous)
        self._channel = None
        self._tickets, self._start_deadlines, self._grants = {}, {}, {}
        self._pending = set()
        self.executions = {}
        self.knowledge = {}  # grantId -> metadata-only state after doubt
        self.next_sequence = 0
        self.tts_invocations = 0

    def now(self):
        return self.clocks[0](), self.clocks[1]()

    # -- one-time Grant ---------------------------------------------------

    def remember_start(self, grant, response, sent):
        """``sent`` is (monotonic, suspend-inclusive) captured BEFORE the
        JournalStart/StartAnswerSegment RPC that returned ``response``."""
        ticket, timing = response.get("consumeTicket"), response.get("consumeTiming")
        _require(ticket is not None and timing is not None, "GRANT_TICKET_INVALID")
        _require(grant["grantId"] not in self._grants, "GRANT_TICKET_INVALID")
        if not isinstance(ticket, SecretString):
            ticket = dto.decode("ReceiverConsumeTicket", dto.canonical_json(ticket))
        self._grants[grant["grantId"]] = grant
        self._tickets[grant["grantId"]] = ticket
        self._start_deadlines[grant["grantId"]] = Deadline(
            timing, sent, clocks=self.clocks
        )

    def _forget(self, grant_id, state):
        self._tickets.pop(grant_id, None)
        self.knowledge[grant_id] = state

    def _channel_for_consume(self):
        if self._channel is None or self._channel.dead:
            self._channel = self._open_channel()
        return self._channel

    async def consume(self, registration, references, artifact):
        """Return a fixed Execution, or raise. Never retried by this class."""
        grant_id = references["grantId"]
        _require(grant_id in self._tickets, "GRANT_TICKET_INVALID")
        nonce, sent_any = None, False
        try:
            self.wire.validate_artifact(artifact)
            _require(
                artifact["artifactId"] == references["artifactId"], "ANSWER_CONFLICT"
            )
            _require(
                artifact["artifactHash"] == references["artifactHash"],
                "ANSWER_CONFLICT",
            )
            start = self._start_deadlines[grant_id]
            start.check()
            binding = registration["binding"]
            nonce = request_id("consume")
            self._pending.add(nonce)
            q = dict(
                REVISIONS,
                requestId=request_id(),
                references=dict(references),
                consumeTicket=self._tickets[grant_id],
                consumeRequestId=nonce,
                expectedGenerationId=binding["generationId"],
                expectedGuardianIncarnation=binding["guardianIncarnation"],
                expectedRegistrationRevision=registration["revision"],
            )
            channel = self._channel_for_consume()
            sent = self.now()
            sent_any = True  # from here on the Backend latch may exist
            ack = await channel.call("ReceiverConsume", q)
            if ack["consumeAuthorized"] is not True:
                self._forget(grant_id, "NOT_AUTHORIZED")
                raise ReceiverRefused("CONSUMPTION_CONFLICT")
            _require(nonce in self._pending, "CONSUMPTION_UNKNOWN")
            record = ack["consumption"]
            execution_binding = record["binding"]
            _require(record["consumeRequestId"] == nonce, "CONSUMPTION_CONFLICT")
            _require(execution_binding["grantId"] == grant_id, "CONSUMPTION_CONFLICT")
            _require(
                execution_binding["artifactId"] == artifact["artifactId"],
                "ANSWER_CONFLICT",
            )
            _require(
                execution_binding["artifactHash"] == artifact["artifactHash"],
                "ANSWER_CONFLICT",
            )
            lineage = Lineage(
                execution_binding["executionId"],
                artifact["artifactId"],
                artifact["artifactHash"],
            )
            _require(lineage.execution_id not in self.executions, "CONSUMPTION_UNKNOWN")
            ack_deadline = Deadline(ack["consumeTiming"], sent, clocks=self.clocks)
            start.check()
            ack_deadline.check()
            # Fresh proof exchange BEFORE TTS; deadlines rechecked after it.
            proof_sent = self.now()
            proof = await channel.call(
                "ReceiverRenew",
                dict(
                    REVISIONS,
                    requestId=request_id(),
                    executionId=lineage.execution_id,
                    artifactId=lineage.artifact_id,
                    artifactHash=lineage.artifact_hash,
                    permitId=references["permitId"],
                ),
            )
            proof_deadline = Deadline(
                proof["timing"], proof_sent, grant=False, clocks=self.clocks
            )
            proof_deadline.check("LEASE_LOST")
            start.check()
            ack_deadline.check()
        except ReceiverRefused:
            if self.knowledge.get(grant_id) != "NOT_AUTHORIZED":
                self._forget(grant_id, "UNKNOWN" if sent_any else "REFUSED")
            raise
        except asyncio.CancelledError:
            self._forget(grant_id, "UNKNOWN")
            raise
        except Exception:  # noqa: BLE001 - any doubt is UNKNOWN by contract
            self._forget(grant_id, "UNKNOWN")
            raise ReceiverUnknown() from None
        finally:
            self._pending.discard(nonce)
        execution = Execution(lineage, record, channel, proof_deadline)
        self.executions[lineage.execution_id] = execution
        self._forget(grant_id, "CONSUMED")
        self._start_deadlines.pop(grant_id, None)
        return execution

    # -- exactly one TTS ----------------------------------------------------

    async def speak_once(self, execution, artifact, synthesize):
        """Invoke ``synthesize(text)`` exactly once for the committed body.

        The latch is taken before the call, so neither an exception nor a
        second caller can ever start TTS again for this execution.
        """
        _require(
            self.executions.get(execution.lineage.execution_id) is execution,
            "STALE_EXECUTION",
        )
        _require(
            execution.state == "ACTIVE" and not execution.tts_started,
            "TTS_ALREADY_STARTED",
        )
        _require(
            artifact["artifactHash"] == execution.lineage.artifact_hash,
            "ANSWER_CONFLICT",
        )
        execution.proof.check("LEASE_LOST")
        execution.tts_started = True
        self.tts_invocations += 1
        return await synthesize(artifact["answerText"])

    # -- lineage-bound media -----------------------------------------------

    def submit(self, execution):
        """Capture the owner of work at submission time (PCM/GPU request)."""
        _require(execution.state == "ACTIVE", "STALE_EXECUTION")
        return execution.lineage

    def _active(self, lineage):
        execution = self.executions.get(lineage.execution_id)
        _require(
            execution is not None and execution.state == "ACTIVE", "STALE_EXECUTION"
        )
        _require(execution.lineage == lineage, "STALE_EXECUTION")
        return execution

    async def _call(self, execution, operation, document):
        try:
            return await execution.channel.call(operation, document)
        except ReceiverUnknown:
            execution.state = "UNKNOWN"
            raise
        except ReceiverRefused:
            # Guardian closed this channel; nothing else may use it.
            execution.state = "UNKNOWN"
            raise

    async def renew(self, lineage, permit_id):
        execution = self._active(lineage)
        sent = self.now()
        proof = await self._call(
            execution, "ReceiverRenew", execution.request(permitId=permit_id)
        )
        deadline = Deadline(proof["timing"], sent, grant=False, clocks=self.clocks)
        deadline.check("LEASE_LOST")
        execution.proof = deadline
        return proof

    async def media(self, lineage, permit_id, kind, payload, pts_us=None):
        execution = self._active(lineage)
        _require(execution.tts_started, "STALE_EXECUTION")
        _require(kind in {"audio", "video"}, "INVALID_ARGUMENT")
        _require((pts_us is None) == (kind == "audio"), "INVALID_ARGUMENT")
        execution.proof.check("LEASE_LOST")
        out = await self._call(
            execution,
            "ReceiverMedia",
            execution.request(
                permitId=permit_id,
                kind=kind,
                sequence=self.next_sequence,
                ptsUs=pts_us,
                payload=base64.b64encode(payload).decode("ascii"),
            ),
        )
        if out.get("accepted") is not True:
            execution.state = "UNKNOWN"
            raise ReceiverUnknown()
        self.next_sequence += 1  # advances only on acceptance
        return out

    async def finish(self, lineage):
        """Return trusted drain evidence (ReceiverProof) for Journal confirm."""
        execution = self._active(lineage)
        out = await self._call(execution, "ReceiverFinishUnit", execution.request())
        _require(out["executionId"] == lineage.execution_id, "STALE_EXECUTION")
        _require(out["artifactHash"] == lineage.artifact_hash, "ANSWER_CONFLICT")
        execution.state = "FINISHED"
        return out["evidence"]

    async def query(self, bootstrap_id, grant_id):
        """Metadata only. It can never re-arm an execution or a TTS."""
        channel = self._channel_for_consume()
        out = await channel.call(
            "ReceiverQueryConsumption",
            dict(
                REVISIONS,
                requestId=request_id(),
                bootstrapId=bootstrap_id,
                grantId=grant_id,
            ),
        )
        return out["summary"]

    async def close(self):
        """Process restart semantics: drop every pending/executable state."""
        for execution in self.executions.values():
            if execution.state == "ACTIVE":
                execution.state = "UNKNOWN"
        self._tickets.clear()
        self._pending.clear()
        if self._channel is not None:
            await self._channel.close()
