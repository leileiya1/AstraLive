"""Contract-shaped, GPU-free runtime for integration testing."""
import asyncio
import heapq
from datetime import datetime, timezone
import json
import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Command(Strict):
    commandId: str = Field(min_length=1)
    traceId: str = Field(min_length=1)


class Avatar(Strict):
    avatarId: str
    engine: str


class CreateVoice(Strict):
    voiceId: str
    provider: str


class SpeakVoice(Strict):
    voiceId: str


class Preview(Strict):
    type: str = Field(pattern="^WEBRTC$")


class Config(Strict):
    fps: int = Field(ge=1)
    preview: Preview


class Create(Command):
    sessionId: str
    avatar: Avatar
    voice: CreateVoice
    config: Config
    context: "SessionContext"


class SessionContext(Strict):
    roomId: str = Field(min_length=1)
    systemPrompt: str
    activeProductId: str | None = Field(default=None, min_length=1)
    knowledgeBaseId: str | None = Field(default=None, min_length=1)


class PlatformUser(Strict):
    externalId: str = Field(min_length=1)
    nickname: str = Field(min_length=1)


class PlatformContext(Strict):
    eventType: str = Field(pattern="^COMMENT$")
    user: PlatformUser


class Utterance(Command):
    utteranceId: str
    text: str = Field(min_length=1)
    priority: int
    interruptPolicy: str = Field(pattern="^(NONE|INTERRUPT_LOWER_PRIORITY|FORCE)$")
    source: str = Field(pattern="^(OPERATOR|PLATFORM_EVENT|AUTO_SCRIPT|SYSTEM)$")
    platformContext: PlatformContext | None = None
    voice: SpeakVoice


class Interrupt(Command):
    reason: str


class Publisher:
    def __init__(self):
        self.events = []
        self.client = None
        self.url = os.getenv("REDIS_URL")
        self.stream = os.getenv("REDIS_RUNTIME_EVENT_STREAM", "dh.runtime.events.v1")

    async def publish(self, event):
        self.events.append(event)
        if self.url:
            if self.client is None:
                from redis.asyncio import from_url
                self.client = from_url(self.url, decode_responses=True)
            await self.client.xadd(self.stream, {"data": json.dumps(event, ensure_ascii=False)})

    async def close(self):
        if self.client:
            await self.client.aclose()


def create_app(publisher=None):
    app = FastAPI(title="AstraLive Integration Mock Runtime")
    pub = publisher or Publisher()
    sessions = {}
    app.state.publisher = pub
    app.state.sessions = sessions

    def error(status, code, message):
        return JSONResponse(status_code=status, content={"code": code, "message": message,
            "details": {}, "requestId": f"req_{uuid4().hex}",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error(exc.status_code, str(exc.detail), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error(422, "INVALID_ARGUMENT", "Invalid request")

    async def emit(kind, sid, trace, uid=None):
        await pub.publish({"schemaVersion": "1.0", "eventId": f"evt_{uuid4().hex}",
                           "eventType": kind, "sessionId": sid, "utteranceId": uid,
                           "traceId": trace, "occurredAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                           "source": "AI_RUNTIME", "payload": {}})

    def accepted():
        return {"accepted": True, "operationId": f"op_runtime_{uuid4().hex}"}

    def get(sid):
        if sid not in sessions:
            raise HTTPException(404, "SESSION_NOT_FOUND")
        return sessions[sid]

    @app.get("/internal/v1/health")
    async def health():
        return {"status": "UP", "runtimeVersion": "mock-0.1.0", "gpu": {"available": False},
                "activeSessions": len(sessions), "providers": {"llm": "mock", "tts": "mock", "avatar": "mock", "media": "mock"}}

    @app.post("/internal/v1/sessions", status_code=202)
    async def create(body: Create):
        if body.sessionId in sessions:
            raise HTTPException(409, "CONFLICT")
        sessions[body.sessionId] = {"status": "PREPARING", "context": body.context,
            "speech_queue": [], "current_utterance": None, "current_task": None,
            "worker": None, "sequence": 0, "wake": asyncio.Event(), "lock": asyncio.Lock()}

        async def prepare():
            await asyncio.sleep(0.2)
            await emit("SESSION_PREPARING", body.sessionId, body.traceId)
            await asyncio.sleep(0.3)
            await emit("SESSION_READY", body.sessionId, body.traceId)
            sessions[body.sessionId]["status"] = "READY"

        asyncio.create_task(prepare())
        return accepted()

    @app.post("/internal/v1/sessions/{sid}/start", status_code=202)
    async def start(sid: str, body: Command):
        state = get(sid)
        if state["status"] != "READY":
            raise HTTPException(409, "SESSION_NOT_READY")
        state["status"] = "LIVE"
        state["worker"] = asyncio.create_task(work(sid, state))

        async def started():
            await asyncio.sleep(0.3)
            await emit("SESSION_STARTED", sid, body.traceId)

        asyncio.create_task(started())
        return accepted()

    @app.post("/internal/v1/sessions/{sid}/utterances", status_code=202)
    async def speak(sid: str, body: Utterance):
        state = get(sid)
        async with state["lock"]:
            if state["status"] != "LIVE":
                raise HTTPException(409, "SESSION_NOT_RUNNING")
            current = state["current_utterance"]
            if current and (body.interruptPolicy == "FORCE" or
                (body.interruptPolicy == "INTERRUPT_LOWER_PRIORITY" and body.priority > current.priority)):
                await interrupt_current(sid, state)
            await emit("UTTERANCE_QUEUED", sid, body.traceId, body.utteranceId)
            state["sequence"] += 1
            heapq.heappush(state["speech_queue"], (-body.priority, state["sequence"], body))
            state["wake"].set()
        return accepted()

    async def run_utterance(sid, state, body):
        for kind in ("UTTERANCE_GENERATING", "UTTERANCE_SYNTHESIZING", "UTTERANCE_RENDERING", "UTTERANCE_PLAYING", "UTTERANCE_COMPLETED"):
            await emit(kind, sid, body.traceId, body.utteranceId)
            await asyncio.sleep(0.1)

    async def work(sid, state):
        try:
            while True:
                await state["wake"].wait()
                async with state["lock"]:
                    if not state["speech_queue"]:
                        state["wake"].clear()
                        continue
                    _, _, body = heapq.heappop(state["speech_queue"])
                    state["current_utterance"] = body
                    task = asyncio.create_task(run_utterance(sid, state, body))
                    state["current_task"] = task
                try:
                    await task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                finally:
                    async with state["lock"]:
                        if state["current_task"] is task:
                            state["current_task"] = None
                        if state["current_utterance"] is body:
                            state["current_utterance"] = None
        except asyncio.CancelledError:
            pass

    async def interrupt_current(sid, state):
        body = state["current_utterance"]
        if body:
            state["current_utterance"] = None
            state["current_task"].cancel()
            await emit("UTTERANCE_INTERRUPTED", sid, body.traceId, body.utteranceId)

    @app.post("/internal/v1/sessions/{sid}/interrupt", status_code=202)
    async def interrupt(sid: str, body: Interrupt):
        state = get(sid)
        async with state["lock"]:
            if state["status"] != "LIVE":
                raise HTTPException(409, "SESSION_NOT_RUNNING")
            await interrupt_current(sid, state)
        return accepted()

    @app.post("/internal/v1/sessions/{sid}/webrtc/offer")
    async def webrtc_offer(sid: str, body: dict):
        get(sid)
        if body.get("type") != "offer" or not isinstance(body.get("sdp"), str) or not body["sdp"] or set(body) != {"type", "sdp"}:
            raise HTTPException(422, "INVALID_ARGUMENT")
        return error(503, "WEBRTC_FAILED", "Mock media does not support WebRTC")

    @app.post("/internal/v1/sessions/{sid}/stop", status_code=202)
    async def stop(sid: str, body: Command):
        state = get(sid)
        async with state["lock"]:
            state["status"] = "STOPPING"
            await interrupt_current(sid, state)
            queued = [entry[2] for entry in state["speech_queue"]]
            state["speech_queue"].clear()
            state["worker"].cancel() if state["worker"] else None
        if state["worker"]:
            await asyncio.gather(state["worker"], return_exceptions=True)
        await emit("SESSION_STOPPING", sid, body.traceId)
        for item in queued:
            await emit("UTTERANCE_INTERRUPTED", sid, item.traceId, item.utteranceId)
        await emit("SESSION_ENDED", sid, body.traceId)
        del sessions[sid]
        return accepted()

    return app


app = create_app()
