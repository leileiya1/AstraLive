"""Isolated, bounded fanout for independent media sinks."""
import asyncio
from dataclasses import dataclass, field
import logging
import math
from typing import Awaitable, Callable

from .drop_rate import DropRateMonitor
from .providers import AudioChunk, MediaDeliveryError, MediaOutput, VideoFrame


log = logging.getLogger(__name__)
WarningHandler = Callable[[dict], Awaitable[None]]


@dataclass
class _SinkChannel:
    name: str
    output: MediaOutput
    audio: asyncio.Queue
    video: asyncio.Queue
    tasks: tuple[asyncio.Task, asyncio.Task] | None = None
    running: bool = False
    failed_pushes: int = 0
    audio_dropped: int = 0
    video_dropped: int = 0
    rates: dict = field(default_factory=lambda: {"audio": DropRateMonitor(), "video": DropRateMonitor()})


class FanoutMediaOutput:
    """Dispatches each sink through separate time-bounded audio/video queues.

    A slow or failed sink can drop its own stale media, but cannot block another
    sink's playback clock or lifecycle.
    """

    def __init__(self, sinks: list[tuple[str, MediaOutput]], fps: int = 25,
                 video_buffer_ms: int = 400, audio_buffer_ms: int = 400) -> None:
        if not sinks:
            raise ValueError("At least one media sink is required")
        video_capacity = max(1, math.ceil(fps * video_buffer_ms / 1000))
        audio_capacity = max(1, math.ceil(audio_buffer_ms / 20))
        self.channels = [
            _SinkChannel(name, output, asyncio.Queue(audio_capacity), asyncio.Queue(video_capacity))
            for name, output in sinks
        ]
        self.generation_id = 1
        self.running = False
        self.warnings: list[dict] = []
        self.warning_handler: WarningHandler | None = None
        self.drain_timeout = 20.0

    def configure_session(self, config) -> None:
        for channel in self.channels:
            channel.output.configure_session(config)

    def set_warning_handler(self, handler: WarningHandler) -> None:
        self.warning_handler = handler
        for channel in self.channels:
            setter = getattr(channel.output, "set_warning_handler", None)
            if setter:
                setter(handler)

    def _warn(self, warning: dict) -> None:
        self.warnings.append(warning)
        log.warning("media_sink_warning %s", warning)
        if self.warning_handler:
            asyncio.create_task(self.warning_handler(warning))

    def record_render_ms(self, render_ms: float) -> None:
        for channel in self.channels:
            recorder = getattr(channel.output, "record_render_ms", None)
            if recorder:
                recorder(render_ms)

    async def start(self) -> None:
        started: list[_SinkChannel] = []
        try:
            for channel in self.channels:
                await channel.output.start()
                channel.running = True
                channel.tasks = (
                    asyncio.create_task(self._audio_worker(channel), name=f"media-{channel.name}-audio"),
                    asyncio.create_task(self._video_worker(channel), name=f"media-{channel.name}-video"),
                )
                started.append(channel)
            self.running = True
        except Exception:
            for channel in reversed(started):
                await channel.output.stop()
            raise

    async def _audio_worker(self, channel: _SinkChannel) -> None:
        while channel.running:
            chunk = await channel.audio.get()
            try:
                if chunk.generation_id == self.generation_id:
                    await channel.output.push_audio(chunk)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                channel.failed_pushes += 1
                self._warn({"code": "MEDIA_SINK_DEGRADED", "sink": channel.name,
                            "media": "audio", "errorType": type(exc).__name__})
            finally:
                channel.audio.task_done()

    async def _video_worker(self, channel: _SinkChannel) -> None:
        while channel.running:
            frame = await channel.video.get()
            try:
                if frame.generation_id == self.generation_id:
                    await channel.output.push_video(frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                channel.failed_pushes += 1
                self._warn({"code": "MEDIA_SINK_DEGRADED", "sink": channel.name,
                            "media": "video", "errorType": type(exc).__name__})
            finally:
                channel.video.task_done()

    def _drop_and_offer(self, channel: _SinkChannel, queue: asyncio.Queue, item, media: str) -> None:
        try:
            queue.get_nowait()
            queue.task_done()
        except asyncio.QueueEmpty:
            pass
        if media == "audio":
            channel.audio_dropped += 1
        else:
            channel.video_dropped += 1
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            return
        channel.rates[media].drop()
        log.debug("media_sink_backpressure_drop sink=%s media=%s", channel.name, media)

    async def _dispatch(self, item, media: str) -> None:
        active = [channel for channel in self.channels if channel.running]
        queues = [(channel, channel.audio if media == "audio" else channel.video) for channel in active]
        full = []
        accepted = False
        for channel, queue in queues:
            warning = channel.rates[media].offer()
            if warning:
                self._warn({"code": "MEDIA_SINK_BACKPRESSURE_DROP", "sink": channel.name,
                            "media": media, **warning})
            try:
                queue.put_nowait(item)
                accepted = True
            except asyncio.QueueFull:
                full.append((channel, queue))
        if accepted:
            if item.generation_id != self.generation_id:
                return
            for channel, queue in full:
                self._drop_and_offer(channel, queue, item, media)
            return
        if not full:
            return
        # Pace the producer by the fastest live sink. A stalled sink is allowed
        # to drop only its own stale item and cannot hold the other sinks back.
        pending = {asyncio.create_task(queue.put(item)): (channel, queue) for channel, queue in full}
        done, waiting = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        if waiting:
            grace = 0.04 if media == "audio" else 0.08
            also_done, waiting = await asyncio.wait(waiting, timeout=grace)
            done.update(also_done)
        for task in waiting:
            task.cancel()
        if waiting:
            await asyncio.gather(*waiting, return_exceptions=True)
        for task in done:
            task.result()
        completed_channels = {
            id(channel) for task, (channel, _) in pending.items()
            if not task.cancelled() and task.done() and task.exception() is None
        }
        if item.generation_id != self.generation_id:
            for _, queue in queues:
                kept = []
                while not queue.empty():
                    queued = queue.get_nowait()
                    queue.task_done()
                    if queued.generation_id == self.generation_id:
                        kept.append(queued)
                for queued in kept:
                    queue.put_nowait(queued)
            return
        for task, (channel, queue) in pending.items():
            if id(channel) not in completed_channels:
                self._drop_and_offer(channel, queue, item, media)

    async def push_audio(self, chunk: AudioChunk) -> None:
        if self.running and chunk.generation_id == self.generation_id:
            await self._dispatch(chunk, "audio")

    async def push_video(self, frame: VideoFrame) -> None:
        if self.running and frame.generation_id == self.generation_id:
            await self._dispatch(frame, "video")

    async def drain(self, generation_id: int) -> None:
        if generation_id != self.generation_id or not self.running:
            return
        results = []
        for channel in self.channels:
            try:
                await asyncio.wait_for(
                    asyncio.gather(channel.audio.join(), channel.video.join()), self.drain_timeout
                )
                await channel.output.drain(generation_id)
                results.append(True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                results.append(False)
                diagnostic = getattr(channel.output, "diagnostics", lambda: {})()
                self._warn({"code": "MEDIA_SINK_DRAIN_FAILED", "sink": channel.name,
                            "errorType": type(exc).__name__, "diagnostics": diagnostic})
        if results and not any(results):
            raise MediaDeliveryError("All media sinks failed to drain")

    async def create_answer(self, offer_sdp: str) -> str:
        for channel in self.channels:
            create_answer = getattr(channel.output, "create_answer", None)
            if create_answer:
                return await create_answer(offer_sdp)
        raise RuntimeError("WebRTC media output is unavailable")

    async def interrupt(self, generation_id: int) -> None:
        self.generation_id = generation_id
        for channel in self.channels:
            for queue in (channel.audio, channel.video):
                while not queue.empty():
                    queue.get_nowait()
                    queue.task_done()
        await asyncio.gather(
            *(channel.output.interrupt(generation_id) for channel in self.channels),
            return_exceptions=True,
        )

    def pop_warnings(self) -> list[dict]:
        warnings, self.warnings = self.warnings, []
        for channel in self.channels:
            pop = getattr(channel.output, "pop_warnings", None)
            if pop:
                warnings.extend(pop())
        return [] if self.warning_handler else warnings

    def diagnostics(self) -> dict:
        return {
            channel.name: {
                "audioQueueSize": channel.audio.qsize(),
                "audioQueueMax": channel.audio.maxsize,
                "videoQueueSize": channel.video.qsize(),
                "videoQueueMax": channel.video.maxsize,
                "audioDropped": channel.audio_dropped,
                "videoDropped": channel.video_dropped,
                "audioDropRate": channel.rates["audio"].rate,
                "videoDropRate": channel.rates["video"].rate,
                "failedPushes": channel.failed_pushes,
                "sink": getattr(channel.output, "diagnostics", lambda: {})(),
            }
            for channel in self.channels
        }

    async def stop(self) -> None:
        self.running = False
        for channel in self.channels:
            channel.running = False
            if channel.tasks:
                for task in channel.tasks:
                    task.cancel()
        tasks = [task for channel in self.channels for task in (channel.tasks or ())]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(channel.output.stop() for channel in self.channels), return_exceptions=True)
