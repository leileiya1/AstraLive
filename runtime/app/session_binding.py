"""v0.4 integration around frozen Session and Worker contracts."""
import asyncio
from datetime import datetime, timezone
import json
import os
from types import SimpleNamespace
import httpx
from .providers import OpenAICompatibleLLMProvider
from .session import RuntimeFailure, SessionManager


def enabled():
    return os.getenv("SESSION_BINDINGS_ENABLED") == "true"


def service_token(path):
    from gpu_worker.config import secret
    return secret(path)


class BindingClient:
    def __init__(self, base_url, token_path, transport=None):
        self.base_url, self.token_path, self.transport = base_url.rstrip("/"), token_path, transport

    async def call(self, method, sid):
        if not sid or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for c in sid):
            raise RuntimeFailure("INVALID_ARGUMENT", "Invalid Session", 422)
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False, transport=self.transport) as client:
                response = await client.request(method, f"{self.base_url}/internal/v0.4/sessions/{sid}/binding", headers={"Authorization": "Bearer " + service_token(self.token_path)})
                if len(response.content) > 131072:
                    raise ValueError
                packet = response.json()
                if response.status_code >= 300 or packet.get("code") != "OK":
                    code = packet.get("code")
                    if code not in {"PROVIDER_BINDING_EXPIRED", "PROVIDER_BINDING_UNAVAILABLE", "CONFIG_NOT_VERIFIED", "WORKER_NOT_READY", "WORKER_UNAVAILABLE", "WORKER_UNREGISTERED", "RESOURCE_NOT_FOUND", "PROVIDER_NOT_CONFIGURED", "PROVIDER_UNSUPPORTED", "PROVIDER_BINDING_INVALID"}:
                        code = "PROVIDER_BINDING_UNAVAILABLE"
                    raise RuntimeFailure(code, "Provider binding unavailable", 503 if response.status_code >= 500 else 409)
                return packet["data"]
        except RuntimeFailure:
            raise
        except Exception:
            raise RuntimeFailure("PROVIDER_BINDING_UNAVAILABLE", "Binding service unavailable", 503) from None

    async def resolve(self, sid):
        return await self.call("GET", sid)

    async def release(self, sid):
        await self.call("DELETE", sid)


class FixedDeepSeekTransport(httpx.AsyncBaseTransport):
    def __init__(self, temperature=None, transport=None):
        self.inner = transport or httpx.AsyncHTTPTransport(trust_env=False)
        self.temperature = temperature

    async def handle_async_request(self, request):
        if str(request.url) != "https://api.deepseek.com/chat/completions":
            raise RuntimeError("LLM endpoint blocked")
        payload = json.loads(request.content)
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        request = httpx.Request("POST", "https://api.deepseek.com/chat/completions", headers=request.headers, content=json.dumps(payload).encode())
        request.headers["Content-Length"] = str(len(request.content))
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()


class BoundDeepSeek(OpenAICompatibleLLMProvider):
    propagate_failures = True
    def __init__(self, config, key, errors):
        super().__init__("https://api.deepseek.com", key, config["model"], config["maxTokens"])
        self.config, self.errors = config, errors

    async def stream(self, request):
        self.transport = FixedDeepSeekTransport(self.config.get("temperature"))
        try:
            async for token in super().stream(request):
                yield token
            self.errors["errorCode"] = ""
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = "PROVIDER_AUTH_FAILED" if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403} else "LLM_FAILED"
            self.errors["errorCode"] = code
            raise RuntimeFailure(code, "Bound LLM request failed", 502) from None


class BoundXiaoYa:
    def __init__(self, model_dir):
        from .real_tts import SherpaOnnxTTSProvider
        self.inner = SherpaOnnxTTSProvider(model_dir, 0, int(os.getenv("TTS_NUM_THREADS", "2")))

    async def synthesize_stream(self, text, voice, ctx):
        from .models import VoiceConfig
        async for chunk in self.inner.synthesize_stream(text, VoiceConfig(voiceId="xiao_ya", provider="xiaoya"), ctx):
            yield chunk


def bundle_factories(packet, sid, media_factory, errors):
    from gpu_worker.client import resolve_binding
    from gpu_worker.runtime_adapter import RemoteAvatarEngine
    from .bound_media import BoundConsumptionMediaOutput
    binding, scope = packet["binding"], packet["scope"]
    profiles = {p["kind"]: p for p in binding["profiles"]}
    if len(profiles) != len(binding["profiles"]) or any(k not in profiles for k in ("LLM", "TTS", "AVATAR", "GPU_WORKER")):
        raise RuntimeFailure("PROVIDER_NOT_CONFIGURED", "Required defaults are missing", 409)
    llm, tts = profiles["LLM"], profiles["TTS"]
    for p in profiles.values():
        if not p["enabled"] or not p["isDefault"]:
            raise RuntimeFailure("PROVIDER_BINDING_INVALID", "Invalid selected Provider", 409)
    key = packet["credentials"].get(llm["profileId"])
    if llm["provider"] != "deepseek" or llm["verification"] != "VERIFIED" or not key:
        raise RuntimeFailure("CONFIG_NOT_VERIFIED", "Verified DeepSeek credential required", 409)
    if tts["provider"] != "xiaoya" or tts["config"] != {"voiceId": "xiao_ya", "speed": 1, "modelRef": "xiaoya-default"}:
        raise RuntimeFailure("PROVIDER_UNSUPPORTED", "XiaoYa preset speed 1 required", 409)
    endpoint = resolve_binding(binding, os.environ["GPU_WORKER_INFERENCE_REGISTRY_FILE"], scope)
    endpoint["allowSimulation"] = False
    cfg = SimpleNamespace(state_dir=os.environ["SESSION_PROVIDER_STATE_DIR"], worker_ref=profiles["GPU_WORKER"]["config"]["workerRef"], startup_timeout_s=300, log_bytes=10*1024*1024, log_backups=5)

    class StrictSoulX(RemoteAvatarEngine):
        async def prepare(self, config):
            await super().prepare(config)
            ready = self.link.ready or {}
            if self.degraded or ready.get("simulation") or ready.get("input_asset_sha256") != endpoint["assetSHA256"] or not ready.get("cache_id"):
                await self.stop()
                raise RuntimeFailure("WORKER_NOT_READY", "Selected SoulX Worker unavailable", 503)

    pair = {}
    def avatar_factory():
        if pair:
            raise RuntimeError("Provider bundle already assigned")
        pair["avatar"] = StrictSoulX(endpoint, sid, cfg, os.getenv("AVATAR_IMAGE_PATH") or None)
        return pair["avatar"]
    return (lambda: BoundDeepSeek(llm["config"], key, errors), lambda: BoundXiaoYa(os.environ["TTS_MODEL_DIR"]), avatar_factory, lambda: BoundConsumptionMediaOutput(media_factory(), pair["avatar"]))


class BoundSessionManager(SessionManager):
    def __init__(self, settings, publisher, *factories, binding_client=None, bundle_builder=None):
        super().__init__(settings, publisher, *factories)
        self.binding_client = binding_client or BindingClient(os.environ["CONFIG_BACKEND_URL"], os.environ["CONFIG_WORKER_TOKEN_FILE"])
        self.bundle_builder = bundle_builder or bundle_factories
        self.bound, self.leases, self.monitors = {}, {}, {}
        self.admission = asyncio.Lock()
        self.releasing, self.release_pending = set(), set()
        self.cleanups=set()

    async def create_session(self, request, **kwargs):
        async with self.admission:
            if request.sessionId in self.sessions:
                raise RuntimeFailure("CONFLICT", "Session already exists", 409)
            packet = None
            try:
                packet = await self.binding_client.resolve(request.sessionId)
                binding = packet["binding"]
                expires = datetime.fromisoformat(binding["expiresAt"].replace("Z", "+00:00"))
                ttl = (expires - datetime.now(timezone.utc)).total_seconds()
                if packet.get("integrationVersion") != "0.4.0" or binding.get("contractVersion") != "0.3.0" or not 60 < ttl <= 86400:
                    raise RuntimeFailure("PROVIDER_BINDING_EXPIRED", "Binding lease exhausted", 409)
                worker = next(p["config"]["workerRef"] for p in binding["profiles"] if p["kind"] == "GPU_WORKER")
                if any(v["workerRef"] == worker for v in self.bound.values()):
                    raise RuntimeFailure("RUNTIME_OVERLOADED", "Selected Worker already assigned", 429)
                errors = {"errorCode": ""}
                factories = self.bundle_builder(packet, request.sessionId, self.media_factory, errors)
                self.bound[request.sessionId] = {"integrationVersion": "0.4.0", "sessionId": request.sessionId, "bindingId": binding["bindingId"], "capturedAt": packet["capturedAt"], "expiresAt": binding["expiresAt"], "profiles": [{k: p[k] for k in ("profileId", "kind", "provider", "version", "updatedAt")} for p in binding["profiles"] if p["kind"] != "LIVE_PLATFORM"], "errors": errors, "workerRef": worker, "deadline": asyncio.get_running_loop().time()+ttl}
                await super().create_session(request, factories=factories, max_queue=binding["settings"]["policy"]["maxQueue"])
                self.leases[request.sessionId] = asyncio.create_task(self._lease(request.sessionId, ttl-60))
                self.monitors[request.sessionId] = asyncio.create_task(self._monitor(request.sessionId))
                for task in tuple(self.sessions[request.sessionId].tasks):
                    task.add_done_callback(lambda t, sid=request.sessionId: asyncio.create_task(self._prepare_done(sid)))
            except BaseException:
                if packet is not None:
                    await self._failed_cleanup(request.sessionId)
                raise
            finally:
                if packet:
                    packet.get("credentials", {}).clear()

    async def _prepare_done(self, sid):
        session = self.sessions.get(sid)
        if session and session.state == "FAILED":
            await self._failed_cleanup(sid)

    async def _failed_cleanup(self, sid):
        task=asyncio.current_task()
        self.cleanups.add(task)
        try:
            await self._cleanup_failed_session(sid)
        finally:
            self.cleanups.discard(task)

    async def _cleanup_failed_session(self, sid):
        session = self.sessions.pop(sid, None)
        if session:
            tasks={task for task in (session.worker,session.current_task,*session.tasks) if task and task is not asyncio.current_task() and not task.done()}
            for task in tasks:
                task.cancel()
            if tasks:
                try:
                    await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),2)
                except asyncio.TimeoutError:
                    pass
            for obj in (session.avatar_engine, session.media_output):
                try:
                    await asyncio.wait_for(obj.stop(), 10)
                except Exception:
                    pass
            if hasattr(session.llm, "api_key"):
                session.llm.api_key = ""
        await self._release(sid)

    async def _release(self, sid):
        if sid in self.releasing:
            return
        self.releasing.add(sid)
        try:
            for tasks in (self.leases, self.monitors):
                task = tasks.pop(sid, None)
                if task and task is not asyncio.current_task():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            self.bound.pop(sid, None)
            try:
                await self.binding_client.release(sid)
                self.release_pending.discard(sid)
            except Exception:
                self.release_pending.add(sid)
        finally:
            self.releasing.discard(sid)

    def _check_lease(self, sid):
        rec = self.bound.get(sid)
        if rec is None or asyncio.get_running_loop().time() >= rec["deadline"]-60:
            raise RuntimeFailure("PROVIDER_BINDING_EXPIRED", "Binding lease exhausted", 409)

    async def start_session(self, sid, trace):
        self._check_lease(sid)
        if self.get_session(sid).state != "READY":
            raise RuntimeFailure("SESSION_NOT_READY", "Session is not ready", 409)
        try:
            await super().start_session(sid, trace)
        except Exception:
            session = self.sessions.get(sid)
            if session:
                session.state = "FAILED"
                await session.emit("SESSION_FAILED", trace, payload={"code": "PROVIDER_START_FAILED"})
            await self._failed_cleanup(sid)
            raise

    async def speak(self, sid, item):
        self._check_lease(sid)
        await super().speak(sid, item)

    async def interrupt(self, sid, trace):
        self._check_lease(sid)
        await super().interrupt(sid, trace)

    async def webrtc_answer(self, sid, sdp):
        self._check_lease(sid)
        return await super().webrtc_answer(sid, sdp)

    async def stop_session(self, sid, trace):
        session = self.sessions.get(sid)
        try:
            if session:
                await super().stop_session(sid, trace)
        finally:
            if session and hasattr(session.llm, "api_key"):
                session.llm.api_key = ""
            await self._release(sid)

    async def _lease(self, sid, delay):
        await asyncio.sleep(delay)
        session = self.sessions.get(sid)
        if session:
            await session.emit("RUNTIME_WARNING", session.request.traceId, payload={"code": "PROVIDER_BINDING_EXPIRED"})
            if session.state in {"PREPARING", "READY"}:
                session.state = "FAILED"
                await session.emit("SESSION_FAILED", session.request.traceId, payload={"code": "PROVIDER_BINDING_EXPIRED"})
                await self._failed_cleanup(sid)
            else:
                await self.stop_session(sid, session.request.traceId)

    def provider_status(self, sid):
        rec = self.bound.get(sid)
        if rec is None:
            raise RuntimeFailure("PROVIDER_BINDING_UNAVAILABLE", "Binding unavailable", 404)
        session = self.get_session(sid)
        avatar = session.avatar_engine
        mode = "UNAVAILABLE" if session.state not in {"LIVE", "READY"} else "DEGRADED" if getattr(avatar, "degraded", False) else "REAL"
        ready = getattr(getattr(avatar, "link", None), "ready", {}) or {}
        if mode == "REAL" and (not ready or ready.get("simulation")):
            mode = "UNAVAILABLE"
        code = rec["errors"]["errorCode"] or ("WORKER_DISCONNECTED" if mode == "DEGRADED" else "SESSION_NOT_STARTED" if mode == "UNAVAILABLE" else "")
        if rec["errors"]["errorCode"]:
            mode = "UNAVAILABLE"
        return {**{k: v for k, v in rec.items() if k not in {"errors", "workerRef", "deadline"}}, "mode": mode, "errorCode": code, "workerEpoch": getattr(getattr(avatar, "link", None), "epoch", "") or ""}

    async def _monitor(self, sid):
        previous = None
        was_degraded = False
        while sid in self.bound:
            session = self.sessions.get(sid)
            if not session:
                return
            status = self.provider_status(sid)
            if session.state == "LIVE" and self.bound[sid]["errors"]["errorCode"] in {"PROVIDER_AUTH_FAILED","LLM_FAILED"}:
                code=self.bound[sid]["errors"]["errorCode"]
                session.state="FAILED"
                await session.emit("SESSION_FAILED",session.request.traceId,payload={"code":code})
                await self._failed_cleanup(sid)
                return
            degraded = bool(getattr(session.avatar_engine,"degraded",False))
            if session.state == "LIVE" and degraded != was_degraded:
                await session.emit("SESSION_DEGRADED" if degraded else "SESSION_STARTED", session.request.traceId, payload={"code":"WORKER_DISCONNECTED" if degraded else "WORKER_RECOVERED"})
                was_degraded = degraded
            if session.state == "LIVE" and status["errorCode"] and status["errorCode"] != previous:
                await session.emit("RUNTIME_WARNING", session.request.traceId, payload={"code": status["errorCode"]})
            if previous == "WORKER_DISCONNECTED" and status["errorCode"] == "":
                await session.emit("RUNTIME_WARNING", session.request.traceId, payload={"code": "WORKER_RECOVERED"})
            previous = status["errorCode"]
            for pending in tuple(self.release_pending):
                try:
                    await self.binding_client.release(pending)
                    self.release_pending.discard(pending)
                except Exception:
                    pass
            await asyncio.sleep(1)

    async def close(self):
        for sid in tuple(self.sessions):
            await self.stop_session(sid, self.sessions[sid].request.traceId)
        if self.cleanups:
            await asyncio.gather(*(task for task in tuple(self.cleanups) if task is not asyncio.current_task()),return_exceptions=True)
        for sid in tuple(self.release_pending):
            await self._release(sid)
