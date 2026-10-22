"""Real speech media for one committed answer unit (stage 2d).

``SpeechMedia`` is the single TTS invocation handed to ``speak_once``: it
streams the existing TTS provider's PCM (e.g. sherpa-onnx VITS), resamples it
exactly once to the trusted Session rate with one stateful libav resampler
(flushed at the end, so no tail samples are dropped), cuts it into bounded
chunks and, when an avatar is configured, feeds each chunk to the existing
avatar engine and interleaves its frames.

Session continuity: one ``SpeechMedia`` (and its avatar engine) lives for the
whole Session, so the avatar's frame clock -- and therefore video PTS --
keeps increasing across answer units instead of restarting per unit. Audio
continuity is the Guardian's own sample clock. Nothing here touches tickets,
Journal state or Guardian proofs; it only produces media for the lineage the
caller already captured.

Importing this module loads no model and opens no device.
"""

import av
import numpy as np

from ..providers import AudioChunk, GenerationContext

AUDIO, VIDEO = "audio", "video"
AVATAR_GENERATION = 1  # the avatar engine's own local generation tag


class SpeechMedia:
    def __init__(
        self,
        tts,
        voice,
        *,
        sample_rate,
        avatar=None,
        frame_size=None,
        chunk_ms=200,
        session_id="session",
        trace_id="trace",
    ):
        if sample_rate not in (16000, 24000, 48000):
            raise ValueError("unsupported Session sample rate")
        if not 20 <= chunk_ms <= 1000:
            raise ValueError("chunk must be between 20ms and 1s")
        if avatar is not None and frame_size is None:
            raise ValueError("avatar requires the Session frame size")
        self.tts, self.voice, self.avatar = tts, voice, avatar
        self.sample_rate, self.frame_size = sample_rate, frame_size
        self.chunk_samples = sample_rate * chunk_ms // 1000
        self.session_id, self.trace_id = session_id, trace_id
        self.units = 0
        self.samples_in = self.samples_out = 0  # diagnostics only

    def __call__(self, text):
        """Return the async media stream; work starts on first iteration."""
        self.units += 1
        return self._stream(text, self.units)

    async def _stream(self, text, unit):
        ctx = GenerationContext(
            AVATAR_GENERATION, self.trace_id, self.session_id, f"unit-{unit}"
        )
        resampler = av.AudioResampler(
            format="s16", layout="mono", rate=self.sample_rate
        )
        pending = bytearray()
        source_rate, source_pts = None, 0
        async for chunk in self.tts.synthesize_stream(text, self.voice, ctx):
            if chunk.channels != 1:
                raise ValueError("mono TTS output required")
            if source_rate is None:
                source_rate = chunk.sample_rate
            elif chunk.sample_rate != source_rate:
                raise ValueError("TTS sample rate changed mid-unit")
            samples = np.frombuffer(chunk.pcm, dtype="<i2")
            self.samples_in += len(samples)
            frame = av.AudioFrame.from_ndarray(
                samples.reshape(1, -1), format="s16", layout="mono"
            )
            frame.sample_rate, frame.pts = source_rate, source_pts
            source_pts += len(samples)
            for out in resampler.resample(frame):
                pending.extend(_pcm(out))
            while len(pending) >= self.chunk_samples * 2:
                piece = bytes(pending[: self.chunk_samples * 2])
                del pending[: self.chunk_samples * 2]
                async for item in self._emit(piece):
                    yield item
        if source_rate is None:
            raise ValueError("TTS produced no audio")
        for out in resampler.resample(None):  # flush the resampler tail
            pending.extend(_pcm(out))
        while pending:
            piece = bytes(pending[: self.chunk_samples * 2])
            del pending[: self.chunk_samples * 2]
            async for item in self._emit(piece):
                yield item

    async def _emit(self, pcm):
        self.samples_out += len(pcm) // 2
        yield AUDIO, pcm, None
        if self.avatar is None:
            return
        frames = await self.avatar.push_audio(
            AudioChunk(AVATAR_GENERATION, 0, pcm, self.sample_rate, 1)
        )
        for frame in frames:
            if (frame.width, frame.height) != self.frame_size:
                raise ValueError("avatar frame size differs from the Session")
            yield VIDEO, frame.rgb, frame.pts_us


def _pcm(frame):
    return frame.to_ndarray().astype("<i2", copy=False).reshape(-1).tobytes()
