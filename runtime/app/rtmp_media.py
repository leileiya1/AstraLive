"""Headless FFmpeg RTMP sink with continuous audio/video clocks."""
import asyncio
from collections import deque
from dataclasses import asdict
import logging
import math
import os
import shutil
import time
from typing import Awaitable, Callable

from .config import RTMPSettings
from .providers import AudioChunk, VideoFrame
from .media_timeline import enabled as timeline_enabled, AudioMasterClock, FrameDispositions


log = logging.getLogger(__name__)
WarningHandler = Callable[[dict], Awaitable[None]]


class FFmpegRTMPMediaOutput:
    audio_frame_ms = 20

    def __init__(self, settings: RTMPSettings | None = None) -> None:
        self.timeline_v2 = timeline_enabled()
        self.settings = settings or RTMPSettings.from_env()
        if not self.settings.enabled:
            raise ValueError("FFmpegRTMPMediaOutput requires RTMP_ENABLED=true")
        self.generation_id = 1
        self.running = False
        self.audio_queue: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue(
            max(1, math.ceil(self.settings.audio_buffer_ms / self.audio_frame_ms))
        )
        self.video_queue: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue(
            max(1, math.ceil(self.settings.fps * self.settings.video_buffer_ms / 1000))
        )
        self._audio_pending = bytearray()
        self._latest_video = self._blank_frame()
        self._process: asyncio.subprocess.Process | None = None
        self._audio_fd: int | None = None
        self._video_fd: int | None = None
        self._supervisor_task: asyncio.Task | None = None
        self._audio_clock_task: asyncio.Task | None = None
        self._video_clock_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._process_lock = asyncio.Lock()
        self.warning_handler: WarningHandler | None = None
        self.warnings: list[dict] = []
        self.stderr_lines: deque[str] = deque(maxlen=200)
        self.process_starts = 0
        self.reconnect_count = 0
        self.audio_enqueued = 0
        self.audio_consumed = 0
        self.video_enqueued = 0
        self.video_consumed = 0
        self.video_written = 0
        self.audio_enqueued_total = 0
        self.audio_consumed_total = 0
        self.video_enqueued_total = 0
        self.video_consumed_total = 0
        self.audio_dropped = 0
        self.video_dropped = 0
        self.write_failures = 0
        self.started_monotonic: float | None = None
        self.last_process_started_monotonic: float | None = None
        self.connection_incarnation = 0
        self.timeline_clock = None
        self.timeline_in_flight = {}
        self.cancelled_in_flight = 0
        if self.timeline_v2:
            # Lazy import keeps the flag-off RTMP dependency surface unchanged.
            from .webrtc_media import _TimelineAudioTrack
            self.timeline_clock = AudioMasterClock(self.settings.audio_sample_rate)
            self._timeline_audio = _TimelineAudioTrack(self.timeline_clock)
            self._timeline_audio.sample_rate = self.settings.audio_sample_rate
            self._timeline_audio.frame_samples = self.settings.audio_sample_rate // 50
            from .media_timeline import RationalResampler
            self._timeline_audio.resampler = RationalResampler(self.settings.audio_sample_rate)
            self.audio_queue = self._timeline_audio.queue
            self._audio_pending = self._timeline_audio.pending
            self.video_queue = asyncio.Queue(math.ceil(self.settings.fps * self.timeline_clock.policy.interruptible_ms / 1000))
            self._video_tick = 0
            self._video_dispositions = FrameDispositions()
            self.video_resolved = 0
            self.audio_retired = 0

    def bind_timeline(self, timeline):
        if not self.timeline_v2 or self.running:
            raise ValueError("bind V2 timeline before output start")
        self.timeline_clock.timeline = timeline
        self.timeline_clock.source_rate = timeline.sample_rate
        self.timeline_clock.policy = timeline.policy
        self._timeline_audio.clock = self.timeline_clock
        def fence():
            self._timeline_audio.pending.clear()
            self._latest_video = self._blank_frame()
            for queue in (self.audio_queue, self.video_queue):
                while not queue.empty():
                    queue.get_nowait()
                    queue.task_done()
        timeline.sink_fences.append(fence)
        timeline.sink_observers.append(self.timeline_progress)

    def timeline_progress(self):
        return {"sink": f"rtmp:{self.connection_incarnation}",
                "clock": self.timeline_clock.snapshot(),
                "inFlight": {media: {**item, "identity": asdict(item["identity"]) if item["identity"] else None}
                             for media, item in self.timeline_in_flight.items()},
                "cancelledInFlight": self.cancelled_in_flight}

    def video_disposition(self, frame):
        return self._video_dispositions.get(frame) if self.timeline_v2 else None

    def _dispose_video(self, frame, state):
        self._video_dispositions.record(frame, state)
        self.video_resolved += 1

    def configure_session(self, config) -> None:
        # RTMP owns its output dimensions and clock; Session config is input metadata.
        return None

    def set_warning_handler(self, handler: WarningHandler) -> None:
        self.warning_handler = handler

    def _warn(self, warning: dict) -> None:
        self.warnings.append(warning)
        if self.timeline_v2:
            del self.warnings[:-256]
        log.warning("rtmp_output_warning %s", warning)
        if self.warning_handler:
            asyncio.create_task(self.warning_handler(warning))

    def pop_warnings(self) -> list[dict]:
        warnings, self.warnings = self.warnings, []
        return [] if self.warning_handler else warnings

    def _blank_frame(self) -> bytes:
        return bytes(self.settings.width * self.settings.height * 3)

    def _command(self, video_read_fd: int, audio_read_fd: int) -> list[str]:
        s = self.settings
        return [
            s.ffmpeg_binary, "-hide_banner", "-loglevel", "warning", "-nostdin",
            "-probesize", "32", "-analyzeduration", "0",
            "-thread_queue_size", "64", "-f", "s16le", "-ar", str(s.audio_sample_rate),
            "-ac", "1", "-i", f"pipe:{audio_read_fd}",
            "-probesize", "32", "-analyzeduration", "0",
            "-thread_queue_size", "64", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-video_size", f"{s.width}x{s.height}", "-framerate", str(s.fps),
            "-i", f"pipe:{video_read_fd}",
            "-map", "1:v:0", "-map", "0:a:0", "-c:v", "libx264", "-preset", s.preset,
            "-tune", "zerolatency", "-b:v", s.video_bitrate, "-pix_fmt", "yuv420p",
            "-r", str(s.fps), "-g", str(s.gop_frames), "-sc_threshold", "0",
            "-c:a", "aac", "-b:a", s.audio_bitrate, "-ar", str(s.audio_sample_rate),
            "-ac", "2", "-af", "aresample=async=1:first_pts=0",
            "-flvflags", "no_duration_filesize", "-f", "flv", s.target,
        ]

    async def start(self) -> None:
        if self.running:
            return
        if shutil.which(self.settings.ffmpeg_binary) is None:
            raise RuntimeError("FFmpeg binary is unavailable")
        self.running = True
        self._stop_event.clear()
        self.started_monotonic = time.monotonic()
        try:
            await self._launch_process()
        except Exception as exc:
            self.running = False
            raise RuntimeError("Unable to start FFmpeg RTMP output") from exc
        self._audio_clock_task = asyncio.create_task(self._audio_clock(), name="rtmp-audio-clock")
        self._video_clock_task = asyncio.create_task(self._video_clock(), name="rtmp-video-clock")
        self._supervisor_task = asyncio.create_task(self._supervise(), name="rtmp-ffmpeg-supervisor")
        log.info("rtmp_output_started target=%s", self.settings.redacted_target)

    async def _launch_process(self) -> None:
        async with self._process_lock:
            video_read, video_write = os.pipe()
            audio_read, audio_write = os.pipe()
            os.set_blocking(video_write, False)
            os.set_blocking(audio_write, False)
            try:
                process = await asyncio.create_subprocess_exec(
                    *self._command(video_read, audio_read),
                    pass_fds=(video_read, audio_read),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception:
                for fd in (video_read, video_write, audio_read, audio_write):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                raise
            os.close(video_read)
            os.close(audio_read)
            self._process = process
            self._video_fd = video_write
            self._audio_fd = audio_write
            self.process_starts += 1
            self.connection_incarnation += 1
            if self.timeline_v2:
                # New FFmpeg is a new mux clock domain. Never report reset as
                # surviving-connection PTS continuity or replay the old tail.
                self.timeline_clock.output_samples = 0
                self._video_tick = 0
                if self.process_starts > 1:
                    self._latest_video = self._blank_frame()
                    for queue in (self.audio_queue, self.video_queue):
                        while not queue.empty():
                            item = queue.get_nowait()
                            queue.task_done()
                            if queue is self.audio_queue:
                                self.audio_retired += 1
                                self.audio_dropped += 1
                            else:
                                self._dispose_video(item[2], "dropped")
                                self.video_dropped += 1
                    self._timeline_audio.pending.clear()
                    self._warn({"code": "MEDIA_TIMELINE_DISCONTINUITY", "sink": "rtmp",
                                "connectionIncarnation": self.connection_incarnation, "tailState": "unknown"})
            self.last_process_started_monotonic = time.monotonic()
            self._stderr_task = asyncio.create_task(self._read_stderr(process), name="rtmp-ffmpeg-stderr")

    async def _read_stderr(self, process: asyncio.subprocess.Process) -> None:
        assert process.stderr is not None
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip()
            text = self.settings.redact(text)
            self.stderr_lines.append(text)

    async def _supervise(self) -> None:
        delay = self.settings.reconnect_initial_ms / 1000
        failure_started: float | None = None
        while self.running:
            process = self._process
            if process is None:
                return
            return_code = await process.wait()
            process_uptime = time.monotonic() - (self.last_process_started_monotonic or time.monotonic())
            await self._close_input_fds()
            if self._stderr_task:
                await asyncio.gather(self._stderr_task, return_exceptions=True)
            if not self.running:
                return
            now = time.monotonic()
            if process_uptime * 1000 >= self.settings.recovery_window_ms:
                failure_started = None
                delay = self.settings.reconnect_initial_ms / 1000
            failure_started = failure_started or now
            self._warn({"code": "RTMP_OUTPUT_FAILED", "returnCode": return_code,
                        "target": self.settings.redacted_target, "reconnectInMs": round(delay * 1000)})
            if (now - failure_started) * 1000 >= self.settings.recovery_window_ms:
                self._warn({"code": "MEDIA_OUTPUT_FAILED", "sink": "rtmp",
                            "recoveryWindowMs": self.settings.recovery_window_ms})
                failure_started = now
            try:
                await asyncio.wait_for(self._stop_event.wait(), delay)
                return
            except asyncio.TimeoutError:
                pass
            if not self.running:
                return
            try:
                await self._launch_process()
                self.reconnect_count += 1
                self._warn({"code": "RTMP_RECONNECTING", "attempt": self.reconnect_count,
                            "target": self.settings.redacted_target})
                delay = min(delay * 2, self.settings.reconnect_max_ms / 1000)
            except Exception as exc:
                self._warn({"code": "RTMP_RECONNECT_FAILED", "errorType": type(exc).__name__})

    @staticmethod
    def _resample_mono(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
        if source_rate == target_rate:
            return pcm
        import numpy as np
        source = np.frombuffer(pcm, dtype="<i2")
        count = round(len(source) * target_rate / source_rate)
        if not count or not len(source):
            return b""
        positions = np.linspace(0, len(source) - 1, count)
        return np.interp(positions, np.arange(len(source)), source).astype("<i2").tobytes()

    @staticmethod
    def _scale_and_pad(frame: VideoFrame, width: int, height: int) -> bytes:
        from PIL import Image
        image = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb)
        ratio = min(width / frame.width, height / frame.height)
        scaled = (max(1, round(frame.width * ratio)), max(1, round(frame.height * ratio)))
        image = image.resize(scaled, Image.Resampling.BILINEAR)
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        canvas.paste(image, ((width - scaled[0]) // 2, (height - scaled[1]) // 2))
        return canvas.tobytes()

    async def push_audio(self, chunk: AudioChunk) -> None:
        if not self.running or chunk.generation_id != self.generation_id:
            return
        if self.timeline_v2:
            await self._timeline_audio.push(chunk, lambda: self.running and chunk.generation_id == self.generation_id)
            self.audio_enqueued = self._timeline_audio.enqueued
            self.audio_enqueued_total = self._timeline_audio.total_enqueued
            return
        if chunk.channels != 1:
            raise ValueError("RTMP audio input requires mono PCM")
        pcm = self._resample_mono(chunk.pcm, chunk.sample_rate, self.settings.audio_sample_rate)
        self._audio_pending.extend(pcm)
        frame_bytes = self.settings.audio_sample_rate * self.audio_frame_ms // 1000 * 2
        while len(self._audio_pending) >= frame_bytes:
            payload = bytes(self._audio_pending[:frame_bytes])
            del self._audio_pending[:frame_bytes]
            if chunk.generation_id != self.generation_id:
                return
            self.audio_enqueued += 1
            self.audio_enqueued_total += 1
            await self.audio_queue.put((chunk.generation_id, payload))

    async def push_video(self, frame: VideoFrame) -> None:
        if not self.running or frame.generation_id != self.generation_id:
            return
        payload = await asyncio.to_thread(
            self._scale_and_pad, frame, self.settings.width, self.settings.height
        )
        if frame.generation_id != self.generation_id:
            return
        self.video_enqueued += 1
        self.video_enqueued_total += 1
        await self.video_queue.put((frame.generation_id, payload, frame) if self.timeline_v2 else (frame.generation_id, payload))
        if frame.generation_id != self.generation_id:
            # Dequeue also rechecks the fence; no old generation pipe handoff.
            return

    async def _wait_writable(self, fd: int) -> None:
        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        loop.add_writer(fd, ready.set_result, None)
        try:
            await ready
        finally:
            loop.remove_writer(fd)

    async def _write_fd(self, fd: int | None, payload: bytes) -> None:
        if fd is None:
            return
        view = memoryview(payload)
        while view and self.running:
            try:
                written = os.write(fd, view)
                view = view[written:]
            except BlockingIOError:
                await asyncio.wait_for(self._wait_writable(fd), 5.0)
            except (BrokenPipeError, OSError):
                self.write_failures += 1
                return

    async def _audio_clock(self) -> None:
        if self.timeline_v2:
            await self._timeline_audio_clock()
            return
        samples = self.settings.audio_sample_rate * self.audio_frame_ms // 1000
        silence = bytes(samples * 2)
        period = self.audio_frame_ms / 1000
        next_at = time.monotonic()
        while self.running:
            now = time.monotonic()
            await asyncio.sleep(max(0, next_at - now))
            next_at += period
            if next_at < time.monotonic() - period:
                next_at = time.monotonic() + period
            payload = silence
            try:
                generation_id, queued = self.audio_queue.get_nowait()
                self.audio_queue.task_done()
                if generation_id == self.generation_id:
                    payload = queued
                    self.audio_consumed += 1
                    self.audio_consumed_total += 1
                else:
                    self.audio_dropped += 1
            except asyncio.QueueEmpty:
                pass
            try:
                await self._write_fd(self._audio_fd, payload)
            except asyncio.TimeoutError:
                self.write_failures += 1
                await self._abort_process("audio_write_timeout")

    async def _video_clock(self) -> None:
        if self.timeline_v2:
            await self._timeline_video_clock()
            return
        period = 1 / self.settings.fps
        next_at = time.monotonic()
        while self.running:
            now = time.monotonic()
            await asyncio.sleep(max(0, next_at - now))
            next_at += period
            if next_at < time.monotonic() - period:
                next_at = time.monotonic() + period
            delivery = None
            try:
                generation_id, queued = self.video_queue.get_nowait()
                self.video_queue.task_done()
                if generation_id == self.generation_id:
                    self._latest_video = queued
                    self.video_consumed += 1
                    self.video_consumed_total += 1
                    delivery = (generation_id, self.video_consumed)
                else:
                    self.video_dropped += 1
            except asyncio.QueueEmpty:
                pass
            try:
                fd, failures = self._video_fd, self.write_failures
                await self._write_fd(fd, self._latest_video)
                if (delivery and fd is not None and self.running
                        and self._video_fd == fd and self.write_failures == failures
                        and delivery[0] == self.generation_id):
                    self.video_written = delivery[1]
            except asyncio.TimeoutError:
                self.write_failures += 1
                await self._abort_process("video_write_timeout")

    def video_delivery_position(self) -> tuple[int, int] | None:
        """Private sink credit after a complete pipe write, not platform readiness."""
        if self.running and self._process and self._process.returncode is None:
            return self.generation_id, self.video_written
        return None

    async def _abort_process(self, reason: str) -> None:
        process = self._process
        if process and process.returncode is None:
            self._warn({"code": "RTMP_OUTPUT_FAILED", "reason": reason})
            process.terminate()

    async def drain(self, generation_id: int) -> None:
        if generation_id != self.generation_id:
            return
        if self.timeline_v2:
            await self._timeline_audio.flush(lambda: self.running and generation_id == self.generation_id)
            self.audio_enqueued = self._timeline_audio.enqueued
            self.audio_enqueued_total = self._timeline_audio.total_enqueued
            target_audio, target_video = self.audio_enqueued, self.video_enqueued
            deadline = time.monotonic() + 20
            while generation_id == self.generation_id and self.running:
                if self.audio_consumed + self.audio_retired >= target_audio and self.video_resolved >= target_video:
                    return
                if time.monotonic() >= deadline:
                    raise TimeoutError("RTMP V2 sink drain timed out")
                await asyncio.sleep(.02)
            return
        if self._audio_pending:
            frame_bytes = self.settings.audio_sample_rate * self.audio_frame_ms // 1000 * 2
            self.audio_enqueued += 1
            self.audio_enqueued_total += 1
            await self.audio_queue.put(
                (generation_id, bytes(self._audio_pending).ljust(frame_bytes, b"\0"))
            )
            self._audio_pending.clear()
        audio_target, video_target = self.audio_enqueued, self.video_enqueued
        deadline = time.monotonic() + 20
        while generation_id == self.generation_id and self.running:
            if self.audio_consumed >= audio_target and self.video_consumed >= video_target:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("RTMP media drain timed out")
            await asyncio.sleep(0.02)

    async def interrupt(self, generation_id: int) -> None:
        self.generation_id = generation_id
        self.audio_enqueued = self.audio_consumed = 0
        self.video_enqueued = self.video_consumed = 0
        self.video_written = 0
        if self.timeline_v2:
            self._timeline_audio.generation_id = generation_id
            self._timeline_audio.enqueued = self._timeline_audio.consumed = 0
            from .media_timeline import RationalResampler
            self._timeline_audio.resampler = RationalResampler(self.settings.audio_sample_rate)
            self._timeline_audio.resample_origin = self._timeline_audio.source_cursor
            self._timeline_audio.pending_identity = None
            self._video_dispositions.clear()
            self.video_resolved = 0
            self.audio_retired = 0
        self._audio_pending.clear()
        self._latest_video = self._blank_frame()
        for queue, media in ((self.audio_queue, "audio"), (self.video_queue, "video")):
            while not queue.empty():
                queue.get_nowait()
                queue.task_done()
                if media == "audio":
                    self.audio_dropped += 1
                else:
                    self.video_dropped += 1

    async def _timeline_audio_clock(self):
        samples = self.settings.audio_sample_rate // 50
        next_at = time.monotonic()
        while self.running:
            await asyncio.sleep(max(0, next_at - time.monotonic()))
            next_at = max(next_at + .02, time.monotonic())
            payload, metadata = bytes(samples * 2), None
            if self._audio_fd is not None:
                while not self.audio_queue.empty():
                    generation, queued, start, end, identity = self.audio_queue.get_nowait()
                    self.audio_queue.task_done()
                    timeline = self.timeline_clock.timeline
                    if generation != self.generation_id or (timeline and not timeline.eligible(identity, start, end)):
                        self.audio_dropped += 1
                        continue
                    payload, metadata = queued, (generation, start, end, identity)
                    break
            fd, failures, incarnation = self._audio_fd, self.write_failures, self.connection_incarnation
            if metadata:
                self.timeline_in_flight["audio"] = {"identity": metadata[3], "startSample": metadata[1], "endSample": metadata[2]}
            try:
                await self._write_fd(fd, payload)
                if (fd is not None and fd == self._audio_fd and failures == self.write_failures and
                        incarnation == self.connection_incarnation and self.running):
                    valid = metadata and metadata[0] == self.generation_id and (
                        self.timeline_clock.timeline is None or self.timeline_clock.timeline.eligible(
                            metadata[3], metadata[1], metadata[2]))
                    if metadata and not valid:
                        self.cancelled_in_flight += 1
                    self.timeline_clock.advance(samples, metadata[2] if valid else None)
                    if valid:
                        self.audio_consumed += 1
                        self.audio_consumed_total += 1
                        self._timeline_audio.last_recv_monotonic = time.monotonic()
                        timeline = self.timeline_clock.timeline
                        if timeline:
                            timeline.observe_sink_progress(metadata[3], f"rtmp:{incarnation}", "audio", metadata[1], metadata[2])
            except asyncio.TimeoutError:
                self.write_failures += 1
                await self._abort_process("audio_write_timeout")
            finally:
                self.timeline_in_flight.pop("audio", None)

    async def _timeline_video_clock(self):
        clock = self.timeline_clock
        while self.running:
            incarnation = self.connection_incarnation
            await clock.wait_video_tick(self._video_tick, self.settings.fps,
                                        lambda: self.running and incarnation == self.connection_incarnation)
            if not self.running:
                return
            if incarnation != self.connection_incarnation:
                continue
            selected = None
            while not self.video_queue.empty():
                generation, payload, frame = self.video_queue._queue[0]
                sample = getattr(frame, "sourceSample", frame.pts_us * clock.source_rate // 1000000)
                end = sample + clock.source_rate // self.settings.fps
                if clock.timeline and getattr(frame, "identity", None):
                    commit = clock.timeline.commits.get(frame.identity.segmentId)
                    if commit:
                        end = min(end, commit.end)
                if generation != self.generation_id or not clock.accepts(frame, sample, end):
                    self.video_queue.get_nowait(); self.video_queue.task_done()
                    self.video_dropped += 1
                    self._dispose_video(frame, "fenced")
                    continue
                action = clock.video_action(sample)
                if action == "wait":
                    break
                self.video_queue.get_nowait(); self.video_queue.task_done()
                if action == "drop":
                    self.video_dropped += 1
                    clock.video_late_drops += 1
                    self._dispose_video(frame, "dropped")
                    continue
                self._latest_video = payload
                selected = (frame, sample, end)
                break
            if selected is None:
                clock.video_holds += 1
            fd, failures = self._video_fd, self.write_failures
            if selected:
                self.timeline_in_flight["video"] = {"identity": getattr(selected[0], "identity", None),
                    "startSample": selected[1], "endSample": selected[2]}
            try:
                await self._write_fd(fd, self._latest_video)
                if (selected and fd is not None and fd == self._video_fd and self.running and
                        failures == self.write_failures and incarnation == self.connection_incarnation and
                        selected[0].generation_id == self.generation_id and clock.accepts(selected[0], selected[1], selected[2])):
                    self.video_consumed += 1
                    self.video_consumed_total += 1
                    self.video_written = self.video_consumed
                    self._dispose_video(selected[0], "consumed")
                    if clock.timeline:
                        clock.timeline.observe_sink_progress(selected[0].identity, f"rtmp:{incarnation}", "video", selected[1], selected[2])
            except asyncio.TimeoutError:
                self.write_failures += 1
                await self._abort_process("video_write_timeout")
            finally:
                self.timeline_in_flight.pop("video", None)
            self._video_tick += 1

    async def _close_input_fds(self) -> None:
        async with self._process_lock:
            for name in ("_video_fd", "_audio_fd"):
                fd = getattr(self, name)
                setattr(self, name, None)
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    async def stop(self) -> None:
        if not self.running:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(self.audio_queue.join(), self.video_queue.join()),
                max(self.settings.audio_buffer_ms, self.settings.video_buffer_ms) / 1000 + 1,
            )
        except asyncio.TimeoutError:
            pass
        self.running = False
        self._stop_event.set()
        for task in (self._audio_clock_task, self._video_clock_task):
            if task:
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._audio_clock_task, self._video_clock_task) if task),
            return_exceptions=True,
        )
        await self._close_input_fds()
        process = self._process
        if process and process.returncode is None:
            timeout = self.settings.stop_timeout_ms / 1000
            try:
                await asyncio.wait_for(process.wait(), timeout)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        if self._supervisor_task:
            await asyncio.gather(self._supervisor_task, return_exceptions=True)
        if self._stderr_task:
            await asyncio.gather(self._stderr_task, return_exceptions=True)
        log.info("rtmp_output_stopped target=%s", self.settings.redacted_target)

    def diagnostics(self) -> dict:
        process = self._process
        return {
            **({"mediaTimeline": self.timeline_clock.snapshot(),
                "adaptiveTargetMs": self._timeline_audio.adaptive.target_ms,
                "pendingSamples": len(self._audio_pending) // 2,
                "inFlight": self.timeline_progress()["inFlight"],
                "cancelledInFlight": self.cancelled_in_flight,
                "connectionIncarnation": self.connection_incarnation}
               if self.timeline_v2 else {}),
            "enabled": self.settings.enabled,
            "running": self.running,
            "connected": None,  # Process liveness does not prove platform acceptance.
            "ffmpegPid": process.pid if process and process.returncode is None else None,
            "audioQueueMs": self.audio_queue.qsize() * self.audio_frame_ms,
            "videoQueueMs": round(self.video_queue.qsize() * 1000 / self.settings.fps, 1),
            "lastError": self.settings.redact(self.stderr_lines[-1]) if self.stderr_lines else None,
            "pid": process.pid if process and process.returncode is None else None,
            "returnCode": process.returncode if process else None,
            "processStarts": self.process_starts,
            "reconnectCount": self.reconnect_count,
            "targetFps": self.settings.fps,
            "resolution": f"{self.settings.width}x{self.settings.height}",
            "audioSampleRate": self.settings.audio_sample_rate,
            "audioQueueSize": self.audio_queue.qsize(),
            "audioQueueMax": self.audio_queue.maxsize,
            "videoQueueSize": self.video_queue.qsize(),
            "videoQueueMax": self.video_queue.maxsize,
            "audioEnqueued": self.audio_enqueued,
            "audioConsumed": self.audio_consumed,
            "videoEnqueued": self.video_enqueued,
            "videoConsumed": self.video_consumed,
            "audioEnqueuedTotal": self.audio_enqueued_total,
            "audioConsumedTotal": self.audio_consumed_total,
            "videoEnqueuedTotal": self.video_enqueued_total,
            "videoConsumedTotal": self.video_consumed_total,
            "audioDropped": self.audio_dropped,
            "videoDropped": self.video_dropped,
            "writeFailures": self.write_failures,
            "stderrTail": [self.settings.redact(line) for line in list(self.stderr_lines)[-20:]],
        }
