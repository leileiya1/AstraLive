"""CPU-only real bound-provider preflight; credentials never enter output/logs."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
import wave

from app.models import VoiceConfig
from app.providers import GenerationContext, LLMRequest
from app.session_binding import BoundDeepSeek, BoundXiaoYa, service_token
from app.voice_stream import StreamingVoiceAdapter


async def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    result = {"scope": "REAL_LLM_REAL_CPU_TTS_PREFLIGHT_ONLY", "gpu": "NOT_TESTED",
        "llm": {"endpoint": "https://api.deepseek.com", "model": args.model},
        "tts": {"provider": "xiaoya", "mock": False}}
    llm = None
    try:
        key_path = Path(args.llm_key_file)
        result["llm"]["privateCredentialFile"] = key_path.is_file() and not (key_path.stat().st_mode & 0o077)
        key = service_token(key_path)
        errors = {"errorCode": ""}
        llm = BoundDeepSeek({"model": args.model, "maxTokens": 128}, key, errors)
        began = time.monotonic()
        async with asyncio.timeout(30):
            text = "".join([token async for token in llm.stream(LLMRequest(
                "请只用一句简短的中文欢迎观众。", "回答自然简短，不能提及任何密钥或配置。", "此预检无商品事实。"))])
        if not text.strip():
            raise ValueError("empty provider response")
        result["llm"].update(status="PASS", characters=len(text),
            responseSHA256=hashlib.sha256(text.encode()).hexdigest(), seconds=round(time.monotonic()-began, 3),
            propagateFailures=llm.propagate_failures)
    except Exception as exc:
        result["llm"].update(status="FAIL", errorType=type(exc).__name__,
            code=getattr(exc, "code", "PROVIDER_PREFLIGHT_FAILED"))
    finally:
        if llm:
            llm.api_key = ""
            await llm.aclose()
    try:
        model_dir = Path(args.tts_model_dir)
        model = model_dir / "zh_CN-xiao_ya-medium.onnx"
        result["tts"]["modelSHA256"] = hashlib.sha256(model.read_bytes()).hexdigest()
        provider = await asyncio.to_thread(BoundXiaoYa, str(model_dir))
        adapter = StreamingVoiceAdapter(provider, "xiao_ya")
        samples = []
        for index, phrase in enumerate(["欢迎。", "售价九十九元。", "这个水箱容量是五升，适合日常使用。"]):
            began = time.monotonic()
            context = GenerationContext(index+1, "cpu-provider-preflight", "cpu-provider-preflight", f"tts_{index}")
            async with asyncio.timeout(30):
                pcm = b"".join([chunk.pcm async for chunk in adapter.synthesize_stream(
                    phrase, VoiceConfig(voiceId="xiao_ya", provider="xiaoya"), context)])
            original = len(pcm)//2
            pad = (-original)%640
            if not original or not any(pcm):
                raise ValueError("empty/silent TTS")
            filename = f"tts-{index}.wav"
            with wave.open(str(output/filename), "wb") as target:
                target.setnchannels(1); target.setsampwidth(2); target.setframerate(16000); target.writeframes(pcm)
            samples.append({"text": phrase, "sampleRate": 16000, "originalSamples": original,
                "padSamples": pad, "sourceSamples": original+pad,
                "paddedDurationMs": (original+pad)*1000//16000,
                "fitsShortProfile": original+pad<=30720, "fitsSegment8Profile": original+pad<=128000,
                "pcmSHA256": hashlib.sha256(pcm).hexdigest(), "wav": filename,
                "seconds": round(time.monotonic()-began, 3)})
        result["tts"].update(status="PASS", samples=samples)
    except Exception as exc:
        result["tts"].update(status="FAIL", errorType=type(exc).__name__, code="CPU_TTS_PREFLIGHT_FAILED")
    result["status"] = "PASS" if all(result[name].get("status")=="PASS" for name in ["llm", "tts"]) else "FAIL"
    (output/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"]=="PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm-key-file", required=True)
    parser.add_argument("--tts-model-dir", required=True)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--output", required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
