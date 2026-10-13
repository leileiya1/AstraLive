"""Headless FFmpeg RTMP sink with continuous audio/video clocks."""
import asyncio
from collections import deque
import logging
import math
import os
import shutil
import time
from typing import Awaitable, Callable

from .config import RTMPSettings
from .providers import AudioChunk, VideoFrame


log = logging.getLogger(__name__)
WarningHandler = Callable[[dict], Awaitable[None]]


class FFmpegRTMPMediaOutput:
    audio_frame_ms = 20

    def __init__(self, settings: RTMPSettings | None = None) -> None:
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
        self.audio_enqueued_total = 0
        self.audio_consumed_total = 0
        self.video_enqueued_total = 0
        self.video_consumed_total = 0
        self.audio_dropped = 0
        self.video_dropped = 0
        self.write_failures = 0
        self.started_monotonic: float | None = None
        self.last_process_started_monotonic: float | None = None

    def configure_session(self, config) -> None:
        # RTMP owns its output dimensions and clock; Session config is input metadata.
        return None

    def set_warning_handler(self, handler: WarningHandler) -> None:
        self.warning_handler = handler

    def _warn(self, warning: dict) -> None:
        self.warnings.append(warning)
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
        await self.video_queue.put((frame.generation_id, payload))

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
        period = 1 / self.settings.fps
        next_at = time.monotonic()
        while self.running:
            now = time.monotonic()
            await asyncio.sleep(max(0, next_at - now))
            next_at += period
            if next_at < time.monotonic() - period:
                next_at = time.monotonic() + period
            try:
                generation_id, queued = self.video_queue.get_nowait()
                self.video_queue.task_done()
                if generation_id == self.generation_id:
                    self._latest_video = queued
                    self.video_consumed += 1
                    self.video_consumed_total += 1
                else:
                    self.video_dropped += 1
            except asyncio.QueueEmpty:
                pass
            try:
                await self._write_fd(self._video_fd, self._latest_video)
            except asyncio.TimeoutError:
                self.write_failures += 1
                await self._abort_process("video_write_timeout")

    async def _abort_process(self, reason: str) -> None:
        process = self._process
        if process and process.returncode is None:
            self._warn({"code": "RTMP_OUTPUT_FAILED", "reason": reason})
            process.terminate()

    async def drain(self, generation_id: int) -> None:
        if generation_id != self.generation_id:
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
