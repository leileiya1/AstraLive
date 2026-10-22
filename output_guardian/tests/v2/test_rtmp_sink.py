"""Stage 3b: Guardian RTMP publisher sink + independent RTMP Observer process.

Real: v2 Receiver gate, owned publisher child speaking RTMP to a tap, the tap
as a SEPARATE Observer process (own pid, kernel-peer pinned both ways) that
parses the pipe and forwards it to a dedicated loopback MediaMTX which
accepts the publish. Evidence is built by the Observer from the bytes on the
pipe, not by the Guardian. Not covered here: Backend recording of that
evidence (Go end-to-end, 3b-3) and audience delivery (never claimed).
"""

import asyncio
import hashlib
import json
import multiprocessing
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio

from output_guardian.v2.rtmp import RTMPMedia
from runtime.app.receiver1.rtmp_observer import TapEvidence
from runtime.app.receiver1.transport import identity

from .conftest import acknowledge, media

ROOT = Path(__file__).resolve().parents[3]
MEDIAMTX = os.environ.get("GUARDIAN_TEST_MEDIAMTX", "/tmp/astralive-guardian-tools/mediamtx")
if not Path(MEDIAMTX).is_file():
    pytest.skip("dedicated MediaMTX binary required", allow_module_level=True)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ingest(tmp_path):
    port = free_port()
    config = tmp_path / "mediamtx.yml"
    config.write_text(
        f"logLevel: debug\nrtmpAddress: 127.0.0.1:{port}\napi: no\nrtsp: no\nhls: no\n"
        "webrtc: no\nsrt: no\nplayback: no\nmoq: no\npaths:\n  all_others:\n"
    )
    log = (tmp_path / "mediamtx.log").open("w")
    process = subprocess.Popen([MEDIAMTX, str(config)], stdout=log, stderr=log)
    for _ in range(100):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.02)
    try:
        yield port, tmp_path / "mediamtx.log"
    finally:
        process.terminate()
        process.wait(timeout=5)
        log.close()


def start_observer(sink_id, upstream_port, origin):
    private = Path(tempfile.mkdtemp(prefix="ag5-obs-", dir="/tmp"))  # AF_UNIX length
    path = private / "evidence.sock"
    process = subprocess.Popen(
        [sys.executable, "-m", "runtime.app.receiver1.rtmp_observer"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    process.stdin.write(json.dumps(dict(
        sinkId=sink_id, upstream=["127.0.0.1", upstream_port], audioOrigin=origin,
        sampleRate=16000, guardianPid=os.getpid(), evidencePath=str(path),
    )) + "\n")
    process.stdin.flush()
    word, port = process.stdout.readline().split()
    assert word == "READY"
    return process, int(port), path


def tone(n, seed):
    t = np.arange(n) + seed * 7919
    return (np.sin(t / 9.0) * 9000).astype("<i2").tobytes()


@pytest_asyncio.fixture
async def published(domain, ingest):
    d = domain
    mtx_port, log = ingest
    sinks = d.r.required_sinks
    observer, tap, evidence_path = start_observer(next(iter(sinks)), mtx_port, d.r.gate.audio_end)
    sink = RTMPMedia(
        d.r.gate, d.tmp / "children", sinks,
        publish_url=f"rtmp://127.0.0.1:{tap}/live/room",
        evidence_builder=TapEvidence(evidence_path, identity(observer.pid)),
    )
    d.r.outputs = sink
    try:
        await sink.start()
        yield d, sink, observer, evidence_path, log
    finally:
        await sink.close()
        observer.stdin.close()
        observer.wait(5)


async def run_unit(d, units=25):
    _, q = await acknowledge(d)
    sent, sequence, pts = [], 0, 0
    renewer = asyncio.create_task(_renew(d, q))
    try:
        for n in range(units):  # 40ms A/V pairs at live pace
            pcm = tone(640, n)
            sent.append(pcm)
            await media(d, q, sequence=sequence, payload=pcm)
            await media(d, q, sequence=sequence + 1, kind="video",
                        payload=bytes([n * 9 % 256]) * (64 * 64 * 3), pts=pts)
            sequence, pts = sequence + 2, pts + 40000
            await asyncio.sleep(0.04)
        result = await d.r.finish(d.runtime, q)
    finally:
        renewer.cancel()
        await asyncio.gather(renewer, return_exceptions=True)
    return result, b"".join(sent)


async def ask(path, request):
    reader, writer = await asyncio.open_unix_connection(str(path))
    writer.write(json.dumps(request).encode() + b"\n")
    await writer.drain()
    out = json.loads(await reader.readline())
    writer.close()
    return out


@pytest.mark.asyncio
async def test_unit_tail_drains_on_independent_observer_evidence(published):
    d, sink, observer, evidence_path, _ = published
    assert sink.readiness["kind"] == "RTMP_PUBLISH_READY"  # ingest accepted publish
    assert "redacted" in repr(sink) and "rtmp://" not in repr(sink)
    started = time.monotonic()
    result, whole = await run_unit(d)
    # The tail reached the pipe while the connection stays open: no padding,
    # no flush, no disconnect is needed for the Observer to prove the drain.
    assert result["state"] == "LOCAL_MEDIA_DRAINED", result
    assert time.monotonic() - started < 1.0 + 0.5
    proof = result["evidence"]["sinkProofs"][0]
    assert proof["kind"] == "RTMP_PIPE_WRITE" and proof["terminal"] is True
    assert (proof["firstAudioSample"], proof["finalAudioSampleExclusive"]) == (0, 25 * 640)
    assert proof["finalVideoFrame"] == 24
    assert result["evidence"]["audienceVisibility"] == "UNVERIFIED"
    assert sink.process.is_alive() and observer.poll() is None  # pipe still open

    # A tail the pipe never carried is UNPROVEN; a wrong hash is a CONFLICT.
    base = dict(audioStart=0, audioEnd=25 * 640, videoPts=[i * 40000 for i in range(25)],
                finalVideoFrame=24, generationId="g", evidenceRef="probe")
    good = hashlib.sha256(whole).hexdigest()
    assert (await ask(evidence_path, dict(base, audioHash=good)))["ok"] is True
    beyond = await ask(evidence_path, dict(base, audioEnd=26 * 640, audioHash=good))
    assert beyond == {"ok": False, "code": "OUTPUT_FENCE_UNPROVEN"}
    wrong = await ask(evidence_path, dict(base, audioHash="0" * 64))
    assert wrong == {"ok": False, "code": "EVIDENCE_CONFLICT"}
    shifted = [i * 40000 + (2000 if i == 12 else 0) for i in range(25)]
    retimed = await ask(evidence_path, dict(base, videoPts=shifted, audioHash=good))
    assert retimed == {"ok": False, "code": "EVIDENCE_CONFLICT"}


@pytest.mark.asyncio
async def test_observer_refuses_unpinned_evidence_peer(published):
    evidence_path = published[3]
    script = (
        "import socket,sys;s=socket.socket(socket.AF_UNIX);s.connect(sys.argv[1]);"
        "s.sendall(b'{}\\n');print(s.makefile().readline())"
    )
    probe = await asyncio.to_thread(
        subprocess.run, [sys.executable, "-c", script, str(evidence_path)],
        capture_output=True, text=True, timeout=10, check=True,
    )
    assert json.loads(probe.stdout) == {"ok": False, "code": "UNAUTHENTICATED"}


@pytest.fixture
def held():
    ctx = multiprocessing.get_context("spawn")
    return {"before_write": ctx.Event(), "at_before_write": ctx.Event()}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["audio", "video"])
async def test_revoked_item_never_reaches_the_pipe(domain, ingest, held, kind):
    d = domain
    mtx_port, _ = ingest
    sinks = d.r.required_sinks
    observer, tap, evidence_path = start_observer(next(iter(sinks)), mtx_port, d.r.gate.audio_end)
    sink = RTMPMedia(
        d.r.gate, d.tmp / "children", sinks,
        publish_url=f"rtmp://127.0.0.1:{tap}/live/room",
        evidence_builder=TapEvidence(evidence_path, identity(observer.pid)),
        pauses=held,
    )
    d.r.outputs = sink
    renewer = asyncio.create_task(asyncio.sleep(0))
    try:
        await sink.start()
        _, q = await acknowledge(d)
        renewer = asyncio.create_task(_renew(d, q))  # proof stays valid until Stop
        audio = dict(payload=tone(640, 0))
        video = dict(kind="video", payload=bytes(64 * 64 * 3), pts=0)
        first, last = (video, audio) if kind == "audio" else (audio, video)
        held["before_write"].set()  # the other kind is written and acknowledged
        await media(d, q, sequence=0, **first)
        for _ in range(200):
            if any(sink.sinks.values()) and all(sink.sinks.values()):
                break
            await asyncio.sleep(0.005)
        assert all(sink.sinks.values())
        held["before_write"].clear()
        held["at_before_write"].clear()
        await media(d, q, sequence=1, **last)
        assert await asyncio.to_thread(held["at_before_write"].wait, 2)
        # Encoded and about to be written: Stop closes the edge first.
        with d.r.gate.lock:
            d.r.gate.stop_locked(d.r.staged["runId"])
        renewer.cancel()
        release(held["before_write"])
        await asyncio.sleep(0.2)
        assert all(row["last"] == 0 for rows in sink.sinks.values() for row in rows.values())
        # Correct hash and PTS: a leaked write would be provable; it is not.
        probe = dict(audioStart=0, audioEnd=640, videoPts=[0], finalVideoFrame=0,
                     generationId="g", evidenceRef="probe",
                     audioHash=hashlib.sha256(audio["payload"]).hexdigest())
        assert await ask(evidence_path, probe) == {"ok": False, "code": "OUTPUT_FENCE_UNPROVEN"}
    finally:
        renewer.cancel()
        await asyncio.gather(renewer, return_exceptions=True)
        await sink.close()
        observer.stdin.close()
        observer.wait(5)


def release(event):
    # A multiprocessing Event.set() waits for every sleeper to wake; a child
    # that already died must not hang the test, so set it from a daemon thread.
    setter = threading.Thread(target=event.set, daemon=True)
    setter.start()
    setter.join(1)


async def _renew(d, q):
    while True:
        await asyncio.sleep(0.075)
        await d.r.renew(d.runtime, dict(q, permitId=d.q["references"]["permitId"]))
