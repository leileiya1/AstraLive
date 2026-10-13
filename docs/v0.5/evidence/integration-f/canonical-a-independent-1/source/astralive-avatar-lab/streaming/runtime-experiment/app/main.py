import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import shutil
import subprocess
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .config import Settings
from .events import MemoryEventPublisher, RedisEventPublisher, utc_now
from .models import Accepted, Command, CreateSession, Interrupt, Utterance, WebRTCOffer
from .providers import MockAvatarEngine, MockLLMProvider, MockMediaOutput, MockTTSProvider, OpenAICompatibleLLMProvider
from .session import RuntimeFailure, SessionManager


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        item = {"level": record.levelname, "message": record.getMessage(), "traceId": getattr(record, "traceId", None), "sessionId": getattr(record, "sessionId", None), "utteranceId": getattr(record, "utteranceId", None), "generationId": getattr(record, "generationId", None)}
        if record.exc_info:
            item["errorType"] = record.exc_info[0].__name__
            item["error"] = str(record.exc_info[1])
        return json.dumps(item, ensure_ascii=False)


def create_app(settings: Settings | None = None, publisher=None, factories=None) -> FastAPI:
    settings = settings or Settings.from_env()
    runtime_logger = logging.getLogger("app")
    runtime_logger.setLevel(os.getenv("RUNTIME_LOG_LEVEL", "INFO").upper())
    if not any(isinstance(h.formatter, JsonFormatter) for h in runtime_logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        runtime_logger.addHandler(handler)
    publisher = publisher or (RedisEventPublisher(settings.redis_url) if settings.redis_url else MemoryEventPublisher())
    if settings.redis_url and os.getenv("AVATAR_PROVIDER") == "SOULX_LITE_REMOTE":
        class ExperimentJournal:
            def __init__(self,inner):self.inner=inner;self.events=[]
            async def publish(self,event):
                await self.inner.publish(event);self.events.append(event)
                if len(self.events)>1000:del self.events[:-1000]
            async def close(self):await self.inner.close()
        publisher=ExperimentJournal(publisher)

    if factories is None:
        if settings.mock_llm:
            llm_factory = MockLLMProvider
        else:
            base, key, model = (os.getenv(name) for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"))
            if not all((base, key, model)):
                raise RuntimeError("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are required")
            max_tokens = int(os.getenv("LLM_MAX_TOKENS", "256"))
            llm_factory = lambda: OpenAICompatibleLLMProvider(base, key, model, max_tokens=max_tokens)
        if settings.mock_tts:
            tts_factory = MockTTSProvider
        else:
            from .real_tts import SherpaOnnxTTSProvider
            model_dir = os.getenv("TTS_MODEL_DIR")
            if not model_dir:
                raise RuntimeError("TTS_MODEL_DIR is required when MOCK_TTS=false")
            speaker_id = int(os.getenv("TTS_SPEAKER_ID", "0"))
            num_threads = int(os.getenv("TTS_NUM_THREADS", "2"))
            tts_factory = lambda: SherpaOnnxTTSProvider(model_dir, speaker_id, num_threads)
        remote_avatar_enabled = os.getenv("AVATAR_PROVIDER", "LIGHTWEIGHT_AVATAR") == "SOULX_LITE_REMOTE"
        remote_pair = {}
        if remote_avatar_enabled:
            from .soulx_remote import RemoteAvatarEngine, ConsumptionMediaOutput
            def avatar_factory():
                avatar = RemoteAvatarEngine()
                remote_pair["avatar"] = avatar
                return avatar
        else:
            if settings.mock_avatar:
                avatar_factory = MockAvatarEngine
            else:
                from .lightweight_avatar import LightweightAvatarEngine
                image_path = os.getenv("AVATAR_IMAGE_PATH") or None
                avatar_factory = lambda: LightweightAvatarEngine(image_path=image_path)
        def media_factory():
            sinks = []
            if settings.mock_media:
                sinks.append(("mock", MockMediaOutput()))
            elif settings.webrtc_enabled:
                from .webrtc_media import WebRTCMediaOutput
                sinks.append(("webrtc", WebRTCMediaOutput()))
            if settings.rtmp.enabled:
                from .rtmp_media import FFmpegRTMPMediaOutput
                if remote_avatar_enabled and os.getenv("SOULX_PAIRED_RTMP") == "1":
                    from .soulx_rtmp_clock import PairedRTMPMediaOutput
                    sinks.append(("rtmp", PairedRTMPMediaOutput(settings.rtmp)))
                else:
                    sinks.append(("rtmp", FFmpegRTMPMediaOutput(settings.rtmp)))
            if not sinks:
                raise RuntimeError("No media output is enabled")
            if len(sinks) == 1 and sinks[0][0] in {"mock", "webrtc"}:
                result = sinks[0][1]
                return ConsumptionMediaOutput(result, remote_pair["avatar"]) if remote_avatar_enabled else result
            from .media_fanout import FanoutMediaOutput
            result = FanoutMediaOutput(
                sinks,
                fps=settings.rtmp.fps if settings.rtmp.enabled else 25,
                video_buffer_ms=settings.rtmp.video_buffer_ms if settings.rtmp.enabled else 400,
                audio_buffer_ms=settings.rtmp.audio_buffer_ms if settings.rtmp.enabled else 400,
            )
            return ConsumptionMediaOutput(result, remote_pair["avatar"]) if remote_avatar_enabled else result
        factories = (llm_factory, tts_factory, avatar_factory, media_factory)
    manager = SessionManager(settings, publisher, *factories)

    async def acceptance_diagnostics() -> None:
        interval = float(os.getenv("RUNTIME_MEDIA_METRICS_INTERVAL_SECONDS", os.getenv("ACCEPTANCE_MEDIA_METRICS_INTERVAL_SECONDS", "0")))
        if interval <= 0:
            return
        while True:
            rows = []
            for session_id, session in tuple(manager.sessions.items()):
                diagnostic = getattr(session.media_output, "diagnostics", lambda: {})()
                rows.append({"sessionId": session_id, "state": session.state,
                             "generationId": session.generation_id, "media": diagnostic})
            runtime_logger.info("runtime_media_metrics %s", json.dumps({"sessions": rows}))
            await asyncio.sleep(interval)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        diagnostic_task = None
        if float(os.getenv("RUNTIME_MEDIA_METRICS_INTERVAL_SECONDS", os.getenv("ACCEPTANCE_MEDIA_METRICS_INTERVAL_SECONDS", "0"))) > 0:
            diagnostic_task = asyncio.create_task(acceptance_diagnostics(), name="acceptance-media-metrics")
        try:
            yield
        finally:
            if diagnostic_task:
                diagnostic_task.cancel()
                await asyncio.gather(diagnostic_task, return_exceptions=True)
            await manager.close()
            if hasattr(publisher, "close"):
                await publisher.close()

    app = FastAPI(title="AstraLive AI Runtime", version="0.1.0", lifespan=lifespan)
    app.state.manager = manager
    app.state.publisher = publisher

    @app.exception_handler(RuntimeFailure)
    async def runtime_error(request: Request, exc: RuntimeFailure):
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": str(exc), "details": {}, "requestId": request.headers.get("X-Request-Id", f"req_{uuid4().hex}"), "timestamp": utc_now()})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"code": "INVALID_ARGUMENT", "message": "Invalid request", "details": {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}, "requestId": request.headers.get("X-Request-Id", f"req_{uuid4().hex}"), "timestamp": utc_now()})

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        logging.getLogger("app").exception("internal_error")
        return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": "Internal runtime error", "details": {}, "requestId": request.headers.get("X-Request-Id", f"req_{uuid4().hex}"), "timestamp": utc_now()})

    def accepted() -> Accepted:
        return Accepted(operationId=f"op_runtime_{uuid4().hex}")

    @app.post("/internal/v1/sessions", status_code=202, response_model=Accepted)
    async def create_session(body: CreateSession):
        await manager.create_session(body)
        return accepted()

    @app.post("/internal/v1/sessions/{sessionId}/start", status_code=202, response_model=Accepted)
    async def start_session(sessionId: str, body: Command):
        await manager.start_session(sessionId, body.traceId)
        return accepted()

    @app.post("/internal/v1/sessions/{sessionId}/utterances", status_code=202, response_model=Accepted)
    async def speak(sessionId: str, body: Utterance):
        await manager.speak(sessionId, body)
        return accepted()

    @app.post("/internal/v1/sessions/{sessionId}/webrtc/offer")
    async def webrtc_offer(sessionId: str, body: WebRTCOffer):
        return {"type": "answer", "sdp": await manager.webrtc_answer(sessionId, body.sdp)}

    @app.post("/internal/v1/sessions/{sessionId}/interrupt", status_code=202, response_model=Accepted)
    async def interrupt(sessionId: str, body: Interrupt):
        await manager.interrupt(sessionId, body.traceId)
        return accepted()

    @app.post("/internal/v1/sessions/{sessionId}/stop", status_code=202, response_model=Accepted)
    async def stop(sessionId: str, body: Command):
        await manager.stop_session(sessionId, body.traceId)
        return accepted()

    @app.get("/internal/v1/health")
    async def health():
        gpu_available = False
        if not settings.mock_avatar and shutil.which("nvidia-smi"):
            try:
                gpu_available = subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=2, check=False).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                gpu_available = False
        outputs = []
        if settings.mock_media:
            outputs.append("mock")
        elif settings.webrtc_enabled:
            outputs.append("webrtc")
        if settings.rtmp.enabled:
            outputs.append("rtmp")
        return {"status": "UP", "runtimeVersion": "0.1.0", "gpu": {"available": gpu_available}, "activeSessions": sum(s.state not in {"ENDED", "FAILED"} for s in manager.sessions.values()), "providers": {"llm": "mock" if settings.mock_llm else "openai-compatible", "tts": "mock" if settings.mock_tts else "sherpa-onnx", "avatar": "soulx-lite-remote" if os.getenv("AVATAR_PROVIDER") == "SOULX_LITE_REMOTE" else ("mock" if settings.mock_avatar else "lightweight-2d"), "media": "+".join(outputs), "events": "redis" if settings.redis_url else "memory"}}

    @app.get("/experiment/real-avatar-status")
    async def experiment_status(request: Request):
        import hmac
        from pathlib import Path
        root = os.getenv("SOULX_EXPERIMENT_DIR")
        if not root or not hmac.compare_digest(request.headers.get("X-Experiment-Token", ""), (Path(root)/".private/token").read_text().strip()):
            return JSONResponse(status_code=403,content={"error":"private experiment"})
        rows=[]
        for sid,session in manager.sessions.items():
            avatar=session.avatar_engine
            if hasattr(avatar,"link"):
                rows.append({"sessionId":sid,"state":session.state,"generationId":session.generation_id,"firstPCMMonotonic":avatar.first_pcm,"marker":avatar.marker,"speaking":avatar.speaking,"degraded":avatar.degraded,"workerEpoch":avatar.link.epoch if avatar.link else None,"sourceJob":avatar.pipeline.job_id if avatar.pipeline else None,"lastFrame":{k:v for k,v in (avatar.last_frame or {}).items() if k in {"source","generation_id","frame_sequence","pts_us"}}})
        return {"schoolMonotonic":__import__("time").monotonic(),"sessions":rows,"events":getattr(publisher,"events",[])[-100:]}
    return app


app = create_app()
