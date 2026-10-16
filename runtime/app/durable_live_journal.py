"""durable-live-1 journal client, execution inbox and fenced sink adapter.

No legacy FSM/Worker/TCP/credit changes. Integration supplies an exact-text or
comment executor and a guardian-owned sink; nothing is enabled on import.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from starlette.requests import Request
from jsonschema import Draft202012Validator, FormatChecker

REVISION = "durable-live-1"
MAX_BODY = 262144
ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts/v0.5/durable-live/schema.json").read_text())
PROTOCOL = json.loads((ROOT / "contracts/v0.5/durable-live/protocol.json").read_text())
OPERATIONS = {x["operationId"]: x for x in PROTOCOL["operations"]}


class JournalError(Exception):
    def __init__(self, code="DEPENDENCY_UNAVAILABLE"):
        super().__init__(code)
        self.code = code


def _pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise JournalError("INVALID_ARGUMENT")
        obj[key] = value
    return obj


def _integer(value):
    n = int(value)
    if not -9007199254740991 <= n <= 9007199254740991:
        raise JournalError("INVALID_ARGUMENT")
    return n


def _no_float(value):
    raise JournalError("INVALID_ARGUMENT")


def decode(raw: bytes):
    if len(raw) > MAX_BODY:
        raise JournalError("INVALID_ARGUMENT")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_int=_integer, parse_float=_no_float, parse_constant=_no_float)
    except (ValueError, UnicodeError):
        raise JournalError("INVALID_ARGUMENT") from None


def canonical(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    decode(raw)  # recursively reject floats/unsafe integers even for local callers
    return raw


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate(name, value):
    schema = {"$schema": SCHEMA["$schema"], "$defs": SCHEMA["$defs"], "$ref": "#/$defs/" + name}
    if list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)):
        raise JournalError("INVALID_ARGUMENT")


def common(command):
    return {k: command[k] for k in ("schemaVersion", "contractRevision", "tenantId", "ownerId", "runId")} | {"requestId": "req_" + uuid.uuid4().hex}


class JournalClient:
    """No retry on START or other network ambiguity; callers query the journal."""
    def __init__(self, base_url, token, producer, *, client=None):
        if len(token) < 32 or not producer:
            raise JournalError("UNAUTHENTICATED")
        self.base_url, self._token, self.producer = base_url.rstrip("/"), token, producer
        self.client = client or httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False)

    async def call(self, operation, request):
        op = OPERATIONS[operation]
        if "RUNTIME_JOURNAL" not in op["roles"] or op["target"] != "BACKEND":
            raise JournalError("FORBIDDEN")
        validate(op["requestSchema"].split("/")[-1], request)
        path = op["path"].replace("{runId}", __import__("urllib.parse", fromlist=["quote"]).quote(request["runId"], safe=""))
        try:
            response = await self.client.post(self.base_url + path, content=canonical(request),
                                              headers={"Authorization": "Bearer " + self._token,
                                                       "Content-Type": "application/json"})
        except httpx.HTTPError:
            raise JournalError() from None
        data = decode(response.content)
        if response.status_code != op["successStatus"]:
            code = data.get("code", "DEPENDENCY_UNAVAILABLE")
            raise JournalError(code if code in PROTOCOL["httpErrors"] else "DEPENDENCY_UNAVAILABLE")
        validate(op["responseSchema"].split("/")[-1], data)
        return data

    async def query(self, command):
        return await self.call("QueryExecutionStatus", common(command) | {"commandId": command["commandId"], "runEpoch": command["runEpoch"]})

    async def close(self):
        await self.client.aclose()


@dataclass(frozen=True)
class Permit:
    data: dict
    deadline: float
    suspend_deadline: float

    @classmethod
    def received(cls, data, sent_at, suspend_at):
        validate("AcquireOutputPermitResponse", data)
        ttl = data["ttlMs"] / 1000 - .100
        p = cls(copy.deepcopy(data), sent_at + ttl, suspend_at + ttl)
        p.check()
        return p

    def check(self):
        # CLOCK_BOOTTIME on Linux / CLOCK_MONOTONIC_RAW on macOS continues across
        # suspension. The monotonic deadline starts BEFORE the permit round trip.
        if time.monotonic() >= self.deadline or suspend_clock() >= self.suspend_deadline:
            raise JournalError("LEASE_LOST")


def suspend_clock():
    return time.clock_gettime(getattr(time, "CLOCK_BOOTTIME", getattr(time, "CLOCK_MONOTONIC_RAW", time.CLOCK_MONOTONIC)))


class OutputGate:
    """Last local handoff guard; guardian owns and closes the actual sink.

    publish is awaited under the guardian lock, so takeover/close waits until the
    bounded handoff ends. It must never expose a bypass publisher to Runtime.
    """
    def __init__(self, close_sink: Callable[[], Awaitable[None]], *, max_handoff=.050):
        self._lock = asyncio.Lock()
        self._close = close_sink
        self._max_handoff = max_handoff
        self._binding = None
        self._permit = None
        self._identity = None
        self._watchdog = None
        self._closed = False
        self.barrier = 0

    async def install(self, room, run, epoch, binding, session, producer):
        async with self._lock:
            if self._closed:
                raise JournalError("OUTPUT_FENCE_UNPROVEN")
            if self._binding is not None:
                old_room, old_run, old_epoch, old_binding, *_ = self._binding
                if room != old_room or binding <= old_binding or (run == old_run and epoch < old_epoch):
                    raise JournalError("STALE_RUN_EPOCH")
            await asyncio.wait_for(self._close(), self._max_handoff)
            self.barrier += 1
            self._permit = self._identity = None
            self._binding = (room, run, epoch, binding, session, producer)
            return "fence_" + uuid.uuid4().hex

    def set_permit(self, permit, run_id, expected_barrier=None):
        if self._closed or (expected_barrier is not None and self.barrier != expected_barrier):
            raise JournalError("OUTPUT_FENCE_UNPROVEN")
        permit.check()
        d = permit.data
        if self._binding != (d["roomId"], run_id,
                             d["runEpoch"], d["outputBindingVersion"], d["sessionId"], d["producerIncarnation"]):
            raise JournalError("STALE_RUN_EPOCH")
        self._permit = permit
        if self._watchdog is None or self._watchdog.done():
            self._watchdog = asyncio.create_task(self._expire())

    def bind_attempt(self, command, generation):
        self.check(command, generation, new_attempt=True)
        self._identity = (command["attemptId"], command["utteranceId"], generation)

    def check(self, command, generation, *, new_attempt=False):
        if self._closed or self._binding is None or self._permit is None:
            raise JournalError("OUTPUT_FENCE_UNPROVEN")
        self._permit.check()
        if (command["runId"], command["runEpoch"], command["sessionId"]) != (self._binding[1], self._binding[2], self._binding[4]):
            raise JournalError("STALE_RUN_EPOCH")
        if type(generation) is not int or generation < 1:
            raise JournalError("INVALID_ARGUMENT")
        if not new_attempt and self._identity != (command["attemptId"], command["utteranceId"], generation):
            raise JournalError("STALE_RUN_EPOCH")

    async def handoff(self, command, generation, write):
        async with self._lock:
            self.check(command, generation)
            try:
                await asyncio.wait_for(write(), self._max_handoff)
                self.check(command, generation)
            except BaseException:
                self.barrier += 1
                self._permit = None
                await self._close()
                raise

    async def _expire(self):
        while self._permit is not None:
            try:
                self._permit.check()
            except JournalError:
                async with self._lock:
                    self._permit = None
                    await self._close()
                return
            await asyncio.sleep(.010)

    async def revoke(self):
        async with self._lock:
            self.barrier += 1
            self._permit = self._identity = None
            await self._close()

    async def close(self):
        await self.revoke()
        self._closed = True
        if self._watchdog:
            self._watchdog.cancel()
            await asyncio.gather(self._watchdog, return_exceptions=True)


class ExecutionInbox:
    """In-memory task ownership plus SQL journal; never restart a STARTED task.

    Executors receive the immutable command and fenced gate. They must use exact
    script text and submit genuine sink checkpoints through the journal. This
    wrapper intentionally cannot call the legacy speak/LLM path for scripts.
    """
    def __init__(self, journal, gate, executor, *, guardian_id, readiness, capacity=256, prepare_comment=None):
        if executor is None or readiness is None or type(capacity) is not int or not 1 <= capacity <= 1000:
            raise JournalError("DEPENDENCY_UNAVAILABLE")
        self.prepare_comment = prepare_comment
        self.journal, self.gate, self.executor = journal, gate, executor
        self.guardian_id, self.readiness, self.capacity = guardian_id, readiness, capacity
        self._lock = asyncio.Lock()
        self._receipts, self._commands, self._tasks = {}, {}, {}
        self.last_errors = {}
        self._closed = False

    async def accept(self, command):
        validate("RuntimeCommand", command)
        if digest({k: v for k, v in command.items() if k != "requestHash"}) != command["requestHash"]:
            raise JournalError("COMMAND_CONFLICT")
        if hashlib.sha256(command["payload"]["text"].encode()).hexdigest() != command["payload"]["textHash"]:
            raise JournalError("COMMAND_CONFLICT")
        async with self._lock:
            if self._closed:
                raise JournalError("RUN_STOPPED")
            key = command["commandId"]
            if key in self._commands and canonical(command) != canonical(self._commands[key]):
                raise JournalError("COMMAND_CONFLICT")
            # Query the durable record before admitting anything after reconnect.
            # UNKNOWN with no receipt is distinguishable from persisted UNKNOWN.
            query = (await self.journal.query(command))["status"]
            if query["state"] != "UNKNOWN" or query["receiptId"] is not None:
                if query["executorIncarnation"] != self.journal.producer:
                    raise JournalError("RECOVERY_UNKNOWN")
                receipt = {"accepted": True, "commandId": key, "receiptId": query["receiptId"],
                           "requestHash": command["requestHash"], "revision": query["revision"], "state": query["state"]}
                if query["state"] == "ACCEPTED" and key not in self._tasks:
                    # A new object/process with the same producer token is not a
                    # valid resume identity. Only this live object's receipt can
                    # authorize reconstructing its own not-started queue item.
                    if key not in self._receipts:
                        raise JournalError("RECOVERY_UNKNOWN")
                    self._tasks[key] = asyncio.create_task(self._execute(copy.deepcopy(command), receipt))
                return receipt
            if len(self._commands) >= self.capacity:
                raise JournalError("OVERLOADED")
            await self.readiness(command)
            receipt = await self.journal.call("JournalAccept", common(command) | {"command": command, "producerIncarnation": self.journal.producer})
            self._commands[key] = copy.deepcopy(command)
            self._receipts[key] = copy.deepcopy(receipt)
            if receipt["state"] == "ACCEPTED":
                self._tasks[key] = asyncio.create_task(self._execute(copy.deepcopy(command), receipt))
            return receipt

    async def _permit(self, command):
        barrier = self.gate.barrier
        sent, suspended = time.monotonic(), suspend_clock()
        data = await self.journal.call("AcquireOutputPermit", common(command) | {
            "sessionId": command["sessionId"], "runEpoch": command["runEpoch"],
            "producerIncarnation": self.journal.producer, "guardianId": self.guardian_id})
        permit = Permit.received(data, sent, suspended)
        self.gate.set_permit(permit, command["runId"], barrier)
        return permit

    async def _execute(self, command, receipt):
        renew = None
        try:
            await self.readiness(command)
            if command["payload"]["mode"] == "COMMENT_QUESTION":
                if self.prepare_comment is None:
                    raise JournalError("DEPENDENCY_UNAVAILABLE")
                await self.prepare_comment(command)
            permit = await self._permit(command)
            auth = await self.journal.call("JournalStart", common(command) | {
                "commandId": command["commandId"], "attemptId": command["attemptId"],
                "runEpoch": command["runEpoch"], "producerIncarnation": self.journal.producer,
                "permitId": permit.data["permitId"], "requestHash": command["requestHash"],
                "expectedInboxRevision": receipt["revision"]})
            if not auth["startAuthorized"]:
                return
            permit.check()  # never execute a delayed START response
            renew = asyncio.create_task(self._renew(command))
            await self.executor(command, self.gate)
        except JournalError as exc:
            self.last_errors[command["commandId"]] = exc.code
            await self.gate.revoke()
        except asyncio.CancelledError:
            await self.gate.revoke()
        except Exception as exc:
            self.last_errors[command["commandId"]] = type(exc).__name__
            await self.gate.revoke()
        finally:
            if renew:
                renew.cancel()
                await asyncio.gather(renew, return_exceptions=True)

    async def _renew(self, command):
        try:
            while True:
                await asyncio.sleep(.250)
                await self._permit(command)
        except asyncio.CancelledError:
            raise
        except JournalError:
            await self.gate.revoke()

    async def close(self):
        self._closed = True
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        await self.gate.close()


def router(inbox, control_token):
    """Optional versioned router. Agent 4 mounts it only in durable Session mode."""
    from fastapi import APIRouter, Request, HTTPException
    if len(control_token) < 32:
        raise JournalError("UNAUTHENTICATED")
    api = APIRouter()

    @api.post(OPERATIONS["RuntimeExecute"]["path"], status_code=202)
    async def execute(sessionId: str, request: Request):
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + control_token):
            raise HTTPException(401, "UNAUTHENTICATED")
        try:
            body = decode(await request.body())
            if body.get("sessionId") != sessionId:
                raise JournalError("COMMAND_CONFLICT")
            return await inbox.accept(body)
        except JournalError as exc:
            from fastapi.responses import JSONResponse
            return JSONResponse({"requestId": "runtime", "code": exc.code, "message": exc.code,
                                 "retryable": exc.code == "DEPENDENCY_UNAVAILABLE"},
                                status_code=PROTOCOL["httpErrors"][exc.code])
    return api


class RuntimeControl:
    """Management-only handlers; proof callbacks belong to trusted integration.

    verify_stop returns a durably verified stopRevision for a registered historic
    Session. install_fence returns the independent guardian's persisted receipt.
    Missing callbacks close admission; neither operation can create media.
    """
    def __init__(self, inbox, *, verify_stop, install_fence, stop_session):
        self.inbox, self.verify_stop = inbox, verify_stop
        self.install_fence, self.stop_session = install_fence, stop_session
        self._lock = asyncio.Lock()
        self._responses = {}

    async def call(self, operation, command):
        name = "RuntimeStop" if operation == "STOP_RUN" else "FenceInstall"
        validate(name + "Request", command)
        if digest({k: v for k, v in command.items() if k != "requestHash"}) != command["requestHash"]:
            raise JournalError("COMMAND_CONFLICT")
        key = command["commandId"]
        async with self._lock:
            if key in self._responses:
                previous, response = self._responses[key]
                if previous != command["requestHash"]:
                    raise JournalError("COMMAND_CONFLICT")
                return copy.deepcopy(response)
            if operation == "STOP_RUN":
                if self.verify_stop is None or self.stop_session is None:
                    raise JournalError("OUTPUT_FENCE_UNPROVEN")
                revision = await self.verify_stop(command)
                if type(revision) is not int or revision != command["stopRevision"]:
                    raise JournalError("RUN_STOPPED")
                await self.inbox.close()  # seals local admission before any await to providers
                await self.stop_session(command["sessionId"])
                response = dict(accepted=True, commandId=key, requestHash=command["requestHash"],
                                receiptId="stop_" + uuid.uuid4().hex, revision=1, state="COMPLETED")
            else:
                if self.install_fence is None or command["producerIncarnation"] != self.inbox.journal.producer:
                    raise JournalError("OUTPUT_FENCE_UNPROVEN")
                receipt = await self.install_fence(command)
                confirmed = await self.inbox.journal.call("ConfirmRunFence", common(command) | {
                    "sessionId": command["sessionId"], "runEpoch": command["runEpoch"],
                    "producerIncarnation": self.inbox.journal.producer, "guardianProofRef": command["guardianProofRef"],
                    "fenceReceiptId": receipt, "idempotencyKey": command["idempotencyKey"]})
                response = dict(requestId=command["requestId"], runEpoch=confirmed["runEpoch"],
                                phase=confirmed["phase"], fenceReceiptId=receipt)
            validate(name + "Response", response)
            self._responses[key] = (command["requestHash"], copy.deepcopy(response))
            return response


def management_router(control, control_token):
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
    if len(control_token) < 32:
        raise JournalError("UNAUTHENTICATED")
    api = APIRouter()

    def endpoint(operation):
        async def handle(sessionId: str, request: Request):
            if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + control_token):
                return JSONResponse(dict(requestId="management", code="UNAUTHENTICATED", message="UNAUTHENTICATED", retryable=False), status_code=401)
            try:
                body = decode(await request.body())
                if body.get("sessionId") != sessionId:
                    raise JournalError("COMMAND_CONFLICT")
                return await control.call(operation, body)
            except JournalError as exc:
                return JSONResponse(dict(requestId="management", code=exc.code, message=exc.code,
                                         retryable=exc.code == "DEPENDENCY_UNAVAILABLE"), status_code=PROTOCOL["httpErrors"][exc.code])
        return handle
    for name, operation in (("RuntimeStop", "STOP_RUN"), ("FenceInstall", "INSTALL_FENCE")):
        api.add_api_route(OPERATIONS[name]["path"], endpoint(operation), methods=["POST"], status_code=202)
    return api
