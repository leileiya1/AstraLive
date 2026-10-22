"""Runtime AnswerCoordinator over the real Guardian v2 Receiver + PrivateIPC.

Real: Guardian Receiver/gate/IPC, kernel peer pins, ReceiverRuntime, the
coordinator and executor, and the oracle's own range/manifest/hash checks.
Explicit stand-ins: the Backend Journal is the contract oracle behind the same
``call(operation, document)`` interface as JournalClient (the real Journal
transport is proven by TestPostgresReceiver1RuntimeOwnedJournalFlow), the
Observer envelope is derived from the real tail, and TTS is a counting fake.
"""

import copy
import secrets
import time

import pytest
import pytest_asyncio

from output_guardian.v2.ipc import PrivateIPC
from runtime.app.receiver1.answer_coordinator import (
    AnswerCoordinator,
    CoordinatorError,
    JournalExecutor,
    PrepareUncertain,
)
from runtime.app.receiver1.journal_client import JournalUnknown
from runtime.app.receiver1.runtime_client import GuardianChannel, ReceiverRuntime
from runtime.app.receiver1.transport import Credential, continuous, identity
from runtime.app.receiver1.wire import GuardianWire

from .test_runtime_receiver import FRAME, observe_tail, process_pin


class OracleJournal:
    """Contract Backend oracle behind JournalClient's call() interface."""

    def __init__(self, x):
        self.x, self.calls, self.lose_next = x, [], None

    async def call(self, operation, document):
        sent = (time.monotonic(), continuous())
        x, peer = self.x, self.x.r.peer
        self.calls.append(operation)
        doc = copy.deepcopy(document)
        if operation == "JournalPrepareAnswer":
            out = dict(
                x.b.prepare(peer, doc), receiptId="receipt_" + secrets.token_hex(4)
            )
        elif operation == "AcquireOutputPermit":
            out = {"permitId": x.b.acquire(peer, doc["answerArtifactId"])["permitId"]}
        elif operation == "JournalStart":
            out = x.b.grant(peer, doc)
        elif operation == "JournalStartAnswerSegment":
            # The oracle omits wire-required answerRevision; the real Store
            # returns it. Supply it from oracle state (no other field added).
            out = dict(x.b.grant(peer, doc, True), answerRevision=x.j.answer_revision)
        elif operation == "JournalConfirmAnswerSegment":
            out = x.j.drain(doc)
        elif operation == "JournalSealAnswer":
            out = x.j.seal(doc)
        elif operation == "JournalQueryAnswer":  # read-only projection of oracle state
            out = {
                "answer": {
                    "answerRevision": x.j.answer_revision,
                    "inboxRevision": x.j.inbox_revision,
                }
            }
        else:
            raise AssertionError(operation)
        if self.lose_next == operation:  # applied, then the reply is lost
            self.lose_next = None
            raise JournalUnknown()
        return copy.deepcopy(out), sent


def command_of(d):
    x = d.x
    base = x.rows["JournalPrepareAnswer"]["request"]
    keys = (
        "tenantId",
        "ownerId",
        "runId",
        "commandId",
        "attemptId",
        "sessionId",
        "runEpoch",
        "producerIncarnation",
        "requestHash",
    )
    return dict(
        {k: base[k] for k in keys},
        guardianId=x.b.registration["binding"]["guardianId"],
        bootstrapId=x.b.registration["binding"]["bootstrapId"],
        registration=x.b.registration,
        expectedInboxRevision=x.j.inbox_revision,
        expectedAnswerRevision=x.j.answer_revision,
    )


class Speaker:
    def __init__(self):
        self.texts = []

    async def __call__(self, text):
        self.texts.append(text)
        return [
            ("audio", bytes(640), None),
            ("audio", bytes(640), None),
            ("video", FRAME, 40000 * len(self.texts)),
        ]


async def source(artifacts):
    for artifact in artifacts:
        yield copy.deepcopy(artifact)


@pytest_asyncio.fixture
async def wired(closed_domain):
    d = closed_domain
    token = secrets.token_urlsafe(32)
    ipc = PrivateIPC(d.r, d.ipc_dir, [process_pin(d, "REGISTERED_RUNTIME", token)])
    await ipc.start()
    me = identity(__import__("os").getpid())
    rt = ReceiverRuntime(
        lambda: GuardianChannel(
            ipc.directory / "runtime.sock", me, Credential(token.encode())
        ),
        GuardianWire(),
    )
    journal, speak = OracleJournal(d.x), Speaker()
    executor = JournalExecutor(journal, rt, command_of(d), speak)
    observe_tail(d)
    try:
        yield d, rt, journal, speak, executor
    finally:
        await rt.close()
        await ipc.close()


@pytest.mark.asyncio
async def test_two_units_prepare_start_drain_seal_with_continuous_clock(wired):
    d, rt, journal, speak, executor = wired
    coord = AnswerCoordinator(source(d.x.artifacts), executor)
    assert await coord.prepare_next()
    await coord.start_next()  # START + one consume + one TTS + media
    assert await coord.prepare_next()  # lookahead while unit1 plays
    with pytest.raises(CoordinatorError, match="ANSWER_WINDOW_FULL"):
        await coord.prepare_next()
    with pytest.raises(CoordinatorError, match="ANSWER_PREDECESSOR_NOT_DRAINED"):
        await coord.start_next()
    await coord.drain()  # Guardian evidence + Backend confirm (range checked)
    await coord.start_next()  # continuation Grant, same Attempt/Generation
    await coord.drain()  # oracle rejects unless unit2 starts where unit1 ended
    assert not await coord.prepare_next()  # EOF -> seal with real hashes
    assert coord.view() == {
        "prepared": 2,
        "drained": 2,
        "sealed": True,
        "stopped": False,
        "unknown": False,
        "preparing": False,
    }
    assert speak.texts == [a["answerText"] for a in d.x.artifacts]
    assert rt.tts_invocations == 2 and not rt._tickets
    assert coord.seal_receipt["state"] == "SEALED"
    assert journal.calls.count("JournalStart") == 1
    assert journal.calls.count("JournalStartAnswerSegment") == 1


@pytest.mark.asyncio
async def test_uncertain_prepare_retries_same_artifact_only(wired):
    d, _rt, journal, _speak, executor = wired
    journal.lose_next = "JournalPrepareAnswer"
    coord = AnswerCoordinator(source(d.x.artifacts), executor)
    with pytest.raises(PrepareUncertain):
        await coord.prepare_next()
    assert coord.retry["artifactId"] == d.x.artifacts[0]["artifactId"]
    assert await coord.prepare_next()  # same immutable unit, idempotent key
    assert [a["artifactId"] for a, _ in coord.entries] == [
        d.x.artifacts[0]["artifactId"]
    ]


@pytest.mark.asyncio
async def test_lost_start_reply_is_terminal_unknown_without_tts(wired):
    d, rt, journal, speak, executor = wired
    journal.lose_next = "JournalStart"
    coord = AnswerCoordinator(source(d.x.artifacts), executor)
    await coord.prepare_next()
    with pytest.raises(CoordinatorError, match="ANSWER_UNKNOWN"):
        await coord.start_next()
    assert speak.texts == [] and rt.tts_invocations == 0 and not rt._tickets
    assert coord.view()["unknown"]
    for step in (coord.prepare_next, coord.start_next, coord.drain):
        with pytest.raises(CoordinatorError, match="ANSWER_UNKNOWN"):
            await step()  # never retried, never resumed


@pytest.mark.asyncio
async def test_stop_during_playback_is_irreversible(wired):
    d, rt, _journal, _speak, executor = wired
    coord = AnswerCoordinator(source(d.x.artifacts), executor)
    await coord.prepare_next()
    await coord.start_next()
    coord.stop()
    assert coord.view()["stopped"] and coord.view()["unknown"]
    for step in (coord.prepare_next, coord.start_next, coord.drain):
        with pytest.raises(CoordinatorError, match="RUN_STOPPED"):
            await step()
    assert rt.tts_invocations == 1


@pytest.mark.asyncio
async def test_failed_drain_never_confirms_or_starts_next_unit(wired):
    d, rt, journal, _speak, executor = wired

    async def no_proof(lineage, tail):
        raise RuntimeError("observer unavailable")

    coord = AnswerCoordinator(source(d.x.artifacts), executor)
    await coord.prepare_next()
    await coord.start_next()
    d.outputs.observe = no_proof
    with pytest.raises(CoordinatorError, match="ANSWER_UNKNOWN"):
        await coord.drain()
    assert "JournalConfirmAnswerSegment" not in journal.calls
    assert d.x.j.units[0]["state"] == "STARTED"  # Backend never confirmed drain
    with pytest.raises(CoordinatorError, match="ANSWER_UNKNOWN"):
        await coord.start_next()
    assert rt.tts_invocations == 1


@pytest.mark.asyncio
async def test_foreign_artifact_is_refused_before_prepare(wired):
    d, _rt, journal, _speak, executor = wired
    foreign = copy.deepcopy(d.x.artifacts[0])
    foreign["commandId"] = "command_other"
    coord = AnswerCoordinator(source([foreign]), executor)
    with pytest.raises(CoordinatorError, match="ANSWER_UNKNOWN"):
        await coord.prepare_next()
    assert journal.calls == []
