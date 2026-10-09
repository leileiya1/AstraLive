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


@dataclass(eq=False)
class _Peer:
    peer_id: str
    connection: RTCPeerConnection
    audio: _AudioTrack
    video: _VideoTrack


class WebRTCMediaOutput:
    def __init__(self, fps: int = 25):
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

    def pop_warnings(self) -> list[dict]:
        warnings, self.warnings = self.warnings, []
        return warnings

    def _diagnostic(self, peer: _Peer) -> dict:
        elapsed = max(0.001, time.monotonic() - (peer.video.first_recv_monotonic or time.monotonic()))
        return {"peerId": peer.peer_id, "connectionState": peer.connection.connectionState,
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
        audio = _AudioTrack(self.audio_buffer_ms, self.max_audio_buffer_ms)
        video = _VideoTrack(self.fps, self.video_buffer_ms, self.max_video_buffer_ms)
        audio.generation_id = video.generation_id = self.generation_id
        peer = _Peer("peer_" + uuid4().hex, peer_connection, audio, video)
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
                       (peer.audio.consumed < audio or peer.video.consumed < video)]
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
                stalled_video = peer.video.consumed < video and now - (peer.video.last_recv_monotonic or started) >= self.stale_window
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
