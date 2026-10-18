"""Real CPU delayed initialization; budgets/margins and rejection stay strict."""

import asyncio
import multiprocessing
import time

import pytest

from output_guardian.model import Closed
from output_guardian.v2.cpu import CPUMedia

from .conftest import acknowledge, media, mock_evidence
from .test_cpu import av_unit, renew


@pytest.mark.asyncio
async def test_startup_delayed_before_grant_two_units_remain_continuous(closed_domain):
    import copy

    d = closed_domain
    ctx = multiprocessing.get_context("spawn")
    entered, release = ctx.Event(), ctx.Event()
    cpu = CPUMedia(
        d.r.gate,
        d.tmp / "ready-child",
        d.r.required_sinks,
        evidence_builder=mock_evidence,
        startup_barrier=(entered, release),
    )
    d.r.outputs = cpu
    task = asyncio.create_task(cpu.start())
    renewer = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        await asyncio.sleep(0.9)  # longer than the example Grant; none issued yet
        assert not task.done() and not cpu.ready and not d.x.b.latches
        assert not d.x.j.grants and not any(cpu.edge.tag)
        release.set()
        await task
        assert cpu.ready and cpu.readiness["pid"] == cpu.process.pid
        d.x.prepare()
        d.q, _ = d.x.permit_and_start()
        first, q = await acknowledge(d)
        pid = cpu.process.pid
        renewer = asyncio.create_task(renew(d, q))
        await av_unit(d, q, 0, 0)
        result = await d.r.finish(d.runtime, q)
        renewer.cancel()
        await asyncio.gather(renewer, return_exceptions=True)
        confirm = copy.deepcopy(d.x.rows["JournalConfirmAnswerSegment"]["request"])
        confirm.update(
            expectedAnswerRevision=d.x.j.answer_revision, evidence=result["evidence"]
        )
        d.x.j.drain(confirm)
        d.x.prepare(1)
        d.q, _ = d.x.permit_and_start(1)
        second, q2 = await acknowledge(d)
        renewer = asyncio.create_task(renew(d, q2))
        await av_unit(d, q2, 4, 80000, seed=2)
        await d.r.finish(d.runtime, q2)
        assert cpu.process.pid == pid and cpu.process.is_alive()
        assert (
            first["consumption"]["binding"]["generationId"]
            == second["consumption"]["binding"]["generationId"]
        )
        assert (
            d.r.gate.audio_end == 2560
            and d.r.gate.video_end == 120000
            and d.r.gate.sequence == 7
        )
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if renewer:
            renewer.cancel()
            await asyncio.gather(renewer, return_exceptions=True)
        assert await cpu.close()


@pytest.mark.asyncio
async def test_consume_before_native_ready_never_queries_authority(domain):
    d = domain
    ctx = multiprocessing.get_context("spawn")
    entered, release = ctx.Event(), ctx.Event()
    cpu = CPUMedia(
        d.r.gate,
        d.tmp / "not-ready",
        d.r.required_sinks,
        startup_barrier=(entered, release),
    )
    d.r.outputs = cpu
    task = asyncio.create_task(cpu.start())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        with pytest.raises(Closed):
            await acknowledge(d)
        assert not d.authority.calls and not d.x.b.latches and not any(cpu.edge.tag)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        assert await cpu.close()


@pytest.mark.asyncio
async def test_ready_timeout_kills_child_and_does_not_open_gate(domain):
    d = domain
    ctx = multiprocessing.get_context("spawn")
    cpu = CPUMedia(
        d.r.gate,
        d.tmp / "timeout",
        d.r.required_sinks,
        startup_barrier=(ctx.Event(), ctx.Event()),
        startup_timeout=0.03,
    )
    d.r.outputs = cpu
    with pytest.raises(Closed):
        await cpu.start()
    assert cpu.process is None and not cpu.ready and not cpu.registry.exists()
    assert not d.x.b.latches and not any(cpu.edge.tag)


@pytest.mark.asyncio
async def test_stop_immediately_after_native_spawn_reaps_child(domain, monkeypatch):
    d = domain
    cpu = CPUMedia(d.r.gate, d.tmp / "spawn-stop", d.r.required_sinks)
    d.r.outputs = cpu
    start = multiprocessing.process.BaseProcess.start
    owned = []

    def stop_after_spawn(process):
        start(process)
        owned.append(process.pid)
        with d.r.gate.lock:
            d.r.gate.stop_locked(d.r.staged["runId"])

    monkeypatch.setattr(multiprocessing.process.BaseProcess, "start", stop_after_spawn)
    with pytest.raises(Closed):
        await cpu.start()
    assert owned and cpu.process is None and not cpu.ready
    assert not cpu.registry.exists() and not any(cpu.edge.tag)
    import psutil

    assert not psutil.pid_exists(owned[0])


@pytest.mark.asyncio
async def test_actual_expiry_during_event_loop_stall_still_rejects(domain):
    d = domain
    cpu = CPUMedia(d.r.gate, d.tmp / "expired", d.r.required_sinks)
    d.r.outputs = cpu
    await cpu.start()
    _, q = await acknowledge(d)
    try:
        time.sleep(0.8)  # deliberately starve renewal, as in the first failure
        with pytest.raises(Closed, match="LEASE_LOST"):
            await media(d, q)
        assert d.r.gate.sequence == -1 and not d.r.gate.media
    finally:
        assert await cpu.close()
