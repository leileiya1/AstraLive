"""Official sole codec with explicit contract MOCK Authority/Registrar.

No production dependency imports these fixtures. Local gate, filesystem,
process/socket and libav operations under test are real; SQL/Registrar/evidence
registration in this fixture remain mocks; separate native SQL tests cover official ports.
"""

import asyncio
import copy
import hashlib
import json
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest_asyncio

from output_guardian.v2.ipc import Peer
from output_guardian.v2.journal import DenyJournal
from output_guardian.v2.receiver import ObservedDrain, Receiver, envelope
from runtime.app.receiver1.wire import GuardianWire
from tests import test_receiver_contracts as contract


class MockAuthority:
    def __init__(self, x):
        self.x, self.calls, self.pauses = x, [], {}
        self.drop_ack = False

    async def _pause(self, name):
        self.calls.append(name)
        pause = self.pauses.get(name)
        if pause:
            pause[0].set()
            await pause[1].wait()

    async def query_receiver_authority(self, q):
        out = self.x.b.snapshot(self.x.g.peer, q)
        await self._pause("final" if self.x.b.latches else "query")
        return out

    async def commit_receiver_consume(self, q):
        # Test Backend oracle consumes wire JSON, exactly as native transport.
        q = json.loads(GuardianWire().canonical(q))
        out = self.x.b.commit(self.x.g.peer, q)
        await self._pause("commit")
        if self.drop_ack:
            raise ConnectionError("injected Backend ACK loss")
        return out

    async def query_receiver_consumption(self, q):
        return self.x.b.consumption_summary(self.x.g.peer, q)


class MockInstall:
    def __init__(self, x):
        self.x = x

    async def read(self, q):
        return self.x.p.supervisor.read_installation(self.x.g.peer, q)


class MockOutputs:
    def __init__(self, evidence):
        self.evidence = evidence
        self.pause = None
        self.closed = 0
        self.proven = True

    async def close(self):
        self.closed += 1
        return self.proven

    async def observe(self, lineage, tail):
        if self.pause:
            self.pause[0].set()
            await self.pause[1].wait()
        return ObservedDrain(
            tail, frozenset(self.evidence["requiredSinks"]), self.evidence
        )


def peer(p):
    return Peer(
        p.principalId,
        p.role,
        p.incarnation,
        ("tenant_demo", "owner_demo", "room_demo"),
        p.channelBinding,
    )


@asynccontextmanager
async def domain_source(tmp_path, issue=True):
    x = contract.ReceiverContractTests()
    x.setUp()
    if issue:
        request, grant = x.ready()
    else:
        x.bootstrap()
        request, grant = None, None
    scope = tuple(
        x.b.registration["binding"][k] for k in ("tenantId", "ownerId", "roomId")
    )
    runtime = peer(x.r.peer)
    runtime = Peer(
        runtime.principal_id,
        runtime.role,
        runtime.incarnation,
        scope,
        runtime.channel_binding,
    )
    control = Peer(
        x.p.control.principalId,
        "CONTROL_REGISTRAR",
        x.p.control.incarnation,
        scope,
        x.p.control.channelBinding,
    )
    authority = MockAuthority(x)
    evidence = copy.deepcopy(
        x.rows["JournalConfirmAnswerSegment"]["request"]["evidence"]
    )
    outputs = MockOutputs(evidence)
    journal = DenyJournal(tmp_path / "deny")
    r = Receiver(
        GuardianWire(),
        authority,
        MockInstall(x),
        outputs,
        journal,
        guardian_principal=x.g.peer.principalId,
        guardian_incarnation=x.g.peer.incarnation,
        signing_key=x.g.key,
        key_id=x.g.key_id,
        scope=scope,
        required_sinks=evidence["requiredSinks"],
    )
    stage = x.p.transcript[0]["request"]
    await r.stage(control, stage)
    d = SimpleNamespace(
        x=x,
        r=r,
        q=request,
        grant=grant,
        runtime=runtime,
        control=control,
        authority=authority,
        outputs=outputs,
        journal=journal,
        evidence=evidence,
        tmp=tmp_path,
    )

    def execution(ack):
        b = ack["consumption"]["binding"]
        return envelope(
            executionId=b["executionId"],
            artifactId=b["artifactId"],
            artifactHash=b["artifactHash"],
        )

    d.execution = execution
    d.ipc_dir = Path(tempfile.mkdtemp(prefix="ag5-v2-", dir="/tmp"))
    try:
        yield d
    finally:
        await r.restart()
        journal.close()
        shutil.rmtree(d.ipc_dir)


@pytest_asyncio.fixture
async def domain(tmp_path):
    async with domain_source(tmp_path) as d:
        yield d


@pytest_asyncio.fixture
async def closed_domain(tmp_path):
    async with domain_source(tmp_path, issue=False) as d:
        yield d


async def acknowledge(d):
    ack = await d.r.consume(d.runtime, d.q)
    return ack, d.execution(ack)


async def media(d, q, *, sequence=0, kind="audio", payload=None, pts=None):
    import base64

    payload = payload if payload is not None else bytes(640)
    return await d.r.media(
        d.runtime,
        dict(
            q,
            permitId=d.q["references"]["permitId"],
            sequence=sequence,
            kind=kind,
            payload=base64.b64encode(payload).decode(),
            ptsUs=pts,
        ),
    )


def pause():
    return asyncio.Event(), asyncio.Event()


async def mock_evidence(lineage, tail, sinks):
    """Synthetic registration envelope only; CPU ranges come from real decode."""
    return dict(
        evidenceType="ALL_REQUIRED_DRAIN",
        evidenceRef="mock_cpu_observer",
        evidenceHash=hashlib.sha256(repr(tail).encode()).hexdigest(),
        requiredSinks=sorted(sinks),
        sinkProofs=[
            dict(
                sinkId=s,
                kind="RTMP_PIPE_WRITE",
                generationId=json.loads(lineage.identity)["registration"][
                    "generationId"
                ],
                firstAudioSample=tail.audio_start,
                finalAudioSampleExclusive=tail.audio_end,
                audioConsumedThroughExclusive=tail.audio_end,
                finalVideoFrame=tail.final_video_frame,
                videoConsumedThroughFrame=tail.final_video_frame,
                terminal=True,
            )
            for s in sorted(sinks)
        ],
        predecessorCheckpointIds=["mock_sink_admitted"],
        audienceVisibility="UNVERIFIED",
    )
