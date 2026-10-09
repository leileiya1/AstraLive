"""CPU-only acceptance benchmarks for the School-Linux deployment."""

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import resource
import statistics
import time


def rss_mib() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return round(int(line.split()[1]) / 1024, 1)
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


async def benchmark_tts(model_dir: str) -> dict:
    from app.models import VoiceConfig
    from app.providers import GenerationContext
    from app.real_tts import SherpaOnnxTTSProvider

    load_started = time.perf_counter()
    provider = SherpaOnnxTTSProvider(model_dir)
    load_ms = (time.perf_counter() - load_started) * 1000
    phrases = {
        "ordinary_chinese": "欢迎大家来到直播间，今天为大家介绍这款舒适的纯棉卫衣。",
        "price": "这款商品现在的价格是人民币一百二十九元。",
        "aggregate_stock": "这款商品整体库存还有二十七件。",
        "xl_size": "这款有 XL 尺码，目前商品整体还有库存，但暂时没有 XL 单独库存数据。",
        "comment": "感谢这位朋友的评论，喜欢的话可以看看商品详情。",
    }
    results = []
    voice = VoiceConfig(voiceId="voice_school_linux")
    for sequence, (name, text) in enumerate(phrases.items(), 1):
        before_rss = rss_mib()
        cpu_started = time.process_time()
        started = time.perf_counter()
        first_at = None
        chunks = []
        context = GenerationContext(sequence, f"trace_{sequence}", "session_benchmark", f"utt_{sequence}")
        async for chunk in provider.synthesize_stream(text, voice, context):
            if first_at is None:
                first_at = time.perf_counter()
            chunks.append(chunk)
        ended = time.perf_counter()
        cpu_s = time.process_time() - cpu_started
        wall_s = ended - started
        pcm_bytes = sum(len(chunk.pcm) for chunk in chunks)
        audio_s = pcm_bytes / (2 * provider.sample_rate)
        results.append({
            "case": name,
            "text": text,
            "first_chunk_ms": round((first_at - started) * 1000, 1) if first_at else None,
            "total_generation_ms": round(wall_s * 1000, 1),
            "cpu_pct_process_over_wall": round(cpu_s / wall_s * 100, 1),
            "rss_before_mib": before_rss,
            "rss_after_mib": rss_mib(),
            "pcm_bytes": pcm_bytes,
            "audio_seconds": round(audio_s, 3),
            "sample_rate": provider.sample_rate,
            "channels": 1,
        })
    return {
        "provider": "sherpa-onnx CPU",
        "model_load_ms": round(load_ms, 1),
        "physical_sound_card_required": False,
        "cases": results,
    }


async def benchmark_avatar(frames: int, size: int) -> dict:
    import numpy as np
    from app.lightweight_avatar import LightweightAvatarEngine
    from app.models import AvatarConfig, SessionConfig
    from app.providers import AudioChunk

    engine = LightweightAvatarEngine(fps=25, size=size)
    engine.configure_session(SessionConfig(fps=25, preview={"type": "WEBRTC"}))
    await engine.prepare(AvatarConfig(avatarId="avatar_school_linux", engine="LIGHTWEIGHT"))
    await engine.start()
    samples_per_frame = 22050 // 25
    pcm = (np.sin(np.linspace(0, 8, samples_per_frame)) * 8000).astype("<i2").tobytes()
    latencies_ms = []
    cpu_started = time.process_time()
    wall_started = time.perf_counter()
    rss_before = rss_mib()
    produced = 0
    for sequence in range(frames):
        started = time.perf_counter()
        rendered = engine._render(AudioChunk(1, sequence, pcm, 22050, 1))
        latencies_ms.append((time.perf_counter() - started) * 1000)
        produced += len(rendered)
    wall_s = time.perf_counter() - wall_started
    cpu_s = time.process_time() - cpu_started
    rss_after = rss_mib()
    await engine.stop()
    return {
        "engine": "LIGHTWEIGHT_AVATAR",
        "device": "CPU",
        "frames_requested": frames,
        "frames_produced": produced,
        "size": size,
        "configured_audio_clock_fps": 25,
        "average_render_capacity_fps": round(produced / wall_s, 2),
        "average_frame_ms": round(statistics.mean(latencies_ms), 3),
        "p50_frame_ms": round(statistics.median(latencies_ms), 3),
        "p95_frame_ms": round(percentile(latencies_ms, 0.95), 3),
        "cpu_pct_process_over_wall": round(cpu_s / wall_s * 100, 1),
        "rss_before_mib": rss_before,
        "rss_after_mib": rss_after,
        "gpu_acceleration": "NOT REQUIRED FOR LIGHTWEIGHT V0.1",
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tts-model-dir", required=True)
    parser.add_argument("--frames", type=int, default=250)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "host": os.uname().nodename,
        "tts": await benchmark_tts(args.tts_model_dir),
        "avatar": await benchmark_avatar(args.frames, args.size),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
