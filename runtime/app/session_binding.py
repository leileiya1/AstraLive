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
        self.inner = transport or httpx.AsyncHTTPTransport(trust_env=False, limits=httpx.Limits(max_connections=1, max_keepalive_connections=1, keepalive_expiry=60))
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
        # Test-only provider call evidence is captured once; no secret/prompt
        # contents are persisted and production logging is unchanged by default.
        self.observer_dir = os.getenv("ASTRALIVE_STAGING_OBSERVER_DIR")
        self.observer_sequence = 0

    async def stream(self, request):
        if self.client is None:
            self.transport = FixedDeepSeekTransport(self.config.get("temperature"))
            self.client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), transport=self.transport, trust_env=False, follow_redirects=False)
        started = asyncio.get_running_loop().time()
        self.observer_sequence += 1
        observed = ""
        outcome = "FAILED"
        try:
            async for token in super().stream(request):
                observed += token
                yield token
            self.errors["errorCode"] = ""
            outcome = "COMPLETED"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = "PROVIDER_AUTH_FAILED" if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403} else "LLM_FAILED"
            self.errors["errorCode"] = code
            raise RuntimeFailure(code, "Bound LLM request failed", 502) from None
        finally:
            if self.observer_dir:
                import hashlib
                from pathlib import Path
                folder=Path(self.observer_dir);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                role="bridge_choice" if request.system_prompt.startswith("你只选择口语过渡") else "ordinary_speech"
                row={"scope":"REAL_BOUND_LLM_CALL_OBSERVER","role":role,"callSequence":self.observer_sequence,
                    "status":outcome,"model":self.config["model"],"requestHash":"sha256:"+hashlib.sha256(request.text.encode()).hexdigest(),
                    "responseHash":"sha256:"+hashlib.sha256(observed.encode()).hexdigest(),"responseChars":len(observed),
                    "durationMs":round((asyncio.get_running_loop().time()-started)*1000),"audienceAudible":False}
                with (folder/"llm-calls.jsonl").open("a") as handle:handle.write(json.dumps(row,ensure_ascii=False)+"\n")

    async def aclose(self):
        if self.client is not None:
            client, self.client = self.client, None
            await client.aclose()


class BoundXiaoYa:
    def __init__(self, model_dir):
        from .real_tts import SherpaOnnxTTSProvider
        self.inner = SherpaOnnxTTSProvider(model_dir, 0, int(os.getenv("TTS_NUM_THREADS", "2")))

    async def synthesize_stream(self, text, voice, ctx):
        from .models import VoiceConfig
        async for chunk in self.inner.synthesize_stream(text, VoiceConfig(voiceId="xiao_ya", provider="xiaoya"), ctx):
            yield chunk


def bundle_factories(packet, sid, media_factory, errors, staging=None):
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

    if staging is not None and staging.enabled:
        from .soulx_staging import StagingAvatarEngine
        return (lambda: BoundDeepSeek(llm["config"], key, errors),
                lambda: BoundXiaoYa(os.environ["TTS_MODEL_DIR"]),
                lambda: StagingAvatarEngine(endpoint,sid,cfg.worker_ref,staging),media_factory)

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
        self.release_requires_ack = set()
        self.cleanups=set()
        # Volatile proof only; never persisted/rehydrated after Runtime restart.
        self.failed_create_cleanup={}
        from .staging_settings import StagingSettings
        self.staging_settings=StagingSettings()

    async def create_session(self, request, **kwargs):
        async with self.admission:
            if request.sessionId in self.sessions:
                raise RuntimeFailure("CONFLICT", "Session already exists", 409)
            packet = None
            phase={"avatar":None,"mediaEntered":False};begin=None;binding=None
            self.failed_create_cleanup.pop(request.sessionId,None)
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
                commands=getattr(self.publisher,"run_commands",{})
                begin=commands.get((request.sessionId,"BEGIN_RUN"))
                flags=begin.get("payload",{}).get("featureFlags",{}) if begin else {}
                self.staging_settings.check_capture(flags)
                if self.staging_settings.enabled:
                    if not begin or self.bundle_builder is not bundle_factories:
                        raise RuntimeFailure("DEPENDENCY_UNAVAILABLE","Authenticated staging capture required",503)
                    factories=bundle_factories(packet,request.sessionId,self.media_factory,errors,self.staging_settings)
                    llm_factory,tts_factory,avatar_factory,media_factory=factories
                    def tracked_avatar():
                        avatar=avatar_factory();phase["avatar"]=avatar;return avatar
                    def tracked_media():
                        phase["mediaEntered"]=True;return media_factory()
                    factories=(llm_factory,tts_factory,tracked_avatar,tracked_media)
                else:factories = self.bundle_builder(packet, request.sessionId, self.media_factory, errors)
                self.bound[request.sessionId] = {"integrationVersion": "0.4.0", "sessionId": request.sessionId, "bindingId": binding["bindingId"], "capturedAt": packet["capturedAt"], "expiresAt": binding["expiresAt"], "profiles": [{k: p[k] for k in ("profileId", "kind", "provider", "version", "updatedAt")} for p in binding["profiles"] if p["kind"] != "LIVE_PLATFORM"], "errors": errors, "workerRef": worker, "deadline": asyncio.get_running_loop().time()+ttl}
                await super().create_session(request, factories=factories, max_queue=binding["settings"]["policy"]["maxQueue"])
                self.leases[request.sessionId] = asyncio.create_task(self._lease(request.sessionId, ttl-60))
                self.monitors[request.sessionId] = asyncio.create_task(self._monitor(request.sessionId))
                for task in tuple(self.sessions[request.sessionId].tasks):
                    task.add_done_callback(lambda t, sid=request.sessionId: asyncio.create_task(self._prepare_done(sid)))
            except BaseException:
                if packet is not None:
                    from .soulx_staging import StagingAvatarEngine
                    avatar=phase["avatar"]
                    journal=getattr(self.publisher,"journal",None)
                    if (isinstance(avatar,StagingAvatarEngine) and avatar.configuration_failed
                        and not avatar.preparation_started and not avatar.link.connection_started and not phase["mediaEntered"]
                        and request.sessionId not in self.sessions and begin and binding
                        and begin.get("schemaVersion")=="0.5" and begin.get("commandType")=="BEGIN_RUN" and begin.get("sessionId")==request.sessionId
                        and type(begin.get("runEpoch")) is int and begin["runEpoch"]>0
                        and begin.get("commandId") and begin.get("requestFingerprint")
                        and getattr(journal,"incarnation",None)):
                        self.failed_create_cleanup[request.sessionId]={
                            **{key:begin[key] for key in ("sessionId","runEpoch","commandId","requestFingerprint")},
                            "producerIncarnation":journal.incarnation,"bindingId":binding["bindingId"],"bindingReleaseACK":False}
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
        try:
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
                await self._close_llm(session)
        finally:
            await self._release(sid)

    async def _close_llm(self, session):
        try:
            close = getattr(session.llm, "aclose", None)
            if close:
                await asyncio.wait_for(close(), 2)
        except Exception:
            pass
        finally:
            if hasattr(session.llm, "api_key"):
                session.llm.api_key = ""

    async def _release(self, sid):
        if sid in self.releasing:
            if sid in self.release_requires_ack:
                raise RuntimeFailure("DEPENDENCY_UNAVAILABLE", "Binding release remains pending", 503)
            return
        self.releasing.add(sid)
        binding_id=self.bound.get(sid,{}).get("bindingId")
        try:
            for tasks in (self.leases, self.monitors):
                task = tasks.pop(sid, None)
                if task and task is not asyncio.current_task():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            strict_release = sid in self.release_requires_ack
            if not strict_release:
                self.bound.pop(sid, None)
            try:
                await self.binding_client.release(sid)
                proof=self.failed_create_cleanup.get(sid)
                if proof and binding_id==proof["bindingId"]:
                    proof["bindingReleaseACK"]=True
                self.release_pending.discard(sid)
                self.bound.pop(sid, None)
                self.release_requires_ack.discard(sid)
            except Exception:
                self.release_pending.add(sid)
                if strict_release:
                    raise RuntimeFailure("DEPENDENCY_UNAVAILABLE", "Binding release remains pending", 503) from None
        finally:
            self.releasing.discard(sid)

    def prephysical_stop_proof(self,sid,epoch,incarnation):
        proof=self.failed_create_cleanup.get(sid)
        begin=getattr(self.publisher,"run_commands",{}).get((sid,"BEGIN_RUN"),{})
        journal=getattr(self.publisher,"journal",None)
        if (not proof or proof["sessionId"]!=sid or proof["runEpoch"]!=epoch
            or proof["producerIncarnation"]!=incarnation or getattr(journal,"incarnation",None)!=incarnation
            or not proof["bindingReleaseACK"] or sid in self.sessions or sid in self.bound
            or sid in self.release_pending or sid in self.release_requires_ack or sid in self.releasing
            or begin.get("commandType")!="BEGIN_RUN"
            or any(begin.get(key)!=proof[key] for key in ("sessionId","runEpoch","commandId","requestFingerprint"))):
            return None
        return dict(proof)

    def acknowledge_prephysical_stop(self,sid,proof):
        if self.failed_create_cleanup.get(sid)==proof:
            self.failed_create_cleanup.pop(sid,None)

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
        if (session and session.continuity is not None) or sid in self.release_requires_ack:
            self.release_requires_ack.add(sid)
            if session:
                # A failed native Stop must retain the Session, credentials and
                # physical Worker reservation; no finally-release on failure.
                await session.stop(trace)
                await self._close_llm(session)
            await self._release(sid)
            async with self.lock:
                if self.sessions.get(sid) is session:
                    self.sessions.pop(sid, None)
            return
        try:
            if session:
                await super().stop_session(sid, trace)
        finally:
            try:
                if session:
                    await self._close_llm(session)
            finally:
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
                    await self._release(pending)
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
