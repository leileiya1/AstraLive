"""Dedicated loopback SQL/RTMP negatives; original range verifier unchanged."""

import asyncio
import copy

import pytest

from output_guardian import service
from output_guardian.model import Closed
from output_guardian.tests.test_guardian import synthetic


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["audio", "video"])
async def test_real_last_packet_missing_never_drains(rig, monkeypatch, missing):
    await rig.activate()
    renewal = asyncio.create_task(rig.renew_forever())
    verify = service.verify_combined
    checks = []

    def missing_tail(paths, observed, manifest):
        observed = copy.deepcopy(observed)
        if observed.get("manifest", {}).get(missing):
            observed["manifest"][missing].pop()
        try:
            return verify(paths, observed, manifest)
        except Closed as exc:
            checks.append(exc.code)
            raise

    monkeypatch.setattr(service, "verify_combined", missing_tail)
    try:
        # Same full64000-sample/100-frame input as the original acceptance:
        # the earlier30-frame test never reached ingest/observer readiness.
        await synthetic(rig, count=100)
        with pytest.raises(Closed, match="DRAIN_UNKNOWN"):
            await rig.guardian.finish(rig.attempt)
        assert checks and rig.guardian.last_drain_result["coverage"] == "PENDING"
        assert rig.guardian.right is None and rig.guardian.publisher.process is None
    finally:
        print(
            "NEGATIVE_BOUNDARY_DIAGNOSTIC",
            rig.guardian.last_drain_result,
            getattr(rig.guardian, "last_drain_stats", None),
            "authority",
            rig.guardian.last_fault,
            "observerStarted",
            rig.guardian.observer_started,
        )
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["stop", "terminal", "expiry", "crash"])
async def test_real_proven_ranges_never_override_lifecycle(rig, monkeypatch, boundary):
    await rig.activate()
    g = rig.guardian
    renewal = asyncio.create_task(rig.renew_forever())
    verified, paused, release, revoked = (asyncio.Event() for _ in range(4))
    loop = asyncio.get_running_loop()
    verify = service.verify_combined

    def verification(*args):
        proof = verify(*args)
        if boundary == "crash":
            # Only the exact Popen owned by this dedicated test rig is killed.
            g.publisher.process.kill()
            g.publisher.process.wait(timeout=1)
        loop.call_soon_threadsafe(verified.set)
        return proof

    monkeypatch.setattr(service, "verify_combined", verification)
    abort = g.publisher.abort

    async def pause_abort(*a, **kw):
        result = await abort(*a, **kw)
        if verified.is_set() and not paused.is_set() and boundary != "crash":
            paused.set()
            await release.wait()
        return result

    monkeypatch.setattr(g.publisher, "abort", pause_abort)
    invalidate = g.invalidate

    def invalidated(*a, **kw):
        invalidate(*a, **kw)
        revoked.set()

    monkeypatch.setattr(g, "invalidate", invalidated)
    finish = late = stopping = None
    try:
        # Same full64000-sample/100-frame input as the original acceptance:
        # the earlier30-frame test never reached ingest/observer readiness.
        await synthetic(rig, count=100)
        if boundary in {"stop", "terminal"}:
            target = await rig.permit()
            committed, sql_release = asyncio.Event(), asyncio.Event()
            original = g.authority.permit

            async def delayed(attempt, permit):
                right = await original(attempt, permit)
                if permit == target:
                    committed.set()
                    await sql_release.wait()  # actual query already completed
                return right

            monkeypatch.setattr(g.authority, "permit", delayed)
            late = asyncio.create_task(g.renew(rig.attempt, target))
            await committed.wait()
        finish = asyncio.create_task(g.finish(rig.attempt))
        if boundary == "crash":
            with pytest.raises(Closed, match="DRAIN_UNKNOWN"):
                await finish
            assert g.last_drain_result["coverage"] == "PASS"
            assert g.last_drain_result["fault"] == "MEDIA_DELIVERY_FAILED"
            return
        await asyncio.wait_for(paused.wait(), 0.8)
        assert g.last_drain_result["coverage"] == "PASS"
        if boundary == "stop":
            stopping = asyncio.create_task(g.stop("run"))
            await revoked.wait()
            assert "run" in g.stopped
        elif boundary == "expiry":
            # Renew admission already closed after proof. Wait on the real
            # watchdog event at the original Right's actual deadline.
            await asyncio.wait_for(revoked.wait(), 1.1)
            assert g.last_fault == "LEASE_LOST" and g.right is None
        if late:
            sql_release.set()
            with pytest.raises(
                Closed,
                match="STATE_CONFLICT" if boundary == "terminal" else "LEASE_LOST",
            ):
                await late
        release.set()
        if boundary == "terminal":
            assert (await finish)["state"] == "LOCAL_MEDIA_DRAINED"
        else:
            with pytest.raises(Closed, match="DRAIN_UNKNOWN"):
                await finish
        if stopping:
            await stopping
        assert g.publisher.process is None
    finally:
        release.set()
        if late:
            sql_release.set()
        renewal.cancel()
        await asyncio.gather(
            renewal, *[t for t in (finish, late, stopping) if t], return_exceptions=True
        )
