import asyncio
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import time
import unittest
import wave

import numpy as np

from app.cosyvoice_tts import CosyVoiceTTSProvider
from app.models import VoiceConfig
from app.providers import AudioChunk, GenerationContext
from app.voice_stream import PCM16kConverter, StreamingVoiceAdapter, XIAOYA_CAPABILITIES
from app.voice_evaluation import measure_voice_stream


CTX = GenerationContext(7, "trace", "session", "utterance")
VOICE = VoiceConfig(voiceId="personal_voice")


class FakeSource:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
        self.read = 0

    async def synthesize_stream(self, text, voice, ctx):
        try:
            for chunk in self.chunks:
                self.read += 1
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk
        finally:
            self.closed = True


class VoiceStreamTests(unittest.IsolatedAsyncioTestCase):
    def test_xiaoya_has_no_clone_capability(self):
        self.assertFalse(XIAOYA_CAPABILITIES.reference_audio)
        self.assertFalse(XIAOYA_CAPABILITIES.speed)

    def test_resampler_is_invariant_to_chunk_boundaries(self):
        for rate in (16000, 22050, 24000, 48000):
            samples = (np.sin(np.arange(rate) * 2 * np.pi * 220 / rate) * 10000).astype("<i2").tobytes()
            def convert(parts):
                converter = PCM16kConverter(7)
                result = []
                for sequence, pcm in enumerate(parts):
                    result.extend(converter.push(AudioChunk(7, sequence, pcm, rate)))
                result.extend(converter.finish())
                self.assertEqual([c.sequence for c in result], list(range(len(result))))
                self.assertTrue(all(c.sample_rate == 16000 and c.channels == 1 and len(c.pcm) <= 640 for c in result))
                return b"".join(c.pcm for c in result)
            whole = convert([samples])
            split = convert([samples[offset:offset + 202] for offset in range(0, len(samples), 202)])
            self.assertEqual(whole, split)
            self.assertEqual(len(whole), 32000)

    def test_invalid_generation_sequence_format_and_rate_change(self):
        valid = AudioChunk(7, 0, bytes(640))
        for invalid in (replace(valid, generation_id=8), replace(valid, sequence=1),
                        replace(valid, channels=2), replace(valid, pcm=b"x"),
                        replace(valid, sample_rate=0), replace(valid, pcm=bytes(1048578))):
            with self.assertRaises(ValueError):
                list(PCM16kConverter(7).push(invalid))
        converter = PCM16kConverter(7)
        list(converter.push(valid))
        with self.assertRaisesRegex(ValueError, "VOICE_RATE_CHANGED"):
            list(converter.push(AudioChunk(7, 1, bytes(640), 24000)))
        list(converter.finish())
        with self.assertRaisesRegex(ValueError, "VOICE_STREAM_CLOSED"):
            list(converter.finish())

    async def test_timestamp_origin_and_unpadded_eof(self):
        source = FakeSource([AudioChunk(7, 0, bytes(666))])
        adapter = StreamingVoiceAdapter(source, VOICE.voiceId)
        output = [c async for c in adapter.timed_stream("你好", VOICE, CTX, 16000)]
        self.assertEqual([c.first_sample_index for c in output], [16000, 16320])
        self.assertEqual([c.pts_us for c in output], [1000000, 1020000])
        self.assertEqual([len(c.chunk.pcm) for c in output], [640, 26])
        self.assertTrue(source.closed)

    async def test_interrupt_drops_tail_and_closes_source(self):
        source = FakeSource([AudioChunk(7, 0, bytes(666)), AudioChunk(7, 1, bytes(640))])
        stream = StreamingVoiceAdapter(source, VOICE.voiceId).synthesize_stream("你好", VOICE, CTX)
        await anext(stream)
        await stream.aclose()
        self.assertTrue(source.closed)
        self.assertEqual(source.read, 1)

    async def test_error_after_audio_propagates_without_fallback(self):
        source = FakeSource([AudioChunk(7, 0, bytes(640)), RuntimeError("native_failure")])
        stream = StreamingVoiceAdapter(source, VOICE.voiceId).synthesize_stream("你好", VOICE, CTX)
        await anext(stream)
        with self.assertRaisesRegex(RuntimeError, "native_failure"):
            await anext(stream)
        self.assertTrue(source.closed)

    async def test_empty_output_and_binding_mismatch(self):
        adapter = StreamingVoiceAdapter(FakeSource([]), VOICE.voiceId)
        with self.assertRaisesRegex(ValueError, "VOICE_EMPTY_OUTPUT"):
            await anext(adapter.synthesize_stream("你好", VOICE, CTX))
        with self.assertRaisesRegex(ValueError, "VOICE_BINDING_MISMATCH"):
            await anext(adapter.synthesize_stream("你好", VoiceConfig(voiceId="other"), CTX))

    async def test_measurement_uses_actual_sample_count_and_marks_subjective_review_pending(self):
        source = FakeSource([AudioChunk(7, 0, bytes(32000))])
        result = await measure_voice_stream(source, "你好", VOICE, CTX)
        self.assertEqual(result["samples"], 16000)
        self.assertEqual(result["audioSeconds"], 1)
        self.assertEqual(result["chunks"], 50)
        self.assertLessEqual(result["firstPcmMs"], result["totalMs"])
        self.assertEqual(result["subjectiveReview"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(result["gpuResources"], "NOT_MEASURED")
        self.assertTrue(source.closed)

    async def test_measurement_timeout_cleans_up_source(self):
        class WaitingSource:
            closed = False
            async def synthesize_stream(self, *args):
                try:
                    await asyncio.sleep(10)
                    yield AudioChunk(7, 0, bytes(640))
                finally:
                    self.closed = True
        source = WaitingSource()
        with self.assertRaises(TimeoutError):
            await measure_voice_stream(source, "你好", VOICE, CTX, timeout_s=.01)
        self.assertTrue(source.closed)


class FakeEngine:
    sample_rate = 24000

    def __init__(self):
        self.generated = 0
        self.closed = False
        self.options = None

    def inference_zero_shot(self, text, reference_text, reference_path, **options):
        self.options = options
        try:
            for _ in range(20):
                self.generated += 1
                yield {"tts_speech": np.full((1, 480), .25, dtype="float32")}
        finally:
            self.closed = True


class CosyVoiceBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "reference.wav"
        with wave.open(str(self.path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(48000 * 2))

    def tearDown(self):
        self.temp.cleanup()

    def provider(self, engine, lock=None, **options):
        return CosyVoiceTTSProvider(engine, lock or threading.Lock(), VOICE.voiceId,
                                    self.path, "参考文本。", **options)

    async def test_incremental_model_flag_and_bounded_backpressure(self):
        engine = FakeEngine()
        provider = self.provider(engine)
        stream = provider.synthesize_stream("你好", VOICE, CTX)
        first = await anext(stream)
        self.assertEqual(first.sample_rate, 24000)
        await asyncio.sleep(.1)
        self.assertLessEqual(engine.generated, 6)  # 1 consumed + 4 queued + 1 pending
        self.assertLess(engine.generated, 20)
        await stream.aclose()
        self.assertTrue(engine.closed)
        self.assertFalse(provider.poisoned)
        self.assertEqual(engine.options, {"stream": True, "speed": 1.0})

    async def test_adapter_pcm_shape_through_16k_boundary_and_reuse(self):
        engine = FakeEngine()
        provider = self.provider(engine)
        adapter = StreamingVoiceAdapter(provider, VOICE.voiceId)
        for generation in (7, 8):
            output = [c async for c in adapter.synthesize_stream("你好", VOICE, replace(CTX, generation_id=generation))]
            self.assertEqual(sum(len(c.pcm) // 2 for c in output), 6400)
            self.assertTrue(all(c.generation_id == generation for c in output))

    async def test_shared_model_lock_rejects_parallel_calls(self):
        engine = FakeEngine()
        lock = threading.Lock()
        first_provider = self.provider(engine, lock)
        second_provider = self.provider(engine, lock)
        stream = first_provider.synthesize_stream("你好", VOICE, CTX)
        await anext(stream)
        with self.assertRaisesRegex(RuntimeError, "VOICE_WORKER_BUSY"):
            await anext(second_provider.synthesize_stream("你好", VOICE, CTX))
        await stream.aclose()

    async def test_native_error_redacted_and_model_lock_released(self):
        class BrokenEngine(FakeEngine):
            def inference_zero_shot(self, *args, **kwargs):
                raise RuntimeError("private reference path and transcript")
        provider = self.provider(BrokenEngine())
        with self.assertRaisesRegex(RuntimeError, "^VOICE_SYNTHESIS_FAILED$"):
            await anext(provider.synthesize_stream("你好", VOICE, CTX))
        self.assertFalse(provider.engine_lock.locked())

    async def test_nonfinite_pcm_rejected(self):
        class BrokenEngine(FakeEngine):
            def inference_zero_shot(self, *args, **kwargs):
                yield {"tts_speech": np.full((1, 20), np.nan)}
        provider = self.provider(BrokenEngine())
        with self.assertRaisesRegex(RuntimeError, "^VOICE_SYNTHESIS_FAILED$"):
            await anext(provider.synthesize_stream("你好", VOICE, CTX))

    async def test_stalled_native_call_is_quarantined_after_timeout(self):
        release = threading.Event()
        class StalledEngine(FakeEngine):
            def inference_zero_shot(self, *args, **kwargs):
                release.wait(2)
                yield {"tts_speech": np.full((1, 20), .25)}
        provider = self.provider(StalledEngine(), cleanup_timeout=.05, first_chunk_timeout=.05)
        start = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                await anext(provider.synthesize_stream("你好", VOICE, CTX))
            self.assertLess(time.monotonic() - start, .5)
            self.assertTrue(provider.poisoned)
            self.assertTrue(provider.engine_lock.locked())
            with self.assertRaisesRegex(RuntimeError, "VOICE_WORKER_UNAVAILABLE"):
                await anext(provider.synthesize_stream("你好", VOICE, CTX))
        finally:
            release.set()
            for _ in range(100):
                if not provider.engine_lock.locked():
                    break
                await asyncio.sleep(.01)
        self.assertFalse(provider.engine_lock.locked())


if __name__ == "__main__":
    unittest.main()
