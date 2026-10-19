"""Actual owned processes/AF_UNIX/libav and required decoded CPU sinks.

Authority, installation and Evidence registration remain explicit mocks. These
are neither RTMP/AAC/WebRTC drain nor production Linux isolation evidence.
"""

import asyncio
import copy
import multiprocessing
import os
import signal

import numpy as np
import pytest

from output_guardian.model import Closed
from output_guardian.v2.cpu import CPUMedia

from .conftest import acknowledge, media, mock_evidence


async def setup_cpu(d, *, pauses=None, builder=mock_evidence):
    cpu = CPUMedia(
        d.r.gate,
        d.tmp / "children",
        d.r.required_sinks,
        evidence_builder=builder,
        pauses=pauses,
    )
    d.r.outputs = cpu
    await cpu.start()
    return cpu


async def renew(d, q):
    while True:
        await asyncio.sleep(0.075)
        await d.r.renew(d.runtime, dict(q, permitId=d.q["references"]["permitId"]))


async def av_unit(d, q, start_sequence, pts, seed=1):
    rng = np.random.default_rng(seed)
    for index in range(2):
        pcm = rng.integers(-30000, 30000, 640, dtype=np.int16).astype("<i2").tobytes()
        rgb = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8).tobytes()
        await media(d, q, sequence=start_sequence + index * 2, payload=pcm)
        await media(
            d,
            q,
            sequence=start_sequence + index * 2 + 1,
            kind="video",
            payload=rgb,
            pts=pts + index * 40000,
        )


@pytest.mark.asyncio
async def test_real_decode_unit1_finish_unit2_same_process_clocks(domain):
    d = domain
    # Trusted Session origins, not rewritten zero-origin media.
    d.r.gate.audio_end, d.r.gate.video_end, d.r.gate.sequence = 48000, 2960000, 119
    d.r.gate.video_frames = 75
    cpu = await setup_cpu(d)
    ack, q = await acknowledge(d)
    publisher_pid = cpu.process.pid
    renewer = asyncio.create_task(renew(d, q))
    try:
        await av_unit(d, q, 120, 3000000)
        result = await d.r.finish(d.runtime, q)
        assert result["state"] == "LOCAL_MEDIA_DRAINED"
        assert cpu.process.pid == publisher_pid and cpu.process.is_alive()
        assert d.r.gate.state == "STAGED_CLOSED" and not d.r.gate.stops
        assert d.r.gate.audio_end == 49280 and d.r.gate.video_end == 3040000
        assert d.r.gate.sequence == 123
        assert all(len(rows) == 1 for rows in cpu.sinks.values())
        for rows in cpu.sinks.values():
            row = next(iter(rows.values()))
            assert row["start"] == 48000 and row["end"] == 49280
            assert row["pts"] == [3000000, 3040000]
        renewer.cancel()
        await asyncio.gather(renewer, return_exceptions=True)
        # Backend is the frozen MOCK; accept real CPU ranges inside explicitly
        # mock registered Evidence, then issue the unit2 continuation ticket.
        confirm = copy.deepcopy(d.x.rows["JournalConfirmAnswerSegment"]["request"])
        confirm.update(
            expectedAnswerRevision=d.x.j.answer_revision, evidence=result["evidence"]
        )
        d.x.j.drain(confirm)
        d.x.prepare(1)
        d.q, _ = d.x.permit_and_start(1)
        ack2, q2 = await acknowledge(d)
        assert (
            ack2["consumption"]["binding"]["generationId"]
            == ack["consumption"]["binding"]["generationId"]
        )
        renewer = asyncio.create_task(renew(d, q2))
        await av_unit(d, q2, 124, 3080000, seed=2)
        await d.r.finish(d.runtime, q2)
        assert cpu.process.pid == publisher_pid and cpu.process.is_alive()
        assert d.r.gate.audio_end == 50560 and d.r.gate.sequence == 127
        assert d.r.gate.video_end == 3120000 and d.r.gate.video_frames == 79
        assert d.x.j.command_start_count == 1 and len(d.x.b.latches) == 2
        with pytest.raises(Closed, match="STALE_EXECUTION"):
            await media(d, q, sequence=128)
        assert all(len(rows) == 2 for rows in cpu.sinks.values())
    finally:
        renewer.cancel()
        await asyncio.gather(renewer, return_exceptions=True)
        assert await cpu.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("edge", ["before_encode", "before_decode", "before_output"])
async def test_real_child_late_media_denied_at_each_edge(domain, edge):
    d = domain
    ctx = multiprocessing.get_context("spawn")
    pauses = {
        name: ctx.Event()
        for name in ("before_encode", "before_decode", "before_output")
    }
    pauses.update({"at_" + name: ctx.Event() for name in tuple(pauses)})
    for name, event in pauses.items():
        if name != edge and not name.startswith("at_"):
            event.set()
    cpu = await setup_cpu(d, pauses=pauses)
    _, q = await acknowledge(d)
    try:
        await media(d, q)
        assert await asyncio.to_thread(pauses["at_" + edge].wait, 1)
        # Direct barrier closes eligibility; release actual blocked native
        # pipeline to demonstrate its own check, BEFORE parent kills it.
        with d.r.gate.lock:
            d.r.gate.stop_locked(d.r.staged["runId"])
        pauses[edge].set()
        await asyncio.sleep(0.1)
        assert all(not rows for rows in cpu.sinks.values())
        assert not any(queue.qsize() for queue in cpu.sink_queues.values())
    finally:
        assert await cpu.close()


@pytest.mark.asyncio
async def test_actual_required_sink_backlog_stop_recheck(domain):
    d = domain
    d.r.required_sinks = frozenset({"cpu_primary", "cpu_secondary"})
    cpu = await setup_cpu(d)
    _, q = await acknowledge(d)
    name = sorted(cpu.required_sinks)[0]
    paused = cpu.sink_pauses[name] = asyncio.Event()
    renewer = asyncio.create_task(renew(d, q))
    try:
        await av_unit(d, q, 0, 0)
        for _ in range(200):
            if any(rows for n, rows in cpu.sinks.items() if n != name):
                break
            await asyncio.sleep(0.005)
        assert not cpu.sinks[name]
        assert any(rows for n, rows in cpu.sinks.items() if n != name)
        with d.r.gate.lock:
            d.r.gate.stop_locked(d.r.staged["runId"])
        paused.set()
        await asyncio.sleep(0.02)
        assert not cpu.sinks[name]  # queued bytes never bypass sink's own edge
    finally:
        renewer.cancel()
        await asyncio.gather(renewer, return_exceptions=True)
        assert await cpu.close()


@pytest.mark.asyncio
async def test_cpu_not_enough_without_registered_evidence(domain):
    d = domain
    cpu = await setup_cpu(d, builder=None)
    _, q = await acknowledge(d)
    renewer = asyncio.create_task(renew(d, q))
    try:
        await av_unit(d, q, 0, 0)
        with pytest.raises(Closed):
            await d.r.finish(d.runtime, q)
        assert d.r.gate.state == "UNKNOWN"
        assert all(rows for rows in cpu.sinks.values())
    finally:
        renewer.cancel()
        await asyncio.gather(renewer, return_exceptions=True)
        assert await cpu.close()


@pytest.mark.asyncio
async def test_actual_child_sigkill_does_not_prove_drain(domain):
    d = domain
    cpu = await setup_cpu(d)
    _, q = await acknowledge(d)
    os.kill(cpu.process.pid, signal.SIGKILL)
    try:
        await asyncio.sleep(0.03)
        with pytest.raises(Closed):
            await media(d, q)
        assert d.r.gate.state == "UNKNOWN"
    finally:
        assert await cpu.close()
