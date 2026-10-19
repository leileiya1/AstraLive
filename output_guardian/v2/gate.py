"""Short local admission gate and revocable cross-process output edges.

Only bounded memory operations and nonblocking socket acceptance belong inside
the gate. Encoding, decoding, fsync, Authority/Observer and readiness waits do not.
Internal dataclasses below are NOT receiver wire DTOs or capabilities from JSON.
"""

import hashlib
import math
import multiprocessing
import os
import time
from collections import deque
from dataclasses import dataclass

from output_guardian.model import Closed

from .clocks import suspend_clock as clock


def require(condition, code="CONSUMPTION_UNKNOWN"):
    if not condition:
        raise Closed(code)


@dataclass(frozen=True)
class Budget:
    mono: float
    suspend: float

    @classmethod
    def received(cls, timing, sent, *, grant=False):
        require(timing["safetyMarginMs"] == 100, "LEASE_LOST")
        ms = (
            min(timing["remainingProofMs"], timing["remainingGrantMs"])
            if grant
            else timing["remainingProofMs"]
        )
        require(type(ms) is int and 100 < ms <= 1000, "LEASE_LOST")
        result = cls(sent[0] + ms / 1000 - 0.100, sent[1] + ms / 1000 - 0.100)
        result.check()
        return result

    def check(self):
        require(math.isfinite(self.mono) and math.isfinite(self.suspend), "LEASE_LOST")
        require(time.monotonic() < self.mono and clock() < self.suspend, "LEASE_LOST")

    def remaining(self):
        return max(
            0, int(min(self.mono - time.monotonic(), self.suspend - clock()) * 1000)
        )


def sent_now():
    return time.monotonic(), clock()


class ShortLock:
    """Bounded shared mutex: a SIGKILL owner cannot deadlock admission forever.

    Multiprocessing RLock is not robust. Contention beyond this safety bound
    irreversibly poisons the incarnation; callers must kill/reconcile outputs.
    The bound is a fail-closed resource limit, not a Stop latency SLA.
    """

    def __init__(self, ctx):
        self.mutex, self.broken = ctx.RLock(), ctx.RawValue("b", 0)

    def __enter__(self):
        require(not self.broken.value, "OUTPUT_FENCE_UNPROVEN")
        if not self.mutex.acquire(timeout=0.025):
            self.broken.value = 1
            raise Closed("OUTPUT_FENCE_UNPROVEN")
        if self.broken.value:
            self.mutex.release()
            raise Closed("OUTPUT_FENCE_UNPROVEN")
        return self

    def __exit__(self, *_):
        self.mutex.release()


@dataclass(frozen=True)
class Lineage:
    """Captured at submission, including complete canonical trusted identity.

    The opaque identity includes parent registration AND immutable consumption,
    so tenant/owner/Room/Run/epoch/Session/producer/Attempt/utterance/Generation,
    output binding, process/channel, Artifact and execution cannot be relabelled.
    """

    run_id: str
    execution_id: str
    artifact_id: str
    artifact_hash: str
    identity: bytes
    revision: int

    @property
    def tag(self):
        return hashlib.sha256(self.identity + self.revision.to_bytes(8, "big")).digest()


class Boundary:
    """Shared with *owned* CPU children, never mapped into Runtime.

    Use a fresh boundary per Guardian incarnation. A dead parent or expired
    proof revokes outputs even if the Guardian cannot run cleanup. A child
    holding this lock across a blocking operation violates this interface.
    """

    def __init__(self, context=None):
        ctx = context or multiprocessing.get_context("spawn")
        self.lock = ShortLock(ctx)
        self.tag = ctx.RawArray("B", 32)
        self.deadlines = ctx.RawArray("d", 2)
        self.parent_pid = os.getpid()

    def arm_locked(self, lineage, budget):
        budget.check()
        self.tag[:] = lineage.tag
        self.deadlines[:] = [budget.mono, budget.suspend]

    def close_locked(self):
        self.tag[:] = bytes(32)
        self.deadlines[:] = [0, 0]

    def check_locked(self, lineage):
        require(bytes(self.tag) == lineage.tag, "STALE_EXECUTION")
        Budget(*self.deadlines).check()
        # In the parent, os.getppid() is unrelated; child has no fallback owner.
        require(os.getpid() == self.parent_pid or os.getppid() == self.parent_pid)

    def check(self, lineage):
        with self.lock:
            self.check_locked(lineage)


class Gate:
    def __init__(self, stops=(), denied=(), boundary=None, capacity=8):
        self.edge = boundary or Boundary()
        self.lock = self.edge.lock
        self.state, self.revision = "FENCED", 0
        self.run_id, self.registration, self.active = None, None, None
        self.stops, self.denied = set(stops), set(denied)
        self.sequence, self.audio_end, self.video_end = -1, 0, -1
        self.video_frames = 0
        self.accepted = deque(maxlen=128)  # metadata only
        self.media, self.acks = deque(), deque()
        self.capacity = capacity
        self.poisoned = False

    def capture_locked(self):
        return self.revision, self.registration, self.active

    def compare_locked(self, captured):
        require(captured == self.capture_locked())
        require(not self.poisoned and self.run_id not in self.stops)

    def stage_locked(self, run_id, registration):
        require(not self.poisoned, "OUTPUT_FENCE_UNPROVEN")
        require(run_id not in self.stops, "RUN_STOPPED")
        require(
            self.state in {"FENCED", "STAGED_CLOSED"} and self.active is None,
            "ACTIVE_UNIT_CONFLICT",
        )
        require(
            self.registration is None or self.registration == registration,
            "STATE_CONFLICT",
        )
        self.edge.close_locked()
        self.revision += 1
        self.run_id, self.registration, self.state = (
            run_id,
            registration,
            "STAGED_CLOSED",
        )

    def execution_locked(self, lineage):
        require(
            self.state == "ACTIVE_UNIT" and self.active == lineage, "STALE_EXECUTION"
        )
        require(not self.poisoned and self.run_id not in self.stops, "RUN_STOPPED")
        self.edge.check_locked(lineage)

    def stop_locked(self, run_id):
        self.stops.add(run_id)
        if self.run_id != run_id:
            return False
        self.revision += 1
        self.state, self.active = "CLOSING", None
        self.edge.close_locked()
        self.media.clear()
        self.acks.clear()
        self.accepted.append(("STOP", self.revision, run_id))
        return True

    def unknown_locked(self):
        self.revision += 1
        self.state, self.active, self.poisoned = "UNKNOWN", None, True
        self.edge.close_locked()
        self.media.clear()
        self.acks.clear()

    def finish_locked(self, lineage):
        self.execution_locked(lineage)
        self.edge.close_locked()
        self.revision += 1
        self.active, self.state = None, "STAGED_CLOSED"
        self.accepted.append(("FINISH", self.revision, lineage.execution_id))
        # Session ordinal, PCM samples, PTS and owned publisher stay intact.
