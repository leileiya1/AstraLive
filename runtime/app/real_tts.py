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
    # Stop at the end of the actual list. Sweeping the rest of a clause also
    # converted units/model letters in "尺码有 XL，长度 20 M，容量 5 L".
    return re.sub(r"尺码(?:选项)?有\s*" + size + r"(?:\s*[、,/，]\s*" + size + r")*",
                  lambda m: re.sub(size, pronounce, m.group()), text)


# Chinese letter names; S/M/L/X match spoken_sizes() so sizes sound the same.
LETTERS = {
    "A": "诶", "B": "比", "C": "西", "D": "迪", "E": "伊", "F": "艾弗", "G": "吉",
    "H": "艾尺", "I": "艾", "J": "杰", "K": "开", "L": "艾尔", "M": "艾姆", "N": "恩",
    "O": "欧", "P": "皮", "Q": "丘", "R": "阿尔", "S": "艾丝", "T": "提", "U": "优",
    "V": "维", "W": "达不溜", "X": "艾克斯", "Y": "歪", "Z": "贼",
}
# Units only directly after a number ("500ML", "20 M", "30 S"): never sizes.
UNITS = {
    "mah": "毫安时", "ml": "毫升", "mm": "毫米", "cm": "厘米", "km": "千米", "kg": "千克",
    "mg": "毫克", "min": "分钟", "gb": "吉字节", "tb": "太字节", "mb": "兆字节",
    "kw": "千瓦", "l": "升", "m": "米", "g": "克", "s": "秒", "h": "小时", "w": "瓦",
    "v": "伏", "a": "安",
}
_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(" + "|".join(sorted(UNITS, key=len, reverse=True))
                   + r")(?![A-Za-z])", re.IGNORECASE)


# Characters the engine may drop without losing meaning (prosody only).
PROSODY = frozenset("“”‘’\"'()（）《》<>[]【】「」-—_·")
# Meaning-carrying symbols the lexicon cannot read; order matters (most
# specific first). Applied before letters so "A/B" keeps both letters.
_SYMBOLS = [
    (re.compile(r"[¥￥]\s*(\d+(?:\.\d+)?)\s*元?"), r"\1元"),
    (re.compile(r"\$\s*(\d+(?:\.\d+)?)"), r"\1美元"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*[%％]"), r"百分之\1"),
    (re.compile(r"(\d)\s*[~～]\s*(?=\d)"), r"\1到"),
    (re.compile(r"[#＃]\s*(\d+)"), r"\1号"),
    (re.compile(r"/(?=[\u4e00-\u9fff])"), "每"),
    (re.compile(r"/"), "或"),
    (re.compile(r"[+＋]"), "加"),
    (re.compile(r"(?<=\d)\s*[xX×]\s*(?=\d)"), "乘"),
    (re.compile(r"×"), "乘"),
    (re.compile(r"℃"), "摄氏度"),
    (re.compile(r"㎡"), "平方米"),
    (re.compile(r"[&＆]"), "和"),
    (re.compile(r"[~～]"), "到"),
    (re.compile(r"[%％]"), "百分号"),
]


def spoken_text(text: str, pronunciations: dict[str, str] | None = None) -> str:
    """Spoken form of committed text for a lexicon without Latin letters.

    The committed answer text is never changed; only what the engine reads.
    Order matters: size labels (unchanged spoken_sizes), operator/product
    glossary, number+unit, the common T恤 reading, then any remaining Latin
    run read letter by letter -- never silently skipped.
    """
    text = spoken_sizes(text)
    for word in sorted(pronunciations or {}, key=len, reverse=True):
        text = re.sub(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])",
                      pronunciations[word], text, flags=re.IGNORECASE)
    for pattern, reading in _SYMBOLS:
        text = pattern.sub(reading, text)
    text = _UNIT.sub(lambda m: m.group(1) + UNITS[m.group(2).lower()], text)
    text = re.sub(r"(?<![A-Za-z])[Tt](?=恤)", "踢", text)
    return re.sub(r"[A-Za-z]+", lambda m: "".join(LETTERS[c.upper()] for c in m.group()), text)


def lexicon_characters(model_dir: str) -> frozenset[str]:
    """Every single character the model's own lexicon can pronounce."""
    root = Path(model_dir).expanduser().resolve()
    chars = set()
    with open(root / "lexicon.txt", encoding="utf-8") as lexicon:
        for line in lexicon:
            word = line.split(" ", 1)[0]
            chars.update(word)
    return frozenset(chars)


def uncovered(text: str, known: frozenset[str]) -> set[str]:
    """Characters the engine would drop that carry meaning: anything not in
    its lexicon except digits (number.fst), whitespace, sentence punctuation
    the engine handles and PROSODY characters."""
    return {c for c in text if c not in known and not c.isdigit() and not c.isspace()
            and c not in PROSODY and c not in "，。！？、；：,.!?;:…"}


class SherpaOnnxTTSProvider:
    pronunciations = None  # optional operator/product glossary (see spoken_text)

    def __init__(self, model_dir: str, speaker_id: int = 0, num_threads: int = 2,
                 pronunciations: dict[str, str] | None = None):
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
        self.pronunciations = dict(pronunciations or {})

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
                self.engine.generate(spoken_text(text, self.pronunciations), sid=self.speaker_id,
                                     speed=1.0, callback=callback)
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
