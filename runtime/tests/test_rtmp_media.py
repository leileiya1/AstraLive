import os
import json
import unittest
from unittest.mock import patch

from app.config import RTMPSettings
from app.providers import AudioChunk, VideoFrame
from app.rtmp_media import FFmpegRTMPMediaOutput


class RTMPSettingsTests(unittest.TestCase):
    def test_secret_is_only_present_in_private_target(self):
        settings = RTMPSettings(enabled=True, url="rtmp://localhost/live", stream_key="secret-key")
        self.assertEqual(settings.target, "rtmp://localhost/live/secret-key")
        self.assertEqual(settings.redacted_target, "rtmp://localhost/***")
        self.assertNotIn("secret-key", settings.redacted_target)

    def test_enabled_requires_target_and_even_dimensions(self):
        with patch.dict(os.environ, {"RTMP_ENABLED": "true"}, clear=True):
            with self.assertRaises(ValueError):
                RTMPSettings.from_env()
        with patch.dict(os.environ, {
            "RTMP_ENABLED": "true", "RTMP_URL": "rtmp://localhost/live",
            "RTMP_STREAM_KEY": "fake", "RTMP_WIDTH": "721",
        }, clear=True):
            with self.assertRaises(ValueError):
                RTMPSettings.from_env()


class RTMPMediaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = RTMPSettings(
            enabled=True, url="rtmp://localhost/live", stream_key="fake",
            width=8, height=12, fps=25, audio_sample_rate=48000,
            video_buffer_ms=80, audio_buffer_ms=80,
        )
        self.output = FFmpegRTMPMediaOutput(self.settings)

    def test_scale_and_pad_preserves_aspect_ratio(self):
        # 4x4 white square centered in an 8x12 black portrait canvas.
        frame = VideoFrame(1, 0, 4, 4, bytes([255]) * 4 * 4 * 3)
        result = self.output._scale_and_pad(frame, 8, 12)
        self.assertEqual(len(result), 8 * 12 * 3)
        self.assertEqual(result[:8 * 2 * 3], bytes(8 * 2 * 3))
        self.assertEqual(result[8 * 2 * 3:8 * 3 * 3], bytes([255]) * 8 * 3)

    def test_resample_produces_48khz_duration(self):
        pcm = b"\0\0" * 320  # 20 ms at 16 kHz.
        result = self.output._resample_mono(pcm, 16000, 48000)
        self.assertEqual(len(result), 960 * 2)

    def test_diagnostics_are_json_serializable_with_stderr_tail(self):
        self.output.stderr_lines.extend(["first", "second"])
        diagnostic = self.output.diagnostics()
        self.assertEqual(diagnostic["stderrTail"], ["first", "second"])
        json.dumps(diagnostic)

    async def test_interrupt_keeps_process_identity_and_clears_media(self):
        self.output.running = True
        marker = object()
        self.output._process = marker
        await self.output.audio_queue.put((1, b"old"))
        await self.output.video_queue.put((1, b"old"))
        self.output._latest_video = b"old"
        await self.output.interrupt(2)
        self.assertIs(self.output._process, marker)
        self.assertTrue(self.output.audio_queue.empty())
        self.assertTrue(self.output.video_queue.empty())
        self.assertEqual(self.output._latest_video, self.output._blank_frame())
        self.assertEqual(self.output.audio_enqueued, 0)
        self.assertEqual(self.output.audio_consumed, 0)
        self.assertEqual(self.output.video_enqueued, 0)
        self.assertEqual(self.output.video_consumed, 0)

    async def test_audio_and_video_buffers_are_time_bounded(self):
        self.assertEqual(self.output.audio_queue.maxsize, 4)
        self.assertEqual(self.output.video_queue.maxsize, 2)
        self.output.running = True
        await self.output.push_audio(AudioChunk(1, 0, b"\0\0" * 320, 16000, 1))
        self.assertEqual(self.output.audio_queue.qsize(), 1)


if __name__ == "__main__":
    unittest.main()
