import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import shutil
import subprocess
from uuid import uuid4
from typing import Literal
from pydantic import BaseModel, ConfigDict
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .config import Settings
from .events import MemoryEventPublisher, RedisEventPublisher, utc_now
from .models import Accepted, Command, CreateSession, Interrupt, Utterance, WebRTCOffer
from .providers import MockAvatarEngine, MockLLMProvider, MockMediaOutput, MockTTSProvider, OpenAICompatibleLLMProvider
from .session import RuntimeFailure, SessionManager
from .session_binding import BoundSessionManager, BoundXiaoYa, enabled as binding_enabled, service_token
import hmac

class TTSProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voiceId: Literal["xiao_ya"]
    modelRef: Literal["xiaoya-default"]
    speed: Literal[1]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        item = {"level": record.levelname, "message": record.getMessage(), "traceId": getattr(record, "traceId", None), "sessionId": getattr(record, "sessionId", None), "utteranceId": getattr(record, "utteranceId", None), "generationId": getattr(record, "generationId", None)}
        if record.exc_info:
            item["errorType"] = record.exc_info[0].__name__
            item["error"] = "runtime operation failed"
        return json.dumps(item, ensure_ascii=False)


def create_app(settings: Settings | None = None, publisher=None, factories=None) -> FastAPI:
    settings = settings or Settings.from_env()
    bound = binding_enabled()
    if os.getenv("APP_ENV") == "production" and not bound:
        raise RuntimeError("Production Runtime requires Session bindings")
    def require_bundle():
        raise RuntimeFailure("PROVIDER_BINDING_UNAVAILABLE", "A Session binding is required", 409)
    runtime_logger = logging.getLogger("app")
    runtime_logger.setLevel(os.getenv("RUNTIME_LOG_LEVEL", "INFO").upper())
    if not any(isinstance(h.formatter, JsonFormatter) for h in runtime_logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        runtime_logger.addHandler(handler)
    publisher = publisher or (RedisEventPublisher(settings.redis_url) if settings.redis_url else MemoryEventPublisher())
    if factories is None:
        if bound:
            llm_factory = require_bundle
        elif settings.mock_llm:
            llm_factory = MockLLMProvider
        else:
            base, key, model = (os.getenv(name) for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"))
            if not all((base, key, model)):
                raise RuntimeError("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are required")
            max_tokens = int(os.getenv("LLM_MAX_TOKENS", "256"))
            llm_factory = lambda: OpenAICompatibleLLMProvider(base, key, model, max_tokens=max_tokens)
        if bound:
            tts_factory = require_bundle
        elif settings.mock_tts:
            tts_factory = MockTTSProvider
        else:
            from .real_tts import SherpaOnnxTTSProvider
            model_dir = os.getenv("TTS_MODEL_DIR")
            if not model_dir:
                raise RuntimeError("TTS_MODEL_DIR is required when MOCK_TTS=false")
            speaker_id = int(os.getenv("TTS_SPEAKER_ID", "0"))
            num_threads = int(os.getenv("TTS_NUM_THREADS", "2"))
            tts_factory = lambda: SherpaOnnxTTSProvider(model_dir, speaker_id, num_threads)
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
                sinks.append(("rtmp", FFmpegRTMPMediaOutput(settings.rtmp)))
            if not sinks:
                raise RuntimeError("No media output is enabled")
            if len(sinks) == 1 and sinks[0][0] in {"mock", "webrtc"}:
                return sinks[0][1]
            from .media_fanout import FanoutMediaOutput
            return FanoutMediaOutput(
                sinks,
                fps=settings.rtmp.fps if settings.rtmp.enabled else 25,
                video_buffer_ms=settings.rtmp.video_buffer_ms if settings.rtmp.enabled else 400,
                audio_buffer_ms=settings.rtmp.audio_buffer_ms if settings.rtmp.enabled else 400,
            )
        factories = (llm_factory, tts_factory, avatar_factory, media_factory)
    manager = (BoundSessionManager if bound else SessionManager)(settings, publisher, *factories)
    if bound:
        control_token=service_token(os.environ["RUNTIME_CONTROL_TOKEN_FILE"])
        if control_token == service_token(os.environ["CONFIG_WORKER_TOKEN_FILE"]) or control_token == settings.tool_token:
            raise RuntimeError("Runtime control token must be separate")

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
    @app.middleware("http")
    async def trusted_control(request: Request, call_next):
        if bound:
            try:
                expected = "Bearer " + service_token(os.environ["RUNTIME_CONTROL_TOKEN_FILE"])
                authorized = hmac.compare_digest(request.headers.get("Authorization", ""), expected)
            except Exception:
                authorized = False
            if not authorized:
                return JSONResponse(status_code=401, content={"code":"INVALID_ARGUMENT","message":"Trusted control required","details":{"integrationCode":"UNAUTHENTICATED"},"requestId":f"req_{uuid4().hex}","timestamp":utc_now()})
        return await call_next(request)

    @app.get("/internal/v0.4/sessions/{sessionId}/providers")
    async def session_providers(sessionId: str):
        if not bound:
            raise RuntimeFailure("PROVIDER_BINDING_UNAVAILABLE", "Integration disabled", 409)
        return manager.provider_status(sessionId)

    @app.get("/internal/v0.4/sessions/{sessionId}/interaction-traces")
    async def interaction_traces(sessionId: str):
        if not bound:
            raise RuntimeFailure("PROVIDER_BINDING_UNAVAILABLE", "Integration disabled", 409)
        from .interaction_trace import traces
        return {"clockDomain": "runtime_monotonic", "traces": [t.summary() for (sid, _), t in traces.items() if sid == sessionId], "browserObservation": "NOT_TESTED", "rtmpAudienceObservation": "NOT_TESTED"}

    app.state.manager = manager
    app.state.publisher = publisher
    tts_probe_lock=asyncio.Lock()

    @app.post("/internal/v0.4/provider-probes/tts")
    async def probe_tts(body: TTSProbe):
        if not bound:
            raise RuntimeFailure("PROVIDER_TEST_UNAVAILABLE","Integration disabled",409)
        if tts_probe_lock.locked():
            raise RuntimeFailure("PROVIDER_TEST_FAILED","TTS probe busy",429)
        async with tts_probe_lock:
            try:
                # Real installed CPU model; no Mock, GPU work or Session creation.
                provider=await asyncio.to_thread(BoundXiaoYa,os.environ["TTS_MODEL_DIR"])
                from .providers import GenerationContext
                from .models import VoiceConfig
                samples=0;rate=0;nonzero=False
                async with asyncio.timeout(15):
                    async for chunk in provider.synthesize_stream("你好，欢迎来到直播间。",VoiceConfig(voiceId="xiao_ya",provider="xiaoya"),GenerationContext(1,"provider-probe","provider-probe","provider-probe")):
                        rate=chunk.sample_rate;samples+=len(chunk.pcm)//2
                        nonzero=nonzero or any(chunk.pcm)
                if not nonzero or samples<1600:
                    raise ValueError("empty synthesis")
                return {"provider":"xiaoya","real":True,"sampleRate":rate,"samples":samples}
            except Exception:
                raise RuntimeFailure("PROVIDER_TEST_FAILED","Real XiaoYa synthesis unavailable",502) from None

    @app.exception_handler(RuntimeFailure)
    async def runtime_error(request: Request, exc: RuntimeFailure):
        code,details=exc.code,{}
        if request.url.path.startswith("/internal/v1/") and code in {"PROVIDER_BINDING_EXPIRED","PROVIDER_BINDING_UNAVAILABLE","PROVIDER_NOT_CONFIGURED","CONFIG_NOT_VERIFIED","PROVIDER_UNSUPPORTED","PROVIDER_BINDING_INVALID","WORKER_NOT_READY","WORKER_UNAVAILABLE","WORKER_UNREGISTERED","RESOURCE_NOT_FOUND"}:
            code="RUNTIME_UNAVAILABLE" if exc.status>=500 else "CONFLICT"
            details={"integrationCode":exc.code}
        return JSONResponse(status_code=exc.status, content={"code": code, "message": str(exc), "details": details, "requestId": request.headers.get("X-Request-Id", f"req_{uuid4().hex}"), "timestamp": utc_now()})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"code": "INVALID_ARGUMENT", "message": "Invalid request", "details": {}, "requestId": request.headers.get("X-Request-Id", f"req_{uuid4().hex}"), "timestamp": utc_now()})

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
        return {"status": "UP", "runtimeVersion": "0.1.0", "gpu": {"available": gpu_available}, "activeSessions": sum(s.state not in {"ENDED", "FAILED"} for s in manager.sessions.values()), "providers": {"llm": "session-binding" if bound else "mock" if settings.mock_llm else "openai-compatible", "tts": "session-binding" if bound else "mock" if settings.mock_tts else "sherpa-onnx", "avatar": "session-binding" if bound else "mock" if settings.mock_avatar else "lightweight-2d", "media": "+".join(outputs), "events": "redis" if settings.redis_url else "memory"}}

    return app


app = create_app()
