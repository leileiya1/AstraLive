"""Opt-in real TTS / Mock LLM+Avatar+Media integration gate."""
import asyncio
import os
import time
import unittest
import httpx
from app.config import Settings
from app.events import MemoryEventPublisher
from app.main import create_app
from app.models import VoiceConfig
from app.providers import GenerationContext
from app.real_tts import SherpaOnnxTTSProvider


@unittest.skipUnless(os.getenv("RUN_REAL_TTS_INTEGRATION") == "1", "Set RUN_REAL_TTS_INTEGRATION=1")
class RealTTSIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_incremental_pcm(self):
        provider = SherpaOnnxTTSProvider(os.environ["TTS_MODEL_DIR"])
        start = time.monotonic()
        first = None
        chunks = []
        async for chunk in provider.synthesize_stream("欢迎大家来到直播间，今天介绍新款衣服。", VoiceConfig(voiceId="voice_1"), GenerationContext(1, "trace_1", "session_1", "utt_1")):
            if first is None:
                first = time.monotonic()
            chunks.append(chunk)
        end = time.monotonic()
        self.assertGreater(len(chunks), 1)
        self.assertLess(first, end)
        self.assertEqual([c.sequence for c in chunks], list(range(len(chunks))))
        self.assertTrue(all(c.sample_rate == 22050 and c.channels == 1 and len(c.pcm) % 2 == 0 for c in chunks))
        self.assertTrue(any(byte != 0 for c in chunks for byte in c.pcm))
        print(f"TTS first_chunk_ms={int((first-start)*1000)} total_ms={int((end-start)*1000)} chunks={len(chunks)}")

    async def test_stream_close_then_reuse(self):
        provider = SherpaOnnxTTSProvider(os.environ["TTS_MODEL_DIR"])
        ctx = GenerationContext(7, "trace_7", "session_7", "utt_7")
        long_text = "欢迎来到直播间，" * 12
        stream = provider.synthesize_stream(long_text, VoiceConfig(voiceId="voice_1"), ctx)
        first = await stream.__anext__()
        self.assertEqual(first.generation_id, 7)
        await asyncio.wait_for(stream.aclose(), 3)
        replacement = [c async for c in provider.synthesize_stream("大家好。", VoiceConfig(voiceId="voice_1"), GenerationContext(8, "trace_8", "session_7", "utt_8"))]
        self.assertTrue(replacement)
        self.assertTrue(all(c.generation_id == 8 for c in replacement))

    async def test_internal_api_real_tts(self):
        publisher = MemoryEventPublisher()
        combined = os.getenv("RUN_REAL_LLM_WITH_TTS") == "1"
        app = create_app(Settings(mock_llm=not combined, mock_tts=False), publisher)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
            body = {"commandId": "cmd_1", "traceId": "trace_1", "sessionId": "session_1", "avatar": {"avatarId": "avatar_1", "engine": "MOCK"}, "voice": {"voiceId": "voice_1", "provider": "MOCK"}, "config": {"fps": 25, "preview": {"type": "WEBRTC"}}, "context": {"roomId": "room_1", "systemPrompt": "你是直播间主持人。"}}
            self.assertEqual((await client.post("/internal/v1/sessions", json=body)).status_code, 202)
            for _ in range(100):
                if app.state.manager.get_session("session_1").state == "READY":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual((await client.post("/internal/v1/sessions/session_1/start", json={"commandId": "cmd_2", "traceId": "trace_1"})).status_code, 202)
            speak = {"commandId": "cmd_3", "traceId": "trace_1", "utteranceId": "utt_1", "text": "欢迎来到直播间。今天介绍新款衣服。", "priority": 100, "interruptPolicy": "NONE", "source": "OPERATOR", "voice": {"voiceId": "voice_1"}}
            self.assertEqual((await client.post("/internal/v1/sessions/session_1/utterances", json=speak)).status_code, 202)
            for _ in range(100):
                names = [e["eventType"] for e in publisher.events]
                if "UTTERANCE_COMPLETED" in names or "UTTERANCE_FAILED" in names:
                    break
                await asyncio.sleep(0.05)
            self.assertIn("UTTERANCE_COMPLETED", names)
            chunks = app.state.manager.get_session("session_1").media_output.received
            self.assertGreater(len(chunks), 1)
            self.assertEqual([c.sequence for c in chunks], list(range(len(chunks))))
            self.assertEqual((await client.post("/internal/v1/sessions/session_1/stop", json={"commandId": "cmd_4", "traceId": "trace_1"})).status_code, 202)
        await app.state.manager.close()
