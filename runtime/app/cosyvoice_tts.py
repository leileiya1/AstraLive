"""Optional self-hosted CosyVoice bridge; engine/assets must be resolved by services.

Does not load/download models, train, select defaults, or send assets over a network.
The caller must audit the complete model/weight/data/dependency licence chain first.
"""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
import threading
import time

from .models import VoiceConfig
from .providers import AudioChunk, GenerationContext
from .voice_stream import VoiceCapabilities


class CosyVoiceTTSProvider:
    capabilities = VoiceCapabilities(True, True, volume=True)

    def __init__(self, engine, engine_lock, voice_id: str, reference_wav: Path,
                 reference_text: str, volume: float = 1.0,
                 cleanup_timeout: float = 0.5, first_chunk_timeout: float = 30.0,
                 chunk_timeout: float = 10.0, stream_timeout: float = 120.0):
        import math
        # Local normalized WAV only; no URI, user-selected path or implicit fallback.
        path = Path(reference_wav)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError("VOICE_REFERENCE_UNAVAILABLE")
        import wave
        try:
            with wave.open(str(path), "rb") as wav:
                if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                    raise ValueError
                if not 3 <= wav.getnframes() / 16000 <= 30:
                    raise ValueError
        except (OSError, EOFError, ValueError, wave.Error):
            raise ValueError("VOICE_REFERENCE_INVALID") from None
        if (not voice_id or not reference_text.strip() or reference_text != reference_text.strip() or len(reference_text) > 1000
                or "\x00" in reference_text or not math.isfinite(volume) or not 0 <= volume <= 2):
            raise ValueError("VOICE_PARAMETERS_INVALID")
        if any(not math.isfinite(v) or v <= 0 for v in
               (cleanup_timeout, first_chunk_timeout, chunk_timeout, stream_timeout)):
            raise ValueError("VOICE_PARAMETERS_INVALID")
        if not isinstance(engine.sample_rate, int) or not 8000 <= engine.sample_rate <= 96000:
            raise ValueError("VOICE_PCM_INVALID")
        self.engine, self.engine_lock, self.voice_id = engine, engine_lock, voice_id
        self.reference_wav, self.reference_text = path, reference_text
        self.volume, self.cleanup_timeout = volume, cleanup_timeout
        self.first_chunk_timeout, self.chunk_timeout = first_chunk_timeout, chunk_timeout
        self.stream_timeout = stream_timeout
        self.poisoned = False

    async def synthesize_stream(self, text: str, voice: VoiceConfig, ctx: GenerationContext):
        if voice.voiceId != self.voice_id or not text.strip() or len(text) > 4000:
            raise ValueError("VOICE_BINDING_MISMATCH")
        if self.poisoned:
            raise RuntimeError("VOICE_WORKER_UNAVAILABLE")
        if not self.engine_lock.acquire(blocking=False):
            raise RuntimeError("VOICE_WORKER_BUSY")
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue(maxsize=4)
        cancelled = threading.Event()

        def enqueue(item):
            if cancelled.is_set():
                return False
            pending = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
            while not cancelled.is_set():
                try:
                    pending.result(timeout=0.05)
                    return True
                except FutureTimeout:
                    continue
            pending.cancel()
            return False

        def generate():
            source = None
            try:
                import numpy as np
                source = self.engine.inference_zero_shot(
                    text, self.reference_text, str(self.reference_wav), stream=True, speed=1.0)
                for sequence, packet in enumerate(source):
                    if cancelled.is_set():
                        break
                    samples = packet["tts_speech"]
                    if hasattr(samples, "detach"):
                        if samples.numel() > 524288:
                            raise ValueError("VOICE_PCM_INVALID")
                        samples = samples.detach().cpu().numpy()
                    samples = np.asarray(samples)
                    if (samples.ndim not in (1, 2) or samples.ndim == 2 and samples.shape[0] != 1
                            or samples.size > 524288 or not np.isfinite(samples).all()):
                        raise ValueError("VOICE_PCM_INVALID")
                    pcm = (np.clip(samples.reshape(-1) * self.volume, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                    if not enqueue(AudioChunk(ctx.generation_id, sequence, pcm, self.engine.sample_rate, 1)):
                        break
            except Exception:
                # Native exception text can contain private paths/transcripts.
                enqueue(RuntimeError("VOICE_SYNTHESIS_FAILED"))
            finally:
                try:
                    if source is not None and hasattr(source, "close"):
                        source.close()
                except Exception:
                    enqueue(RuntimeError("VOICE_SYNTHESIS_FAILED"))
                finally:
                    self.engine_lock.release()
                    enqueue(None)

        worker = threading.Thread(target=generate, daemon=True, name="personal-voice")
        try:
            worker.start()
        except BaseException:
            self.engine_lock.release()
            raise
        timeout = self.first_chunk_timeout
        deadline = time.monotonic() + self.stream_timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("VOICE_STREAM_TIMEOUT")
                item = await asyncio.wait_for(queue.get(), min(timeout, remaining))
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                timeout = self.chunk_timeout
                yield item
        finally:
            cancelled.set()
            # Native CUDA calls may not be preemptible. Quarantine if they outlive close.
            deadline = time.monotonic() + self.cleanup_timeout
            while worker.is_alive() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            if worker.is_alive():
                self.poisoned = True
