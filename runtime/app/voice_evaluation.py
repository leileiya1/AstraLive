"""Provider-injected timing measurement, with no uploads/model loading/subjective scores."""
import asyncio
import time

from .models import VoiceConfig
from .providers import GenerationContext
from .voice_stream import StreamingVoiceAdapter


async def measure_voice_stream(provider, text: str, voice: VoiceConfig,
                               ctx: GenerationContext, timeout_s: float = 120.0):
    import math
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("VOICE_PARAMETERS_INVALID")
    adapter = StreamingVoiceAdapter(provider, voice.voiceId)
    start = time.monotonic()
    first = previous = None
    gaps = []
    chunks = samples = 0
    stream = adapter.timed_stream(text, voice, ctx)
    try:
        async with asyncio.timeout(timeout_s):
            async for item in stream:
                now = time.monotonic()
                if first is None:
                    first = now
                if previous is not None:
                    gaps.append(now - previous)
                if item.first_sample_index != samples or item.pts_us != samples * 1_000_000 // 16000:
                    raise ValueError("VOICE_TIMELINE_INVALID")
                previous = now
                samples += len(item.chunk.pcm) // 2
                chunks += 1
    finally:
        await stream.aclose()
    total = time.monotonic() - start
    sorted_gaps = sorted(gaps)
    return {
        "evidenceKind": "PROVIDER_STREAM_MEASUREMENT",
        "firstPcmMs": (first - start) * 1000,
        "totalMs": total * 1000,
        "audioSeconds": samples / 16000,
        "chunks": chunks,
        "samples": samples,
        "sampleRate": 16000,
        "maxDeliveryGapMs": max(gaps, default=0) * 1000,
        "p95DeliveryGapMs": sorted_gaps[max(0, math.ceil(len(sorted_gaps) * .95) - 1)] * 1000 if gaps else 0,
        "rtf": total / (samples / 16000),
        "measurementBoundary": "resolved provider request to local normalized PCM; excludes browser/network/SoulX",
        # Chunk counts alone cannot establish genuine incremental model inference.
        "subjectiveReview": "PENDING_HUMAN_REVIEW",
        "gpuResources": "NOT_MEASURED",
    }
