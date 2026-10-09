#!/usr/bin/env python3
"""Create the isolated Chinese avatar-audio test pack with AstraLive's CPU TTS.

This script deliberately imports the existing provider but starts no Runtime
server and changes no Runtime configuration.  It writes only below --output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import wave
from pathlib import Path
import sys


TEXTS = {
    "short_10s.wav": "大家好，欢迎来到 AstraLive 直播间。今天我们一起测试真人数字人的实时互动效果。",
    "medium_30s.wav": "刚才有朋友问，这款卫衣有没有 XL 尺码。这里需要说明，商品支持 XL 尺码，不代表 XL 一定还有库存，具体库存仍然需要实时查询。",
    "long_60s.wav": (
        "大家晚上好，欢迎来到 AstraLive 直播间。现在是晚上八点零五分，我们用这一段自然的中文讲解，"
        "测试真人数字人的说话节奏、停顿和口型同步效果。今天展示的是一款轻薄连帽卫衣，颜色有深灰、"
        "米白和海军蓝三种。尺码从 S 到 XL 都支持选择；不过我需要特别说明，页面显示支持 XL 尺码，"
        "并不等于 XL 此刻一定有货，准确库存要以实时查询结果为准。商品编号是 SKU-AI-2026-1008，"
        "其中 AI 两个英文字符请按字母读出。面料以棉为主，适合二十到二十八摄氏度的日常通勤。"
        "如果您想比较长度，可以先告诉我身高、平时尺码和偏好的宽松程度，我会把问题交给商品信息服务，"
        "再给出明确答复。接下来我们会留出两秒钟停顿，观察待机画面能否稳定切换；随后继续说话，"
        "并检查旧音频、旧视频帧是否已经清理。感谢大家参与这次 PoC 验证，稍后还会测试 FAQ、"
        "数字一百二十八，以及英文缩写 RTX 和 WebRTC 的自然发音。"
    ),
}


async def synthesize(provider, text: str) -> bytes:
    from app.models import VoiceConfig
    from app.providers import GenerationContext

    chunks: list[bytes] = []
    context = GenerationContext(1, "real-avatar-prep", "offline-asset", "offline-asset")
    async for chunk in provider.synthesize_stream(text, VoiceConfig(voiceId="offline_voice"), context):
        chunks.append(chunk.pcm)
    return b"".join(chunks)


def write_pcm_wav(path: Path, pcm: bytes, sample_rate: int, channels: int) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    runtime = args.runtime.resolve()
    sys.path.insert(0, str(runtime))
    from app.real_tts import SherpaOnnxTTSProvider

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    provider = SherpaOnnxTTSProvider(str(args.model_dir.resolve()))
    manifest = []
    for name, transcript in TEXTS.items():
        pcm = await synthesize(provider, transcript)
        target = output / name
        write_pcm_wav(target, pcm, provider.sample_rate, 1)
        manifest.append({
            "file": name,
            "transcript": transcript,
            "sample_rate": provider.sample_rate,
            "channels": 1,
            "pcm_format": "s16le",
        })

    silence = output / "silence_10s.wav"
    write_pcm_wav(silence, b"\0\0" * (provider.sample_rate * 10), provider.sample_rate, 1)
    manifest.append({
        "file": silence.name,
        "transcript": "[10 seconds of digital silence]",
        "sample_rate": provider.sample_rate,
        "channels": 1,
        "pcm_format": "s16le",
    })
    (output / "transcripts.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
