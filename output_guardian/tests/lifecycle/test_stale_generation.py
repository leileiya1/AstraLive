"""A late result of a replaced Generation may only reject itself (PR11 P1).

Covers Agent4 PR11-STALE-MEDIA-RETIRES-NEW-LIFECYCLE: old Media success ACK,
failure and cancellation, the IPC Finish deadline and ingest observations.
Negative controls prove a real fault of the still-current life is retired and
Stop/expiry precedence is unchanged. ``local`` cases are explicit mocks; the
``rig`` cases use the dedicated private PostgreSQL/MediaMTX/native children.
"""

# ruff: noqa: F811 - pytest resolves the re-exported ``local`` fixture by name.

import asyncio
import dataclasses
import json
import secrets

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer

from output_guardian import service
from output_guardian.model import Closed
from output_guardian.tests.lifecycle.serial_rig import serial_rig  # noqa: F401
from output_guardian.tests.lifecycle.test_finish_renew import local  # noqa: F401

AUDIO = {"kind": "audio", "sequence": 0, "payload": b"\0" * 640}


def successor(attempt, generation=2):
    return dataclasses.replace(
        attempt,
        attemptId=f"new-attempt-{generation}",
        utteranceId=f"new-utterance-{generation}",
        commandId=f"new-command-{generation}",
        generation=generation,
    )


def hold_first(publisher, op, *, fail=None):
    """Hold the first ``op`` call after its real result (or raise ``fail``)."""
    entered, release = asyncio.Event(), asyncio.Event()
    original, held = publisher.call, []

    async def call(message, *a, **kw):
        result = await original(message, *a, **kw)
        if message.get("op") == op and not held:
            held.append(message)
            entered.set()
            await release.wait()
            if fail is not None:
                raise fail
        return result

    return call, entered, release


def snapshot(g):
    return g._life, g.barrier, g.right, g.publisher.process


def assert_untouched(g, before):
    life, barrier, right, process = before
    assert g._life is life and life.phase == "ACTIVE" and life.revocation is None
    assert g.barrier == barrier and g.right is right and not g.failed
    assert g.publisher.process is process


# ---------------------------------------------------------------- local mocks


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["ack", "failure", "cancel"])
async def test_stale_media_never_retires_replacement(local, outcome):
    g, a = local.g, local.a
    fail = Closed("MEDIA_DELIVERY_FAILED") if outcome == "failure" else None
    g.publisher.call, entered, release = hold_first(g.publisher, "audio", fail=fail)
    old = asyncio.create_task(g.media(a, AUDIO))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        new = successor(a)
        assert (await g.bind(new, "new-permit"))["state"] == "AUTHORIZED"
        before = snapshot(g)
        if outcome == "cancel":
            old.cancel()
        else:
            release.set()
        with pytest.raises(Closed, match="MEDIA_DELIVERY_FAILED"):
            await old
        assert_untouched(g, before)
        # The replacement still serves its own media after the stale result.
        accepted = await g.media(new, AUDIO)
        assert accepted == {"accepted": True}
        assert_untouched(g, before)
    finally:
        release.set()
        await asyncio.gather(old, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["failure", "cancel", "barrier"])
async def test_current_life_media_fault_is_still_retired(local, outcome):
    g, a = local.g, local.a
    fail = Closed("MEDIA_DELIVERY_FAILED") if outcome == "failure" else None
    g.publisher.call, entered, release = hold_first(g.publisher, "audio", fail=fail)
    life, barrier = g._life, g.barrier
    media = asyncio.create_task(g.media(a, AUDIO))
    await asyncio.wait_for(entered.wait(), 1)
    if outcome == "cancel":
        media.cancel()
    elif outcome == "barrier":
        await g.retire()  # an unrelated revocation of the same life won first
    release.set()
    with pytest.raises(Closed, match="MEDIA_DELIVERY_FAILED"):
        await media
    assert life.phase == "REVOKED" and g.right is None
    assert g.barrier == barrier + 1  # exactly one revocation, never doubled
    assert g.publisher.process is None


@pytest.mark.asyncio
async def test_stale_media_after_stop_keeps_stop_precedence(local):
    g, a = local.g, local.a
    g.publisher.call, entered, release = hold_first(g.publisher, "audio")
    old = asyncio.create_task(g.media(a, AUDIO))
    await asyncio.wait_for(entered.wait(), 1)
    life = g._life
    await g.stop("run")
    barrier = g.barrier
    release.set()
    with pytest.raises(Closed, match="MEDIA_DELIVERY_FAILED"):
        await old
    assert life.phase == "REVOKED" and g.barrier == barrier and g.right is None
    with pytest.raises(Closed):
        await g.bind(successor(a), "new-permit")  # Stop tombstone still wins


@pytest.mark.asyncio
async def test_stale_media_after_expiry_then_replacement(local):
    g, a = local.g, local.a
    g.publisher.call, entered, release = hold_first(g.publisher, "audio")
    old = asyncio.create_task(g.media(a, AUDIO))
    await asyncio.wait_for(entered.wait(), 1)
    expired = g._life
    expired.revocation = "LEASE_LOST"
    await g.retire()  # what the watchdog does on a real expiry
    new = successor(a)
    await g.bind(new, "new-permit")
    before = snapshot(g)
    release.set()
    with pytest.raises(Closed, match="MEDIA_DELIVERY_FAILED"):
        await old
    assert expired.phase == "REVOKED" and expired.revocation == "LEASE_LOST"
    assert_untouched(g, before)


@pytest.mark.asyncio
async def test_old_media_never_reaches_replacement_counters(local):
    g, a = local.g, local.a
    g.publisher.call, entered, release = hold_first(g.publisher, "audio")
    old = asyncio.create_task(g.media(a, AUDIO))
    await asyncio.wait_for(entered.wait(), 1)
    await g.bind(successor(a), "new-permit")
    release.set()
    await asyncio.gather(old, return_exceptions=True)
    assert (g.audio_sequence, g.audio_samples) == (0, 0)
    with pytest.raises(Closed, match="STALE_RUN_EPOCH"):
        await g.media(a, dict(AUDIO, sequence=1))  # old Attempt stays rejected


async def ipc_client(g):
    control = secrets.token_urlsafe(32)
    producer = secrets.token_urlsafe(32)
    app = service.ipc_app(g, control, {producer: "p"})
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, {"Authorization": "Bearer " + control}


@pytest.mark.asyncio
@pytest.mark.parametrize("named", ["old", "current"])
async def test_ipc_finish_deadline_retires_only_named_life(local, monkeypatch, named):
    g, a = local.g, local.a
    started, original = asyncio.Event(), g.finish

    async def hung(attempt):
        started.set()
        await asyncio.Event().wait()  # never completes; cancelled at deadline

    monkeypatch.setattr(g, "finish", hung)
    new = successor(a)
    await g.bind(new, "new-permit")
    before = snapshot(g)
    target = a if named == "old" else new
    client, headers = await ipc_client(g)
    try:
        response = await client.post(
            "/guardian/v1/finish",
            headers=headers,
            data=json.dumps({"attempt": target.json()}),
        )
        assert started.is_set()
        assert response.status == 409
        assert (await response.json())["code"] == "DRAIN_UNKNOWN"
    finally:
        await client.close()
        monkeypatch.setattr(g, "finish", original)
    if named == "old":
        assert_untouched(g, before)
    else:
        assert before[0].phase == "REVOKED"
        assert g.right is None and g.barrier == before[1] + 1


@pytest.mark.asyncio
async def test_poll_ingest_observation_for_replaced_life_is_discarded(local):
    g, a = local.g, local.a
    entered, release = asyncio.Event(), asyncio.Event()
    observed, exclusive = [], []

    async def publishers():
        if observed:
            return []  # the replacement has not published yet
        entered.set()
        await release.wait()
        observed.append(True)
        return [{"id": "old-connection"}]  # taken before the replacement

    async def check_exclusive(expected):
        exclusive.append(expected)

    async def never_ready():
        return False

    g.ingest.publishers, g.ingest.ready = publishers, never_ready
    g.ingest.exclusive = check_exclusive
    g.observer_started = True
    g.publisher_id = "old-connection"
    g.poller = asyncio.create_task(g._poll())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        new = successor(a)
        await g.bind(new, "new-permit")
        g.publisher_id = "new-connection"  # its own publish auth callback
        before = snapshot(g)
        release.set()
        for _ in range(30):
            await asyncio.sleep(0.01)
            if observed:
                break
        await asyncio.sleep(0.2)  # several further real poll iterations
        # A stale list never proves (nor later disproves) the new publisher.
        assert observed and exclusive == [] and not g.publisher_seen
        assert_untouched(g, before)
    finally:
        g.started = False
        release.set()
        g.poller.cancel()
        await asyncio.gather(g.poller, return_exceptions=True)
        g.started = True


# ------------------------------------------- dedicated real SQL/RTMP/children

SUCCESSOR_SQL = """
INSERT INTO utterances(id,session_id,source,text,priority,interrupt_policy,trace_id)
 VALUES ('{u}','session','SCRIPT','test',1,'NONE','trace');
INSERT INTO dl05_turns(tenant_id,owner_id,turn_id,run_id,turn_type,priority,state,scheduled_at,input_text,idempotency_key,document)
 VALUES ('t','o','{t}','run','OPERATOR',1,'PLAYING',clock_timestamp(),'test','{k}','{{}}');
BEGIN;
SET CONSTRAINTS ALL DEFERRED;
INSERT INTO dl05_attempts(tenant_id,owner_id,attempt_id,run_id,turn_id,session_id,run_epoch,utterance_id,command_id,attempt_number,executor_incarnation,last_checkpoint,required_sinks,document)
 VALUES ('t','o','{a}','run','{t}','session',1,'{u}','{c}',1,'producer','PLAYING','["rtmp"]','{{}}');
INSERT INTO dl05_outbox(tenant_id,owner_id,intent_id,run_id,session_id,utterance_id,command_id,attempt_id,turn_id,idempotency_key,run_epoch,operation,request_hash,envelope,status)
 VALUES ('t','o','{i}','run','session','{u}','{c}','{a}','{t}','{k}',1,'EXECUTE_TURN',repeat('a',64),
  jsonb_build_object('contractRevision','durable-live-1','tenantId','t','ownerId','o','runId','run','commandId','{c}','intentId','{i}','sessionId','session','operation','EXECUTE_TURN','requestHash',repeat('a',64),'runEpoch',1,'attemptId','{a}','turnId','{t}','utteranceId','{u}'),'ACCEPTED');
INSERT INTO dl05_runtime_inbox(tenant_id,owner_id,command_id,run_id,attempt_id,run_epoch,request_hash,status,receipt_id,producer_incarnation,started_at)
 VALUES ('t','o','{c}','run','{a}',1,repeat('a',64),'STARTED','{r}','producer',clock_timestamp());
UPDATE dl05_run_slots SET active_attempt_id='{a}' WHERE run_id='run';
COMMIT;
"""


async def provision_successor(rig, attempt):
    """Explicit SQL control-state fixture for the next Attempt (not Session
    registration); actual PostgresAuthority then validates it unmocked."""
    g = attempt.generation
    await rig.db.execute(
        SUCCESSOR_SQL.format(
            a=attempt.attemptId,
            u=attempt.utteranceId,
            c=attempt.commandId,
            t=f"new-turn-{g}",
            k=f"new-key-{g}",
            i=f"new-intent-{g}",
            r=f"new-receipt-{g}",
        )
    )


def tone(sequence):
    t = np.arange(320) + sequence * 320
    pcm = (np.sin(t * 2 * np.pi * 440 / 16000) * 8000).astype("<i2").tobytes()
    return {"kind": "audio", "sequence": sequence, "payload": pcm}


@pytest.mark.asyncio
@pytest.mark.parametrize("repeat", range(3))
async def test_real_stale_media_ack_keeps_new_generation(rig, monkeypatch, repeat):
    await rig.activate()
    g = rig.guardian
    call, entered, release = hold_first(g.publisher, "audio")
    monkeypatch.setattr(g.publisher, "call", call)
    old = asyncio.create_task(g.media(rig.attempt, tone(0)))
    try:
        await asyncio.wait_for(entered.wait(), 0.5)
        old_child = g.publisher.process
        new = successor(rig.attempt)
        await provision_successor(rig, new)
        assert (await g.bind(new, await rig.permit()))["state"] == "AUTHORIZED"
        assert old_child.poll() is not None  # the old owned child was reaped
        before = snapshot(g)
        child = before[3]
        release.set()
        with pytest.raises(Closed, match="MEDIA_DELIVERY_FAILED"):
            await old
        assert_untouched(g, before)
        assert child.poll() is None and not g.stopped
        # The real new Publisher keeps accepting its own Generation's media.
        for sequence in range(3):
            assert await g.media(new, tone(sequence)) == {"accepted": True}
        assert_untouched(g, before)
        assert child.poll() is None
    finally:
        release.set()
        await asyncio.gather(old, return_exceptions=True)


@pytest.mark.asyncio
async def test_real_current_publisher_death_is_still_retired(rig):
    await rig.activate()
    g = rig.guardian
    life, barrier, child = g._life, g.barrier, g.publisher.process
    assert await g.media(rig.attempt, tone(0)) == {"accepted": True}
    child.kill()  # only the exact Popen owned by this dedicated rig
    await asyncio.to_thread(child.wait)
    # Media (or the ingest poller, whichever observes the death first) retires
    # the current life exactly once; a real current fault is never swallowed.
    with pytest.raises(Closed):
        await g.media(rig.attempt, tone(1))
    assert life.phase == "REVOKED"
    assert g.barrier == barrier + 1 and g.right is None
    assert g.publisher.process is None


@pytest.mark.asyncio
async def test_real_fixture_writes_are_serialized(rig):
    await rig.activate()
    renewal = asyncio.create_task(rig.renew_forever())
    try:
        permits = await asyncio.gather(*(rig.permit() for _ in range(8)))
        assert len(set(permits)) == 8
        assert not renewal.done()
    finally:
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)
