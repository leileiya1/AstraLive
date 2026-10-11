"""Authenticated PostgreSQL journal client. No direct Python SQL or memory acceptance fallback."""
import asyncio
import hashlib
import json
import os
import time
from uuid import uuid4
import httpx

MAX_INTEGER = 9007199254740991


def canonical(value) -> bytes:
    return _canonical(value, worker_proof=False)


def timeline_canonical(value) -> bytes:
    """Exact Worker BIGINT only in typed proof carriers; command stays unchanged."""
    return _canonical(value, worker_proof=True)


def _worker_path(path):
    return (path in {("proof", "identity", "workerGenerationId"),
                     ("proof", "descriptor", "workerGenerationId"),
                     ("proof", "commit", "identity", "workerGenerationId"),
                     ("proof", "commit", "descriptor", "workerGenerationId")}
            or (len(path) == 5 and path[:2] == ("proof", "sinkReceipts")
                and type(path[2]) is int and path[3:] == ("identity", "workerGenerationId")))


def _canonical(value, worker_proof):
    def check(item, path=()):
        if worker_proof and _worker_path(path) and item is not None:
            if type(item) is not int or not 0 < item < 2**63:
                raise ValueError("invalid Worker wire integer")
            return
        if isinstance(item, float):
            raise ValueError("fractional/nonfinite JSON forbidden")
        if isinstance(item, int) and not isinstance(item, bool) and abs(item) > MAX_INTEGER:
            raise ValueError("unsafe JSON integer")
        if isinstance(item, dict):
            for key, val in item.items():
                if not isinstance(key, str):
                    raise ValueError("invalid JSON key")
                check(val, path + (key,))
        elif isinstance(item, list):
            for index, val in enumerate(item):
                check(val, path + (index,))
    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def fingerprint(command) -> str:
    fields = ("schemaVersion", "sessionId", "runEpoch", "commandType", "narrationId", "segmentId", "timelineEpoch", "lane", "payload")
    return "sha256:" + hashlib.sha256(canonical({key: command[key] for key in fields if key in command})).hexdigest()


class JournalError(Exception):
    def __init__(self, code="DEPENDENCY_UNAVAILABLE", status=503):
        super().__init__(code)
        self.code, self.status = code, status


class DurabilityClient:
    def __init__(self, base_url=None, token_file=None, transport=None):
        self.base = (base_url or os.environ["CONFIG_BACKEND_URL"]).rstrip("/")
        self.token_file = token_file or os.environ["RUNTIME_JOURNAL_TOKEN_FILE"]
        self.incarnation = f"runtime_{uuid4().hex}"
        self.http = httpx.AsyncClient(timeout=2, transport=transport, follow_redirects=False, trust_env=False)

    async def request(self, method, suffix, value=None):
        from .session_binding import service_token
        try:
            response = await self.http.request(method, self.base + "/internal/v0.5/durability" + suffix,
                json=value, headers={"Authorization": "Bearer " + service_token(self.token_file), "X-Runtime-Incarnation": self.incarnation})
            if response.status_code != 200:
                try:
                    code = response.json().get("code", "DEPENDENCY_UNAVAILABLE")
                except Exception:
                    code = "DEPENDENCY_UNAVAILABLE"
                raise JournalError(code, response.status_code if response.status_code in (409, 422) else 503)
            return response.json()
        except JournalError:
            raise
        except Exception:
            raise JournalError() from None

    async def accept(self, command):
        return await self.request("POST", "/accept", {"command": command})

    async def start(self, command, token):
        return await self.request("POST", "/start", {"sessionId": command["sessionId"], "commandId": command["commandId"],
            "producerIncarnation": self.incarnation, "leaseToken": token})

    async def lookup(self, sid, cid):
        from urllib.parse import quote
        return await self.request("GET", f"/sessions/{quote(sid, safe='')}/commands/{quote(cid, safe='')}")

    async def grant(self, sid, epoch):
        started = time.monotonic()
        run = await self.request("POST", "/grant", {"sessionId": sid, "runEpoch": epoch})
        # Subtract the entire RTT and an extra margin; never subtract cross-host wall/monotonic clocks.
        deadline = time.monotonic() + max(0, run["remainingMs"] / 1000 - (time.monotonic() - started) - .1)
        return run, deadline

    async def close(self):
        await self.http.aclose()


class DurableCommands:
    def __init__(self, journal, publisher, manager):
        self.journal, self.publisher, self.manager = journal, publisher, manager
        self.runs = {}
        self.locks = {}
        self.supervisor = None
        self.tasks = set()

    def start_supervisor(self):
        self.supervisor = asyncio.create_task(self.watch(), name="durable-run-lease")

    async def watch(self):
        while True:
            for sid, run in tuple(self.runs.items()):
                if run["sealed"]:
                    continue
                try:
                    grant, deadline = await self.journal.grant(sid, run["epoch"])
                    if grant.get("barrierSeq", 0) > run.get("barrier", 0) and not run.get("barrier_pending"):
                        run["barrier_pending"] = True
                        session = self.manager.sessions.get(sid)
                        if session:
                            continuity = getattr(session, "continuity", None)
                            if continuity is not None:
                                continuity.fence("CONTROL_BARRIER")
                            session.generation_id += 1
                            if session.current_task:
                                session.current_task.cancel()
                    run["deadline"] = deadline
                except JournalError as exc:
                    if exc.status == 409:
                        run["deadline"] = 0
                if time.monotonic() >= run["deadline"]:
                    run["sealed"] = True
                    session = self.manager.sessions.get(sid)
                    if session:
                        # Fence publication immediately, cleanup independently of the journal outage.
                        continuity = getattr(session, "continuity", None)
                        if continuity is not None:
                            continuity.fence("LEASE_LOST")
                        session.generation_id += 1
                        if session.current_task:
                            session.current_task.cancel()
                        task = asyncio.create_task(self.manager.stop_session(sid, session.request.traceId))
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)
            await asyncio.sleep(.25)

    def check(self, sid, epoch):
        from .session import RuntimeFailure
        run = self.runs.get(sid)
        if not run or run["epoch"] != epoch or run["sealed"] or run.get("barrier_pending") or time.monotonic() >= run["deadline"]:
            raise RuntimeFailure("LEASE_LOST", "Run lease is unavailable", 409)

    async def execute(self, command):
        from .models import CreateSession, Utterance
        from .session import RuntimeFailure
        if command.get("schemaVersion") != "0.5" or fingerprint(command) != command.get("requestFingerprint"):
            raise RuntimeFailure("COMMAND_CONFLICT", "Immutable command mismatch", 409)
        sid, epoch, kind = command["sessionId"], command["runEpoch"], command["commandType"]
        if type(epoch) is not int or not 1 <= epoch <= MAX_INTEGER:
            raise RuntimeFailure("STALE_RUN_EPOCH", "Invalid run epoch", 409)
        async with self.locks.setdefault(sid, asyncio.Lock()):
            acceptance = await self.journal.accept(command)
            if not acceptance["execute"]:
                return acceptance
            run = self.runs.get(sid)
            payload = command["payload"]
            if kind == "BEGIN_RUN":
                expected = payload.get("expectedPreviousEpoch")
                if type(expected) is not int or expected != epoch - 1 or (run and run["epoch"] != expected):
                    raise RuntimeFailure("STALE_RUN_EPOCH", "Run handshake conflict", 409)
            elif kind in ("STOP_SESSION", "FORCE_INTERRUPT"):
                # Cleanup of an absent process/session is safe, but never resumes media.
                if run and run["epoch"] != epoch:
                    raise RuntimeFailure("STALE_RUN_EPOCH", "Retired run", 409)
            else:
                self.check(sid, epoch)
            started_at = time.monotonic()
            started = await self.journal.start(command, acceptance["run"]["leaseToken"])
            started_deadline = time.monotonic() + max(0, started["run"]["remainingMs"] / 1000 - (time.monotonic() - started_at) - .1)
            if not started["execute"]:
                return started
            self.publisher.bind(command, started)
            if time.monotonic() >= started_deadline:
                raise JournalError("LEASE_LOST", 409)
            if run:
                run["deadline"] = started_deadline
            try:
                if kind == "BEGIN_RUN":
                    old = self.manager.sessions.get(sid)
                    if old:
                        await self.manager.stop_session(sid, command["traceId"])
                    deadline = started_deadline
                    self.runs[sid] = {"epoch": epoch, "deadline": deadline, "sealed": bool(payload.get("fenceOnly")), "barrier": 0, "barrier_pending": False}
                    if not payload.get("fenceOnly"):
                        self.check(sid, epoch)
                        await self.manager.create_session(CreateSession.model_validate(payload["createSession"]))
                        self.manager.sessions[sid].durability_guard = lambda: self.check(sid, epoch)
                elif kind == "START_SESSION":
                    await self.manager.start_session(sid, command["traceId"])
                elif kind == "SPEAK":
                    await self.manager.speak(sid, Utterance.model_validate(payload))
                elif kind == "FORCE_INTERRUPT":
                    await self.manager.interrupt(sid, command["traceId"])
                    run["barrier"] = command["commandSeq"]
                    run["barrier_pending"] = False
                elif kind == "STOP_SESSION":
                    if run:
                        run["sealed"] = True
                    if sid in self.manager.sessions:
                        await self.manager.stop_session(sid, command["traceId"])
                else:
                    raise RuntimeFailure("INVALID_ARGUMENT", "Unsupported command", 422)
                if kind != "SPEAK":
                    await self.journal.request("POST", "/receipts", {"sessionId": sid, "runEpoch": epoch, "commandId": command["commandId"],
                        "receiptSeq": 3, "state": "completed", "producerIncarnation": self.journal.incarnation,
                        "evidenceType": "control_cleanup", "evidenceRef": command["commandId"] + ":control"})
            except Exception:
                # STARTED has been committed. Any exception here remains UNKNOWN for reconciliation.
                raise
            return started

    async def receipt(self, sid, cid):
        state = await self.journal.lookup(sid, cid)
        # Missing in-memory incarnation after restart is NOT proof of nonexecution.
        if state.get("executionState") == "STARTED" and state.get("executorIncarnation") != self.journal.incarnation:
            state["executionState"] = "UNKNOWN"
        return state

    async def close(self):
        if self.supervisor:
            self.supervisor.cancel()
            await asyncio.gather(self.supervisor, return_exceptions=True)
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


class PostgresTimelineJournal:
    """B's TimelineJournal protocol backed by A's authenticated PostgreSQL transaction.

    Identity/range and C cursor validation happen on Go. This adapter never fabricates
    sink receipts, hydrates a volatile timeline, replays media, or asserts
    viewer audibility. C registers the Go projection before using completion.
    """
    def __init__(self, client):
        self.client = client

    async def record(self, operation, command, proof):
        from dataclasses import fields, is_dataclass
        def encode(value):
            if is_dataclass(value):
                result = {field.name: encode(getattr(value, field.name)) for field in fields(value)}
                if all(hasattr(value, attr) for attr in ("sampleIndex", "sampleRate", "ptsUs")):
                    result["ptsUs"] = value.ptsUs
                return result
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise JournalError("COMMAND_CONFLICT", 409)
                return {key: encode(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [encode(item) for item in value]
            return value
        spool = getattr(self.client, "timeline_spool", None)
        if spool is None:
            raise JournalError("DEPENDENCY_UNAVAILABLE")
        result = await spool.record_timeline({
            "operation": operation, "command": encode(command), "proof": encode(proof),
            "producerIncarnation": self.client.incarnation,
        })
        if result.get("durable") is not True:
            raise JournalError("RECOVERY_UNKNOWN", 409)
        return result
