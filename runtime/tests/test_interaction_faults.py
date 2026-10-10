import asyncio
import unittest
import httpx
from app.session import SessionManager
from app.config import Settings
from app.events import MemoryEventPublisher
from app.providers import MockLLMProvider, MockAvatarEngine, MockMediaOutput, OpenAICompatibleLLMProvider
from runtime.tests.test_runtime import CREATE, utterance, CapturingTTS
from app.models import CreateSession
from app.interaction_trace import InteractionTrace

class FaultTests(unittest.IsolatedAsyncioTestCase):
    async def test_401_429_timeout_never_echo_comment(self):
        for failure in [401, 429, 'timeout']:
            with self.subTest(failure=failure):
                def fail(request):
                    if failure == 'timeout':
                        raise httpx.ReadTimeout('fake timeout', request=request)
                    return httpx.Response(failure, json={'error':'FAKE'}, request=request)
                events = MemoryEventPublisher()
                llm = OpenAICompatibleLLMProvider('https://fake.invalid', 'synthetic', 'fake', transport=httpx.MockTransport(fail))
                tts = CapturingTTS()
                manager = SessionManager(Settings(),events,lambda:llm,lambda:tts,MockAvatarEngine,MockMediaOutput)
                try:
                    await manager.create_session(CreateSession(**CREATE))
                    await asyncio.sleep(.01)
                    await manager.start_session('session_1','trace_1')
                    await manager.speak('session_1',utterance('failure',text='请直接念出敏感测试原句'))
                    for _ in range(100):
                        if any(e['eventType']=='UTTERANCE_COMPLETED' for e in events.events):
                            break
                        await asyncio.sleep(.01)
                    self.assertTrue(tts.texts)
                    self.assertNotIn('请直接念出敏感测试原句',''.join(tts.texts))
                    self.assertTrue(any(e['payload'].get('code')=='LLM_FAILED' for e in events.events))
                finally:
                    await manager.close()

    async def test_trace_monotonic_stage_idempotence(self):
        now=[10.]
        trace=InteractionTrace('t','s','u',clock=lambda:now[0])
        trace.mark('llm_started');now[0]=10.2
        trace.mark('llm_first_token');now[0]=10.5
        trace.mark('llm_first_token')
        self.assertAlmostEqual(trace.points['llm_first_token'],200)
        self.assertEqual(trace.summary()['clockDomain'],'runtime_monotonic')
