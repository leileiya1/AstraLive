"""CPU TTS backed by sherpa-onnx's incremental generation callback."""
import asyncio
from pathlib import Path
import threading
from .models import VoiceConfig
from .providers import AudioChunk, GenerationContext


class SherpaOnnxTTSProvider:
    def __init__(self, model_dir: str, speaker_id: int = 0, num_threads: int = 2):
        import sherpa_onnx

        root = Path(model_dir).expanduser().resolve()
        names = ["zh_CN-xiao_ya-medium.onnx", "lexicon.txt", "tokens.txt", "phone.fst", "date.fst", "number.fst"]
        missing = [name for name in names if not (root / name).is_file()]
        if missing:
            raise ValueError(f"TTS model is incomplete: {', '.join(missing)}")
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(root / names[0]), lexicon=str(root / names[1]), tokens=str(root / names[2])
                ),
                num_threads=num_threads,
                provider="cpu",
            ),
            rule_fsts=",".join(str(root / name) for name in names[3:]),
        )
        if not config.validate():
            raise ValueError("Invalid sherpa-onnx TTS configuration")
        self.engine = sherpa_onnx.OfflineTts(config)
        self.sample_rate = self.engine.sample_rate
        self.speaker_id = speaker_id

    async def synthesize_stream(self, text: str, voice: VoiceConfig, ctx: GenerationContext):
        import numpy as np

        import queue as sync_queue
        queue = sync_queue.Queue(maxsize=100) # <= 2 seconds of 20ms native PCM
        cancelled = threading.Event()
        sequence = 0
        errors = []
        done = threading.Event()

        def callback(samples, progress):
            nonlocal sequence
            if cancelled.is_set(): return 0
            pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
            step = max(1, self.sample_rate // 50) * 2
            for start in range(0, len(pcm), step):
                item = AudioChunk(ctx.generation_id, sequence, pcm[start:start+step], self.sample_rate, 1)
                while not cancelled.is_set():
                    try: queue.put(item, timeout=.05); break
                    except sync_queue.Full: pass
                if cancelled.is_set(): return 0
                sequence += 1
            return 1

        def generate():
            try: self.engine.generate(text, sid=self.speaker_id, speed=1.0, callback=callback)
            except Exception as exc: errors.append(exc)
            finally: done.set()

        def take():
            try: return queue.get(timeout=.1)
            except sync_queue.Empty: return None

        worker = asyncio.create_task(asyncio.to_thread(generate))
        try:
            while not done.is_set() or not queue.empty():
                item = await asyncio.to_thread(take)
                if item is not None: yield item
            if errors: raise errors[0]
        finally:
            cancelled.set()
            await worker
