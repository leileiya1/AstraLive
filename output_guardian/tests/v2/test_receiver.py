import asyncio
import os
import threading
from dataclasses import replace

import pytest

from output_guardian.model import Closed
from output_guardian.v2.journal import DenyJournal
from output_guardian.v2.receiver import envelope

from .conftest import acknowledge, media, pause


async def stop(d, run=None):
    return await d.r.stop(d.control, envelope(runId=run or d.r.staged["runId"]))


@pytest.mark.asyncio
async def test_stop_a_local_before_backend(domain):
    d = domain
    await stop(d)
    assert d.x.b.registration["state"] == "ACTIVE"  # Backend has NOT stopped
    with pytest.raises(Closed, match="RUN_STOPPED"):
        await d.r.consume(d.runtime, d.q)
    assert not d.x.b.latches and not d.r.gate.acks
    with pytest.raises(Closed):
        await d.r.stage(d.control, d.x.p.transcript[0]["request"])


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["query", "commit", "final"])
async def test_stop_c_every_consume_rpc_pause(domain, phase):
    d = domain
    entered, release = d.authority.pauses[phase] = pause()
    task = asyncio.create_task(d.r.consume(d.runtime, d.q))
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.wait_for(stop(d), 1)  # no gate across suspended RPC
    release.set()
    with pytest.raises(Closed):
        await task
    assert not d.r.gate.acks and d.r.gate.active is None
    assert list(d.r.audit.values()) == ["UNKNOWN"]
    assert len(d.x.b.latches) == (0 if phase == "query" else 1)
    assert d.r.gate.state == "FENCED"


@pytest.mark.asyncio
async def test_backend_ack_lost_never_rearms(domain):
    d = domain
    d.authority.drop_ack = True
    with pytest.raises(Closed):
        await d.r.consume(d.runtime, d.q)
    assert len(d.x.b.latches) == 1
    with pytest.raises(Closed):
        await d.r.consume(d.runtime, d.q)
    query = envelope(
        bootstrapId=d.q["references"]["bootstrapId"],
        grantId=d.q["references"]["grantId"],
    )
    assert (await d.r.query(d.runtime, query))["summary"]["state"] == "UNKNOWN"
    assert not d.r.gate.acks


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [1, 2])
async def test_actual_file_and_directory_fsync_failure(domain, monkeypatch, failure):
    d = domain
    original, calls = os.fsync, []

    def faulty(fd):
        calls.append(fd)
        if len(calls) == failure:
            raise OSError("injected fsync EIO")
        return original(fd)

    monkeypatch.setattr(os, "fsync", faulty)
    with pytest.raises(Closed):
        await d.r.consume(d.runtime, d.q)
    monkeypatch.setattr(os, "fsync", original)
    assert len(d.x.b.latches) == 1 and not d.r.gate.acks
    assert d.r.gate.state == "UNKNOWN"
    d.journal.close()
    if failure == 1:
        with pytest.raises(Closed):
            DenyJournal(d.tmp / "deny")  # partial temp remains a startup fault
    else:
        recovered = DenyJournal(d.tmp / "deny")
        assert d.r.staged["runId"] in recovered.stops
        assert d.q["references"]["grantId"] in recovered.denied
        recovered.close()


@pytest.mark.asyncio
async def test_stop_while_real_fsync_thread_paused(domain, monkeypatch):
    d = domain
    entered, release = threading.Event(), threading.Event()
    original = os.fsync
    first = []

    def suspended(fd):
        if not first:
            first.append(True)
            entered.set()
            assert release.wait(2)
        original(fd)

    monkeypatch.setattr(os, "fsync", suspended)
    task = asyncio.create_task(d.r.consume(d.runtime, d.q))
    assert await asyncio.to_thread(entered.wait, 1)
    # Admission closes even while a real file fsync phase is suspended.
    stop_task = asyncio.create_task(stop(d))
    await asyncio.wait_for(stop_task, 1)
    assert not release.is_set()
    assert d.r.gate.state == "FENCED" and d.r.gate.active is None
    release.set()
    with pytest.raises(Closed):
        await task
    assert d.r.audit[d.q["references"]["grantId"]] == "UNKNOWN"


@pytest.mark.asyncio
async def test_stop_b_local_cached_proof_cannot_handoff(domain):
    d = domain
    _, q = await acknowledge(d)
    await stop(d)
    with pytest.raises(Closed):
        await media(d, q)
    assert d.r.gate.sequence == -1 and not d.r.gate.media


@pytest.mark.asyncio
async def test_media_concurrency_bounded_ordinal(domain):
    d = domain
    _, q = await acknowledge(d)
    calls = len(d.authority.calls)
    results = await asyncio.gather(
        *(media(d, q) for _ in range(32)), return_exceptions=True
    )
    assert sum(isinstance(v, dict) for v in results) == 1
    assert len(d.r.gate.media) == 1 and d.r.gate.sequence == 0
    assert len(d.authority.calls) == calls  # no blocking per-frame SQL/RPC
    with pytest.raises(Closed):
        await media(d, dict(q, artifactHash="0" * 64), sequence=1)
    with pytest.raises(Closed):
        await d.r.renew(
            replace(d.runtime, channel_binding="0" * 64),
            dict(q, permitId=d.q["references"]["permitId"]),
        )


@pytest.mark.asyncio
async def test_two_consume_contenders_only_one_commit(domain):
    d = domain
    results = await asyncio.gather(
        *(d.r.consume(d.runtime, d.q) for _ in range(32)), return_exceptions=True
    )
    assert sum(isinstance(v, dict) and v["consumeAuthorized"] for v in results) == 1
    assert len(d.x.b.latches) == 1 and len(d.r.gate.acks) == 1


@pytest.mark.asyncio
async def test_stop_renew_and_observer_waits(domain):
    d = domain
    _, q = await acknowledge(d)
    entered, release = d.authority.pauses["final"] = pause()
    task = asyncio.create_task(
        d.r.renew(d.runtime, dict(q, permitId=d.q["references"]["permitId"]))
    )
    await entered.wait()
    await stop(d)
    release.set()
    with pytest.raises(Closed):
        await task
    assert d.r.gate.state == "FENCED"


@pytest.mark.asyncio
async def test_stop_finish_does_not_reopen(domain):
    d = domain
    _, q = await acknowledge(d)
    await media(d, q)
    entered, release = d.outputs.pause = pause()
    task = asyncio.create_task(d.r.finish(d.runtime, q))
    await entered.wait()
    await stop(d)
    release.set()
    with pytest.raises(Closed):
        await task
    assert d.r.gate.state == "FENCED" and not d.r.finished


@pytest.mark.asyncio
async def test_restart_and_old_run_tombstone_real_files(domain):
    d = domain
    await acknowledge(d)
    assert len(list((d.tmp / "deny").glob("*.json"))) == 2
    for path in (d.tmp / "deny").glob("*.json"):
        assert d.q["consumeTicket"].encode() not in path.read_bytes()
        assert b"consumeAuthorized" not in path.read_bytes()
    await d.r.restart()
    d.journal.close()
    recovered = DenyJournal(d.tmp / "deny")
    assert d.r.staged["runId"] in recovered.stops
    assert d.q["references"]["grantId"] in recovered.denied
    recovered.close()
    with pytest.raises(Closed):
        await d.r.stage(d.control, d.x.p.transcript[0]["request"])


@pytest.mark.asyncio
async def test_unrelated_run_stop_cannot_close_current_output(domain):
    d = domain
    _, q = await acknowledge(d)
    before = d.r.gate.revision
    await stop(d, "other_run")
    assert d.r.gate.state == "ACTIVE_UNIT" and d.r.gate.revision == before
    await media(d, q)


@pytest.mark.asyncio
async def test_expired_proof_renew_cannot_resurrect(domain):
    d = domain
    _, q = await acknowledge(d)
    with d.r.gate.lock:
        d.r.gate.edge.deadlines[:] = [0, 0]
    with pytest.raises(Closed):
        await media(d, q)
    with pytest.raises(Closed):
        await d.r.renew(d.runtime, dict(q, permitId=d.q["references"]["permitId"]))


@pytest.mark.asyncio
async def test_stop_cleanup_unproven_never_claims_fenced(domain):
    d = domain
    await acknowledge(d)
    d.outputs.proven = False
    with pytest.raises(Closed, match="OUTPUT_FENCE_UNPROVEN"):
        await stop(d)
    assert d.r.gate.state == "UNKNOWN"
    d.outputs.proven = True


def test_journal_owner_and_corruption_closed(tmp_path):
    j = DenyJournal(tmp_path / "state")
    with pytest.raises(Closed):
        DenyJournal(tmp_path / "state")
    j.append("stop", "run")
    j.close()
    path = next((tmp_path / "state").glob("*.json"))
    path.write_text("{}")
    with pytest.raises(Closed):
        DenyJournal(tmp_path / "state")


@pytest.mark.asyncio
async def test_stop_b_during_media_hash_final_handoff(domain):
    d = domain
    _, q = await acknowledge(d)
    entered, release = threading.Event(), threading.Event()
    digest = d.r.audio_hash

    class PausedDigest:
        def copy(self):
            return self

        def update(self, payload):
            entered.set()
            assert release.wait(2)
            digest.update(payload)

    d.r.audio_hash = PausedDigest()
    task = asyncio.create_task(asyncio.to_thread(lambda: asyncio.run(media(d, q))))
    assert await asyncio.to_thread(entered.wait, 1)
    await asyncio.wait_for(stop(d), 1)
    assert not release.is_set()
    release.set()
    with pytest.raises(Closed):
        await task
    assert d.r.gate.sequence == -1 and not d.r.gate.media


@pytest.mark.asyncio
async def test_consumed_grant_expiry_is_not_session_cutoff(domain):
    d = domain
    ack, q = await acknowledge(d)
    d.x.j.now += 1.1  # original Grant is now expired on authoritative MOCK time
    permit = d.x.b.acquire(d.x.r.peer, q["artifactId"], True)
    renewal = await d.r.renew(d.runtime, dict(q, permitId=permit["permitId"]))
    assert renewal["timing"]["remainingGrantMs"] == 0
    d.q["references"]["permitId"] = permit["permitId"]
    await media(d, q)
    assert len(d.x.b.latches) == 1 and d.x.j.command_start_count == 1
    assert ack["consumption"]["binding"]["generationId"] == d.r.staged["generationId"]


@pytest.mark.asyncio
async def test_authority_timeout_never_retries_consume(domain):
    d = domain
    entered, release = d.authority.pauses["commit"] = pause()
    with pytest.raises(Closed):
        await d.r.consume(d.runtime, d.q)
    assert entered.is_set() and not release.is_set()
    assert len(d.x.b.latches) == 1 and d.authority.calls.count("commit") == 1
    assert d.r.gate.state == "UNKNOWN" and not d.r.gate.acks


@pytest.mark.asyncio
async def test_stop_fsync_failure_still_closes_owned_outputs(domain, monkeypatch):
    d = domain
    await acknowledge(d)

    def fail(_):
        raise OSError("injected stop disk error")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(Closed):
        await stop(d)
    assert d.outputs.closed == 1 and d.r.gate.state == "UNKNOWN"


def test_both_local_deadline_clocks_must_hold():
    import time

    from output_guardian.v2.clocks import suspend_clock
    from output_guardian.v2.gate import Budget

    with pytest.raises(Closed):
        Budget(time.monotonic() + 1, suspend_clock() - 1).check()
    with pytest.raises(Closed):
        Budget(time.monotonic() - 1, suspend_clock() + 1).check()
