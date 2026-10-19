"""Additional Receiver invariants against explicit mock Authority/Observer."""

import asyncio

import pytest

from output_guardian.model import Closed
from output_guardian.v2.receiver import envelope

from .conftest import acknowledge, media, pause


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        "tenantId",
        "roomId",
        "runEpoch",
        "sessionId",
        "outputBindingVersion",
        "producerIncarnation",
        "generationId",
        "guardianIncarnation",
    ],
)
async def test_current_authority_cannot_replace_installed_identity(domain, field):
    d = domain
    original = d.authority.query_receiver_authority

    async def replaced(request):
        out = await original(request)
        b = out["snapshot"]["registration"]["binding"]
        b[field] = b[field] + 1 if type(b[field]) is int else "replaced_identity"
        return out

    d.authority.query_receiver_authority = replaced
    with pytest.raises(Closed):
        await d.r.consume(d.runtime, d.q)
    assert not d.x.b.latches and not d.r.gate.acks


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["query", "commit", "final"])
async def test_restart_during_consume_never_reconstitutes_ack(domain, phase):
    d = domain
    entered, release = d.authority.pauses[phase] = pause()
    task = asyncio.create_task(d.r.consume(d.runtime, d.q))
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.wait_for(d.r.restart(), 1)
    release.set()
    with pytest.raises(Closed):
        await task
    assert d.r.gate.state == "UNKNOWN" and not d.r.gate.acks and d.r.gate.active is None
    assert len(d.x.b.latches) == (0 if phase == "query" else 1)
    with pytest.raises(Closed):
        await d.r.consume(d.runtime, d.q)


@pytest.mark.asyncio
async def test_concurrent_stop_restart_keeps_run_irreversibly_closed(domain):
    d = domain
    await acknowledge(d)
    await asyncio.gather(
        d.r.stop(d.control, envelope(runId=d.r.staged["runId"])), d.r.restart()
    )
    assert d.r.staged["runId"] in d.r.gate.stops
    assert d.r.gate.active is None and not any(d.r.gate.edge.tag)
    with pytest.raises(Closed):
        await d.r.stage(d.control, d.x.p.transcript[0]["request"])


@pytest.mark.asyncio
async def test_enqueue_or_observer_counter_does_not_supply_required_proofs(domain):
    d = domain
    _, q = await acknowledge(d)
    await media(d, q)
    await media(d, q, sequence=1, kind="video", payload=bytes(64 * 64 * 3), pts=0)
    d.outputs.evidence["sinkProofs"] = []
    with pytest.raises(Closed):
        await d.r.finish(d.runtime, q)
    assert d.r.gate.state == "UNKNOWN" and not d.r.finished
    assert d.x.j.units[0]["state"] == "STARTED"  # no business drain/cursor advance


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", [1, 2])
async def test_actual_os_fsync_ebadf_never_authorizes(domain, monkeypatch, phase):
    """Real fsync syscall failure after fd fault; not a simulated disk EIO.

    File and directory fsync both hit the actual kernel with an invalidated
    descriptor. Hardware power loss/media corruption is still NOT TESTED.
    """
    import errno
    import os

    d = domain
    original, calls, observed = os.fsync, [], []

    def invalidate_then_fsync(fd):
        calls.append(fd)
        if len(calls) == phase:
            os.close(fd)
            try:
                original(fd)  # actual OS syscall, must return EBADF
            except OSError as exc:
                observed.append(exc.errno)
                raise
            raise AssertionError("kernel accepted invalid descriptor")
        original(fd)

    monkeypatch.setattr(os, "fsync", invalidate_then_fsync)
    with pytest.raises(Closed):
        await d.r.consume(d.runtime, d.q)
    assert observed == [errno.EBADF]
    assert len(d.x.b.latches) == 1 and d.r.gate.active is None
    assert not d.r.gate.acks and d.r.audit[d.q["references"]["grantId"]] == "UNKNOWN"
