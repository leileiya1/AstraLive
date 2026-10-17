"""Guardian-owned denial journal. No tickets, true responses or recovery rights.

Each immutable record uses temp -> file fsync -> rename -> directory fsync.
Independent immutable files need no serialization behind a Consume fsync. A prior Run
seen by this incarnation is quarantined on restart, even if Stop fsync failed.
No automatic compaction/deletion: disk exhaustion fails closed.
"""

import fcntl
import hashlib
import json
import os
import stat
import uuid
from pathlib import Path

from output_guardian.model import Closed


class DenyJournal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = self.directory.lstat()
        if (
            not stat.S_ISDIR(st.st_mode)
            or st.st_uid != os.geteuid()
            or st.st_mode & 0o077
        ):
            raise Closed()
        self.owner = os.open(
            self.directory / "owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.stops, self.denied = self._load()
        except BaseException:
            os.close(self.owner)
            raise Closed() from None

    def _load(self):
        stops, denied = set(), set()
        for path in self.directory.iterdir():
            if path.name == "owner.lock":
                continue
            # A temp or malformed/truncated record is an unproven crash, not
            # permission to silently discard a possible denial.
            if path.suffix != ".json" or path.is_symlink():
                raise Closed()
            raw = path.read_bytes()
            if len(raw) > 4096:
                raise Closed()
            row = json.loads(raw)
            if set(row) != {"kind", "run", "grant", "receipt"} or row["kind"] not in {
                "run",
                "stop",
                "consume",
            }:
                raise Closed()
            if not all(isinstance(v, str) for v in row.values()):
                raise Closed()
            if path.stem != hashlib.sha256(raw).hexdigest():
                raise Closed()
            # Conservative restart policy: no old Run is automatically staged
            # again; no consumed/ambiguous grant can ever become executable.
            stops.add(row["run"])
            if row["grant"]:
                denied.add(row["grant"])
        return stops, denied

    def append(self, kind, run, grant="", receipt=""):
        row = dict(kind=kind, run=run, grant=grant, receipt=receipt)
        raw = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        if len(raw) > 4096:
            raise Closed()
        target = self.directory / (hashlib.sha256(raw).hexdigest() + ".json")
        temp = self.directory / (uuid.uuid4().hex + ".pending")
        # A failed temp remains evidence. A later start refuses it.
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            raise Closed("CONSUMPTION_UNKNOWN") from None

    def close(self):
        if self.owner is not None:
            os.close(self.owner)
            self.owner = None
