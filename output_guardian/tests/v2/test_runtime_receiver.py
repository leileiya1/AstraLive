"""Runtime receiver-1 client against the real Guardian v2 Receiver + PrivateIPC.

Real: AF_UNIX HTTP, kernel peer pins, channel binding, Guardian gate, deny
journal fsync and the official SDK codec. Mocked (explicitly): the Backend
Authority/Registrar contract oracle and the CPU Observer evidence envelope.
This proves Runtime-side once-TTS/ticket/lineage rules, not production TTS,
SQL serializability, Linux isolation or audience audibility.
"""

import asyncio
import copy
import hashlib
import os
import secrets
import time
from contextlib import asynccontextmanager

import psutil
import pytest

from output_guardian.v2.ipc import PrivateIPC, ProcessPin
from output_guardian.v2.receiver import ObservedDrain, envelope
from runtime.app.receiver1.runtime_client import (
    GuardianChannel,
    Lineage,
    ReceiverRefused,
    ReceiverRuntime,
    ReceiverUnknown,
)
from runtime.app.receiver1.transport import (
    Credential,
    ProcessIdentity,
    continuous,
    identity,
)
from runtime.app.receiver1.wire import GuardianWire

from .conftest import mock_evidence

FRAME = bytes(64 * 64 * 3)  # fixture video geometry


def process_pin(d, role, token):
    peer = d.control if role == "CONTROL_REGISTRAR" else d.runtime
    return ProcessPin(
        peer.principal_id,
        peer.role,
        peer.incarnation,
        peer.scope,
        os.getpid(),
        os.geteuid(),
        psutil.Process().create_time(),
        hashlib.sha256(token.encode()).digest(),
    )


def start_of(d):
    """The FIRST true JournalStart response recorded by the contract oracle."""
    event = next(e for e in reversed(d.x.events) if e["operationId"] == "JournalStart")
    return event["response"]


class Speaker:
    def __init__(self):
        self.calls = []

    async def __call__(self, text):
        self.calls.append(text)
        return [bytes(640), bytes(640)]


@asynccontextmanager
async def runtime_against(d, *, guardian=None, token=None, sent=None):
    token = token or secrets.token_urlsafe(32)
    control_token = secrets.token_urlsafe(32)
    ipc = PrivateIPC(
        d.r,
        d.ipc_dir,
        [
            process_pin(d, "REGISTERED_RUNTIME", token),
            process_pin(d, "CONTROL_REGISTRAR", control_token),
        ],
    )
    await ipc.start()
    me = guardian or identity(os.getpid())  # Guardian runs in this test process

    def open_channel():
        return GuardianChannel(
            ipc.directory / "runtime.sock", me, Credential(token.encode())
        )

    rt = ReceiverRuntime(open_channel, GuardianWire())
    rt.remember_start(d.grant, start_of(d), sent or (time.monotonic(), continuous()))
    try:
        yield rt, ipc, control_token
    finally:
        await rt.close()
        await ipc.close()


def observe_tail(d):
    """Explicit trusted-Observer stand-in: envelope derived from the real tail."""

    async def observe(lineage, tail):
        sinks = frozenset(d.evidence["requiredSinks"])
        return ObservedDrain(tail, sinks, await mock_evidence(lineage, tail, sinks))

    d.outputs.observe = observe


def refs_of(d):
    return copy.deepcopy(d.q["references"])


def artifact_of(d):
    return copy.deepcopy(d.x.r.artifacts[d.q["references"]["artifactId"]])


async def consumed(d, rt):
    return await rt.consume(d.x.b.registration, refs_of(d), artifact_of(d))


@pytest.mark.asyncio
async def test_consume_once_tts_once_media_finish_returns_drain_proof(domain):
    d = domain
    async with runtime_against(d) as (rt, _, _):
        execution = await consumed(d, rt)
        assert not rt._tickets  # ticket erased after the true ACK
        assert rt.knowledge[d.grant["grantId"]] == "CONSUMED"
        speak = Speaker()
        pcm = await rt.speak_once(execution, artifact_of(d), speak)
        assert speak.calls == [artifact_of(d)["answerText"]]
        lineage = rt.submit(execution)  # captured at PCM submission
        permit = refs_of(d)["permitId"]
        for chunk in pcm:
            assert (await rt.media(lineage, permit, "audio", chunk))["accepted"]
        await rt.media(lineage, permit, "video", FRAME, pts_us=0)
        await rt.renew(lineage, permit)
        observe_tail(d)
        evidence = await rt.finish(lineage)
        proof = evidence["sinkProofs"][0]
        assert evidence["evidenceType"] == "ALL_REQUIRED_DRAIN" and proof["terminal"]
        assert proof["finalAudioSampleExclusive"] - proof["firstAudioSample"] == 640
        assert rt.tts_invocations == 1 and rt.next_sequence == 3
        assert d.r.gate.state == "STAGED_CLOSED"


@pytest.mark.asyncio
async def test_tts_latch_and_ticket_are_single_use(domain):
    d = domain
    async with runtime_against(d) as (rt, _, _):
        execution = await consumed(d, rt)
        speak = Speaker()
        await rt.speak_once(execution, artifact_of(d), speak)
        with pytest.raises(ReceiverRefused, match="TTS_ALREADY_STARTED"):
            await rt.speak_once(execution, artifact_of(d), speak)
        with pytest.raises(ReceiverRefused, match="GRANT_TICKET_INVALID"):
            await consumed(d, rt)  # no ticket left: nothing is sent
        assert len(speak.calls) == 1 and rt.tts_invocations == 1


@pytest.mark.asyncio
async def test_tts_failure_never_reopens_the_latch(domain):
    d = domain
    async with runtime_against(d) as (rt, _, _):
        execution = await consumed(d, rt)

        async def broken(text):
            raise RuntimeError("provider failed")

        with pytest.raises(RuntimeError):
            await rt.speak_once(execution, artifact_of(d), broken)
        with pytest.raises(ReceiverRefused, match="TTS_ALREADY_STARTED"):
            await rt.speak_once(execution, artifact_of(d), Speaker())


@pytest.mark.asyncio
async def test_competing_runtime_channel_never_gets_a_second_true_ack(domain):
    d = domain
    async with runtime_against(d) as (rt, ipc, _):
        token = secrets.token_urlsafe(32)
        ipc.pins = ipc.pins + (process_pin(d, "REGISTERED_RUNTIME", token),)
        rival = ReceiverRuntime(
            lambda: GuardianChannel(
                ipc.directory / "runtime.sock",
                identity(os.getpid()),
                Credential(token.encode()),
            ),
            GuardianWire(),
        )
        rival.remember_start(d.grant, start_of(d), (time.monotonic(), continuous()))
        await consumed(d, rt)
        with pytest.raises((ReceiverRefused, ReceiverUnknown)):
            await consumed(d, rival)
        assert not rival.executions and rival.tts_invocations == 0
        assert not rival._tickets
        await rival.close()


@pytest.mark.asyncio
async def test_old_lineage_is_rejected_not_relabelled(domain):
    d = domain
    async with runtime_against(d) as (rt, _, _):
        execution = await consumed(d, rt)
        await rt.speak_once(execution, artifact_of(d), Speaker())
        lineage = rt.submit(execution)
        permit = refs_of(d)["permitId"]
        await rt.media(lineage, permit, "audio", bytes(640))
        await rt.media(lineage, permit, "video", FRAME, pts_us=0)
        observe_tail(d)
        await rt.finish(lineage)
        before = rt.next_sequence
        with pytest.raises(ReceiverRefused, match="STALE_EXECUTION"):
            await rt.media(lineage, permit, "audio", bytes(640))  # delayed unit1 frame
        forged = Lineage("execution_other", lineage.artifact_id, lineage.artifact_hash)
        with pytest.raises(ReceiverRefused, match="STALE_EXECUTION"):
            await rt.media(forged, permit, "audio", bytes(640))
        assert rt.next_sequence == before  # no ordinal advance on rejection


@pytest.mark.asyncio
async def test_channel_loss_after_ack_is_unknown_and_closes_guardian_output(domain):
    d = domain
    async with runtime_against(d) as (rt, _, _):
        execution = await consumed(d, rt)
        await rt.speak_once(execution, artifact_of(d), Speaker())
        lineage = rt.submit(execution)
        execution.channel._streams[1].transport.abort()  # connection dies
        for _ in range(50):
            if d.outputs.closed:
                break
            await asyncio.sleep(0.01)
        assert d.outputs.closed  # Guardian fenced the owned execution
        assert d.r.audit[d.grant["grantId"]] == "UNKNOWN"
        with pytest.raises(ReceiverUnknown):
            await rt.media(lineage, refs_of(d)["permitId"], "audio", bytes(640))
        assert execution.state == "UNKNOWN"
        with pytest.raises(ReceiverRefused, match="STALE_EXECUTION"):
            await rt.media(lineage, refs_of(d)["permitId"], "audio", bytes(640))


@pytest.mark.asyncio
async def test_stop_closes_execution_without_retry(domain):
    d = domain
    async with runtime_against(d) as (rt, ipc, control_token):
        execution = await consumed(d, rt)
        await rt.speak_once(execution, artifact_of(d), Speaker())
        lineage = rt.submit(execution)
        reader, writer = await asyncio.open_unix_connection(
            str(ipc.directory / "control.sock")
        )
        body = d.r.wire.canonical(envelope(runId=d.r.staged["runId"]))
        writer.write(
            b"POST /guardian/durable-live-2/stop HTTP/1.1\r\nHost: g\r\nAuthorization: Bearer "
            + control_token.encode()
            + b"\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
            + body
        )
        await writer.drain()
        assert b"200 OK" in await reader.readuntil(b"\r\n\r\n")
        writer.close()
        with pytest.raises(ReceiverRefused):
            await rt.media(lineage, refs_of(d)["permitId"], "audio", bytes(640))
        assert execution.state == "UNKNOWN" and rt.next_sequence == 0
        with pytest.raises(ReceiverRefused, match="STALE_EXECUTION"):
            await rt.renew(lineage, refs_of(d)["permitId"])


@pytest.mark.asyncio
async def test_lost_backend_ack_is_unknown_and_query_never_rearms(domain):
    d = domain
    d.authority.drop_ack = True
    async with runtime_against(d) as (rt, _, _):
        with pytest.raises((ReceiverRefused, ReceiverUnknown)):
            await consumed(d, rt)
        assert rt.knowledge[d.grant["grantId"]] == "UNKNOWN"
        assert not rt._tickets and not rt.executions and rt.tts_invocations == 0
        summary = await rt.query(refs_of(d)["bootstrapId"], d.grant["grantId"])
        assert "consumeTicket" not in summary and not rt.executions
        with pytest.raises(ReceiverRefused, match="GRANT_TICKET_INVALID"):
            await consumed(d, rt)


@pytest.mark.asyncio
async def test_expired_start_deadline_refuses_before_any_ipc(domain):
    d = domain
    stale = (time.monotonic() - 60, continuous() - 60)
    async with runtime_against(d, sent=stale) as (rt, _, _):
        with pytest.raises(ReceiverRefused, match="GRANT_EXPIRED"):
            await consumed(d, rt)
        assert rt._channel is None  # never connected, ticket never left
        assert rt.knowledge[d.grant["grantId"]] == "REFUSED" and not rt._tickets


@pytest.mark.asyncio
async def test_wrong_guardian_identity_never_receives_the_ticket(domain):
    d = domain
    me = identity(os.getpid())
    impostor = ProcessIdentity(me.pid, me.uid, me.birth + "-other")
    async with runtime_against(d, guardian=impostor) as (rt, _, _):
        calls = list(d.authority.calls)
        with pytest.raises(ReceiverUnknown):
            await consumed(d, rt)
        assert d.authority.calls == calls  # Guardian never saw a consume
        assert not rt._tickets and rt.tts_invocations == 0


@pytest.mark.asyncio
async def test_same_execution_other_artifact_is_never_sent_as_current(domain):
    d = domain
    async with runtime_against(d) as (rt, _, _):
        execution = await consumed(d, rt)
        await rt.speak_once(execution, artifact_of(d), Speaker())
        lineage = rt.submit(execution)
        relabel = Lineage(lineage.execution_id, "artifact_other", "f" * 64)
        with pytest.raises(ReceiverRefused, match="STALE_EXECUTION"):
            await rt.media(relabel, refs_of(d)["permitId"], "audio", bytes(640))
        assert rt.next_sequence == 0 and execution.state == "ACTIVE"


@pytest.mark.asyncio
async def test_live_process_that_is_not_the_socket_peer_is_refused(domain):
    d = domain
    other = await asyncio.create_subprocess_exec("sleep", "30")
    try:
        pinned = identity(other.pid)  # valid, alive, but not the listener
        async with runtime_against(d, guardian=pinned) as (rt, _, _):
            calls = list(d.authority.calls)
            with pytest.raises(ReceiverUnknown):
                await consumed(d, rt)
            assert d.authority.calls == calls and rt.tts_invocations == 0
    finally:
        other.kill()
        await other.wait()


def confirm_business_drain(d, index=0):
    """Backend oracle JournalConfirmAnswerSegment (registered-checkpoint stand-in)."""
    x = d.x
    q = copy.deepcopy(x.rows["JournalConfirmAnswerSegment"]["request"])
    a = x.artifacts[index]
    q.update(
        artifactId=a["artifactId"],
        artifactHash=a["artifactHash"],
        idempotencyKey="drain:" + a["artifactId"],
        expectedAnswerRevision=x.j.answer_revision,
    )
    for proof in q["evidence"]["sinkProofs"]:
        proof.update(
            firstAudioSample=84000 * index,
            finalAudioSampleExclusive=84000 * (index + 1),
            audioConsumedThroughExclusive=84000 * (index + 1),
            finalVideoFrame=87 * (index + 1),
            videoConsumedThroughFrame=87 * (index + 1),
        )
    return x.j.drain(q)


@pytest.mark.asyncio
async def test_unit2_continuation_same_channel_continuous_ordinal_rejects_unit1(domain):
    d = domain
    async with runtime_against(d) as (rt, _, _):
        permit1 = refs_of(d)["permitId"]
        unit1 = await consumed(d, rt)
        await rt.speak_once(unit1, artifact_of(d), Speaker())
        old = rt.submit(unit1)
        await rt.media(old, permit1, "audio", bytes(640))
        await rt.media(old, permit1, "video", FRAME, pts_us=0)
        observe_tail(d)
        await rt.finish(old)
        confirm_business_drain(d, 0)
        # Unit2: new Artifact, NEW one-time continuation Grant, same Attempt.
        d.x.prepare(1)
        sent = (time.monotonic(), continuous())
        q2, grant2 = d.x.permit_and_start(1)
        start2 = next(
            e
            for e in reversed(d.x.events)
            if e["operationId"] == "JournalStartAnswerSegment"
        )["response"]
        rt.remember_start(grant2, start2, sent)
        artifact2 = copy.deepcopy(d.x.artifacts[1])
        unit2 = await rt.consume(
            d.x.b.registration, copy.deepcopy(q2["references"]), artifact2
        )
        assert unit2.channel is unit1.channel  # same persistent channel
        assert unit2.lineage.execution_id != old.execution_id
        speak = Speaker()
        await rt.speak_once(unit2, artifact2, speak)
        assert speak.calls == [artifact2["answerText"]] and rt.tts_invocations == 2
        with pytest.raises(ReceiverRefused, match="STALE_EXECUTION"):
            await rt.media(old, permit1, "audio", bytes(640))  # late unit1 frame
        assert rt.next_sequence == 2
        new = rt.submit(unit2)
        await rt.media(new, q2["references"]["permitId"], "audio", bytes(640))
        assert rt.next_sequence == 3  # outer ordinal continuous across units


@pytest.mark.asyncio
async def test_cancelled_consume_propagates_and_leaves_no_ticket_or_execution(domain):
    d = domain
    entered, release = d.authority.pauses["commit"] = (asyncio.Event(), asyncio.Event())
    async with runtime_against(d) as (rt, _, _):
        task = asyncio.create_task(consumed(d, rt))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert rt.knowledge[d.grant["grantId"]] == "UNKNOWN"
        assert not rt._tickets and not rt.executions and rt.tts_invocations == 0
        assert rt._channel.dead  # never reused for this or any later execution
