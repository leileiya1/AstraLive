"""SIGKILL only dedicated test children; no workspace service/GPU access."""

import asyncio
import multiprocessing
import os
import signal
import subprocess
import sys
import time

import psutil
import pytest

from output_guardian.model import Closed
from output_guardian.v2.gate import Boundary, Gate
from output_guardian.v2.journal import DenyJournal


def crash_journal(directory, phase, ready):
    journal = DenyJournal(directory)
    journal.append("run", "crashed_run")
    original, calls = os.fsync, 0

    def paused(fd):
        nonlocal calls
        calls += 1
        if phase == "before_file" and calls == 1:
            ready.set()
            signal.pause()
        original(fd)
        if (phase == "after_file" and calls == 1) or (
            phase == "after_directory" and calls == 2
        ):
            ready.set()
            signal.pause()

    os.fsync = paused
    journal.append("consume", "crashed_run", "consumed_grant", "receipt_only")


@pytest.mark.parametrize("phase", ["before_file", "after_file", "after_directory"])
def test_actual_sigkill_fsync_restart_quarantines(phase, tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    process = ctx.Process(
        target=crash_journal, args=(str(tmp_path / "journal"), phase, ready)
    )
    process.start()
    try:
        assert ready.wait(3)
        process.kill()
        process.join(2)
        assert not process.is_alive()
        if phase != "after_directory":
            with pytest.raises(Closed):
                DenyJournal(tmp_path / "journal")
        else:
            recovered = DenyJournal(tmp_path / "journal")
            assert recovered.stops == {"crashed_run"} and recovered.denied == {
                "consumed_grant"
            }
            recovered.close()
    finally:
        if process.is_alive():
            process.kill()
            process.join(2)
        process.close()


def own_lock(edge, ready):
    with edge.lock:
        ready.set()
        signal.pause()


def test_sigkill_inside_shared_commit_cannot_deadlock_new_admission():
    ctx = multiprocessing.get_context("spawn")
    edge, ready = Boundary(ctx), ctx.Event()
    process = ctx.Process(target=own_lock, args=(edge, ready))
    process.start()
    try:
        assert ready.wait(3)
        process.kill()
        process.join(2)
        began = time.monotonic()
        with pytest.raises(Closed, match="OUTPUT_FENCE_UNPROVEN"):
            with edge.lock:
                pass
        assert time.monotonic() - began < 1  # deadlock detector, not SLA
        assert edge.lock.broken.value
        with pytest.raises(Closed):
            with edge.lock:
                pass
    finally:
        if process.is_alive():
            process.kill()
            process.join(2)
        process.close()


def guardian_with_cpu(directory, ready, child_pid):
    # Test-owned Guardian process only, starts CLOSED and receives no production
    # credentials. Grandchild must exit on SIGKILL without parent cleanup code.
    from output_guardian.v2.cpu import CPUMedia

    async def run():
        cpu = CPUMedia(Gate(), directory, {"cpu"})
        await cpu.start()
        child_pid.value = cpu.process.pid
        ready.set()
        await asyncio.Event().wait()

    asyncio.run(run())


@pytest.mark.asyncio
async def test_guardian_sigkill_owned_child_exits_and_recovery_closes(tmp_path):
    from output_guardian.v2.cpu import CPUMedia

    ctx = multiprocessing.get_context("spawn")
    ready, child_pid = ctx.Event(), ctx.RawValue("i", 0)
    process = ctx.Process(
        target=guardian_with_cpu, args=(str(tmp_path / "child"), ready, child_pid)
    )
    process.start()
    try:
        assert await asyncio.to_thread(ready.wait, 3)
        pid = child_pid.value
        process.kill()
        await asyncio.to_thread(process.join, 2)
        for _ in range(100):
            if (
                not psutil.pid_exists(pid)
                or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
            ):
                break
            await asyncio.sleep(0.01)
        assert (
            not psutil.pid_exists(pid)
            or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
        )
        # New incarnation never inherits an active tag, permit or child.
        replacement = CPUMedia(Gate(), tmp_path / "child", {"cpu"})
        await replacement.start()
        try:
            assert replacement.gate.state == "FENCED" and not any(replacement.edge.tag)
            assert replacement.process.pid != pid
        finally:
            assert await replacement.close()
    finally:
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 2)
        process.close()


def test_separate_process_room_state_lock(tmp_path):
    journal = DenyJournal(tmp_path / "room")
    script = """import sys
from output_guardian.v2.journal import DenyJournal
from output_guardian.model import Closed
try: DenyJournal(sys.argv[1])
except Closed: raise SystemExit(0)
raise SystemExit(1)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / "room")],
            capture_output=True,
            timeout=3,
        )
        assert result.returncode == 0
    finally:
        journal.close()


def test_standalone_entry_cannot_enable_live():
    result = subprocess.run(
        [sys.executable, "-m", "output_guardian.v2"],
        capture_output=True,
        timeout=3,
        env=dict(os.environ, ASTRALIVE_DURABLE_LIVE_ENABLED="true"),
    )
    assert result.returncode == 78 and b"OUTPUT_FENCE_UNPROVEN" in result.stdout
