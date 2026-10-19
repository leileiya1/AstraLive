"""Inert ordinary-file adversaries. NEVER real cgroups, PIDs or process signals.

Only filesystem recognition is stubbed for scope models. Matching ownership
uses real dedicated CPU children and native PID/birth/UID/parent checks; children
exit via stdin EOF, never a signal. A valid census is not mutation authority.
"""

import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from output_guardian.model import Closed
from output_guardian.v2 import linux_fence as lf
from runtime.app.receiver1.transport import ProcessIdentity


@pytest.fixture(params=range(3), ids=lambda n: f"repeat-{n}")
def model(tmp_path, monkeypatch, request):
    path = tmp_path / "leaf"
    path.mkdir(mode=0o700)
    for name, text in {
        "cgroup.procs": "",
        "cgroup.kill": "",
        "cgroup.events": "populated 0\n",
        "cgroup.max.descendants": "0\n",
    }.items():
        p = path / name
        p.write_text(text)
        p.chmod(0o600)
    group = lf.OwnedCgroup.__new__(lf.OwnedCgroup)
    group.path, group.inode, group.device = path, path.stat().st_ino, path.stat().st_dev
    group.members, group.retired, group._lock = {}, False, threading.RLock()
    monkeypatch.setattr(lf, "_cgroup2", lambda p: None)
    writes, write_text, rmdir = [], Path.write_text, Path.rmdir

    def write(p, *args, **kw):
        if p in (path / "cgroup.kill", path / "cgroup.procs"):
            writes.append(str(p))
        return write_text(p, *args, **kw)

    def remove(p, *args, **kw):
        if p == path:
            writes.append("rmdir")
        return rmdir(p, *args, **kw)

    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(Path, "rmdir", remove)
    children = []
    yield SimpleNamespace(
        group=group, path=path, writes=writes, raw_write=write_text, children=children
    )
    for child in children:
        child.stdin.close()  # natural exit, no kill/terminate/signal
        child.wait(timeout=2)


def unchanged(m, before=""):
    assert (m.path / "cgroup.kill").read_bytes() == b""
    assert (m.path / "cgroup.procs").read_text() == before
    assert not m.writes


def nested(m):
    child = m.path / "unknown"
    child.mkdir(mode=0o700)
    (child / "cgroup.procs").write_text("999998\n")


def registered(m):
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.buffer.read(1)"],
        stdin=subprocess.PIPE,
    )
    m.children.append(child)
    native = lf.identity(child.pid)
    m.group.members[native.pid] = native
    m.raw_write(m.path / "cgroup.procs", f"{native.pid}\n")
    return native


def test_A_parent_empty_unknown_subgroup_denied_before_kill(model):
    nested(model)
    with pytest.raises(Closed):
        model.group.fence()
    unchanged(model)


def test_B_subgroup_injected_after_parent_members_read(model, monkeypatch):
    original = Path.read_text
    injected = []

    def read(path, *a, **kw):
        value = original(path, *a, **kw)
        if path == model.path / "cgroup.procs" and not injected:
            nested(model)
            injected.append(True)
        return value

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(Closed):
        model.group.fence()
    assert injected
    unchanged(model)


def test_C_unknown_direct_pid_denied_before_kill(model):
    model.raw_write(model.path / "cgroup.procs", "999998\n")
    with pytest.raises(Closed):
        model.group.fence()
    unchanged(model, "999998\n")


def test_D_matching_owned_leaf_is_census_not_mutation_authority(model, monkeypatch):
    native = registered(model)
    model.group._owned()
    assert model.group._members() == [native.pid]
    with pytest.raises(Closed, match="OUTPUT_FENCE_UNPROVEN"):
        model.group.fence()
    unchanged(model, f"{native.pid}\n")


def test_E_reused_pid_identity_denied(model, monkeypatch):
    native = registered(model)
    # Corrupt the recorded birth; the actual native identity remains untouched.
    model.group.members[native.pid] = ProcessIdentity(
        native.pid, native.uid, "old-birth"
    )
    with pytest.raises(Closed):
        model.group.fence()
    unchanged(model, f"{native.pid}\n")


@pytest.mark.parametrize(
    "change", ["inode", "device", "uid", "permissions", "symlink", "replacement"]
)
def test_F_native_scope_changed(model, monkeypatch, change):
    group = model.group
    if change == "inode":
        group.inode += 1
    elif change == "device":
        group.device += 1
    elif change == "uid":
        monkeypatch.setattr(lf.os, "geteuid", lambda: model.path.stat().st_uid + 1)
    elif change == "permissions":
        model.path.chmod(0o750)
    elif change == "symlink":
        original = model.path.with_name("replaced")
        model.path.rename(original)
        model.path.symlink_to(original, target_is_directory=True)
    else:
        model.path.rename(model.path.with_name("replaced"))
        model.path.mkdir(mode=0o700)
        for name, value in {
            "cgroup.kill": "",
            "cgroup.procs": "",
            "cgroup.events": "populated 0\n",
        }.items():
            model.raw_write(model.path / name, value)
    with pytest.raises(Closed):
        group.fence()
    unchanged(model)


@pytest.mark.parametrize("mode", [0o666, 0o620, 0o600])
def test_G_writable_members_or_same_uid_writer_is_not_exclusive(model, mode):
    (model.path / "cgroup.procs").chmod(mode)
    # Even0600/0700 plus max.descendants=0 cannot exclude same-UID or inherited
    # FD writers. Never treat the nominally safe mode as a positive guard.
    with pytest.raises(Closed):
        model.group.fence()
    unchanged(model)


def test_H_control_lost_after_last_snapshot_still_no_write(model, monkeypatch):
    original = model.group._exclusive_mutation
    reached = []

    def lose_control():
        reached.append(True)
        nested(model)
        (model.path / "cgroup.procs").chmod(0o666)
        original()

    monkeypatch.setattr(model.group, "_exclusive_mutation", lose_control)
    with pytest.raises(Closed):
        model.group.fence()
    assert reached
    unchanged(model)


def test_H_concurrent_lifecycle_never_authorizes(model):
    errors = []

    def call(op):
        try:
            op()
        except Closed:
            errors.append(True)

    threads = [
        threading.Thread(target=call, args=(op,))
        for op in (model.group.fence, model.group.close, model.group.fence)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(1)
        assert not thread.is_alive()
    assert len(errors) == 3 and model.group.retired
    unchanged(model)


def test_J_stop_repeat_partial_failure_and_exit_never_reauthorize(model, monkeypatch):
    native = registered(model)
    with pytest.raises(Closed):
        model.group.attach(native)
    assert model.group.retired
    model.children[0].stdin.close()
    model.children[0].wait(timeout=2)
    model.children.clear()
    # Natural process exit cannot authorize retry/adoption of the failed handle.
    model.raw_write(model.path / "cgroup.procs", "")
    for op in (model.group.fence, model.group.close, model.group.fence):
        with pytest.raises(Closed):
            op()
    unchanged(model)


def test_J_unreadable_scope_denies_without_retry(model, monkeypatch):
    original = Path.read_text

    def denied(path, *a, **kw):
        if path == model.path / "cgroup.procs":
            raise PermissionError("inert injected read failure")
        return original(path, *a, **kw)

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(PermissionError):
        model.group.fence()
    assert model.group.retired and not model.writes
    monkeypatch.setattr(Path, "read_text", original)
    with pytest.raises(Closed):
        model.group.fence()
    unchanged(model)


def test_I_fake_kernel_files_never_actual_kernel_evidence(tmp_path):
    # No filesystem stub here, no real cgroup operations on any platform.
    for name in ("cgroup.procs", "cgroup.kill", "cgroup.events"):
        (tmp_path / name).write_text("")
    with pytest.raises(Closed):
        lf._cgroup2(tmp_path)
    assert (tmp_path / "cgroup.kill").read_bytes() == b""


def test_constructor_cannot_allocate_unmanageable_group(tmp_path, monkeypatch):
    # Inert parent only. Constructor refuses even after its filesystem probe
    # would pass; no new cgroup, adoption, or cleanup obligation is created.
    tmp_path.chmod(0o700)
    (tmp_path / "cgroup.controllers").write_text("cpu")
    monkeypatch.setattr(lf.sys, "platform", "linux")
    monkeypatch.setattr(lf, "_cgroup2", lambda p: None)
    with pytest.raises(Closed, match="OUTPUT_FENCE_UNPROVEN"):
        lf.OwnedCgroup(tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {"cgroup.controllers"}
