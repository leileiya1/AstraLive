"""Deterministic local lifecycle tests; Authority/output/evidence are explicit mocks.

Actual SQL/RTMP, original unmodified coverage and process ownership are exercised
separately by the original Agent4 probes and Guardian regressions.
"""

import asyncio
import dataclasses
import subprocess
import sys
import threading
from multiprocessing import Pipe
from types import SimpleNamespace

import pytest
import pytest_asyncio

from output_guardian import service
from output_guardian.model import Attempt, Binding, Closed, Right, clock
from output_guardian.process import Publisher


def right(name="permit"):
    import time

    return Right.from_remaining(name, 0.9, clock(), time.monotonic())


class Idle(asyncio.Event):
    def __init__(self):
        super().__init__()
        self.waiting = asyncio.Event()
        self.set()

    async def wait(self):
        self.waiting.set()
        return await super().wait()


class Endpoint:
    def __init__(self):
        self.alive = True
        self.process = SimpleNamespace(poll=lambda: None if self.alive else 71)
        self.pipe = object()
        self.calls = []
        self.permit_entered, self.aborted = asyncio.Event(), asyncio.Event()
        self.permit_release = self.abort_release = None
        self.failure = None

    async def start(self, config):
        self.alive = True
        self.process = SimpleNamespace(poll=lambda: None if self.alive else 71)
        self.pipe = object()

    async def call(self, msg, **kw):
        if self.failure:
            raise self.failure
        if self.process is None or not self.alive:
            raise Closed("MEDIA_DELIVERY_FAILED")
        self.calls.append(msg["op"])
        if msg["op"] == "permit":
            self.permit_entered.set()
            if self.permit_release:
                await self.permit_release.wait()
        return {"manifest": {}, "audioSamples": 64000, "videoPTSUS": [0]}

    async def abort(self, *a):
        self.process = self.pipe = None
        self.alive = False
        self.aborted.set()
        if self.abort_release:
            await self.abort_release.wait()


@pytest_asyncio.fixture
async def local(tmp_path, monkeypatch):
    a = Attempt(Binding("t", "o", "room", "run", 1, "s", 1, "p"), "a", "u", 1, "c")
    sql = SimpleNamespace(entered=asyncio.Event(), release=None, fail=None, calls=0)

    async def permit(*args):
        value = right()
        sql.returned = value
        sql.calls += 1
        sql.entered.set()
        if sql.release:
            await sql.release.wait()
        if sql.fail:
            raise sql.fail
        value.check()
        return value

    async def noop(*a):
        pass

    auth = SimpleNamespace(
        permit=permit, guardian_id="g", scope_check=lambda b: None, pending=noop
    )
    ingest = SimpleNamespace(isolate=noop)
    g = service.Guardian(
        auth,
        ingest,
        tmp_path / "state",
        tmp_path,
        rtmp_url="rtmp://127.0.0.1:1935",
        path="room",
    )
    g.state_dir.mkdir(mode=0o700)
    g.started, g.failed = True, False
    g.binding, g.attempt, g.right = a.binding, a, right()
    g._life = service._Lifecycle(a, g.barrier)
    g._life.idle = Idle()
    g.publisher, g.receiver = Endpoint(), Endpoint()
    g.used_attempts.add(a.attemptId)
    monkeypatch.setattr(
        service, "verify_combined", lambda *a: {"decodedAudioSamples": 64000}
    )
    yield SimpleNamespace(g=g, a=a, sql=sql)
    # Release every test-only scheduling barrier before cleanup.
    for ep in (g.publisher, g.receiver):
        for event in (ep.permit_release, ep.abort_release):
            if event:
                event.set()
    if sql.release:
        sql.release.set()
    await g.retire()


@pytest.mark.asyncio
async def test_normal_teardown_new_and_late_renew_never_retire(local):
    g, a = local.g, local.a
    g.publisher.abort_release = asyncio.Event()
    task = asyncio.create_task(g.finish(a))
    await asyncio.wait_for(g.publisher.aborted.wait(), 1)
    barrier = g.barrier
    with pytest.raises(Closed, match="STATE_CONFLICT"):
        await g.renew(a, "fresh")
    assert local.sql.calls == 0 and g.barrier == barrier
    g.publisher.abort_release.set()
    assert (await task)["state"] == "LOCAL_MEDIA_DRAINED"
    assert g.last_drain_result["coverage"] == "PASS" and g.last_drain_fault is None
    with pytest.raises(Closed, match="STATE_CONFLICT"):
        await g.renew(a, "late")
    assert g.right is None and g.publisher.process is None


@pytest.mark.asyncio
async def test_reserved_renew_completes_before_teardown(local):
    g, a = local.g, local.a
    g.publisher.permit_release = asyncio.Event()
    renewal = asyncio.create_task(g.renew(a, "valid"))
    await g.publisher.permit_entered.wait()
    finish = asyncio.create_task(g.finish(a))
    await asyncio.wait_for(g._life.idle.waiting.wait(), 1)
    assert not g.publisher.aborted.is_set() and g._life.renewing == 1
    with pytest.raises(Closed, match="STATE_CONFLICT"):
        await g.renew(a, "new-after-quiesce")
    g.publisher.permit_release.set()
    assert (await renewal)["state"] == "AUTHORIZED"
    assert (await finish)["state"] == "LOCAL_MEDIA_DRAINED"


@pytest.mark.asyncio
async def test_sql_reply_after_terminal_is_conflict_without_publisher_call(local):
    g, a = local.g, local.a
    local.sql.release = asyncio.Event()
    renewal = asyncio.create_task(g.renew(a, "committed"))
    await local.sql.entered.wait()
    g.publisher.abort_release = asyncio.Event()
    finish = asyncio.create_task(g.finish(a))
    await asyncio.wait_for(g.publisher.aborted.wait(), 1)
    local.sql.release.set()
    with pytest.raises(Closed, match="STATE_CONFLICT"):
        await renewal
    assert "permit" not in g.publisher.calls
    g.publisher.abort_release.set()
    assert (await finish)["state"] == "LOCAL_MEDIA_DRAINED"


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["before", "reserved-renew", "teardown", "after"])
async def test_stop_linearizes_before_completion_or_after_success(local, point):
    g, a = local.g, local.a
    renewal = finish = None
    if point == "reserved-renew":
        g.publisher.permit_release = asyncio.Event()
        renewal = asyncio.create_task(g.renew(a, "valid"))
        await g.publisher.permit_entered.wait()
        finish = asyncio.create_task(g.finish(a))
        await g._life.idle.waiting.wait()
    elif point in {"teardown", "after"}:
        if point == "teardown":
            g.publisher.abort_release = asyncio.Event()
        finish = asyncio.create_task(g.finish(a))
        if point == "teardown":
            await g.publisher.aborted.wait()
        else:
            assert (await finish)["state"] == "LOCAL_MEDIA_DRAINED"
    stopped = asyncio.Event()
    persist = g.persist_stops

    def persisted():
        persist()
        stopped.set()

    g.persist_stops = persisted
    stopping = asyncio.create_task(g.stop("run"))
    await stopped.wait()  # exact Stop event, not an already-set abort event
    assert "run" in g.stopped and g.right is None
    for event in (g.publisher.permit_release, g.publisher.abort_release):
        if event:
            event.set()
    await stopping
    if renewal:
        with pytest.raises(Closed, match="LEASE_LOST"):
            await renewal
    if finish and point != "after":
        with pytest.raises(Closed, match="DRAIN_UNKNOWN"):
            await finish
    if point == "before":
        with pytest.raises(Closed):
            await g.finish(a)
    await g.stop("run")
    assert g.publisher.process is None and g.right is None


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", ["old", "new", "barrier", "sql-failure"])
async def test_invalid_sql_reply_never_reauthorizes(local, expired):
    g, a = local.g, local.a
    original_right = g.right
    local.sql.release = asyncio.Event()
    task = asyncio.create_task(g.renew(a, "committed"))
    await local.sql.entered.wait()
    if expired == "old":
        object.__setattr__(original_right, "deadline", clock() - 1)
    elif expired == "new":
        object.__setattr__(local.sql.returned, "deadline", clock() - 1)
    elif expired == "barrier":
        g.invalidate()
    else:
        local.sql.fail = Closed("DEPENDENCY_UNAVAILABLE")
    local.sql.release.set()
    with pytest.raises(Closed, match="LEASE_LOST"):
        await task
    assert "permit" not in g.publisher.calls and g.right is None


@pytest.mark.asyncio
async def test_poll_fault_then_full_coverage_has_distinct_final_diagnostic(
    local, monkeypatch
):
    count = 0

    def verify(*args):
        nonlocal count
        count += 1
        if count == 1:
            raise Closed("DRAIN_PACKET_COVERAGE_audio_test")
        return {"decodedAudioSamples": 64000}

    monkeypatch.setattr(service, "verify_combined", verify)
    await local.g.finish(local.a)
    d = local.g.last_drain_result
    assert d["coverage"] == "PASS" and d["terminal"] == "DRAINED"
    assert d["pollFaults"] == [
        {"terminal": False, "code": "DRAIN_PACKET_COVERAGE_audio_test"}
    ]
    assert local.g.last_drain_fault is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["pipe", "teardown", "cancel", "expire", "duplicate"])
async def test_terminal_faults_are_not_success(local, fault):
    g, a = local.g, local.a
    if fault == "pipe":
        g.publisher.failure = Closed("MEDIA_DELIVERY_FAILED")
        with pytest.raises(Closed, match="DRAIN_UNKNOWN"):
            await g.finish(a)
        assert g.last_drain_result["coverage"] == "PENDING"
        return
    if fault == "teardown":

        async def broken():
            raise OSError("never log exception contents")

        g.ingest.isolate = broken
    g.publisher.abort_release = asyncio.Event()
    finish = asyncio.create_task(g.finish(a))
    await g.publisher.aborted.wait()
    if fault == "cancel":
        finish.cancel()
    elif fault == "expire":
        g.right = dataclasses.replace(g.right, deadline=clock() - 1)
    elif fault == "duplicate":
        with pytest.raises(Closed):
            await g.finish(a)
        with pytest.raises(Closed, match="STATE_CONFLICT"):
            await g.renew(a, "fresh")
    g.publisher.abort_release.set()
    if fault == "duplicate":
        assert (await finish)["state"] == "LOCAL_MEDIA_DRAINED"
    else:
        with pytest.raises(Closed, match="DRAIN_UNKNOWN"):
            await finish
        assert g.last_drain_result["coverage"] == "PASS"
        assert g.last_drain_result["terminal"] == "FAILED"
        # Failed cleanup is intentionally quarantined, release fixture safely.
        if fault == "teardown":

            async def noop():
                pass

            g.ingest.isolate = noop
            g._cleanup_task = None


@pytest.mark.asyncio
async def test_dead_publisher_after_verified_ranges_is_unknown(local, monkeypatch):
    def verify(*args):
        local.g.publisher.alive = False
        return {"decodedAudioSamples": 64000}

    monkeypatch.setattr(service, "verify_combined", verify)
    with pytest.raises(Closed, match="DRAIN_UNKNOWN"):
        await local.g.finish(local.a)
    assert local.g.last_drain_result["fault"] == "MEDIA_DELIVERY_FAILED"


@pytest.mark.asyncio
async def test_abort_coalesces_actual_owned_process_and_blocks_reuse(
    tmp_path, monkeypatch
):
    pub = Publisher(tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    parent, child = Pipe()
    child.close()
    pub.process, pub.pipe = proc, parent
    pub.registry.write_text("test-owned child")
    entered, release = threading.Event(), threading.Event()
    wait = proc.wait

    def delayed(*a, **kw):
        entered.set()
        release.wait(1)
        return wait(*a, **kw)

    monkeypatch.setattr(proc, "wait", delayed)
    first = asyncio.create_task(pub.abort())
    await asyncio.to_thread(entered.wait, 1)
    second = asyncio.create_task(pub.abort(proc))
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    with pytest.raises(Closed):
        await pub.start({})
    release.set()
    await second
    await pub.abort()
    assert proc.poll() is not None and parent.closed and not pub.registry.exists()


@pytest.mark.asyncio
async def test_delayed_sql_after_stop_cannot_touch_replacement(local):
    g, a = local.g, local.a
    local.sql.release = asyncio.Event()
    renewal = asyncio.create_task(g.renew(a, "old-request"))
    await local.sql.entered.wait()
    await g.stop("run")
    # Explicit trusted mock replacement, not a Runtime-provided installation.
    replacement = dataclasses.replace(
        a, binding=dataclasses.replace(a.binding, runId="next"), generation=2
    )
    g.binding, g.attempt, g.right = replacement.binding, replacement, right("new")
    g._life = service._Lifecycle(replacement, g.barrier)
    await g.publisher.start({})
    process = g.publisher.process
    local.sql.release.set()
    with pytest.raises(Closed, match="LEASE_LOST"):
        await renewal
    assert g.publisher.process is process and g.right.permit_id == "new"


@pytest.mark.asyncio
async def test_stop_fsync_failure_still_revokes_and_closes(local):
    def broken():
        raise OSError("injected fsync failure")

    local.g.persist_stops = broken
    with pytest.raises(Closed):
        await local.g.stop("run")
    assert "run" in local.g.stopped and local.g.failed
    assert local.g.right is None and local.g.publisher.process is None
    with pytest.raises(Closed):
        await local.g.finish(local.a)


@pytest.mark.asyncio
async def test_expired_right_during_terminal_is_never_normal_conflict(local):
    g, a = local.g, local.a
    g.publisher.abort_release = asyncio.Event()
    finish = asyncio.create_task(g.finish(a))
    await g.publisher.aborted.wait()
    g.right = dataclasses.replace(g.right, deadline=clock() - 1)
    retired = asyncio.Event()
    invalidated = g.invalidate

    def invalidate(*args, **kw):
        invalidated(*args, **kw)
        retired.set()

    g.invalidate = invalidate
    renewal = asyncio.create_task(g.renew(a, "fresh-but-old-expired"))
    await retired.wait()
    assert g.right is None
    g.publisher.abort_release.set()
    with pytest.raises(Closed, match="LEASE_LOST"):
        await renewal
    with pytest.raises(Closed, match="DRAIN_UNKNOWN"):
        await finish
    assert g.last_drain_result["revocation"] == "LEASE_LOST"


@pytest.mark.asyncio
async def test_rapid_new_generations_close_all_owned_listeners(local):
    g = local.g
    for i in range(2, 7):
        attempt = dataclasses.replace(local.a, generation=i, attemptId=f"a{i}")
        await g.bind(attempt, f"p{i}")
        await g.receiver.start({})  # explicit mock observer for this fresh bind
        assert g._life.attempt == attempt
        socket = g.publishing_socket
        await g.finish(attempt)
        assert socket.closed.is_set() and not socket.tasks and not socket.writers
        assert g.publisher.process is None and g.receiver.process is None
        with pytest.raises(Closed):
            await g.renew(local.a, "old-generation")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["eof", "backpressure"])
async def test_actual_owned_pipe_failure_reaps_only_captured_child(tmp_path, failure):
    pub = Publisher(tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    parent, child = Pipe()
    pub.process, pub.pipe = proc, parent
    pub.registry.write_text("owned synthetic process")
    if failure == "eof":
        child.close()
    try:
        with pytest.raises(Closed, match="MEDIA_DELIVERY_FAILED"):
            await pub.call({"op": "permit"}, timeout=0.01)
        assert proc.poll() is not None and parent.closed
        assert pub.process is None and pub.pipe is None
    finally:
        child.close()
        await pub.abort()


@pytest.mark.asyncio
async def test_child_registry_fsync_failure_cannot_leave_publisher(
    tmp_path, monkeypatch
):
    import os

    pub = Publisher(tmp_path)

    def broken(*a):
        raise OSError("injected registry fsync failure")

    monkeypatch.setattr(os, "fsync", broken)
    with pytest.raises(OSError):
        await pub.start({"identity": {}})
    assert pub.process is None and pub.pipe is None
    assert not pub.registry.exists()
