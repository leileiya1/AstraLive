"""Native CPU installation observations; production exports intentionally deny."""

import asyncio
import os
import subprocess
import sys

import pytest

from output_guardian.model import Closed
from output_guardian.v2.cpu import CPUMedia
from output_guardian.v2.linux_fence import OwnedCgroup, runtime_namespace_census
from output_guardian.v2.physical import CPUInstallationReader, RegistrarPhysicalSource
from runtime.app.receiver1.transport import identity

from .conftest import acknowledge, media, mock_evidence


async def resources(d, binding=None):
    cpu = CPUMedia(
        d.r.gate,
        d.tmp / "installed",
        d.r.required_sinks,
        installed_binding=binding or d.r.staged,
        evidence_builder=mock_evidence,
    )
    d.r.outputs = cpu
    await cpu.start()
    runtime = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    reader = CPUInstallationReader(cpu, identity(runtime.pid), identity(os.getpid()))
    return cpu, runtime, reader


async def cleanup(cpu, runtime):
    assert await cpu.close()
    if runtime.poll() is None:
        runtime.kill()
    runtime.wait(timeout=2)


@pytest.mark.asyncio
async def test_native_generation_installed_closed_before_stage_and_stays_bound(domain):
    d = domain
    cpu, runtime, reader = await resources(d)
    try:
        report = reader.capture_closed(d.r.staged)
        assert report.generation == d.r.staged["generationId"]
        assert report.publisher.pid == cpu.process.pid and not any(cpu.edge.tag)
        assert report.binding_hash == d.r.wire.digest(d.r.staged)
        assert report.origins == (0, -1, 0, -1)
        _, q = await acknowledge(d)
        # Historical closed-install provenance remains current during the same
        # owned active unit; re-reading it must not close the Session publisher.
        assert (
            await reader.read_installed(d.r.staged, reader.runtime, reader.guardian)
            == report
        )
        await media(d, q)
        assert d.r.gate.state == "ACTIVE_UNIT"
        with pytest.raises(Closed, match="OUTPUT_FENCE_UNPROVEN"):
            reader.production_installation()
    finally:
        await cleanup(cpu, runtime)


@pytest.mark.asyncio
async def test_changed_epoch_or_generation_cannot_borrow_native_installation(domain):
    d = domain
    cpu, runtime, reader = await resources(d)
    try:
        report = reader.capture_closed(d.r.staged)
        for key in ("runEpoch", "generationId", "outputBindingVersion"):
            changed = dict(d.r.staged, **{key: d.r.staged[key] + 1})
            with pytest.raises(Closed):
                reader.capture_closed(changed)
        assert reader.record == report
        assert not any(cpu.edge.tag)
    finally:
        await cleanup(cpu, runtime)


@pytest.mark.asyncio
async def test_child_rejects_lineage_from_other_installed_generation(domain):
    d = domain
    changed = dict(d.r.staged, generationId=d.r.staged["generationId"] + 1)
    cpu, runtime, reader = await resources(d, changed)
    try:
        with pytest.raises(Closed):
            reader.capture_closed(d.r.staged)
        # Explicit test bypass of missing physical Registrar proof. Even then,
        # child must reject the wrong installed context at its own real edge.
        _, q = await acknowledge(d)
        await media(d, q)
        for _ in range(100):
            if cpu.fault:
                break
            await asyncio.sleep(0.005)
        assert cpu.fault and all(not rows for rows in cpu.sinks.values())
    finally:
        await cleanup(cpu, runtime)


@pytest.mark.asyncio
async def test_live_retired_publisher_is_not_fencing_evidence(domain):
    d = domain
    cpu, runtime, reader = await resources(d)
    old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        reader.retired = (identity(old.pid),)
        with pytest.raises(Closed):
            reader.capture_closed(d.r.staged)
        old.kill()
        old.wait(timeout=2)
        assert reader.capture_closed(d.r.staged).profile == "CPU_PCM_FFV1_ONLY"
        with pytest.raises(Closed):
            await RegistrarPhysicalSource().observe(
                d.r.staged, reader.runtime, reader.guardian
            )
    finally:
        if old.poll() is None:
            old.kill()
            old.wait(timeout=2)
        await cleanup(cpu, runtime)


def test_non_linux_kernel_claims_always_refused(tmp_path):
    if sys.platform.startswith("linux"):
        pytest.skip("Darwin refusal test; Linux kernel execution has a separate opt-in")
    with pytest.raises(Closed, match="OUTPUT_FENCE_UNPROVEN"):
        OwnedCgroup(tmp_path)
    with pytest.raises(Closed, match="OUTPUT_FENCE_UNPROVEN"):
        runtime_namespace_census(
            identity(os.getpid()),
            identity(os.getpid()),
            control_directory=tmp_path,
            secret_directories=[tmp_path],
        )


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or not os.getenv("AG5_OWNED_CGROUP_PARENT"),
    reason="requires dedicated Linux cgroup-v2 delegation; NOT TESTED on Darwin",
)
def test_linux_real_owned_cgroup_kill():
    group = OwnedCgroup(os.environ["AG5_OWNED_CGROUP_PARENT"])
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        group.attach(identity(child.pid))
        proof = group.fence()
        child.wait(timeout=2)
        assert proof["populated"] == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
        group.close()
