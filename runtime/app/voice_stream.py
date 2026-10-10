"""Opt-in voice PCM boundary. No public DTOs or provider selection live here."""
from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

from .models import VoiceConfig
from .providers import AudioChunk, GenerationContext, TTSProvider


@dataclass(frozen=True)
class VoiceCapabilities:
    reference_audio: bool
    incremental_pcm: bool
    speed: bool = False
    volume: bool = False


class VoiceProvider(TTSProvider, Protocol):
    capabilities: VoiceCapabilities


XIAOYA_CAPABILITIES = VoiceCapabilities(False, True)


@dataclass(frozen=True)
class TimedPCM:
    """Worker-local timing evidence; existing AudioChunk wire contract is intact."""
    chunk: AudioChunk
    first_sample_index: int

    @property
    def pts_us(self) -> int:
        return self.first_sample_index * 1_000_000 // 16000


class PCM16kConverter:
    """One stateful antialiased converter per synthesis; 20ms output, exact EOF."""
    def __init__(self, generation_id: int):
        import av
        self.generation_id = generation_id
        self.converter = av.AudioResampler(format="s16", layout="mono", rate=16000)
        self.source_rate = None
        self.source_samples = 0
        self.source_sequence = 0
        self.sequence = 0
        self.tail = bytearray()
        self.finished = False

    def _emit(self, frames):
        for frame in frames:
            raw = bytes(frame.planes[0])[:frame.samples * 2]
            for offset in range(0, len(raw), 640):
                self.tail.extend(raw[offset:offset + 640])
                while len(self.tail) >= 640:
                    pcm = bytes(self.tail[:640])
                    del self.tail[:640]
                    yield AudioChunk(self.generation_id, self.sequence, pcm)
                    self.sequence += 1

    def push(self, chunk: AudioChunk):
        import av
        import numpy as np
        if self.finished:
            raise ValueError("VOICE_STREAM_CLOSED")
        if chunk.generation_id != self.generation_id:
            raise ValueError("VOICE_STALE_GENERATION")
        if chunk.sequence != self.source_sequence:
            raise ValueError("VOICE_SEQUENCE_INVALID")
        if (chunk.channels != 1 or len(chunk.pcm) % 2 or len(chunk.pcm) > 1_048_576
                or not 8000 <= chunk.sample_rate <= 96000):
            raise ValueError("VOICE_PCM_INVALID")
        if self.source_rate is None:
            self.source_rate = chunk.sample_rate
        if self.source_rate != chunk.sample_rate:
            raise ValueError("VOICE_RATE_CHANGED")
        self.source_sequence += 1
        if not chunk.pcm:
            return
        # Bound conversion allocations even when a native provider emits a sentence.
        for offset in range(0, len(chunk.pcm), 4096):
            samples = np.frombuffer(chunk.pcm[offset:offset + 4096], dtype="<i2").reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
            frame.sample_rate = self.source_rate
            frame.pts = self.source_samples
            frame.time_base = Fraction(1, self.source_rate)
            self.source_samples += samples.size
            yield from self._emit(self.converter.resample(frame))

    def finish(self):
        if self.finished:
            raise ValueError("VOICE_STREAM_CLOSED")
        self.finished = True
        yield from self._emit(self.converter.resample(None))
        if self.tail:
            yield AudioChunk(self.generation_id, self.sequence, bytes(self.tail))
            self.tail.clear()


class StreamingVoiceAdapter:
    """Wrap an explicitly resolved provider; errors stop, never silently change voice."""
    def __init__(self, provider: TTSProvider, voice_id: str):
        self.provider = provider
        self.voice_id = voice_id

    async def timed_stream(self, text: str, voice: VoiceConfig, ctx: GenerationContext,
                           first_sample_index: int = 0):
        if voice.voiceId != self.voice_id or first_sample_index < 0:
            raise ValueError("VOICE_BINDING_MISMATCH")
        converter = PCM16kConverter(ctx.generation_id)
        source = self.provider.synthesize_stream(text, voice, ctx)
        delivered = 0
        try:
            async for chunk in source:
                for output in converter.push(chunk):
                    yield TimedPCM(output, first_sample_index + delivered)
                    delivered += len(output.pcm) // 2
            for output in converter.finish():
                yield TimedPCM(output, first_sample_index + delivered)
                delivered += len(output.pcm) // 2
            if not delivered:
                raise ValueError("VOICE_EMPTY_OUTPUT")
        finally:
            # On interrupt discard converter tail rather than emitting obsolete audio.
            await source.aclose()

    async def synthesize_stream(self, text: str, voice: VoiceConfig, ctx: GenerationContext):
        stream = self.timed_stream(text, voice, ctx)
        try:
            async for item in stream:
                yield item.chunk
        finally:
            await stream.aclose()
