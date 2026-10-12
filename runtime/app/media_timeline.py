"""Opt-in audio-master primitives. No SQL authority or audience playback claims.

The controller implements frozen-1 §5. Its journal is supplied by A/C; this
module never upgrades an in-memory observation to a durable acknowledgement.
"""
import asyncio
import copy
from collections import deque
from dataclasses import dataclass, field
from dataclasses import asdict, is_dataclass
from enum import StrEnum
from fractions import Fraction
import os
import hashlib
import json
import weakref
from typing import Protocol

from .providers import AudioChunk, VideoFrame

MAX_EPOCH = 9007199254740991


class FrameDispositions:
    """Bounded observations without retaining RGB or trusting reused object IDs."""
    def __init__(self, limit=128):
        self.limit = limit
        self.entries = {}

    def record(self, frame, state):
        key = id(frame)
        self.entries.pop(key, None)
        self.entries[key] = (weakref.ref(frame), state)
        while len(self.entries) > self.limit:
            self.entries.pop(next(iter(self.entries)))

    def get(self, frame):
        entry = self.entries.get(id(frame))
        return entry[1] if entry and entry[0]() is frame else None

    def clear(self):
        self.entries.clear()


def positive(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_EPOCH:
        raise ValueError("expected positive exact JSON integer")
    return value


def samples_to_pts(samples: int, sample_rate: int, clock_rate: int) -> int:
    if type(samples) is not int or samples < 0:
        raise ValueError("invalid sample position")
    positive(sample_rate)
    positive(clock_rate)
    return samples * clock_rate // sample_rate


def enabled() -> bool:
    def parse(name):
        value = os.getenv(name)
        if value is None:
            return None
        if value.lower() not in {"true", "false", "1", "0"}:
            raise ValueError(f"invalid {name}")
        return value.lower() in {"true", "1"}
    primary = parse("ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED")
    alias = parse("ASTRALIVE_MEDIA_TIMELINE_ENABLED")
    if primary is not None and alias is not None and primary != alias:
        raise ValueError("conflicting MediaTimeline feature flags")
    return primary if primary is not None else bool(alias)


class Lane(StrEnum):
    NARRATION = "NARRATION"
    AUDIENCE_ANSWER = "AUDIENCE_ANSWER"
    RESUME_BRIDGE = "RESUME_BRIDGE"
    OPERATOR = "OPERATOR"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True)
class MediaIdentity:
    sessionId: str
    runEpoch: int
    timelineEpoch: int
    generationId: int
    segmentId: str
    utteranceId: str
    lane: Lane
    workerEpoch: str | None = None
    workerGenerationId: int | None = None

    def __post_init__(self):
        for value in (self.runEpoch, self.timelineEpoch, self.generationId):
            positive(value)
        if not all(type(v) is str and v for v in
                   (self.sessionId, self.segmentId, self.utteranceId)):
            raise ValueError("missing immutable media identity")
        Lane(self.lane)
        if (self.workerEpoch is None) != (self.workerGenerationId is None):
            raise ValueError("incomplete Worker binding")
        if self.workerGenerationId is not None:
            if type(self.workerGenerationId) is not int or not 0 < self.workerGenerationId < 2**63:
                raise ValueError("invalid Worker wire generation")


@dataclass(frozen=True)
class TimelinePosition:
    sessionId: str
    runEpoch: int
    timelineEpoch: int
    sampleIndex: int
    sampleRate: int

    def __post_init__(self):
        positive(self.runEpoch)
        positive(self.timelineEpoch)
        samples_to_pts(self.sampleIndex, self.sampleRate, 1000000)

    @property
    def ptsUs(self):
        return samples_to_pts(self.sampleIndex, self.sampleRate, 1000000)


@dataclass(frozen=True)
class TimedAudioChunk(AudioChunk):
    identity: MediaIdentity | None = None
    startSample: int = 0
    endSample: int = 0
    timelineRate: int = 16000


@dataclass(frozen=True)
class TimedVideoFrame(VideoFrame):
    identity: MediaIdentity | None = None
    sourceSample: int = 0
    timelineRate: int = 16000


@dataclass(frozen=True)
class BufferPolicy:
    committed_ms: int = 320
    interruptible_ms: int = 800
    speculative_ms: int = 1500
    late_video_ms: int = 150
    max_segments: int = 128

    def __post_init__(self):
        if not (20 <= self.committed_ms <= 500 and
                self.committed_ms <= self.interruptible_ms <= 1500 and
                self.interruptible_ms <= self.speculative_ms <= 2000 and
                0 < self.late_video_ms <= 500 and 1 <= self.max_segments <= 4096):
            raise ValueError("invalid bounded media policy")


@dataclass
class Commit:
    identity: MediaIdentity
    attemptId: str
    descriptor: dict
    start: int
    end: int
    consumed: dict = field(default_factory=dict)
    completed: bool = False
    command: dict = field(default_factory=dict)
    completion_proof: dict | None = None


class TimelineJournal(Protocol):
    async def record(self, operation: str, command: dict, proof: dict) -> dict:
        """A-owned adapter: authenticate/lease/CAS/idempotency and persist proof.

        Return {durable: True, ...}. Test implementations MUST identify themselves
        as test doubles. BEGIN_EPOCH_PREPARED must validate the reservation token;
        BEGIN_EPOCH_ACTIVE must perform the activation CAS.
        """


class MediaTimeline:
    """Volatile eligibility ledger beneath authenticated A/C command authority.

    Methods returning receipts require a journal. Holding the control lock across
    journal calls is deliberate: an interrupted commit never becomes eligible.
    Emergency fencing is synchronous and does not wait for this lock or CUDA.
    """
    def __init__(self, session_id: str, run_epoch: int, sample_rate: int = 16000,
                 journal: TimelineJournal | None = None, policy: BufferPolicy | None = None):
        self.session_id = session_id
        self.run_epoch = positive(run_epoch)
        self.sample_rate = positive(sample_rate)
        self.epoch = 1
        self.revision = 0
        self.committed_end = 0
        self.policy = policy or BufferPolicy()
        self.journal = journal
        self.commits: dict[str, Commit] = {}
        self.sealed = False
        self.blocked = False
        self.suspend_segment: str | None = None
        self.last_completed: str | None = None
        self.lock = asyncio.Lock()
        self.fence_revision = 0
        self.markers = deque(maxlen=128)
        self.sink_fences = []
        self.sink_observers = []
        self.receipts = {}

    def _replay(self, command, operation, arguments):
        positive(command.get("runEpoch"))
        positive(command.get("timelineEpoch"))
        if command.get("sessionId") != self.session_id or command["runEpoch"] != self.run_epoch:
            raise ValueError("STALE_RUN_EPOCH")
        if command.get("commandType") != operation:
            raise ValueError("COMMAND_CONFLICT")
        key = command.get("commandId")
        if not isinstance(key, str) or not key:
            raise ValueError("missing commandId")
        def default(value):
            if is_dataclass(value):
                return asdict(value)
            raise TypeError("noncanonical command argument")
        digest = hashlib.sha256(json.dumps([command, arguments], sort_keys=True, separators=(",", ":"),
                                          default=default).encode()).hexdigest()
        stored = self.receipts.get(key)
        if stored and stored[0] != digest:
            raise ValueError("COMMAND_CONFLICT")
        return key, digest, copy.deepcopy(stored[1]) if stored else None

    def _remember(self, key, digest, receipt):
        self.receipts[key] = (digest, copy.deepcopy(receipt))
        while len(self.receipts) > 128:
            self.receipts.pop(next(iter(self.receipts)))
        return receipt

    def position(self, sample):
        return TimelinePosition(self.session_id, self.run_epoch, self.epoch, sample, self.sample_rate)

    def _command(self, command, expected=None):
        positive(command.get("runEpoch"))
        positive(command.get("timelineEpoch"))
        if self.sealed:
            raise ValueError("RUN_SEALED")
        if command.get("sessionId") != self.session_id or command.get("runEpoch") != self.run_epoch:
            raise ValueError("STALE_RUN_EPOCH")
        if command.get("timelineEpoch") != self.epoch:
            raise ValueError("STALE_TIMELINE_EPOCH")
        if self.blocked:
            raise ValueError("RECOVERY_UNKNOWN")
        if expected is not None and (type(expected) is not int or expected != self.revision):
            raise ValueError("BOUNDARY_CONFLICT")

    def _position(self, p):
        if (p.sessionId, p.runEpoch, p.timelineEpoch, p.sampleRate) != (
                self.session_id, self.run_epoch, self.epoch, self.sample_rate):
            raise ValueError("position clock mismatch")

    async def _record(self, op, command, proof):
        if self.journal is None:
            raise RuntimeError("DEPENDENCY_UNAVAILABLE: A durable journal required")
        result = await self.journal.record(op, command, proof)
        if result.get("durable") is not True:
            raise RuntimeError("RECOVERY_UNKNOWN: non-durable journal ACK")
        return result

    def fence_now(self, reason="STOP"):
        """Authorized caller only; local fence proof, never a durable Stop ACK."""
        self.fence_revision += 1
        self.sealed = True
        self.markers.append({"kind": "cancellation", "reason": reason, "epoch": self.epoch})
        for callback in self.sink_fences:
            callback()

    def eligible(self, identity, start, end):
        if self.sealed or self.blocked or identity is None:
            return False
        commit = self.commits.get(identity.segmentId)
        return bool(commit and identity == commit.identity and
                    identity.timelineEpoch == self.epoch and commit.start <= start <= end <= commit.end)

    async def CommitSegment(self, command, attemptId, generationId, descriptor, startPosition, expectedRevision):
        async with self.lock:
            key, digest, replay = self._replay(command, "COMMIT_SEGMENT", [attemptId, generationId, descriptor, startPosition, expectedRevision])
            if replay:
                return replay
            self._command(command)
            self._position(startPosition)
            positive(generationId)
            descriptor = copy.deepcopy(descriptor)
            if not isinstance(attemptId, str) or not attemptId:
                raise ValueError("invalid attemptId")
            count = positive(descriptor["sampleCount"])
            if descriptor.get("finalMarker") is not True or not descriptor.get("contentHash"):
                raise ValueError("segment is not ready")
            identity = MediaIdentity(self.session_id, self.run_epoch, self.epoch, generationId,
                                     command["segmentId"], descriptor["utteranceId"], Lane(command["lane"]),
                                     descriptor.get("workerEpoch"), descriptor.get("workerGenerationId"))
            previous = self.commits.get(identity.segmentId)
            proposed = Commit(identity, attemptId, descriptor, startPosition.sampleIndex,
                              startPosition.sampleIndex + count)
            proposed.command = copy.deepcopy(command)
            if previous:
                if (previous.identity, previous.attemptId, previous.descriptor, previous.start, previous.end) != (
                        proposed.identity, proposed.attemptId, proposed.descriptor, proposed.start, proposed.end):
                    raise ValueError("SEGMENT_CONFLICT")
                return {"state": "committed", "identity": identity, "revision": self.revision}
            self._command(command, expectedRevision)
            if self.suspend_segment is not None:
                raise ValueError("BOUNDARY_CONFLICT: suspension blocks later commits")
            if len(self.commits) >= self.policy.max_segments:
                retired = next((key for key, c in self.commits.items() if c.completed), None)
                if retired is None:
                    raise ValueError("ledger full; journal and retire completed segments")
                # The append-only durable ledger remains in A. Only a fully
                # journalled local completion may leave this bounded cache.
                del self.commits[retired]
            if proposed.start != self.committed_end:
                raise ValueError("overlap or implicit audio gap")
            fence = self.fence_revision
            await self._record("COMMIT_INTENT", command, {"commit": proposed, "revision": self.revision})
            self._command(command, expectedRevision)
            if fence != self.fence_revision:
                raise ValueError("RUN_SEALED")
            # Install while fenced: COMMIT_INSTALLED must describe an entry
            # already present locally, rather than a future installation intent.
            # Public cursor/revision and eligibility wait for the durable ACK.
            self.blocked = True
            self.commits[identity.segmentId] = proposed
            try:
                await self._record("COMMIT_INSTALLED", command, {"commit": proposed})
                if fence != self.fence_revision or self.sealed:
                    raise ValueError("RUN_SEALED")
                self.committed_end = proposed.end
                self.revision += 1
                self.blocked = False
            except BaseException:
                # Ambiguous journal effect stays fenced pending reconciliation.
                raise
            return self._remember(key, digest, {"state": "committed", "identity": identity, "revision": self.revision})

    async def SuspendAtBoundary(self, command, boundarySegmentId, expectedRevision):
        async with self.lock:
            key, digest, replay = self._replay(command, "SUSPEND_AT_BOUNDARY", [boundarySegmentId, expectedRevision])
            if replay:
                return replay
            self._command(command, expectedRevision)
            commit = self.commits.get(boundarySegmentId)
            if not commit or commit.end != self.committed_end:
                raise ValueError("BOUNDARY_CONFLICT")
            await self._record("SUSPEND_REQUESTED", command, {"segmentId": boundarySegmentId})
            self._command(command, expectedRevision)
            self.suspend_segment = boundarySegmentId
            self.revision += 1
            # Acceptance only. C obtains BOUNDARY_SUSPENDED from SegmentCompleted.
            return self._remember(key, digest, {"state": "accepted", "operationState": "SUSPEND_REQUESTED", "revision": self.revision})

    async def InvalidateAfter(self, command, cutPosition, reason, expectedRevision):
        async with self.lock:
            key, digest, replay = self._replay(command, "INVALIDATE_AFTER", [cutPosition, reason, expectedRevision])
            if replay:
                return replay
            self._command(command, expectedRevision)
            self._position(cutPosition)
            if cutPosition.sampleIndex != self.committed_end:
                raise ValueError("BOUNDARY_CONFLICT: committed prefix cannot be retracted")
            self.blocked = True
            self.fence_revision += 1
            for callback in self.sink_fences:
                callback()
            proof = {"retainedPrefix": cutPosition, "reason": reason,
                     "perSinkProgress": [observe() for observe in self.sink_observers],
                     "residualAudienceBuffers": "unobservable; RTP/decoder/device buffers are not retractable"}
            await self._record("INVALIDATE_AFTER", command, proof)
            self.markers.append({"kind": "cancellation", "epoch": self.epoch, "cut": cutPosition.sampleIndex})
            self.revision += 1
            return self._remember(key, digest, {**proof, "revision": self.revision, "state": "interrupted", "operationState": "FENCED"})

    async def BeginEpoch(self, command, expectedPreviousEpoch, newEpoch, originPosition, reason):
        async with self.lock:
            key, digest, replay = self._replay(command, "BEGIN_EPOCH", [expectedPreviousEpoch, newEpoch, originPosition, reason])
            if replay:
                return replay
            if (self.sealed or command.get("sessionId") != self.session_id or
                    command.get("runEpoch") != self.run_epoch):
                raise ValueError("RUN_SEALED or STALE_RUN_EPOCH")
            positive(newEpoch)
            positive(expectedPreviousEpoch)
            if (expectedPreviousEpoch != self.epoch or newEpoch != self.epoch + 1 or
                    command.get("timelineEpoch") != newEpoch):
                raise ValueError("STALE_TIMELINE_EPOCH")
            self._position(originPosition)
            if originPosition.sampleIndex != self.committed_end:
                raise ValueError("epoch origin must retain committed prefix")
            self.blocked = True
            fence = self.fence_revision
            proof = {"expectedPreviousEpoch": expectedPreviousEpoch, "newEpoch": newEpoch,
                     "originPosition": originPosition, "reason": reason}
            await self._record("BEGIN_EPOCH_PREPARED", command, proof)
            if fence != self.fence_revision or self.sealed:
                raise ValueError("RUN_SEALED")
            self.fence_revision += 1
            for callback in self.sink_fences:
                callback()
            fence = self.fence_revision
            await self._record("BEGIN_EPOCH_ACTIVE", command, proof)
            if fence != self.fence_revision or self.sealed:
                raise ValueError("RUN_SEALED")
            self.epoch = newEpoch
            self.blocked = False
            self.suspend_segment = None
            self.revision += 1
            self.markers.append({"kind": "discontinuity", "epoch": newEpoch, "origin": self.committed_end})
            return self._remember(key, digest, {"state": "committed", "operationState": "ACTIVE", "position": self.position(self.committed_end), "revision": self.revision})

    def CurrentCommittedPTS(self, sessionId, runEpoch):
        if (sessionId, runEpoch) != (self.session_id, self.run_epoch):
            raise ValueError("STALE_RUN_EPOCH")
        return {"activeTimelineEpoch": self.epoch, "committedExclusiveEnd": self.position(self.committed_end),
                "revision": self.revision, "lastSemanticCompletedSegmentId": self.last_completed,
                "perSinkConsumedExclusiveEnd": {key: dict(c.consumed) for key, c in self.commits.items()}}

    def observe_sink_progress(self, identity, sink, media, start, end):
        """Only successful recv/complete pipe writes; dropped ranges never fill holes."""
        commit = self.commits.get(identity.segmentId)
        if not commit or commit.identity != identity or media not in {"audio", "video"}:
            return False
        key = (sink, media)
        cursor = commit.consumed.get(key, commit.start)
        if start != cursor or end <= start or end > commit.end:
            return False
        commit.consumed[key] = end
        return True

    async def SegmentCompleted(self, identity, finalPosition, sinkReceipts):
        async with self.lock:
            commit = self.commits.get(identity.segmentId)
            if not commit or commit.identity != identity or self.sealed:
                raise ValueError("SEGMENT_CONFLICT")
            if (finalPosition.sessionId, finalPosition.runEpoch, finalPosition.timelineEpoch,
                    finalPosition.sampleRate, finalPosition.sampleIndex) != (
                    self.session_id, self.run_epoch, identity.timelineEpoch, self.sample_rate, commit.end):
                raise ValueError("final position mismatch")
            if commit.completed:
                return commit.completion_proof
            required = commit.descriptor.get("requiredSinks", [])
            if not required or any(commit.consumed.get((sink, media)) != commit.end
                                   for sink in required for media in ("audio", "video")):
                raise ValueError("contiguous required-sink proof missing")
            proof = {"identity": identity, "finalPosition": finalPosition, "sinkReceipts": sinkReceipts,
                     "evidenceType": "sink_consumed", "audienceAudible": False}
            await self._record("SEGMENT_COMPLETED", commit.command, proof)
            if self.sealed:
                raise ValueError("RUN_SEALED")
            self.last_completed = identity.segmentId
            commit.completed = True
            if self.suspend_segment == identity.segmentId:
                commit.completion_proof = {**proof, "event": "BOUNDARY_SUSPENDED", "cutPosition": finalPosition}
            else:
                commit.completion_proof = {**proof, "event": "SEGMENT_COMPLETED"}
            return commit.completion_proof


class RationalResampler:
    """Bounded linear PCM conversion with cumulative integer endpoint rounding.

    It holds the final source sample at a chunk edge (<=1 source-sample phase
    error); count mapping is exact even for 44.1kHz and arbitrarily split input.
    """
    def __init__(self, target_rate):
        self.target_rate = positive(target_rate)
        self.source_rate = None
        self.source_count = self.output_count = 0
        self.last = None

    def convert(self, pcm, source_rate):
        import numpy as np
        positive(source_rate)
        if len(pcm) % 2:
            raise ValueError("unaligned PCM")
        if self.source_rate not in (None, source_rate):
            raise ValueError("timestamp discontinuity: sample rate changed without fence")
        self.source_rate = source_rate
        values = np.frombuffer(pcm, dtype="<i2")
        end = self.source_count + len(values)
        output_end = end * self.target_rate // source_rate
        if not len(values):
            return b""
        positions = np.arange(self.output_count, output_end, dtype=np.float64) * source_rate / self.target_rate
        indexes = np.arange(self.source_count, end)
        if self.last is not None:
            indexes = np.concatenate(([self.source_count - 1], indexes))
            values = np.concatenate(([self.last], values))
        result = np.interp(positions, indexes, values).astype("<i2").tobytes()
        self.source_count, self.output_count, self.last = end, output_end, int(values[-1])
        return result


class AudioMasterClock:
    """One clock per peer / encoder connection, never shared across sinks.

    output_samples includes underrun silence, source_sample does not. Video
    ticks wait for the audio clock; content selection uses source_sample.
    """
    def __init__(self, output_rate=48000, source_rate=16000, policy=None):
        self.output_rate = positive(output_rate)
        self.source_rate = positive(source_rate)
        self.policy = policy or BufferPolicy()
        self.output_samples = 0
        self.source_sample = 0
        self.audio_underruns = self.video_late_drops = self.video_holds = 0
        self.changed = asyncio.Event()
        self.timeline: MediaTimeline | None = None

    def advance(self, count, source_end=None):
        self.output_samples += count
        if source_end is None:
            self.audio_underruns += 1
        else:
            self.source_sample = max(self.source_sample, source_end)
        self.changed.set()

    async def wait_video_tick(self, index, fps, active):
        required = index * self.output_rate // fps
        while self.output_samples <= required and active():
            self.changed.clear()
            try:
                await asyncio.wait_for(self.changed.wait(), .1)
            except asyncio.TimeoutError:
                pass

    def accepts(self, item, start, end):
        identity = getattr(item, "identity", None)
        return self.timeline is None or self.timeline.eligible(identity, start, end)

    def video_action(self, sample):
        delta = sample - self.source_sample
        if delta > 0:
            return "wait"
        if delta * 1000 < -self.policy.late_video_ms * self.source_rate:
            return "drop"
        return "display"

    def snapshot(self):
        return {"sourceSample": self.source_sample, "sourceRate": self.source_rate,
                "outputSamples": self.output_samples, "outputRate": self.output_rate,
                "audioUnderruns": self.audio_underruns, "lateVideoDrops": self.video_late_drops,
                "videoHolds": self.video_holds, "evidenceType": "sink_consumed",
                "audienceAudible": False}


class AdaptiveBuffer:
    """Jitter EMA chooses a target within fixed physical queue caps.

    Shrinking a target never truncates audio. Admission waits until occupancy
    falls below it; Stop/epoch publication fences cancel waiting writers.
    """
    def __init__(self, policy=None):
        self.policy = policy or BufferPolicy()
        self.target_ms = self.policy.committed_ms
        self.jitter_ms = 0.0
        self.previous = None

    def observe(self, now, duration_ms):
        if self.previous is not None:
            jitter = abs((now - self.previous) * 1000 - duration_ms)
            self.jitter_ms += .125 * (jitter - self.jitter_ms)
            self.target_ms = min(self.policy.interruptible_ms,
                                 max(self.policy.committed_ms, int(self.policy.committed_ms + 4 * self.jitter_ms)))
        self.previous = now
        return self.target_ms


def split_audio(chunk, frame_ms=20):
    """Bound fanout by duration as well as packet count, without copying a tail."""
    if chunk.channels != 1 or chunk.sample_rate <= 0 or len(chunk.pcm) % 2:
        raise ValueError("invalid mono PCM")
    part = max(1, chunk.sample_rate * frame_ms // 1000)
    total = len(chunk.pcm) // 2
    for offset in range(0, total, part):
        end = min(total, offset + part)
        pcm = chunk.pcm[offset * 2:end * 2]
        if isinstance(chunk, TimedAudioChunk):
            start_sample = chunk.startSample + offset * chunk.timelineRate // chunk.sample_rate
            end_sample = chunk.endSample if end == total else chunk.startSample + end * chunk.timelineRate // chunk.sample_rate
            yield TimedAudioChunk(chunk.generation_id, chunk.sequence, pcm, chunk.sample_rate, 1,
                                  chunk.identity, start_sample, end_sample, chunk.timelineRate)
        else:
            yield AudioChunk(chunk.generation_id, chunk.sequence, pcm, chunk.sample_rate, 1)


class SpeculativeMediaBuffer:
    """C's explicit precommit staging seam; full means producer backpressure.

    No tasks or hidden unbounded waits. C must retry after take/invalidation,
    not allocate a task per rejected offer. Ready descriptors may reference an
    external bounded spool; this queue never holds a whole unbounded segment.
    """
    def __init__(self, timeline, fps=25, max_frame_bytes=8 * 1024 * 1024):
        self.timeline = timeline
        self.audio = deque()
        self.video = deque()
        self.samples = self.peak_samples = 0
        self.sample_cap = timeline.sample_rate * timeline.policy.speculative_ms // 1000
        self.frame_cap = (fps * timeline.policy.speculative_ms + 999) // 1000
        self.max_frame_bytes = positive(max_frame_bytes)
        timeline.sink_fences.append(self.clear)

    def _current(self, identity):
        return bool(identity and not self.timeline.sealed and not self.timeline.blocked and
                    (identity.sessionId, identity.runEpoch, identity.timelineEpoch) ==
                    (self.timeline.session_id, self.timeline.run_epoch, self.timeline.epoch))

    def offer_audio(self, chunk: TimedAudioChunk):
        if not self._current(chunk.identity):
            return False
        count = chunk.endSample - chunk.startSample
        if (chunk.timelineRate != self.timeline.sample_rate or count <= 0 or
                chunk.channels != 1 or len(chunk.pcm) % 2 or chunk.sample_rate <= 0 or
                abs(len(chunk.pcm) // 2 * chunk.timelineRate // chunk.sample_rate - count) > 1 or
                len(chunk.pcm) > self.sample_cap * 6):
            raise ValueError("invalid or oversized staged PCM")
        if count > self.sample_cap:
            raise ValueError("split PCM before speculative admission")
        if self.samples + count > self.sample_cap:
            return False
        self.audio.append(chunk)
        self.samples += count
        self.peak_samples = max(self.peak_samples, self.samples)
        return True

    def offer_video(self, frame: TimedVideoFrame):
        if not self._current(frame.identity):
            return False
        if frame.timelineRate != self.timeline.sample_rate or len(frame.rgb) > self.max_frame_bytes:
            raise ValueError("invalid or oversized staged video")
        if len(self.video) >= self.frame_cap:
            return False
        self.video.append(frame)
        return True

    def take_audio(self):
        if not self.audio:
            return None
        chunk = self.audio[0]
        if not self.timeline.eligible(chunk.identity, chunk.startSample, chunk.endSample):
            return None
        self.audio.popleft()
        self.samples -= chunk.endSample - chunk.startSample
        return chunk

    def take_video(self):
        if not self.video:
            return None
        frame = self.video[0]
        if not self.timeline.eligible(frame.identity, frame.sourceSample, frame.sourceSample):
            return None
        return self.video.popleft()

    def clear(self):
        self.audio.clear()
        self.video.clear()
        self.samples = 0
