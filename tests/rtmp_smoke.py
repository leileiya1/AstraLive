#!/usr/bin/env python3
"""Short real FFmpeg/RTMP smoke. Uses only the local fake ingest path."""
import asyncio
import json
import math
from pathlib import Path
import struct
import tempfile
import time

from runtime.app.config import RTMPSettings
from runtime.app.providers import AudioChunk, VideoFrame
from runtime.app.rtmp_media import FFmpegRTMPMediaOutput


def tone(sample_rate: int, seconds: float, frequency: float = 440) -> bytes:
    return b"".join(
        struct.pack("<h", round(math.sin(2 * math.pi * frequency * i / sample_rate) * 8000))
        for i in range(round(sample_rate * seconds))
    )


async def main() -> None:
    settings = RTMPSettings(
        enabled=True,
        url="rtmp://127.0.0.1:1935/live",
        stream_key="astralive-test",
        width=720,
        height=1280,
        fps=25,
        video_bitrate="3000k",
        audio_bitrate="128k",
        audio_sample_rate=48000,
        preset="veryfast",
        video_buffer_ms=400,
        audio_buffer_ms=400,
    )
    output = FFmpegRTMPMediaOutput(settings)
    started = time.monotonic()
    await output.start()
    initial_pid = output.diagnostics()["pid"]
    rgb = bytes([36, 180, 100]) * (256 * 256)
    pcm = tone(16000, 1.0)
    for sequence in range(50):
        start = sequence * 640
        await output.push_audio(AudioChunk(1, sequence, pcm[start:start + 640], 16000, 1))
        if sequence % 2 == 0:
            await output.push_video(VideoFrame(1, sequence * 20000, 256, 256, rgb))
    await output.drain(1)
    # Allow FFmpeg to finish input discovery, encode the first keyframe and
    # register the publisher before the reader connects.
    await asyncio.sleep(2)
    with tempfile.TemporaryDirectory(prefix="astralive-rtmp-smoke-") as directory:
        capture = Path(directory) / "capture.flv"
        recorder = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-t", "6",
            "-i", settings.target, "-c", "copy", str(capture),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, recorder_error = await asyncio.wait_for(recorder.communicate(), 15)
        if recorder.returncode:
            raise RuntimeError("RTMP capture failed: " + recorder_error.decode("utf-8", "replace"))
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(capture),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        probe_output, probe_error = await asyncio.wait_for(probe.communicate(), 10)
        if probe.returncode:
            raise RuntimeError("ffprobe failed: " + probe_error.decode("utf-8", "replace"))
        ffprobe = json.loads(probe_output)
    final_pid = output.diagnostics()["pid"]
    diagnostics = output.diagnostics()
    await output.stop()
    streams = {stream["codec_type"]: stream for stream in ffprobe["streams"]}
    summary = {
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "pidStable": initial_pid == final_pid,
        "initialPid": initial_pid,
        "finalPid": final_pid,
        "video": {
            "codec": streams["video"]["codec_name"],
            "pixelFormat": streams["video"]["pix_fmt"],
            "width": streams["video"]["width"],
            "height": streams["video"]["height"],
            "fps": streams["video"]["avg_frame_rate"],
        },
        "audio": {
            "codec": streams["audio"]["codec_name"],
            "sampleRate": streams["audio"]["sample_rate"],
            "channels": streams["audio"]["channels"],
        },
        "formatDuration": ffprobe["format"].get("duration"),
        "diagnostics": diagnostics,
        "ffmpegStopped": output._process is None or output._process.returncode is not None,
    }
    assert summary["pidStable"]
    assert summary["video"] == {
        "codec": "h264", "pixelFormat": "yuv420p", "width": 720,
        "height": 1280, "fps": "25/1",
    }
    assert summary["audio"]["codec"] == "aac"
    assert summary["audio"]["sampleRate"] == "48000"
    assert summary["audio"]["channels"] == 2
    assert diagnostics["processStarts"] == 1
    assert summary["ffmpegStopped"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
