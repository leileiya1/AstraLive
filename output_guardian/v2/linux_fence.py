"""Concrete cgroup-v2 owned-process fencing building block, Linux execution pending.

No namespaces are entered and no existing cgroup is adopted. Only direct
supervisor-owned native children may be attached to a fresh delegated cgroup.
Kernel cgroup.kill + populated=0 is process fencing, NOT output key revocation
or complete network/RTMP/WebRTC installation proof.
"""

import ctypes
import os
import stat
import sys
import time
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
        path = parent / ("guardian-" + uuid.uuid4().hex)
        path.mkdir(mode=0o700)  # never adopt a user-supplied/live cgroup
        self.path, self.inode = path, path.stat().st_ino
        self.members, self.retired = {}, False

    def _owned(self):
        _cgroup2(self.path)
        st = self.path.lstat()
        require(
            stat.S_ISDIR(st.st_mode)
            and st.st_ino == self.inode
            and st.st_uid == os.geteuid()
        )
        require(not st.st_mode & 0o022 and (self.path / "cgroup.kill").is_file())

    def attach(self, native):
        require(isinstance(native, ProcessIdentity) and not self.retired)
        self._owned()
        require(
            identity(native.pid) == native
            and psutil.Process(native.pid).ppid() == os.getpid(),
            "UNAUTHENTICATED",
        )
        require(
            native.uid == os.geteuid() and native.pid != os.getpid(), "UNAUTHENTICATED"
        )
        (self.path / "cgroup.procs").write_text(str(native.pid))
        require(identity(native.pid) == native)
        self.members[native.pid] = native

    def fence(self, timeout=0.250):
        require(0 < timeout <= 1)
        self._owned()
        # Unknown members/descendants demand reconciliation. Never kill an
        # untracked PID merely because a caller claims this is its cgroup.
        members = [int(p) for p in (self.path / "cgroup.procs").read_text().split()]
        for pid in members:
            require(
                pid in self.members and identity(pid) == self.members[pid],
                "OUTPUT_FENCE_UNPROVEN",
            )
        self.retired = True
        (self.path / "cgroup.kill").write_text("1")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._owned()
            events = dict(
                line.split()
                for line in (self.path / "cgroup.events").read_text().splitlines()
            )
            if events.get("populated") == "0":
                return {
                    "kernelCgroup": str(self.path),
                    "inode": self.inode,
                    "populated": 0,
                    "scope": "OWNED_PROCESS_FENCE_ONLY",
                }
            time.sleep(0.005)  # external control operation, never an admission gate
        require(False, "OUTPUT_FENCE_UNPROVEN")

    def close(self):
        self._owned()
        require(not (self.path / "cgroup.procs").read_text().strip())
        self.path.rmdir()


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
