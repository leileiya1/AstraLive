"""Opt-in real LLM / Mock TTS+Avatar+Media integration gate."""
import asyncio
import os
import unittest
import httpx
from app.config import Settings
from app.events import MemoryEventPublisher
from app.main import create_app
from app.providers import MockAvatarEngine, MockMediaOutput, MockTTSProvider, OpenAICompatibleLLMProvider


@unittest.skipUnless(os.getenv("RUN_REAL_LLM_INTEGRATION") == "1", "Set RUN_REAL_LLM_INTEGRATION=1")
class RealLLMIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_api_through_real_llm(self):
        base = os.environ["LLM_BASE_URL"]
        key = os.environ["LLM_API_KEY"]
        model = os.environ["LLM_MODEL"]
        publisher = MemoryEventPublisher()
        app = create_app(
            Settings(mock_llm=False), publisher,
            (lambda: OpenAICompatibleLLMProvider(base, key, model,
                                                  max_tokens=int(os.getenv("LLM_MAX_TOKENS", "256"))),
             MockTTSProvider, MockAvatarEngine, MockMediaOutput),
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
            create = {"commandId": "cmd_real_1", "traceId": "trace_real_1", "sessionId": "session_real_1", "avatar": {"avatarId": "avatar_mock", "engine": "MOCK"}, "voice": {"voiceId": "voice_mock", "provider": "MOCK"}, "config": {"fps": 25, "preview": {"type": "WEBRTC"}}, "context": {"roomId": "room_1", "systemPrompt": "你是直播间主持人。"}}
            self.assertEqual((await client.post("/internal/v1/sessions", json=create)).status_code, 202)
            for _ in range(100):
                if app.state.manager.get_session("session_real_1").state == "READY":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual((await client.post("/internal/v1/sessions/session_real_1/start", json={"commandId": "cmd_real_2", "traceId": "trace_real_1"})).status_code, 202)
            utterance = {"commandId": "cmd_real_3", "traceId": "trace_real_1", "utteranceId": "utt_real_1", "text": "请用一句中文向直播间观众问好。", "priority": 100, "interruptPolicy": "NONE", "source": "OPERATOR", "voice": {"voiceId": "voice_mock"}}
            self.assertEqual((await client.post("/internal/v1/sessions/session_real_1/utterances", json=utterance)).status_code, 202)
            for _ in range(600):
                names = [e["eventType"] for e in publisher.events]
                if "UTTERANCE_COMPLETED" in names or "UTTERANCE_FAILED" in names:
                    break
                await asyncio.sleep(0.1)
            self.assertIn("UTTERANCE_COMPLETED", names)
            self.assertNotIn("RUNTIME_WARNING", names, [e["payload"] for e in publisher.events if e["eventType"] == "RUNTIME_WARNING"])
            session = app.state.manager.get_session("session_real_1")
            self.assertGreater(len(session.media_output.received), 0)
            self.assertEqual((await client.post("/internal/v1/sessions/session_real_1/stop", json={"commandId": "cmd_real_4", "traceId": "trace_real_1"})).status_code, 202)
            self.assertIn("SESSION_ENDED", [e["eventType"] for e in publisher.events])
        await app.state.manager.close()
