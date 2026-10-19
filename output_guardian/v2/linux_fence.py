"""Read-only cgroup-v2 scope checks; exclusive mutation boundary is unavailable.

No namespaces are entered and no existing cgroup is adopted. Only direct
supervisor-owned native children may be attached to a fresh delegated cgroup.
No cgroup.kill/procs write or removal is authorized by this implementation.
A future kernel populated=0 proof would still not revoke output keys or peers.
"""

import ctypes
import os
import stat
import sys
import threading
import uuid
from pathlib import Path

import psutil

from runtime.app.receiver1.transport import ProcessIdentity, identity

from .gate import require


def _cgroup2(path):
    require(sys.platform.startswith("linux"), "OUTPUT_FENCE_UNPROVEN")
    # Verify the actual kernel filesystem, not files named cgroup.kill/events
    # in an ordinary directory supplied by a caller.
    data = ctypes.create_string_buffer(256)
    libc = ctypes.CDLL(None, use_errno=True)
    require(libc.statfs(os.fsencode(path), ctypes.byref(data)) == 0)
    require(
        ctypes.c_long.from_buffer(data).value == 0x63677270, "OUTPUT_FENCE_UNPROVEN"
    )


class OwnedCgroup:
    """Fresh native scope census; destructive mutation is currently UNAVAILABLE.

    Mode0700 and cgroup.max.descendants=0 are not exclusive control: same-UID
    children, inherited writable FDs, privileged writers and lifecycle changes
    can invalidate them. No implemented host controller proves their exclusion.
    Consequently no path here writes cgroup.kill/procs or removes a group. A
    local lock serializes our lifecycle only; it does not lock kernel topology.
    Unknown/failed operations retire this handle, never automatically adopt or
    retry it after a process exit. Independent isolation/reconciliation is needed.
    """

    def __init__(self, delegated_parent):
        require(sys.platform.startswith("linux"), "OUTPUT_FENCE_UNPROVEN")
        parent = Path(delegated_parent)
        _cgroup2(parent)
        st = parent.lstat()
        require(
            stat.S_ISDIR(st.st_mode)
            and st.st_uid == os.geteuid()
            and not st.st_mode & 0o022
        )
        require((parent / "cgroup.controllers").is_file(), "OUTPUT_FENCE_UNPROVEN")
        # No controller currently excludes same-UID/privileged/inherited-FD
        # writers. Do not even create an unmanageable group that close() could
        # not safely reclaim. No existing group is accepted or adopted.
        self.path = parent / ("guardian-" + uuid.uuid4().hex)
        self.members, self.retired = {}, False
        self._lock = threading.RLock()
        self.retired = True
        self._exclusive_mutation()

    def _owned(self):
        """Read-only scope checks; success is NOT a mutation authorization."""
        _cgroup2(self.path)
        st = self.path.lstat()
        require(
            stat.S_ISDIR(st.st_mode)
            and st.st_ino == self.inode
            and st.st_dev == getattr(self, "device", st.st_dev)
            and st.st_uid == os.geteuid(),
            "OUTPUT_FENCE_UNPROVEN",
        )
        require(not st.st_mode & 0o077, "OUTPUT_FENCE_UNPROVEN")
        for name in ("cgroup.procs", "cgroup.kill", "cgroup.events"):
            entry = (self.path / name).lstat()
            require(
                stat.S_ISREG(entry.st_mode)
                and entry.st_uid == os.geteuid()
                and not entry.st_mode & 0o022,
                "OUTPUT_FENCE_UNPROVEN",
            )
        # A snapshot detects known bad scope; it never proves the absence of a
        # concurrent creator. Any directory/symlink/unknown interface refuses.
        for entry in self.path.iterdir():
            kind = entry.lstat().st_mode
            require(stat.S_ISREG(kind), "OUTPUT_FENCE_UNPROVEN")

    def _members(self):
        members = [int(p) for p in (self.path / "cgroup.procs").read_text().split()]
        for pid in members:
            require(pid in self.members, "OUTPUT_FENCE_UNPROVEN")
            native = self.members[pid]
            require(
                identity(pid) == native
                and native.uid == os.geteuid()
                and psutil.Process(pid).ppid() == os.getpid(),
                "OUTPUT_FENCE_UNPROVEN",
            )
        return members

    def _exclusive_mutation(self):
        # No bool, callback, chmod, recursive PID snapshot, flock or local lock
        # can supply a missing trusted kernel/host ownership boundary. Even an
        # empty, identity-matched leaf must refuse BEFORE ANY mutation. A future
        # positive implementation requires separate review and Linux evidence.
        require(False, "OUTPUT_FENCE_UNPROVEN")

    def attach(self, native):
        with getattr(self, "_lock", threading.RLock()):
            try:
                require(isinstance(native, ProcessIdentity) and not self.retired)
                self._owned()
                require(
                    identity(native.pid) == native
                    and psutil.Process(native.pid).ppid() == os.getpid()
                    and native.uid == os.geteuid()
                    and native.pid != os.getpid(),
                    "UNAUTHENTICATED",
                )
                self._members()
                self._owned()
                self._exclusive_mutation()  # no cgroup.procs write on refusal
            finally:
                self.retired = True

    def fence(self, timeout=0.250):
        require(0 < timeout <= 1)
        with getattr(self, "_lock", threading.RLock()):
            try:
                require(not self.retired, "OUTPUT_FENCE_UNPROVEN")
                self._owned()
                self._members()
                self._owned()  # detects changes; not a TOCTOU solution
                self._exclusive_mutation()  # no cgroup.kill write exists
            finally:
                self.retired = True
        # No positive fence receipt. Kernel populated=0 would still be required
        # AFTER an independently authorized kill; a pre-kill snapshot is not it.

    def close(self):
        with getattr(self, "_lock", threading.RLock()):
            try:
                self._owned()
                require(not self._members(), "OUTPUT_FENCE_UNPROVEN")
                events = dict(
                    line.split()
                    for line in (self.path / "cgroup.events").read_text().splitlines()
                )
                require(events.get("populated") == "0", "OUTPUT_FENCE_UNPROVEN")
                self._owned()
                self._exclusive_mutation()  # no path-based rmdir on refusal
            finally:
                self.retired = True


def runtime_namespace_census(
    runtime, guardian, *, control_directory, secret_directories
):
    """Actual read-only Linux kernel census; NOT a complete installation proof.

    An approved close-fds/mount/proxy launcher and target/key/socket isolation
    still have to be independently proved. This cannot enable a PhysicalSource.
    """
    require(sys.platform.startswith("linux"), "OUTPUT_FENCE_UNPROVEN")
    require(identity(runtime.pid) == runtime and identity(guardian.pid) == guardian)
    require(runtime.uid != 0 and runtime.uid != guardian.uid)
    status = dict(
        line.split(":", 1)
        for line in Path(f"/proc/{runtime.pid}/status").read_text().splitlines()
        if ":" in line
    )
    require(
        all(
            int(status[k].strip(), 16) == 0
            for k in ("CapEff", "CapPrm", "CapInh", "CapAmb")
        )
    )
    require(status["NoNewPrivs"].strip() == "1")
    groups = {int(v) for v in status["Groups"].split()}
    net = Path(f"/proc/{runtime.pid}/ns/net").stat().st_ino
    require(net != Path(f"/proc/{guardian.pid}/ns/net").stat().st_ino)
    require(
        Path(f"/proc/{runtime.pid}/ns/mnt").stat().st_ino
        != Path(f"/proc/{guardian.pid}/ns/mnt").stat().st_ino
    )
    interfaces = {
        line.split(":", 1)[0].strip()
        for line in Path(f"/proc/{runtime.pid}/net/dev").read_text().splitlines()
        if ":" in line
    }
    require(interfaces == {"lo"})
    control = Path(control_directory).lstat()
    require(
        stat.S_ISDIR(control.st_mode)
        and control.st_uid == guardian.uid
        and not control.st_mode & 0o007
    )
    require(
        control.st_gid not in groups
        and control.st_gid != psutil.Process(runtime.pid).gids().real
    )
    require(bool(secret_directories))
    for directory in secret_directories:
        st = Path(directory).lstat()
        require(
            stat.S_ISDIR(st.st_mode)
            and st.st_uid == guardian.uid
            and not st.st_mode & 0o077
        )
    require(identity(runtime.pid) == runtime and identity(guardian.pid) == guardian)
    return {
        "runtimeNetNamespace": net,
        "interfaces": sorted(interfaces),
        "scope": "KERNEL_NAMESPACE_AND_MODE_CENSUS_ONLY",
    }
