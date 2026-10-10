"""CPU TTS backed by sherpa-onnx's incremental generation callback."""
import asyncio
from pathlib import Path
import threading
import concurrent.futures
import re
from .models import VoiceConfig
from .providers import AudioChunk, GenerationContext


def spoken_sizes(text: str) -> str:
    """Pronounce size letters which the Chinese lexicon otherwise silently skips.

    Restrict conversion to explicit size labels/lists; do not reinterpret units,
    product identifiers, or an answer's factual size selection.
    """
    letters = {"S": "艾丝", "M": "艾姆", "L": "艾尔", "X": "艾克斯"}
    size = r"(?<![A-Za-z0-9])(?:[2-5]XL|X{1,4}L|XS|S|M|L)(?![A-Za-z0-9])"
    def pronounce(match):
        value = match.group()
        if value[0].isdigit():
            value = "X" * int(value[0]) + "L"
        return "".join(letters[letter] for letter in value)
    text = re.sub(size + r"(?=\s*(?:尺码|单独库存|单码库存|码|号))", pronounce, text)
    return re.sub(r"尺码(?:选项)?有[^。；！？\n]*",
                  lambda m: re.sub(size, pronounce, m.group()), text)


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

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[AudioChunk | Exception | None] = asyncio.Queue(maxsize=8)
        cancelled = threading.Event()
        sequence = 0

        def send(item):
            if cancelled.is_set():
                return False
            future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
            while not cancelled.is_set():
                try:
                    future.result(timeout=0.05)
                    return True
                except concurrent.futures.TimeoutError:
                    continue
                except concurrent.futures.CancelledError:
                    return False
            future.cancel()
            return False

        def callback(samples, progress):
            nonlocal sequence
            if cancelled.is_set():
                return 0
            # At most 40ms per slot (8 slots = 320ms queued PCM). Only this
            # native thread blocks; the event loop remains free to consume/cancel.
            step = max(1, self.sample_rate * 40 // 1000)
            for offset in range(0, len(samples), step):
                pcm = (np.clip(samples[offset:offset+step], -1.0, 1.0) * 32767).astype("<i2").tobytes()
                if pcm:
                    if not send(AudioChunk(ctx.generation_id, sequence, pcm, self.sample_rate, 1)):
                        return 0
                    sequence += 1
            return 0 if cancelled.is_set() else 1

        def generate():
            try:
                self.engine.generate(spoken_sizes(text), sid=self.speaker_id, speed=1.0, callback=callback)
            except Exception as exc:
                send(exc)
            finally:
                send(None)

        worker = asyncio.create_task(asyncio.to_thread(generate))
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            cancelled.set()
            await asyncio.shield(worker)
