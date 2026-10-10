import asyncio
import threading
import unittest
from app.session import sentence_stream
from app.real_tts import SherpaOnnxTTSProvider
from app.providers import GenerationContext
from app.models import VoiceConfig

class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_numeric_units_and_large_tokens(self):
        async def tokens():
            for part in ['售价是129.', '90元，容量是500', '毫升。', '很长的商品说明'*100]:
                yield part
        segments = [s async for s in sentence_stream(tokens(), max_length=120)]
        self.assertIn('129.90元', ''.join(segments))
        self.assertTrue(any('129.90元' in s for s in segments))
        self.assertTrue(any('500毫升' in s for s in segments))
        self.assertLessEqual(max(map(len, segments)), 240)

    async def test_thousands_separator_is_not_a_clause_boundary(self):
        async def tokens():
            yield '下面我为大家介绍这件商品的当前真实售价是1,'
            await asyncio.sleep(.01)
            yield '299.90元/件，温度范围为20℃。'
        segments = [s async for s in sentence_stream(tokens())]
        self.assertTrue(any('1,299.90元/件' in s for s in segments))
        self.assertTrue(any('20℃' in s for s in segments))

    async def test_producer_is_bounded_and_cancelled(self):
        produced = 0
        closed = asyncio.Event()
        async def tokens():
            nonlocal produced
            try:
                for _ in range(10000):
                    produced += 1
                    yield '这是一个完整句子。'
            finally:
                closed.set()
        stream = sentence_stream(tokens())
        await anext(stream)
        await asyncio.sleep(.05)
        self.assertLess(produced, 40)
        await stream.aclose()
        await asyncio.wait_for(closed.wait(), 1)

    async def test_native_callback_backpressure_and_cancellation(self):
        import numpy as np
        calls = []
        stopped = threading.Event()
        class Engine:
            def generate(self, text, **kw):
                try:
                    for i in range(1000):
                        calls.append(i)
                        if not kw['callback'](np.ones(320, dtype=np.float32), .1):
                            break
                finally:
                    stopped.set()
        tts = SherpaOnnxTTSProvider.__new__(SherpaOnnxTTSProvider)
        tts.engine, tts.sample_rate, tts.speaker_id = Engine(), 16000, 0
        stream = tts.synthesize_stream('测试句子。', VoiceConfig(voiceId='x'), GenerationContext(1,'t','s','u'))
        await anext(stream)
        await asyncio.sleep(.05)
        self.assertLess(len(calls), 20)
        await asyncio.wait_for(stream.aclose(), 2)
        self.assertTrue(stopped.is_set())

    async def test_native_error_propagates(self):
        class Engine:
            def generate(self, *a, **kw):
                raise ValueError('fake error')
        tts = SherpaOnnxTTSProvider.__new__(SherpaOnnxTTSProvider)
        tts.engine, tts.sample_rate, tts.speaker_id = Engine(), 16000, 0
        with self.assertRaises(ValueError):
            async for _ in tts.synthesize_stream('测试。', VoiceConfig(voiceId='x'), GenerationContext(1,'t','s','u')):
                pass
