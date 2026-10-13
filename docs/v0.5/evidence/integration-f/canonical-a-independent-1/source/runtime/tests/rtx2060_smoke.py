"""Run on the GPU host: real TTS + lightweight Avatar, other providers Mock."""
import asyncio
import json
import subprocess
import time
import httpx
from app.config import Settings
from app.events import MemoryEventPublisher
from app.main import create_app


def gpu_memory():
    output = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.used,memory.free,temperature.gpu,utilization.gpu", "--format=csv,noheader,nounits"], text=True)
    name, used, free, temperature, utilization = (part.strip() for part in output.strip().split(","))
    return {"gpu": name, "usedMiB": int(used), "freeMiB": int(free), "temperatureC": int(temperature), "utilizationPct": int(utilization)}


async def wait_event(events, kind, utterance=None, timeout=15):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if any(e["eventType"] == kind and (utterance is None or e["utteranceId"] == utterance) for e in events):
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {kind} {utterance}")


async def main():
    stages = {"idle": gpu_memory()}
    assert "RTX 2060" in stages["idle"]["gpu"], stages["idle"]["gpu"]
    pub = MemoryEventPublisher()
    app = create_app(Settings(mock_llm=True, mock_tts=False, mock_avatar=False, mock_media=True), pub)
    stages["runtime_started_tts_loaded"] = gpu_memory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
        create = {"commandId": "cmd_gpu_1", "traceId": "trace_gpu_1", "sessionId": "session_gpu_1", "avatar": {"avatarId": "avatar_gpu_1", "engine": "LIGHTWEIGHT"}, "voice": {"voiceId": "voice_gpu_1", "provider": "SHERPA_ONNX"}, "config": {"fps": 25, "preview": {"type": "WEBRTC"}}, "context": {"roomId": "room_1", "systemPrompt": "你是直播间主持人。"}}
        assert (await client.post("/internal/v1/sessions", json=create)).status_code == 202
        await wait_event(pub.events, "SESSION_READY")
        stages["avatar_ready"] = gpu_memory()
        assert (await client.post("/internal/v1/sessions/session_gpu_1/start", json={"commandId": "cmd_gpu_2", "traceId": "trace_gpu_1"})).status_code == 202
        first = {"commandId": "cmd_gpu_3", "traceId": "trace_gpu_1", "utteranceId": "utt_gpu_1", "text": "欢迎来到直播间，今天介绍一件新衣服。" * 8, "priority": 40, "interruptPolicy": "NONE", "source": "OPERATOR", "voice": {"voiceId": "voice_gpu_1"}}
        assert (await client.post("/internal/v1/sessions/session_gpu_1/utterances", json=first)).status_code == 202
        await wait_event(pub.events, "UTTERANCE_PLAYING", "utt_gpu_1")
        stages["speaking"] = gpu_memory()
        second = {"commandId": "cmd_gpu_4", "traceId": "trace_gpu_2", "utteranceId": "utt_gpu_2", "text": "欢迎大家，直播继续。", "priority": 100, "interruptPolicy": "FORCE", "source": "OPERATOR", "voice": {"voiceId": "voice_gpu_1"}}
        assert (await client.post("/internal/v1/sessions/session_gpu_1/utterances", json=second)).status_code == 202
        await wait_event(pub.events, "UTTERANCE_INTERRUPTED", "utt_gpu_1")
        stages["after_interrupt"] = gpu_memory()
        await wait_event(pub.events, "UTTERANCE_COMPLETED", "utt_gpu_2")
        session = app.state.manager.get_session("session_gpu_1")
        audio = session.media_output.received
        video = session.media_output.video_frames
        video_count = len(video)
        duration = sum(len(c.pcm) / (2 * c.sample_rate * c.channels) for c in audio)
        fps = video_count / duration
        assert audio and video and 20 <= fps <= 30, (len(audio), len(video), fps)
        assert all(c.generation_id == session.generation_id for c in audio)
        assert all(f.generation_id == session.generation_id for f in video)
        assert (await client.post("/internal/v1/sessions/session_gpu_1/stop", json={"commandId": "cmd_gpu_5", "traceId": "trace_gpu_2"})).status_code == 202
        assert session.state == "ENDED" and not session.media_output.video_frames
        stages["after_session_stop"] = gpu_memory()
    await app.state.manager.close()
    stages["after_manager_close"] = gpu_memory()
    print(json.dumps({"gpu": stages["idle"]["gpu"], "gpuMemoryBeforeMiB": stages["idle"]["usedMiB"], "gpuMemoryAfterMiB": stages["after_manager_close"]["usedMiB"], "videoFrames": video_count, "audioSeconds": round(duration, 3), "audioClockFps": round(fps, 2), "interrupt": "PASS", "cleanup": "PASS", "gpuStages": stages}))


if __name__ == "__main__":
    asyncio.run(main())
