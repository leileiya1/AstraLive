#!/usr/bin/env python3
"""Real MediaMTX outage/reconnect test with an independent healthy sink."""
import asyncio
import json
import time

from runtime.app.config import RTMPSettings
from runtime.app.media_fanout import FanoutMediaOutput
from runtime.app.providers import AudioChunk, VideoFrame
from runtime.app.rtmp_media import FFmpegRTMPMediaOutput


class CountingSink:
    def __init__(self):
        self.generation_id = 1
        self.audio = 0
        self.video = 0
        self.running = False
    def configure_session(self, config): pass
    async def start(self): self.running = True
    async def push_audio(self, chunk): self.audio += 1
    async def push_video(self, frame): self.video += 1
    async def drain(self, generation_id): pass
    async def interrupt(self, generation_id): self.generation_id = generation_id
    async def stop(self): self.running = False


async def compose(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", "infra/rtmp/compose.yaml", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, error = await process.communicate()
    if process.returncode:
        raise RuntimeError("MediaMTX lifecycle command failed: " + error.decode("utf-8", "replace"))


async def wait_for(condition, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.2)
    raise TimeoutError("condition did not become true")


async def publisher_ready() -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-t", "0.25",
            "-i", "rtmp://127.0.0.1:1935/live/astralive-test", "-f", "null", "-",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), 4)
        return process.returncode == 0
    except Exception:
        return False


async def wait_for_publisher(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await publisher_ready():
            return
        await asyncio.sleep(0.25)
    raise TimeoutError("RTMP publisher did not recover")


async def main() -> None:
    await compose("up", "-d")
    settings = RTMPSettings(
        enabled=True, url="rtmp://127.0.0.1:1935/live", stream_key="astralive-test",
        width=720, height=1280, fps=25, video_buffer_ms=400, audio_buffer_ms=400,
        reconnect_initial_ms=250, reconnect_max_ms=1000, recovery_window_ms=5000,
    )
    rtmp = FFmpegRTMPMediaOutput(settings)
    preview = CountingSink()
    fanout = FanoutMediaOutput([("preview", preview), ("rtmp", rtmp)], fps=25)
    try:
        await fanout.start()
        frame = VideoFrame(1, 0, 16, 16, bytes([80, 120, 220]) * 16 * 16)
        await fanout.push_video(frame)
        await fanout.push_audio(AudioChunk(1, 0, b"\0\0" * 320, 16000, 1))
        await wait_for_publisher()
        initial_pid = rtmp.diagnostics()["pid"]
        preview_before = (preview.audio, preview.video)
        await compose("stop", "mediamtx")
        await wait_for(lambda: rtmp.diagnostics()["processStarts"] >= 2)
        for sequence in range(1, 31):
            await fanout.push_audio(AudioChunk(1, sequence, b"\0\0" * 320, 16000, 1))
            await fanout.push_video(frame)
        preview_during_outage = (preview.audio, preview.video)
        await compose("start", "mediamtx")
        await wait_for_publisher(45)
        recovered_pid = rtmp.diagnostics()["pid"]
        result = {
            "initialPid": initial_pid,
            "recoveredPid": recovered_pid,
            "pidChangedAfterFailure": initial_pid != recovered_pid,
            "processStarts": rtmp.process_starts,
            "reconnectCount": rtmp.reconnect_count,
            "previewBeforeOutage": preview_before,
            "previewDuringOutage": preview_during_outage,
            "previewContinued": preview_during_outage[0] > preview_before[0]
                                and preview_during_outage[1] > preview_before[1],
            "publisherRecovered": await publisher_ready(),
            "diagnostics": fanout.diagnostics(),
        }
        assert result["pidChangedAfterFailure"]
        assert result["reconnectCount"] >= 1
        assert result["previewContinued"]
        assert result["publisherRecovered"]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await fanout.stop()
        await compose("up", "-d")


if __name__ == "__main__":
    asyncio.run(main())
