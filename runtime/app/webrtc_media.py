"""WebRTC media sink. Signaling transport is intentionally outside this adapter."""
import asyncio
from dataclasses import dataclass
from fractions import Fraction
import math
import os
import time
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4
import av
import numpy as np
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from .models import SessionConfig
from .providers import AudioChunk, VideoFrame, MediaDeliveryError
from .media_timeline import (enabled as timeline_enabled, AudioMasterClock,
                             RationalResampler, AdaptiveBuffer, samples_to_pts, TimedAudioChunk, FrameDispositions)

log = logging.getLogger(__name__)


class _AudioTrack(MediaStreamTrack):
    kind = "audio"
    sample_rate = 48000
    frame_samples = 960

    def __init__(self, buffer_ms: int = 400, max_buffer_ms: int = 1000):
        super().__init__()
        self.buffer_ms = min(buffer_ms, max_buffer_ms)
        self.queue: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue(
            maxsize=max(1, math.ceil(self.buffer_ms / 20))
        )
        self.pending = bytearray()
        self.pts = 0
        self.next_at: float | None = None
        self.generation_id = 1
        self.enqueued = 0
        self.consumed = 0
        self.last_recv_at: str | None = None
        self.last_recv_monotonic: float | None = None
        self.first_recv_monotonic: float | None = None
        self.total_enqueued = 0
        self.total_consumed = 0
        self.frames_dropped = 0
        self.backpressure_events = 0
        self.backpressure_wait_ms = 0.0
        self.peak_queue_frames = 0

    async def _put(self, item: tuple[int, bytes], generation_id: int,
                   is_active, stale_window: float, poll_interval: float) -> bool:
        waited_at = None
        progress_at = time.monotonic()
        last_consumed = self.consumed
        try:
            while True:
                if generation_id != self.generation_id or self.readyState != "live" or not is_active():
                    self.frames_dropped += 1
                    return False
                try:
                    self.queue.put_nowait(item)
                except asyncio.QueueFull:
                    if waited_at is None:
                        waited_at = time.monotonic()
                        progress_at = waited_at
                        self.backpressure_events += 1
                    try:
                        await asyncio.wait_for(self.queue.put(item), poll_interval)
                    except asyncio.TimeoutError:
                        now = time.monotonic()
                        if self.consumed != last_consumed:
                            last_consumed = self.consumed
                            progress_at = now
                        last_recv = self.last_recv_monotonic or waited_at
                        if now - progress_at >= stale_window and now - last_recv >= stale_window:
                            raise MediaDeliveryError("WebRTC audio consumer stalled under backpressure")
                        continue
                if generation_id != self.generation_id or self.readyState != "live" or not is_active():
                    self._discard_old_generation()
                    self.frames_dropped += 1
                    return False
                self.enqueued += 1
                self.total_enqueued += 1
                self.peak_queue_frames = max(self.peak_queue_frames, self.queue.qsize())
                return True
        finally:
            if waited_at is not None:
                self.backpressure_wait_ms += (time.monotonic() - waited_at) * 1000

    async def push(self, chunk: AudioChunk, is_active=lambda: True,
                   stale_window: float = 2.0, poll_interval: float = 0.02) -> None:
        if chunk.generation_id != self.generation_id or self.readyState != "live":
            return
        if chunk.channels != 1:
            raise ValueError("WebRTC audio requires mono PCM")
        source = np.frombuffer(chunk.pcm, dtype="<i2")
        if chunk.sample_rate == self.sample_rate:
            pcm = chunk.pcm
        else:
            count = round(len(source) * self.sample_rate / chunk.sample_rate)
            if not count:
                return
            indices = np.linspace(0, max(0, len(source) - 1), count)
            pcm = np.interp(indices, np.arange(len(source)), source).astype("<i2").tobytes()
        self.pending.extend(pcm)
        frame_bytes = self.frame_samples * 2
        while len(self.pending) >= frame_bytes:
            accepted = await self._put(
                (chunk.generation_id, bytes(self.pending[:frame_bytes])), chunk.generation_id,
                is_active, stale_window, poll_interval,
            )
            if not accepted:
                return
            del self.pending[:frame_bytes]

    def clear(self, generation_id: int | None = None) -> None:
        if generation_id is not None:
            self.frames_dropped += self.queue.qsize()
            self.generation_id = generation_id
            self.enqueued = self.consumed = 0
            self.last_recv_monotonic = None
        self.pending.clear()
        while not self.queue.empty():
            self.queue.get_nowait()

    def _discard_old_generation(self) -> None:
        kept = []
        while not self.queue.empty():
            item = self.queue.get_nowait()
            if item[0] == self.generation_id:
                kept.append(item)
        for item in kept:
            self.queue.put_nowait(item)

    async def flush(self, is_active=lambda: True,
                    stale_window: float = 2.0, poll_interval: float = 0.02) -> None:
        if self.pending:
            generation_id = self.generation_id
            frame_bytes = self.frame_samples * 2
            accepted = await self._put(
                (generation_id, bytes(self.pending).ljust(frame_bytes, b"\0")), generation_id,
                is_active, stale_window, poll_interval,
            )
            if not accepted:
                return
            self.pending.clear()

    async def recv(self):
        if self.readyState != "live":
            from aiortc.mediastreams import MediaStreamError
            raise MediaStreamError
        now = time.monotonic()
        if self.next_at is None:
            self.next_at = now
        await asyncio.sleep(max(0, self.next_at - now))
        self.next_at += 0.02
        try:
            while True:
                queued_generation, pcm = self.queue.get_nowait()
                if queued_generation == self.generation_id:
                    self.consumed += 1
                    self.total_consumed += 1
                    self.last_recv_monotonic = time.monotonic()
                    self.first_recv_monotonic = self.first_recv_monotonic or self.last_recv_monotonic
                    self.last_recv_at = datetime.now(timezone.utc).isoformat()
                    break
        except asyncio.QueueEmpty:
            pcm = b"\0" * (self.frame_samples * 2)
        frame = av.AudioFrame(format="s16", layout="mono", samples=self.frame_samples)
        frame.planes[0].update(pcm)
        frame.sample_rate = self.sample_rate
        frame.pts = self.pts
        frame.time_base = Fraction(1, self.sample_rate)
        self.pts += self.frame_samples
        return frame


class _VideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, fps: int = 25, buffer_ms: int = 400, max_buffer_ms: int = 1000):
        super().__init__()
        self.fps = fps
        self.buffer_ms = min(buffer_ms, max_buffer_ms)
        self.queue: asyncio.Queue[VideoFrame] = asyncio.Queue(
            maxsize=max(1, math.ceil(self.fps * self.buffer_ms / 1000))
        )
        self.latest: VideoFrame | None = None
        self.pts = 0
        self.next_at: float | None = None
        self.generation_id = 1
        self.enqueued = 0
        self.consumed = 0
        self.last_recv_at: str | None = None
        self.last_recv_monotonic: float | None = None
        self.first_recv_monotonic: float | None = None
        self.total_enqueued = 0
        self.total_consumed = 0
        self.frames_dropped = 0
        self.backpressure_events = 0
        self.backpressure_wait_ms = 0.0
        self.peak_queue_frames = 0

    async def push(self, frame: VideoFrame, is_active=lambda: True,
                   stale_window: float = 2.0, poll_interval: float = 0.02) -> None:
        if frame.generation_id != self.generation_id or self.readyState != "live":
            self.frames_dropped += 1
            return
        waited_at = None
        progress_at = time.monotonic()
        last_consumed = self.consumed
        try:
            while True:
                if frame.generation_id != self.generation_id or self.readyState != "live" or not is_active():
                    self.frames_dropped += 1
                    return
                try:
                    self.queue.put_nowait(frame)
                except asyncio.QueueFull:
                    if waited_at is None:
                        waited_at = time.monotonic()
                        progress_at = waited_at
                        self.backpressure_events += 1
                    try:
                        await asyncio.wait_for(self.queue.put(frame), poll_interval)
                    except asyncio.TimeoutError:
                        now = time.monotonic()
                        if self.consumed != last_consumed:
                            last_consumed = self.consumed
                            progress_at = now
                        last_recv = self.last_recv_monotonic or waited_at
                        if now - progress_at >= stale_window and now - last_recv >= stale_window:
                            raise MediaDeliveryError("WebRTC video consumer stalled under backpressure")
                        continue
                if frame.generation_id != self.generation_id or self.readyState != "live" or not is_active():
                    self._discard_old_generation()
                    self.frames_dropped += 1
                    return
                self.enqueued += 1
                self.total_enqueued += 1
                self.peak_queue_frames = max(self.peak_queue_frames, self.queue.qsize())
                return
        finally:
            if waited_at is not None:
                self.backpressure_wait_ms += (time.monotonic() - waited_at) * 1000

    def _discard_old_generation(self) -> None:
        kept = []
        while not self.queue.empty():
            item = self.queue.get_nowait()
            if item.generation_id == self.generation_id:
                kept.append(item)
        for item in kept:
            self.queue.put_nowait(item)

    def clear(self, generation_id: int | None = None) -> None:
        if generation_id is not None:
            self.frames_dropped += self.queue.qsize()
            self.generation_id = generation_id
            self.enqueued = self.consumed = 0
            self.last_recv_monotonic = None
        while not self.queue.empty():
            self.queue.get_nowait()
        self.latest = None

    async def recv(self):
        if self.readyState != "live":
            from aiortc.mediastreams import MediaStreamError
            raise MediaStreamError
        now = time.monotonic()
        if self.next_at is None:
            self.next_at = now
        await asyncio.sleep(max(0, self.next_at - now))
        self.next_at += 1 / self.fps
        try:
            self.latest = self.queue.get_nowait()
            self.consumed += 1
            self.total_consumed += 1
            self.last_recv_monotonic = time.monotonic()
            self.first_recv_monotonic = self.first_recv_monotonic or self.last_recv_monotonic
            self.last_recv_at = datetime.now(timezone.utc).isoformat()
        except asyncio.QueueEmpty:
            pass
        if self.latest:
            source = self.latest
            pixels = np.frombuffer(source.rgb, dtype=np.uint8).reshape(source.height, source.width, 3)
        else:
            pixels = np.zeros((256, 256, 3), dtype=np.uint8)
        frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
        frame.pts = self.pts
        frame.time_base = Fraction(1, 90000)
        self.pts += round(90000 / self.fps)
        return frame


class _TimelineAudioTrack(_AudioTrack):
    """V2 only: bounded PCM framing and per-peer audio-master progress."""
    def __init__(self, clock):
        super().__init__(clock.policy.interruptible_ms, clock.policy.interruptible_ms)
        self.clock = clock
        self.adaptive = AdaptiveBuffer(clock.policy)
        self.resampler = RationalResampler(self.sample_rate)
        self.source_cursor = clock.source_sample
        self.resample_origin = self.source_cursor
        self.pending_start = self.source_cursor
        self.pending_identity = None
        self.padding_samples = 0
        self.push_lock = asyncio.Lock()

    def clear(self, generation_id=None):
        super().clear(generation_id)
        self.resampler = RationalResampler(self.sample_rate)
        self.resample_origin = self.source_cursor
        self.pending_start = self.source_cursor
        self.pending_identity = None

    async def push(self, chunk, is_active=lambda: True, stale_window=2., poll_interval=.02):
        async with self.push_lock:
            if chunk.generation_id != self.generation_id or not is_active():
                return
            if chunk.channels != 1 or len(chunk.pcm) % 2 or chunk.sample_rate <= 0:
                raise ValueError("invalid mono PCM")
            identity = getattr(chunk, "identity", None)
            if self.clock.timeline and (identity is None or not self.clock.accepts(chunk, chunk.startSample, chunk.endSample)):
                return
            if identity != self.pending_identity and self.pending:
                await self.flush(is_active, stale_window, poll_interval)
            if identity != self.pending_identity:
                self.resampler = RationalResampler(self.sample_rate)
                self.resample_origin = self.source_cursor
            if isinstance(chunk, TimedAudioChunk):
                if chunk.timelineRate != self.clock.source_rate:
                    raise ValueError("timeline sample rate mismatch")
                if chunk.startSample != self.source_cursor:
                    if self.pending or chunk.startSample < self.source_cursor:
                        raise ValueError("audio overlap/discontinuity")
                    self.source_cursor = chunk.startSample
                    self.resample_origin = self.source_cursor
                    self.resampler = RationalResampler(self.sample_rate)
                expected = len(chunk.pcm) // 2 * chunk.timelineRate // chunk.sample_rate
                if abs(chunk.endSample - chunk.startSample - expected) > 1:
                    raise ValueError("PCM range mismatch")
            self.pending_identity = identity
            self.adaptive.observe(time.monotonic(), len(chunk.pcm) / 2 * 1000 / chunk.sample_rate)
            # Split BEFORE conversion so no second unbounded PCM buffer exists.
            part_bytes = max(2, chunk.sample_rate // 50 * 2)
            for offset in range(0, len(chunk.pcm), part_bytes):
                if chunk.generation_id != self.generation_id or not is_active():
                    return
                pcm = self.resampler.convert(chunk.pcm[offset:offset + part_bytes], chunk.sample_rate)
                if not self.pending:
                    self.pending_start = self.source_cursor
                self.pending.extend(pcm)
                self.source_cursor = self.resample_origin + self.resampler.output_count * self.clock.source_rate // self.sample_rate
                while len(self.pending) >= self.frame_samples * 2:
                    end = self.pending_start + self.frame_samples * self.clock.source_rate // self.sample_rate
                    # The physical cap is interruptible_ms; the target adapts.
                    waited_at = time.monotonic()
                    while self.queue.qsize() * 20 >= self.adaptive.target_ms:
                        if not is_active() or chunk.generation_id != self.generation_id:
                            return
                        if time.monotonic() - (self.last_recv_monotonic or waited_at) > stale_window:
                            raise MediaDeliveryError("WebRTC audio master stalled")
                        await asyncio.sleep(poll_interval)
                    item = (chunk.generation_id, bytes(self.pending[:self.frame_samples * 2]),
                            self.pending_start, end, identity)
                    if not await self._put(item, chunk.generation_id, is_active, stale_window, poll_interval):
                        return
                    del self.pending[:self.frame_samples * 2]
                    self.pending_start = end
            # Exact range endpoints override packet-grid rounding.
            if isinstance(chunk, TimedAudioChunk):
                self.source_cursor = chunk.endSample

    async def flush(self, is_active=lambda: True, stale_window=2., poll_interval=.02):
        if self.pending:
            count = len(self.pending) // 2
            item = (self.generation_id, bytes(self.pending).ljust(self.frame_samples * 2, b"\0"),
                    self.pending_start, self.source_cursor, self.pending_identity)
            if await self._put(item, self.generation_id, is_active, stale_window, poll_interval):
                self.padding_samples += self.frame_samples - count
                self.pending.clear()

    async def recv(self):
        if self.readyState != "live":
            from aiortc.mediastreams import MediaStreamError
            raise MediaStreamError
        now = time.monotonic()
        self.next_at = self.next_at or now
        await asyncio.sleep(max(0, self.next_at - now))
        self.next_at = max(self.next_at + .02, time.monotonic())
        pcm = bytes(self.frame_samples * 2)
        end = None
        while not self.queue.empty():
            generation, payload, start, source_end, identity = self.queue.get_nowait()
            if generation != self.generation_id or (self.clock.timeline and
                    not self.clock.timeline.eligible(identity, start, source_end)):
                self.frames_dropped += 1
                continue
            pcm, end = payload, source_end
            self.consumed += 1
            self.total_consumed += 1
            self.last_recv_monotonic = time.monotonic()
            self.first_recv_monotonic = self.first_recv_monotonic or self.last_recv_monotonic
            self.last_recv_at = datetime.now(timezone.utc).isoformat()
            if self.clock.timeline:
                self.clock.timeline.observe_sink_progress(identity, self.sink_id, "audio", start, source_end)
            break
        frame = av.AudioFrame(format="s16", layout="mono", samples=self.frame_samples)
        frame.planes[0].update(pcm)
        frame.sample_rate = self.sample_rate
        frame.pts = self.clock.output_samples
        frame.time_base = Fraction(1, self.sample_rate)
        self.clock.advance(self.frame_samples, end)
        self.pts = self.clock.output_samples
        return frame


class _TimelineVideoTrack(_VideoTrack):
    def __init__(self, clock, fps=25):
        super().__init__(fps, clock.policy.interruptible_ms, clock.policy.interruptible_ms)
        self.clock = clock
        self.tick = 0
        self.dispositions = FrameDispositions()
        self.resolved = 0

    async def push(self, frame, is_active=lambda: True, stale_window=2., poll_interval=.02):
        sample = getattr(frame, "sourceSample", frame.pts_us * self.clock.source_rate // 1000000)
        if not self.clock.accepts(frame, sample, sample):
            self.frames_dropped += 1
            self.disposition(frame, "fenced")
            return
        await super().push(frame, is_active, stale_window, poll_interval)

    def disposition(self, frame, state):
        self.dispositions.record(frame, state)
        self.resolved += 1

    def clear(self, generation_id=None):
        super().clear(generation_id)
        self.dispositions.clear()
        self.resolved = 0

    async def recv(self):
        if self.readyState != "live":
            from aiortc.mediastreams import MediaStreamError
            raise MediaStreamError
        await self.clock.wait_video_tick(self.tick, self.fps, lambda: self.readyState == "live")
        if self.readyState != "live":
            from aiortc.mediastreams import MediaStreamError
            raise MediaStreamError
        # Do not burst old video after receiver stalls.
        self.tick = max(self.tick, self.clock.output_samples * self.fps // self.clock.output_rate - 1)
        while not self.queue.empty():
            source = self.queue._queue[0]
            sample = getattr(source, "sourceSample", source.pts_us * self.clock.source_rate // 1000000)
            end = sample + self.clock.source_rate // self.fps
            if self.clock.timeline and getattr(source, "identity", None):
                commit = self.clock.timeline.commits.get(source.identity.segmentId)
                if commit:
                    end = min(end, commit.end)
            if source.generation_id != self.generation_id or not self.clock.accepts(source, sample, end):
                self.queue.get_nowait()
                self.frames_dropped += 1
                self.disposition(source, "fenced")
                continue
            action = self.clock.video_action(sample)
            if action == "wait":
                break
            self.queue.get_nowait()
            if action == "drop":
                self.frames_dropped += 1
                self.clock.video_late_drops += 1
                self.disposition(source, "dropped")
                continue
            self.latest = source
            self.consumed += 1
            self.total_consumed += 1
            self.last_recv_monotonic = time.monotonic()
            self.first_recv_monotonic = self.first_recv_monotonic or self.last_recv_monotonic
            self.last_recv_at = datetime.now(timezone.utc).isoformat()
            self.disposition(source, "consumed")
            if self.clock.timeline:
                self.clock.timeline.observe_sink_progress(source.identity, self.sink_id, "video", sample, end)
            break
        else:
            self.clock.video_holds += 1
        if self.latest:
            pixels = np.frombuffer(self.latest.rgb, dtype=np.uint8).reshape(self.latest.height, self.latest.width, 3)
        else:
            pixels = np.zeros((256, 256, 3), dtype=np.uint8)
        frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
        frame.pts = self.tick * 90000 // self.fps
        frame.time_base = Fraction(1, 90000)
        self.tick += 1
        self.pts = self.tick * 90000 // self.fps
        return frame


@dataclass(eq=False)
class _Peer:
    peer_id: str
    connection: RTCPeerConnection
    audio: _AudioTrack
    video: _VideoTrack


class WebRTCMediaOutput:
    def __init__(self, fps: int = 25):
        self.timeline_v2 = timeline_enabled()
        self.timeline = None
        self.standalone_audio_samples = Fraction(0)
        self.fps = int(os.getenv("TARGET_FPS", str(fps)))
        self.video_buffer_ms = int(os.getenv("TARGET_VIDEO_BUFFER_MS", "400"))
        self.audio_buffer_ms = int(os.getenv("TARGET_AUDIO_BUFFER_MS", "400"))
        self.max_video_buffer_ms = int(os.getenv("MAX_VIDEO_BUFFER_MS", "1000"))
        self.max_audio_buffer_ms = int(os.getenv("MAX_AUDIO_BUFFER_MS", "1000"))
        if self.fps <= 0 or min(self.video_buffer_ms, self.audio_buffer_ms,
                                self.max_video_buffer_ms, self.max_audio_buffer_ms) <= 0:
            raise ValueError("Target FPS and media buffer durations must be positive")
        self.generation_id = 1
        self.running = False
        self.peers: set[_Peer] = set()
        self.warnings: list[dict] = []
        self.drain_timeout = 15.0
        self.stale_window = 2.0
        self.peer_close_timeout = 2.0
        self.backpressure_poll_interval = 0.02
        self.peer_stall_events = 0
        self.peer_evictions = 0
        self.render_ms = 0.0

    def record_render_ms(self, render_ms: float) -> None:
        self.render_ms = round(render_ms, 3)

    def bind_timeline(self, timeline):
        if not self.timeline_v2 or self.running:
            raise ValueError("bind V2 timeline before output start")
        self.timeline = timeline
        def fence():
            for peer in tuple(self.peers):
                peer.audio.clear()
                peer.video.clear()
        timeline.sink_fences.append(fence)
        timeline.sink_observers.append(lambda: {"sink": "webrtc", "peers": [
            {"sinkId": peer.peer_id, **peer.audio.clock.snapshot()} for peer in self.peers]})

    def video_disposition(self, frame):
        states = [p.video.dispositions.get(frame) for p in self.peers
                  if isinstance(p.video, _TimelineVideoTrack)]
        if "consumed" in states:
            return "consumed"
        return "dropped" if states and all(s == "dropped" for s in states) else None

    def pop_warnings(self) -> list[dict]:
        warnings, self.warnings = self.warnings, []
        return warnings

    def _diagnostic(self, peer: _Peer) -> dict:
        elapsed = max(0.001, time.monotonic() - (peer.video.first_recv_monotonic or time.monotonic()))
        return {**({"mediaTimeline": peer.audio.clock.snapshot(),
                    "adaptiveTargetMs": peer.audio.adaptive.target_ms,
                    "pendingSamples": len(peer.audio.pending) // 2}
                   if isinstance(peer.audio, _TimelineAudioTrack) else {}),
                "peerId": peer.peer_id, "connectionState": peer.connection.connectionState,
                "iceConnectionState": peer.connection.iceConnectionState,
                "audioQueueSize": peer.audio.queue.qsize(), "videoQueueSize": peer.video.queue.qsize(),
                "audioQueueMax": peer.audio.queue.maxsize, "videoQueueMax": peer.video.queue.maxsize,
                "audioQueueMs": peer.audio.queue.qsize() * 20,
                "videoQueueMs": round(peer.video.queue.qsize() * 1000 / self.fps, 1),
                "audioPeakQueueFrames": peer.audio.peak_queue_frames,
                "audioPeakQueueMs": peer.audio.peak_queue_frames * 20,
                "videoPeakQueueFrames": peer.video.peak_queue_frames,
                "videoPeakQueueMs": round(peer.video.peak_queue_frames * 1000 / self.fps, 1),
                "targetFps": self.fps,
                "consumerFps": round(peer.video.total_consumed / elapsed, 2) if peer.video.first_recv_monotonic else 0.0,
                "renderMs": self.render_ms,
                "lastAudioRecvAt": peer.audio.last_recv_at, "lastVideoRecvAt": peer.video.last_recv_at,
                "audioFramesEnqueued": peer.audio.enqueued, "audioFramesConsumed": peer.audio.consumed,
                "videoFramesEnqueued": peer.video.enqueued, "videoFramesConsumed": peer.video.consumed,
                "audioFramesEnqueuedTotal": peer.audio.total_enqueued,
                "audioFramesConsumedTotal": peer.audio.total_consumed,
                "videoFramesEnqueuedTotal": peer.video.total_enqueued,
                "videoFramesConsumedTotal": peer.video.total_consumed,
                "framesDropped": peer.audio.frames_dropped + peer.video.frames_dropped,
                "backpressureEvents": peer.audio.backpressure_events + peer.video.backpressure_events,
                "backpressureWaitMs": round(peer.audio.backpressure_wait_ms + peer.video.backpressure_wait_ms, 1),
                "peerStallEvents": self.peer_stall_events, "peerEvictions": self.peer_evictions,
                "generationId": self.generation_id}

    async def _evict(self, peer: _Peer, reason: str) -> None:
        if peer not in self.peers:
            return
        self.peer_evictions += 1
        if "stalled" in reason:
            self.peer_stall_events += 1
        diagnostic = self._diagnostic(peer)
        self.peers.discard(peer)
        peer.audio.clear()
        peer.video.clear()
        peer.audio.stop()
        peer.video.stop()
        warning = {"code": "WEBRTC_PEER_EVICTED", "reason": reason, "peer": diagnostic}
        self.warnings.append(warning)
        log.warning("webrtc_peer_evicted %s", json.dumps(warning))
        try:
            await asyncio.wait_for(peer.connection.close(), self.peer_close_timeout)
        except asyncio.TimeoutError:
            self.warnings.append({"code": "WEBRTC_PEER_CLOSE_TIMEOUT", "peerId": peer.peer_id})
            log.warning("webrtc_peer_close_timeout peerId=%s", peer.peer_id)
        except Exception as exc:
            self.warnings.append({"code": "WEBRTC_PEER_CLOSE_FAILED", "peerId": peer.peer_id, "errorType": type(exc).__name__})
            log.warning("webrtc_peer_close_failed peerId=%s errorType=%s", peer.peer_id, type(exc).__name__)

    def configure_session(self, config: SessionConfig) -> None:
        if "TARGET_FPS" not in os.environ:
            self.fps = config.fps

    async def start(self) -> None:
        self.running = True

    async def create_answer(self, offer_sdp: str) -> str:
        if not self.running:
            raise RuntimeError("Media output is not running")
        peer_connection = RTCPeerConnection()
        if self.timeline_v2:
            clock = AudioMasterClock()
            clock.timeline = self.timeline
            if self.timeline:
                clock.source_rate = self.timeline.sample_rate
                clock.policy = self.timeline.policy
                clock.source_sample = self.timeline.committed_end
            else:
                clock.source_sample = int(self.standalone_audio_samples)
            audio = _TimelineAudioTrack(clock)
            video = _TimelineVideoTrack(clock, self.fps)
        else:
            audio = _AudioTrack(self.audio_buffer_ms, self.max_audio_buffer_ms)
            video = _VideoTrack(self.fps, self.video_buffer_ms, self.max_video_buffer_ms)
        audio.generation_id = video.generation_id = self.generation_id
        peer = _Peer("peer_" + uuid4().hex, peer_connection, audio, video)
        audio.sink_id = video.sink_id = peer.peer_id
        self.peers.add(peer)
        peer_connection.addTrack(audio)
        peer_connection.addTrack(video)

        @peer_connection.on("connectionstatechange")
        async def on_connectionstatechange():
            if peer_connection.connectionState in {"failed", "disconnected"}:
                await self._evict(peer, "connection_state")
            elif peer_connection.connectionState == "closed":
                self.peers.discard(peer)
                peer.audio.clear()
                peer.video.clear()
                peer.audio.stop()
                peer.video.stop()

        try:
            await peer_connection.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
            answer = await peer_connection.createAnswer()
            await peer_connection.setLocalDescription(answer)
            if peer_connection.iceGatheringState != "complete":
                gathered = asyncio.Event()

                @peer_connection.on("icegatheringstatechange")
                def on_icegatheringstatechange():
                    if peer_connection.iceGatheringState == "complete":
                        gathered.set()

                if peer_connection.iceGatheringState != "complete":
                    await asyncio.wait_for(gathered.wait(), timeout=20)
            if not self.running or peer not in self.peers:
                raise RuntimeError("Peer was closed during negotiation")
            return peer_connection.localDescription.sdp
        except Exception:
            self.peers.discard(peer)
            peer.audio.stop()
            peer.video.stop()
            await asyncio.wait_for(peer_connection.close(), self.peer_close_timeout)
            raise

    async def push_audio(self, chunk: AudioChunk) -> None:
        if not self.running or chunk.generation_id != self.generation_id:
            return
        if self.timeline_v2 and self.timeline is None:
            if chunk.channels != 1 or len(chunk.pcm) % 2 or chunk.sample_rate <= 0:
                raise ValueError("invalid mono PCM")
            self.standalone_audio_samples += Fraction(len(chunk.pcm) // 2 * 16000, chunk.sample_rate)
        peers = tuple(self.peers)

        async def push(peer: _Peer) -> None:
            try:
                await peer.audio.push(
                    chunk,
                    lambda: self.running and chunk.generation_id == self.generation_id and peer in self.peers
                    and peer.connection.connectionState not in {"failed", "disconnected", "closed"},
                    self.stale_window, self.backpressure_poll_interval,
                )
            except MediaDeliveryError:
                await self._evict(peer, "audio_sender_stalled")
        await asyncio.gather(*(push(peer) for peer in peers))
        if peers and not self.peers and self.running and chunk.generation_id == self.generation_id:
            raise MediaDeliveryError("All WebRTC peers unavailable during audio backpressure")

    async def push_video(self, frame: VideoFrame) -> None:
        if not self.running or frame.generation_id != self.generation_id:
            return
        peers = tuple(self.peers)

        async def push(peer: _Peer) -> None:
            try:
                await peer.video.push(
                    frame,
                    lambda: self.running and frame.generation_id == self.generation_id and peer in self.peers
                    and peer.connection.connectionState not in {"failed", "disconnected", "closed"},
                    self.stale_window, self.backpressure_poll_interval,
                )
            except MediaDeliveryError:
                await self._evict(peer, "video_sender_stalled")
        await asyncio.gather(*(push(peer) for peer in peers))
        if peers and not self.peers and self.running and frame.generation_id == self.generation_id:
            raise MediaDeliveryError("All WebRTC peers unavailable during video backpressure")

    async def drain(self, generation_id: int) -> None:
        if generation_id != self.generation_id:
            return
        if not self.peers:
            raise MediaDeliveryError("No WebRTC peer available for playback")
        peers = tuple(self.peers)
        for peer in peers:
            try:
                await peer.audio.flush(
                    lambda: self.running and generation_id == self.generation_id and peer in self.peers
                    and peer.connection.connectionState not in {"failed", "disconnected", "closed"},
                    self.stale_window, self.backpressure_poll_interval,
                )
            except MediaDeliveryError:
                await self._evict(peer, "audio_flush_stalled")
        targets = {peer: (peer.audio.enqueued, peer.video.enqueued) for peer in peers if peer in self.peers}
        started = time.monotonic()
        deadline = started + self.drain_timeout
        while generation_id == self.generation_id and self.running:
            pending = [peer for peer, (audio, video) in targets.items() if peer in self.peers and
                       (peer.audio.consumed < audio or getattr(peer.video, "resolved", peer.video.consumed) < video)]
            if not pending:
                if any(peer in self.peers for peer in targets):
                    log.warning("webrtc_media_metrics %s", json.dumps({
                        "generationId": generation_id,
                        "peers": [self._diagnostic(peer) for peer in targets if peer in self.peers],
                    }))
                    return
                raise MediaDeliveryError("All WebRTC peers unavailable during playback")
            now = time.monotonic()
            for peer in pending:
                audio, video = targets[peer]
                stalled_audio = peer.audio.consumed < audio and now - (peer.audio.last_recv_monotonic or started) >= self.stale_window
                stalled_video = getattr(peer.video, "resolved", peer.video.consumed) < video and now - (peer.video.last_recv_monotonic or started) >= self.stale_window
                if peer.connection.connectionState in {"failed", "disconnected", "closed"} or stalled_audio or stalled_video:
                    await self._evict(peer, "drain_stalled")
            if time.monotonic() >= deadline:
                diagnostics = [self._diagnostic(peer) for peer in pending]
                log.error("webrtc_drain_timeout %s", json.dumps({"generationId": generation_id, "peers": diagnostics}))
                for peer in pending:
                    await self._evict(peer, "drain_timeout")
                if not any(peer in self.peers for peer in targets):
                    raise MediaDeliveryError("WebRTC playback drain timed out")
            await asyncio.sleep(0.02)

    async def interrupt(self, generation_id: int) -> None:
        self.generation_id = generation_id
        for peer in tuple(self.peers):
            peer.audio.clear(generation_id)
            peer.video.clear(generation_id)

    async def stop(self) -> None:
        self.running = False
        peers = tuple(self.peers)
        self.peers.clear()
        for peer in peers:
            peer.audio.clear()
            peer.video.clear()
            peer.audio.stop()
            peer.video.stop()
        results = await asyncio.gather(*(asyncio.wait_for(peer.connection.close(), self.peer_close_timeout) for peer in peers), return_exceptions=True)
        for peer, result in zip(peers, results):
            if isinstance(result, BaseException):
                log.warning("webrtc_stop_peer_close_failed peerId=%s errorType=%s", peer.peer_id, type(result).__name__)
