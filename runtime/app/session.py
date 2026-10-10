import asyncio
from dataclasses import dataclass, field, replace
import heapq
import logging
import json
import os
import re
import time
from uuid import uuid4
from .config import Settings
from .events import EventPublisher, envelope
from .models import CreateSession, InterruptPolicy, Utterance
from .providers import AvatarEngine, GenerationContext, LLMProvider, LLMRequest, MediaOutput, TTSProvider
from .tools import ToolClient
from .fact_answer import FactAnswerResolver
from .providers import MediaDeliveryError


log = logging.getLogger(__name__)


SIZE_PATTERN = re.compile(
    r"(?<![a-z0-9])(?P<letter>xxxl|xxl|xl|s|m|l)(?![a-z0-9])"
    r"|(?<!\d)(?P<number>\d{1,3})\s*(?:码|号)(?!\d)",
    re.IGNORECASE,
)


def mentioned_sizes(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        (match.group("letter") or match.group("number")).upper()
        for match in SIZE_PATTERN.finditer(text)
    ))


def required_product_facts(text: str) -> tuple[str, ...]:
    lower = text.lower()
    stock = any(word in lower for word in ("库存", "存货", "有货", "现货", "还有吗", "还有没有", "剩几", "剩多少", "stock", "available", "in stock"))
    price = any(word in lower for word in ("价格", "价钱", "多少钱", "售价", "卖多少", "price", "cost", "how much"))
    product = bool(mentioned_sizes(text)) or any(word in lower for word in ("商品", "产品", "材质", "面料", "尺码", "型号", "规格", "尺寸", "product", "material", "size"))
    return tuple(name for name, needed in (("product", product), ("stock", stock), ("price", price)) if needed)


async def sentence_stream(tokens, max_wait: float = 0.25, max_length: int = 120):
    """Yield sentences while the producer continues streaming tokens."""
    queue: asyncio.Queue = asyncio.Queue()

    async def produce():
        try:
            async for token in tokens:
                await queue.put((token, None))
        except Exception as exc:
            await queue.put((None, exc))
        finally:
            await queue.put((None, None))

    producer = asyncio.create_task(produce())
    buffer = ""
    try:
        while True:
            try:
                token, error = await asyncio.wait_for(queue.get(), max_wait if buffer else None)
            except asyncio.TimeoutError:
                yield buffer.strip()
                buffer = ""
                continue
            if error:
                raise error
            if token is None:
                if buffer.strip():
                    yield buffer.strip()
                return
            buffer += token
            boundary = any(mark in buffer for mark in "。！？!?") or (len(buffer) >= 20 and any(mark in buffer for mark in ",，"))
            if boundary or len(buffer) >= max_length:
                yield buffer.strip()
                buffer = ""
    finally:
        producer.cancel()
        try:
            await producer
        except asyncio.CancelledError:
            pass


class RuntimeFailure(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True)
class FactContext:
    text: str
    fallback: str | None
    data: dict[str, dict] = field(default_factory=dict)

    def __iter__(self):
        yield self.text
        yield self.fallback


@dataclass
class RuntimeSession:
    request: CreateSession
    llm: LLMProvider
    tts_provider: TTSProvider
    avatar_engine: AvatarEngine
    media_output: MediaOutput
    publisher: EventPublisher
    max_queue: int
    tool_client: ToolClient | None = None
    state: str = "CREATED"
    generation_id: int = 1
    speech_queue: list[tuple[int, int, Utterance]] = field(default_factory=list)
    current_utterance: Utterance | None = None
    tasks: set[asyncio.Task] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    sequence: int = 0
    worker: asyncio.Task | None = None
    current_task: asyncio.Task | None = None
    seen_utterances: dict[str, Utterance] = field(default_factory=dict)

    @property
    def session_id(self) -> str:
        return self.request.sessionId

    @property
    def context(self):
        return self.request.context

    async def _fact_context(self, item: Utterance) -> FactContext:
        needed = required_product_facts(item.text)
        product_id = self.context.activeProductId
        if not product_id:
            unavailable = "当前 Session 没有 activeProductId；商品详情、库存和价格均不可用。不得猜测。"
            if needed:
                labels = {"product": "商品信息", "stock": "库存", "price": "价格"}
                return FactContext(unavailable, "我现在暂时查不到" + "和".join(labels[name] for name in needed) + "。")
            return FactContext(unavailable, None)
        if not needed:
            return FactContext("本轮未查询商品动态事实；不得猜测商品详情、库存或价格。", None)
        facts = []
        fact_data = {}
        missing = []
        for name in needed:
            try:
                if self.tool_client is None:
                    raise RuntimeError("ToolClient is not configured")
                method = {"product": self.tool_client.get_product, "stock": self.tool_client.get_product_stock, "price": self.tool_client.get_product_price}[name]
                result = await method(product_id)
                if result.get("ok") is not True or not isinstance(result.get("data"), dict):
                    raise ValueError("Tool returned unavailable result")
                data = result["data"]
                if data.get("productId") != product_id or (name != "product" and name not in data):
                    raise ValueError("Tool result does not match requested product/fact")
                if name == "product" and (not isinstance(data.get("sizes"), list) or not all(isinstance(size, str) for size in data["sizes"])):
                    raise ValueError("Product sizes are unavailable")
                if name == "product":
                    # Product identity/details and aggregate price/stock have separate Tool facts.
                    # Never place duplicate aggregate values beside offered sizes in LLM context.
                    data = {key: value for key, value in data.items() if key not in {"stock", "price", "currency"}}
                fact_data[name] = data
                facts.append(f"{name}: " + json.dumps(data, ensure_ascii=False))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.emit("RUNTIME_WARNING", item.traceId, item.utteranceId, {"code": "TOOL_FAILED", "tool": name, "errorType": type(exc).__name__})
                facts.append(f"{name}: unavailable; do not guess")
                missing.append(name)
        fallback = None
        if missing:
            labels = {"product": "商品信息", "stock": "库存", "price": "价格"}
            fallback = "我现在暂时查不到" + "和".join(labels[name] for name in missing) + "。"
        sizes = mentioned_sizes(item.text)
        if sizes and "product" in fact_data:
            offered = {size.strip().upper().removesuffix("码").removesuffix("号") for size in fact_data["product"]["sizes"]}
            for size in sizes:
                facts.append(f"size_offered[{size}]: {'yes' if size in offered else 'no'} (based only on Product.sizes)")
        if "product" in needed and (sizes or "尺码" in item.text):
            aggregate = fact_data.get("stock", {}).get("stock")
            facts.append(f"aggregate_stock: {aggregate if aggregate is not None else 'unavailable'} (whole product only)")
            facts.append("per_size_stock: unavailable; Product.sizes only indicates offered sizes. Never treat aggregate stock as stock for any specific size or claim that a size is in stock.")
        return FactContext("\n".join(facts), fallback, fact_data)

    async def emit(self, kind: str, trace: str, utterance: str | None = None, payload: dict | None = None) -> None:
        await self.publisher.publish(envelope(kind, self.session_id, trace, utterance, payload))

    async def prepare(self) -> None:
        try:
            await self.emit("SESSION_PREPARING", self.request.traceId)
            await self.avatar_engine.prepare(self.request.avatar)
            async with self.lock:
                if self.state != "PREPARING":
                    return
                self.state = "READY"
            await self.emit("SESSION_READY", self.request.traceId)
        except Exception:
            log.exception("session_prepare_failed", extra={"traceId": self.request.traceId, "sessionId": self.session_id})
            async with self.lock:
                self.state = "FAILED"
            await self.emit("SESSION_FAILED", self.request.traceId)

    async def start(self, trace: str) -> None:
        async with self.lock:
            if self.state == "LIVE":
                raise RuntimeFailure("SESSION_ALREADY_RUNNING", "Session already running", 409)
            if self.state != "READY":
                raise RuntimeFailure("SESSION_NOT_READY", "Session is not ready", 409)
            await self.avatar_engine.start()
            if hasattr(self.media_output, "set_warning_handler"):
                self.media_output.set_warning_handler(
                    lambda warning: self.emit("RUNTIME_WARNING", trace, payload=warning)
                )
            await self.media_output.start()
            self.state = "LIVE"
            self._ensure_worker_locked()
            await self.emit("MEDIA_READY", trace)
            await self.emit("SESSION_STARTED", trace)

    async def speak(self, item: Utterance) -> None:
        async with self.lock:
            if self.state != "LIVE":
                raise RuntimeFailure("SESSION_NOT_RUNNING", "Session is not live", 409)
            old = self.seen_utterances.get(item.utteranceId)
            if old:
                if old != item:
                    raise RuntimeFailure("CONFLICT", "Utterance ID already used", 409)
                return
            if len(self.speech_queue) >= self.max_queue:
                raise RuntimeFailure("RUNTIME_OVERLOADED", "Speech queue is full", 429)
            current = self.current_utterance
            should_interrupt = bool(current and (item.interruptPolicy == InterruptPolicy.FORCE or (item.interruptPolicy == InterruptPolicy.INTERRUPT_LOWER_PRIORITY and item.priority > current.priority)))
            if should_interrupt:
                await self._interrupt_locked()
            # The control plane must observe QUEUED before any worker transition.
            await self.emit("UTTERANCE_QUEUED", item.traceId, item.utteranceId)
            self.sequence += 1
            heapq.heappush(self.speech_queue, (-item.priority, self.sequence, item))
            self.seen_utterances[item.utteranceId] = item
            self.wake.set()
            # A cancelled/failed worker must never strand an accepted utterance.
            # This also closes the narrow race where the previous worker finishes
            # immediately before a new item is queued.
            self._ensure_worker_locked()

    def _ensure_worker_locked(self) -> None:
        if self.state != "LIVE" or (self.worker is not None and not self.worker.done()):
            return
        worker = asyncio.create_task(self._worker())
        self.worker = worker
        worker.add_done_callback(self._worker_done)

    def _worker_done(self, worker: asyncio.Task) -> None:
        if worker.cancelled():
            error = None
        else:
            error = worker.exception()
        if error is not None:
            log.error(
                "session_worker_failed sessionId=%s errorType=%s",
                self.session_id,
                type(error).__name__,
                exc_info=(type(error), error, error.__traceback__),
            )
        if self.state == "LIVE":
            asyncio.create_task(self._recover_worker(worker))

    async def _recover_worker(self, finished: asyncio.Task) -> None:
        async with self.lock:
            if self.worker is finished:
                self.worker = None
            if self.state == "LIVE":
                self._ensure_worker_locked()

    async def interrupt(self, trace: str) -> None:
        async with self.lock:
            if self.state != "LIVE":
                raise RuntimeFailure("SESSION_NOT_RUNNING", "Session is not live", 409)
            await self._interrupt_locked()

    async def webrtc_answer(self, sdp: str) -> str:
        async with self.lock:
            if self.state != "LIVE":
                raise RuntimeFailure("SESSION_NOT_RUNNING", "Session is not live", 409)
            media = self.media_output
            if not hasattr(media, "create_answer"):
                raise RuntimeFailure("WEBRTC_FAILED", "WebRTC media output is unavailable", 503)
        try:
            return await media.create_answer(sdp)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("webrtc_negotiation_failed", extra={"sessionId": self.session_id})
            raise RuntimeFailure("WEBRTC_FAILED", "WebRTC negotiation failed", 500) from exc

    async def _interrupt_locked(self) -> Utterance | None:
        old = self.current_utterance
        self.generation_id += 1
        if self.current_task:
            self.current_task.cancel()
        await self.avatar_engine.interrupt(self.generation_id)
        await self.media_output.interrupt(self.generation_id)
        if old:
            self.current_utterance = None
            await self.emit("UTTERANCE_INTERRUPTED", old.traceId, old.utteranceId)
        return old

    async def stop(self, trace: str) -> None:
        try:
            await asyncio.wait_for(self.lock.acquire(), 2)
        except asyncio.TimeoutError:
            log.warning("stop_initial_lock_timeout sessionId=%s", self.session_id)
            self.state = "STOPPING"
            if self.current_task:
                self.current_task.cancel()
            if self.worker:
                self.worker.cancel()
            queued = [entry[2] for entry in self.speech_queue]
            self.speech_queue.clear()
            worker = self.worker
            prepare_tasks = tuple(self.tasks)
            for task in prepare_tasks:
                task.cancel()
        else:
            try:
                if self.state in {"STOPPING", "ENDED"}:
                    return
                self.state = "STOPPING"
                try:
                    await asyncio.wait_for(self._interrupt_locked(), 2)
                except Exception as exc:
                    log.warning("stop_interrupt_failed sessionId=%s errorType=%s", self.session_id, type(exc).__name__)
                queued = [entry[2] for entry in self.speech_queue]
                self.speech_queue.clear()
                if self.worker:
                    self.worker.cancel()
                worker = self.worker
                prepare_tasks = tuple(self.tasks)
                for task in prepare_tasks:
                    task.cancel()
            finally:
                self.lock.release()
        if worker:
            try:
                await asyncio.wait_for(asyncio.gather(worker, return_exceptions=True), 2)
            except asyncio.TimeoutError:
                log.warning("stop_worker_timeout sessionId=%s", self.session_id)
        if prepare_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*prepare_tasks, return_exceptions=True), 2)
            except asyncio.TimeoutError:
                log.warning("stop_prepare_timeout sessionId=%s", self.session_id)
        try:
            await asyncio.wait_for(self.emit("SESSION_STOPPING", trace), 2)
        except Exception as exc:
            log.warning("stop_event_failed sessionId=%s event=SESSION_STOPPING errorType=%s", self.session_id, type(exc).__name__)
        if queued:
            try:
                await asyncio.wait_for(asyncio.gather(*(self.emit("UTTERANCE_INTERRUPTED", item.traceId, item.utteranceId) for item in queued), return_exceptions=True), 2)
            except asyncio.TimeoutError:
                log.warning("stop_queued_event_timeout sessionId=%s", self.session_id)
        for name, cleanup, timeout in (
            ("avatar", self.avatar_engine.stop, 4),
            ("media", self.media_output.stop, 10),
        ):
            try:
                await asyncio.wait_for(cleanup(), timeout)
            except Exception as exc:
                log.warning("stop_cleanup_failed sessionId=%s component=%s errorType=%s", self.session_id, name, type(exc).__name__)
        try:
            await asyncio.wait_for(self.lock.acquire(), 2)
        except asyncio.TimeoutError:
            log.warning("stop_final_lock_timeout sessionId=%s", self.session_id)
            self.state = "ENDED"
        else:
            try:
                self.state = "ENDED"
            finally:
                self.lock.release()
        try:
            await asyncio.wait_for(self.emit("SESSION_ENDED", trace), 2)
        except Exception as exc:
            log.warning("stop_event_failed sessionId=%s event=SESSION_ENDED errorType=%s", self.session_id, type(exc).__name__)

    async def _worker(self) -> None:
        try:
            while True:
                await self.wake.wait()
                async with self.lock:
                    if not self.speech_queue:
                        self.wake.clear()
                        continue
                    _, _, item = heapq.heappop(self.speech_queue)
                    self.current_utterance = item
                    generation = self.generation_id
                    self.current_task = asyncio.create_task(self._process(item, generation))
                    task = self.current_task
                try:
                    await task
                except asyncio.CancelledError:
                    if self.state == "STOPPING" or asyncio.current_task().cancelling():
                        raise
                finally:
                    async with self.lock:
                        if self.current_task is task:
                            self.current_task = None
                        if self.current_utterance is item:
                            self.current_utterance = None
        except asyncio.CancelledError:
            pass

    async def _process(self, item: Utterance, generation: int) -> None:
        ctx = GenerationContext(generation, item.traceId, self.session_id, item.utteranceId)
        rendering = playing = synthesizing = False
        failure_stage = "GENERATION"
        try:
            await self.emit("UTTERANCE_GENERATING", item.traceId, item.utteranceId)
            fact_context = await self._fact_context(item)
            safe_answer = FactAnswerResolver().resolve(
                item.text, required_product_facts(item.text), mentioned_sizes(item.text), fact_context.data
            )
            request = LLMRequest(item.text, self.context.systemPrompt, fact_context.text)
            async def sentences():
                emitted = False
                try:
                    if safe_answer:
                        yield safe_answer
                        return
                    if fact_context.fallback:
                        yield fact_context.fallback
                        return
                    async for sentence in sentence_stream(self.llm.stream(request)):
                        emitted = True
                        yield sentence
                    if not emitted:
                        raise ValueError("Empty LLM output")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await self.emit("RUNTIME_WARNING", item.traceId, item.utteranceId, {"code": "LLM_FAILED", "fallback": "input_text", "errorType": type(exc).__name__})
                    if not emitted:
                        yield "我现在暂时无法回答这个问题。" if required_product_facts(item.text) else item.text
                    else:
                        raise

            audio_sequence = 0
            async def synthesized_audio():
                nonlocal synthesizing, failure_stage
                async for sentence in sentences():
                    if os.getenv("CAPTURE_TTS_TEXT_EVIDENCE") == "1":
                        log.warning("tts_evidence %s", json.dumps({
                            "sessionId": self.session_id, "utteranceId": item.utteranceId,
                            "generationId": generation, "text": sentence,
                        }, ensure_ascii=False))
                    if generation != self.generation_id:
                        return
                    if not synthesizing:
                        await self.emit("UTTERANCE_SYNTHESIZING", item.traceId, item.utteranceId)
                        synthesizing = True
                    failure_stage = "TTS"
                    async for chunk in self.tts_provider.synthesize_stream(sentence, item.voice, ctx):
                        yield chunk
            audio_source = synthesized_audio()
            stream_hook = getattr(self.avatar_engine, "stream_audio", None)
            if stream_hook:
                audio_source = stream_hook(audio_source, generation)
            async for chunk in audio_source:
                if generation != self.generation_id or chunk.generation_id != generation:
                    continue
                chunk = replace(chunk, sequence=audio_sequence)
                audio_sequence += 1
                if not rendering:
                    await self.emit("UTTERANCE_RENDERING", item.traceId, item.utteranceId)
                    rendering = True
                failure_stage = "AVATAR"
                render_started = time.monotonic()
                frames = await self.avatar_engine.push_audio(chunk)
                if hasattr(self.media_output, "record_render_ms"):
                    self.media_output.record_render_ms((time.monotonic() - render_started) * 1000)
                if generation != self.generation_id:
                    return
                if not playing:
                    await self.emit("UTTERANCE_PLAYING", item.traceId, item.utteranceId)
                    playing = True
                failure_stage = "MEDIA"
                await self.media_output.push_audio(chunk)
                for frame in frames:
                    if frame.generation_id != self.generation_id:
                        break
                    await self.media_output.push_video(frame)
                failure_stage = "TTS"
            if generation == self.generation_id:
                failure_stage = "MEDIA"
                await self.media_output.drain(generation)
            if hasattr(self.media_output, "pop_warnings"):
                for warning in self.media_output.pop_warnings():
                    await self.emit("RUNTIME_WARNING", item.traceId, item.utteranceId, warning)
            async with self.lock:
                if generation == self.generation_id and self.current_utterance is item:
                    await self.emit("UTTERANCE_COMPLETED", item.traceId, item.utteranceId)
                    self.current_utterance = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("utterance_failed", extra={"traceId": item.traceId, "sessionId": self.session_id, "utteranceId": item.utteranceId, "generationId": generation})
            async with self.lock:
                if generation == self.generation_id and self.current_utterance is item:
                    if hasattr(self.media_output, "pop_warnings"):
                        for warning in self.media_output.pop_warnings():
                            await self.emit("RUNTIME_WARNING", item.traceId, item.utteranceId, warning)
                    if isinstance(exc, MediaDeliveryError) or failure_stage == "MEDIA":
                        await self.emit("MEDIA_FAILED", item.traceId, item.utteranceId, {"code": "MEDIA_OUTPUT_FAILED", "errorType": type(exc).__name__})
                    elif failure_stage == "TTS":
                        await self.emit("RUNTIME_WARNING", item.traceId, item.utteranceId, {"code": "TTS_FAILED", "errorType": type(exc).__name__})
                    elif failure_stage == "AVATAR":
                        await self.emit("RUNTIME_WARNING", item.traceId, item.utteranceId, {"code": "AVATAR_RENDER_FAILED", "errorType": type(exc).__name__})
                    await self.emit("UTTERANCE_FAILED", item.traceId, item.utteranceId)
                    self.current_utterance = None


class SessionManager:
    def __init__(self, settings: Settings, publisher: EventPublisher, llm_factory, tts_factory, avatar_factory, media_factory):
        self.settings, self.publisher = settings, publisher
        self.llm_factory, self.tts_factory = llm_factory, tts_factory
        self.avatar_factory, self.media_factory = avatar_factory, media_factory
        self.sessions: dict[str, RuntimeSession] = {}
        self.tool_client = ToolClient(settings.tool_base_url, settings.tool_token) if settings.tool_base_url else None
        self.lock = asyncio.Lock()

    def get_session(self, session_id: str) -> RuntimeSession:
        try:
            return self.sessions[session_id]
        except KeyError:
            raise RuntimeFailure("SESSION_NOT_FOUND", "Session not found", 404) from None

    async def create_session(self, request: CreateSession) -> None:
        async with self.lock:
            if request.sessionId in self.sessions:
                raise RuntimeFailure("CONFLICT", "Session already exists", 409)
            if sum(s.state not in {"ENDED", "FAILED"} for s in self.sessions.values()) >= self.settings.max_sessions:
                raise RuntimeFailure("RUNTIME_OVERLOADED", "Session capacity reached", 429)
            avatar = self.avatar_factory()
            avatar.configure_session(request.config)
            media = self.media_factory()
            media.configure_session(request.config)
            session = RuntimeSession(request, self.llm_factory(), self.tts_factory(), avatar, media, self.publisher, self.settings.max_queue, self.tool_client)
            session.state = "PREPARING"
            self.sessions[request.sessionId] = session
            task = asyncio.create_task(session.prepare())
            session.tasks.add(task)
            task.add_done_callback(session.tasks.discard)

    async def start_session(self, session_id: str, trace: str) -> None:
        await self.get_session(session_id).start(trace)

    async def speak(self, session_id: str, item: Utterance) -> None:
        await self.get_session(session_id).speak(item)

    async def interrupt(self, session_id: str, trace: str) -> None:
        await self.get_session(session_id).interrupt(trace)

    async def stop_session(self, session_id: str, trace: str) -> None:
        session = self.get_session(session_id)
        await session.stop(trace)
        async with self.lock:
            if self.sessions.get(session_id) is session:
                del self.sessions[session_id]

    async def webrtc_answer(self, session_id: str, sdp: str) -> str:
        return await self.get_session(session_id).webrtc_answer(sdp)

    async def close(self) -> None:
        for session in tuple(self.sessions.values()):
            if session.state not in {"ENDED", "FAILED"}:
                await session.stop(session.request.traceId)
        self.sessions.clear()
