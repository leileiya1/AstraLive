import asyncio
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runtime.app.durable_live_journal import (ExecutionInbox, JournalClient, JournalError,
    OutputGate, Permit, canonical, decode, digest, suspend_clock, validate)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = json.loads((ROOT / "contracts/v0.5/durable-live/examples/protocol.json").read_text())
COMMAND = next(x["request"] for x in EXAMPLES if x["operationId"] == "RuntimeExecute")


def test_frozen_hash_and_schema_vectors():
    vectors = json.loads((ROOT / "contracts/v0.5/durable-live/examples/hash-vectors.json").read_text())
    for v in vectors:
        assert canonical(v["value"]).decode() == v["canonicalUtf8"]
        assert digest(v["value"]) == v["sha256"]
    for bad in [b'{"a":1,"a":2}', b'{"x":1.0}', b'{"x":9007199254740992}', b'{"x":NaN}']:
        with pytest.raises(JournalError):
            decode(bad)
    bad = copy.deepcopy(COMMAND)
    bad["runEpoch"] = True
    with pytest.raises(JournalError):
        validate("RuntimeCommand", bad)


def permit_data(ttl=1000):
    cmd = COMMAND
    return dict(requestId="test", permitId="permit", runEpoch=cmd["runEpoch"], leaseVersion=1,
                ttlMs=ttl, issuedAt="2026-10-16T00:00:00Z", expiresAt="2026-10-16T00:00:01Z",
                roomId="room", outputBindingVersion=1, sessionId=cmd["sessionId"], producerIncarnation="producer")


@pytest.mark.asyncio
async def test_output_gate_rejects_old_epoch_and_generation_at_handoff():
    closed, written = [], []
    async def close(): closed.append(True)
    gate = OutputGate(close)
    await gate.install("room", COMMAND["runId"], COMMAND["runEpoch"], 1, COMMAND["sessionId"], "producer")
    p = Permit.received(permit_data(), time.monotonic(), suspend_clock())
    gate.set_permit(p, COMMAND["runId"])
    gate.bind_attempt(COMMAND, 3)
    async def write(): written.append(1)
    await gate.handoff(COMMAND, 3, write)
    with pytest.raises(JournalError):
        await gate.handoff(COMMAND, 2, write)
    old = copy.deepcopy(COMMAND); old["runEpoch"] -= 1
    with pytest.raises(JournalError):
        await gate.handoff(old, 3, write)
    assert written == [1]
    await gate.close()


@pytest.mark.asyncio
async def test_permit_roundtrip_expiry_closes_sink_without_next_frame():
    with pytest.raises(JournalError):
        Permit.received(permit_data(), time.monotonic()-1, suspend_clock()-1)
    closed = []
    async def close(): closed.append(True)
    gate = OutputGate(close)
    await gate.install("room", COMMAND["runId"], COMMAND["runEpoch"], 1, COMMAND["sessionId"], "producer")
    closed.clear()
    gate.set_permit(Permit.received(permit_data(200), time.monotonic(), suspend_clock()), COMMAND["runId"])
    await asyncio.sleep(.150)
    assert closed
    await gate.close()


class FakeJournal:
    producer = "producer"
    def __init__(self, start_loss=False):
        self.state, self.receipt, self.revision = "UNKNOWN", None, 1
        self.start_loss, self.starts, self.accepts = start_loss, 0, 0
    async def query(self, command):
        return {"status": {"state": self.state, "receiptId": self.receipt,
            "executorIncarnation": self.producer if self.receipt else None, "revision": self.revision}}
    async def call(self, operation, request):
        if operation == "AcquireOutputPermit": return permit_data()
        if operation == "JournalAccept":
            self.accepts += 1; self.receipt = "receipt"; self.state = "ACCEPTED"
            return dict(accepted=True, commandId=COMMAND["commandId"], receiptId=self.receipt,
                        requestHash=COMMAND["requestHash"], revision=1, state=self.state)
        if operation == "JournalStart":
            first = self.state == "ACCEPTED"
            if first: self.starts += 1; self.state = "STARTED"; self.revision += 1
            if self.start_loss: raise JournalError()
            return dict(startAuthorized=first, state=self.state, revision=self.revision, evidenceRef="receipt", requestId="req")
        raise AssertionError(operation)


async def make_inbox(journal, execute):
    async def close(): pass
    async def ready(command): pass
    gate = OutputGate(close)
    await gate.install("room", COMMAND["runId"], COMMAND["runEpoch"], 1, COMMAND["sessionId"], "producer")
    return ExecutionInbox(journal, gate, execute, guardian_id="guardian", readiness=ready)


@pytest.mark.asyncio
async def test_duplicate_execute_never_repeats_effect():
    calls = []
    async def execute(command, gate): calls.append(command["utteranceId"])
    j = FakeJournal(); inbox = await make_inbox(j, execute)
    await asyncio.gather(*(inbox.accept(copy.deepcopy(COMMAND)) for _ in range(8)))
    await asyncio.sleep(.025)
    await inbox.accept(COMMAND)
    assert len(calls) == 1 and j.starts == 1 and j.accepts == 1
    restarted = await make_inbox(j, execute)
    response = await restarted.accept(COMMAND)
    assert response["state"] == "STARTED"
    await asyncio.sleep(.025)
    assert len(calls) == 1
    await restarted.close(); await inbox.close()


@pytest.mark.asyncio
async def test_lost_start_ack_is_not_execution_authorization():
    calls = []
    async def execute(*args): calls.append(True)
    j = FakeJournal(start_loss=True); inbox = await make_inbox(j, execute)
    await inbox.accept(COMMAND); await asyncio.sleep(.025)
    await inbox.accept(COMMAND)
    assert j.state == "STARTED" and j.starts == 1 and calls == []
    await inbox.close()


@pytest.mark.asyncio
async def test_restarted_process_cannot_sweep_accepted_queue():
    j = FakeJournal(); j.state = "ACCEPTED"; j.receipt = "receipt"
    async def execute(*args): raise AssertionError("replayed accepted work")
    restarted = await make_inbox(j, execute)
    with pytest.raises(JournalError, match="RECOVERY_UNKNOWN"):
        await restarted.accept(COMMAND)
    await restarted.close()


@pytest.mark.asyncio
async def test_missing_backend_and_unready_worker_fail_before_effects():
    async def transport(request): raise httpx.ConnectError("offline")
    c = JournalClient("http://127.0.0.1", "x"*32, "producer", client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    with pytest.raises(JournalError): await c.query(COMMAND)
    await c.close()
    j = FakeJournal()
    async def execute(*args): raise AssertionError("unready worker executed")
    inbox = await make_inbox(j, execute)
    async def not_ready(command): raise JournalError("DEPENDENCY_UNAVAILABLE")
    inbox.readiness = not_ready
    with pytest.raises(JournalError): await inbox.accept(COMMAND)
    assert j.accepts == 0 and j.starts == 0
    await inbox.close()


@pytest.mark.asyncio
async def test_delayed_permit_cannot_reopen_after_stop_barrier():
    async def close(): pass
    gate = OutputGate(close)
    await gate.install("room", COMMAND["runId"], COMMAND["runEpoch"], 1, COMMAND["sessionId"], "producer")
    barrier = gate.barrier
    permit = Permit.received(permit_data(), time.monotonic(), suspend_clock())
    await gate.revoke()
    with pytest.raises(JournalError):
        gate.set_permit(permit, COMMAND["runId"], barrier)
    await gate.close()


@pytest.mark.asyncio
async def test_runtime_router_authentication_and_duplicate_execute():
    from fastapi import FastAPI
    from runtime.app.durable_live_journal import router
    j = FakeJournal(); effects = []
    async def execute(command, gate): effects.append(True)
    inbox = await make_inbox(j, execute)
    app = FastAPI(); app.include_router(router(inbox, "x"*32))
    path = "/internal/v0.5/durable-live/sessions/" + COMMAND["sessionId"] + "/commands"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(path, content=canonical(COMMAND))).status_code == 401
        for _ in range(2):
            response = await client.post(path, content=canonical(COMMAND), headers={"Authorization": "Bearer " + "x"*32})
            assert response.status_code == 202, response.text
        await asyncio.sleep(.025)
        assert len(effects) == 1
    await inbox.close()


@pytest.mark.asyncio
async def test_management_stop_verifies_tombstone_and_never_executes_media():
    from runtime.app.durable_live_journal import RuntimeControl
    stop = copy.deepcopy(next(x["request"] for x in EXAMPLES if x["operationId"] == "RuntimeStop"))
    effects, closed = [], []
    async def execute(*args): effects.append(True)
    inbox = await make_inbox(FakeJournal(), execute)
    async def verify(command): return command["stopRevision"]
    async def stop_session(sid): closed.append(sid)
    control = RuntimeControl(inbox, verify_stop=verify, install_fence=None, stop_session=stop_session)
    first = await control.call("STOP_RUN", stop)
    again = await control.call("STOP_RUN", stop)
    assert first == again and closed == [stop["sessionId"]] and effects == []
    with pytest.raises(JournalError, match="RUN_STOPPED"):
        await inbox.accept(COMMAND)


@pytest.mark.asyncio
async def test_cross_run_binding_version_fences_old_publisher_even_same_epoch():
    async def close(): pass
    gate = OutputGate(close)
    await gate.install("room", COMMAND["runId"], COMMAND["runEpoch"], 1, COMMAND["sessionId"], "producer")
    old = Permit.received(permit_data(), time.monotonic(), suspend_clock())
    await gate.install("room", "different-run", COMMAND["runEpoch"], 2, COMMAND["sessionId"], "producer")
    with pytest.raises(JournalError):
        gate.set_permit(old, COMMAND["runId"])
    await gate.close()
