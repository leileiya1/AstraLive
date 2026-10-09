"""Opt-in real LLM + real TTS + lightweight Avatar / Mock Media gate."""
import asyncio
import os
from pathlib import Path
import unittest
import httpx
from app.config import Settings
from app.events import MemoryEventPublisher
from app.main import create_app
from app.models import AvatarConfig, SessionConfig
from app.providers import AudioChunk


@unittest.skipUnless(os.getenv("RUN_REAL_AVATAR_INTEGRATION") == "1", "Set RUN_REAL_AVATAR_INTEGRATION=1")
class LightweightAvatarIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_clock_frames_and_interrupt(self):
        from app.lightweight_avatar import LightweightAvatarEngine
        engine = LightweightAvatarEngine(size=256)
        engine.configure_session(SessionConfig(fps=25, preview={"type": "WEBRTC"}))
        await engine.prepare(AvatarConfig(avatarId="a", engine="LIGHTWEIGHT"))
        await engine.start()
        import numpy as np
        pcm = (np.sin(np.linspace(0, 100, 16000)) * 8000).astype("<i2").tobytes()
        frames = await engine.push_audio(AudioChunk(1, 0, pcm, 16000, 1))
        self.assertEqual(len(frames), 25)
        self.assertEqual([f.pts_us for f in frames], list(range(0, 1_000_000, 40_000)))
        self.assertTrue(all(len(f.rgb) == 256 * 256 * 3 for f in frames))
        await engine.interrupt(2)
        self.assertEqual(await engine.push_audio(AudioChunk(1, 1, pcm)), [])
        self.assertTrue(await engine.push_audio(AudioChunk(2, 0, pcm)))
        preview = os.getenv("AVATAR_PREVIEW_PATH")
        if preview:
            from PIL import Image
            Image.frombytes("RGB", (256, 256), frames[0].rgb).save(preview)
        await engine.stop()

    async def test_internal_api_avatar_with_prior_real_providers(self):
        publisher = MemoryEventPublisher()
        app = create_app(Settings(mock_llm=False, mock_tts=False, mock_avatar=False), publisher)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
            create = {"commandId": "cmd_a1", "traceId": "trace_a1", "sessionId": "session_a1", "avatar": {"avatarId": "avatar_a1", "engine": "LIGHTWEIGHT"}, "voice": {"voiceId": "voice_a1", "provider": "SHERPA_ONNX"}, "config": {"fps": 25, "preview": {"type": "WEBRTC"}}, "context": {"roomId": "room_1", "systemPrompt": "你是直播间主持人。"}}
            self.assertEqual((await client.post("/internal/v1/sessions", json=create)).status_code, 202)
            for _ in range(100):
                if app.state.manager.get_session("session_a1").state == "READY":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual((await client.post("/internal/v1/sessions/session_a1/start", json={"commandId": "cmd_a2", "traceId": "trace_a1"})).status_code, 202)
            speak = {"commandId": "cmd_a3", "traceId": "trace_a1", "utteranceId": "utt_a1", "text": "请用一句话欢迎直播间观众。", "priority": 100, "interruptPolicy": "NONE", "source": "OPERATOR", "voice": {"voiceId": "voice_a1"}}
            self.assertEqual((await client.post("/internal/v1/sessions/session_a1/utterances", json=speak)).status_code, 202)
            for _ in range(150):
                names = [e["eventType"] for e in publisher.events]
                if "UTTERANCE_COMPLETED" in names or "UTTERANCE_FAILED" in names:
                    break
                await asyncio.sleep(0.1)
            self.assertIn("UTTERANCE_COMPLETED", names)
            session = app.state.manager.get_session("session_a1")
            self.assertGreater(len(session.media_output.video_frames), 0)
            self.assertGreater(len(session.media_output.received), 0)
            self.assertTrue(all(f.generation_id == session.generation_id for f in session.media_output.video_frames))
            self.assertEqual((await client.post("/internal/v1/sessions/session_a1/stop", json={"commandId": "cmd_a4", "traceId": "trace_a1"})).status_code, 202)
        await app.state.manager.close()
