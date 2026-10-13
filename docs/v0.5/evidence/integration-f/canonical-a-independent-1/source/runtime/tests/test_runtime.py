import asyncio
import json
from pathlib import Path
import unittest
import httpx
from app.config import Settings
from app.events import MemoryEventPublisher, RedisEventPublisher, STREAM, envelope
from app.main import create_app
from app.models import CreateSession, Utterance
from app.providers import AudioChunk, LLMRequest, MockAvatarEngine, MockLLMProvider, MockMediaOutput, MockTTSProvider, OpenAICompatibleLLMProvider
from app.session import SessionManager, required_product_facts, sentence_stream


ROOT = Path(__file__).resolve().parents[2]
CREATE = {"commandId": "cmd_1", "traceId": "trace_1", "sessionId": "session_1", "avatar": {"avatarId": "avatar_1", "engine": "MOCK"}, "voice": {"voiceId": "voice_1", "provider": "MOCK"}, "config": {"fps": 25, "preview": {"type": "WEBRTC"}}, "context": {"roomId": "room_1", "systemPrompt": "你是直播间主持人。"}}


def utterance(uid, priority=40, policy="NONE", text="hello"):
    return Utterance(commandId=f"cmd_{uid}", traceId=f"trace_{uid}", utteranceId=uid, text=text, priority=priority, interruptPolicy=policy, source="OPERATOR", voice={"voiceId": "voice_1"})


class SlowTTS(MockTTSProvider):
    async def synthesize_stream(self, text, voice, ctx):
        for i in range(15):
            await asyncio.sleep(0.01)
            yield AudioChunk(ctx.generation_id, i, b"\0" * 320)


class FailingLLM:
    async def stream(self, request):
        raise RuntimeError("provider down")
        yield ""


class CapturingLLM:
    def __init__(self):
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        yield "这是测试回答。"


class DisobedientLLM(CapturingLLM):
    async def stream(self, request):
        self.requests.append(request)
        yield "XL 有 27 件。"


class CapturingTTS(MockTTSProvider):
    def __init__(self):
        self.texts = []

    async def synthesize_stream(self, text, voice, ctx):
        self.texts.append(text)
        async for chunk in super().synthesize_stream(text, voice, ctx):
            yield chunk


class FakeTools:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    async def get_product(self, product_id):
        self.calls.append(("product", product_id))
        if self.fail == "product":
            raise RuntimeError("tool down")
        return {"ok": True, "data": {"productId": product_id, "name": "卫衣", "sizes": ["M", "L", "XL"], "stock": 27}}

    async def get_product_stock(self, product_id):
        self.calls.append(("stock", product_id))
        if self.fail == "stock":
            raise RuntimeError("tool down")
        return {"ok": True, "data": {"productId": product_id, "stock": 27}}

    async def get_product_price(self, product_id):
        self.calls.append(("price", product_id))
        if self.fail == "price":
            raise RuntimeError("tool down")
        return {"ok": True, "data": {"productId": product_id, "price": 129}}


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = MemoryEventPublisher()
        self.manager = SessionManager(Settings(), self.events, MockLLMProvider, SlowTTS, MockAvatarEngine, MockMediaOutput)
        await self.manager.create_session(CreateSession(**CREATE))
        await asyncio.sleep(0.01)
        await self.manager.start_session("session_1", "trace_1")
        self.session = self.manager.get_session("session_1")

    async def asyncTearDown(self):
        await self.manager.close()

    async def test_lifecycle_and_priority_fifo(self):
        await self.manager.speak("session_1", utterance("a", 40))
        await self.manager.speak("session_1", utterance("b", 80))
        await self.manager.speak("session_1", utterance("c", 80))
        await asyncio.sleep(0.6)
        completed = [e["utteranceId"] for e in self.events.events if e["eventType"] == "UTTERANCE_COMPLETED"]
        self.assertEqual(completed, ["b", "c", "a"])

    async def test_context_persistence_and_platform_source(self):
        self.assertEqual(self.session.context.roomId, "room_1")
        self.assertEqual(self.session.context.systemPrompt, "你是直播间主持人。")
        snapshot = {**CREATE, "sessionId": "session_context", "context": {"roomId": "room_snapshot", "systemPrompt": "专用提示词", "activeProductId": "product_snapshot", "knowledgeBaseId": "kb_snapshot"}}
        await self.manager.create_session(CreateSession(**snapshot))
        saved = self.manager.get_session("session_context").context
        self.assertEqual((saved.roomId, saved.systemPrompt, saved.activeProductId, saved.knowledgeBaseId),
                         ("room_snapshot", "专用提示词", "product_snapshot", "kb_snapshot"))
        item = Utterance.model_validate({**utterance("comment", text="你好").model_dump(mode="json"), "source": "PLATFORM_EVENT", "platformContext": {"eventType": "COMMENT", "user": {"externalId": "viewer_1", "nickname": "观众"}}})
        await self.manager.speak("session_1", item)
        self.assertEqual(self.session.seen_utterances["comment"].source, "PLATFORM_EVENT")
        self.assertEqual(self.session.seen_utterances["comment"].platformContext.user.nickname, "观众")

    async def test_system_prompt_and_product_tools(self):
        self.session.request.context.activeProductId = "product_live"
        llm = CapturingLLM()
        tools = FakeTools()
        self.session.llm, self.session.tool_client = llm, tools
        await self.manager.speak("session_1", utterance("facts", text="这个商品库存和价格是多少？product_fake"))
        await asyncio.sleep(0.12)
        self.assertEqual(tools.calls, [("product", "product_live"), ("stock", "product_live"), ("price", "product_live")])
        self.assertEqual(llm.requests[0].system_prompt, "你是直播间主持人。")
        self.assertIn('"stock": 27', llm.requests[0].fact_context)
        self.assertIn('"price": 129', llm.requests[0].fact_context)
        self.assertNotIn("product_fake", llm.requests[0].fact_context)

    async def test_variant_facts_do_not_infer_size_stock(self):
        self.session.request.context.activeProductId = "product_live"
        tools = FakeTools()
        self.session.tool_client = tools
        cases = (
            ("有 XL 吗？", ["product"], "size_offered[XL]: yes"),
            ("有 XXXL 吗？", ["product"], "size_offered[XXXL]: no"),
            ("库存还有多少？", ["stock"], '"stock": 27'),
            ("XL 还有库存吗？", ["product", "stock"], "size_offered[XL]: yes"),
        )
        for question, expected_tools, expected_fact in cases:
            with self.subTest(question=question):
                tools.calls.clear()
                context, fallback = await self.session._fact_context(utterance("variant", text=question))
                self.assertIsNone(fallback)
                self.assertEqual([name for name, _ in tools.calls], expected_tools)
                self.assertIn(expected_fact, context)
                self.assertNotIn("size_stock[", context)
                if "XL" in question:
                    self.assertIn("per_size_stock: unavailable", context)
                    self.assertIn("Never treat aggregate stock as stock for any specific size", context)
                    self.assertIn(
                        "aggregate_stock: 27 (whole product only)" if "库存" in question
                        else "aggregate_stock: unavailable (whole product only)", context,
                    )
                else:
                    self.assertNotIn("per_size_stock:", context)

        for question in ("S 码有吗？", "M 有吗？", "L 有吗？", "XXL 有吗？", "42 码有吗？", "尺码有哪些？"):
            with self.subTest(question=question):
                self.assertIn("product", required_product_facts(question))
        self.assertEqual(required_product_facts("价格是多少？"), ("price",))

    async def test_deterministic_product_answers_reach_tts_without_llm(self):
        self.session.request.context.activeProductId = "product_live"
        tools, llm, tts = FakeTools(), DisobedientLLM(), CapturingTTS()
        self.session.tool_client, self.session.llm, self.session.tts_provider = tools, llm, tts
        cases = (
            ("有 XL 吗？", ("有 XL 尺码",), ("XL 有 27 件",)),
            ("有 XXXL 吗？", ("没有 XXXL 尺码",), ("XL 有 27 件",)),
            ("库存还有多少？", ("整体库存", "27 件"), ("XL 有 27 件",)),
            ("XL 还有库存吗？", ("有 XL 尺码", "商品整体还有库存", "没有 XL 单独库存数据"), ("XL 有 27 件",)),
            ("价格是多少？", ("价格是 129", "币种信息暂不可用"), ("XL 有 27 件",)),
            ("这款商品有哪些特点？", ("卫衣", "提供的尺码有M、L、XL", "不代表各尺码有单独库存"), ("库存27件", "XL 有 27 件")),
            ("介绍一下这件商品。", ("卫衣", "提供的尺码有M、L、XL", "不代表各尺码有单独库存"), ("库存27件", "XL 有 27 件")),
        )
        for index, (question, required, forbidden) in enumerate(cases):
            with self.subTest(question=question):
                await self.manager.speak("session_1", utterance(f"safe_{index}", text=question))
                for _ in range(100):
                    if any(e["eventType"] == "UTTERANCE_COMPLETED" and e["utteranceId"] == f"safe_{index}" for e in self.events.events):
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(len(tts.texts), index + 1)
                answer = tts.texts[-1]
                for phrase in required:
                    self.assertIn(phrase, answer)
                for phrase in forbidden:
                    self.assertNotIn(phrase, answer)
        self.assertEqual(llm.requests, [])

        await self.manager.speak("session_1", utterance("chat_safe", text="你好"))
        for _ in range(100):
            if len(tts.texts) == len(cases) + 1:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(tts.texts[-1], "XL 有 27 件。")
        self.assertEqual(len(llm.requests), 1)

    async def test_without_product_has_unavailable_context_and_plain_chat(self):
        llm = CapturingLLM()
        tools = FakeTools()
        self.session.llm, self.session.tool_client = llm, tools
        await self.manager.speak("session_1", utterance("chat", text="你好"))
        await asyncio.sleep(0.25)
        self.assertEqual(tools.calls, [])
        self.assertIn("不可用", llm.requests[0].fact_context)
        self.assertIn("UTTERANCE_COMPLETED", [e["eventType"] for e in self.events.events])
        await self.manager.speak("session_1", utterance("missing_product", text="库存还有多少？"))
        await asyncio.sleep(0.25)
        self.assertEqual(tools.calls, [])
        self.assertEqual(len(llm.requests), 1)
        self.assertIn("UTTERANCE_COMPLETED", [e["eventType"] for e in self.events.events if e["utteranceId"] == "missing_product"])

    async def test_tool_failure_warns_and_uses_natural_fallback(self):
        self.session.request.context.activeProductId = "product_live"
        llm = CapturingLLM()
        tools = FakeTools(fail="stock")
        self.session.llm, self.session.tool_client = llm, tools
        await self.manager.speak("session_1", utterance("fail", text="还有库存吗？"))
        await asyncio.sleep(0.25)
        warnings = [e for e in self.events.events if e["eventType"] == "RUNTIME_WARNING"]
        self.assertEqual(warnings[0]["payload"]["code"], "TOOL_FAILED")
        self.assertEqual(tools.calls, [("stock", "product_live")])
        self.assertEqual(llm.requests, [])
        self.assertIn("UTTERANCE_COMPLETED", [e["eventType"] for e in self.events.events])

    async def test_force_interrupt_and_old_generation_discard(self):
        await self.manager.speak("session_1", utterance("a", 40))
        await asyncio.sleep(0.03)
        old_generation = self.session.generation_id
        await self.manager.speak("session_1", utterance("b", 100, "FORCE"))
        self.assertEqual(self.session.generation_id, old_generation + 1)
        await self.session.avatar_engine.push_audio(AudioChunk(old_generation, 100, b"old"))
        await self.session.media_output.push_audio(AudioChunk(old_generation, 100, b"old"))
        self.assertNotIn(b"old", [c.pcm for c in self.session.avatar_engine.received])
        self.assertNotIn(b"old", [c.pcm for c in self.session.media_output.received])
        await asyncio.sleep(0.3)
        self.assertEqual(sum(e["eventType"] == "UTTERANCE_INTERRUPTED" and e["utteranceId"] == "a" for e in self.events.events), 1)

    async def test_lower_priority_does_not_interrupt(self):
        await self.manager.speak("session_1", utterance("a", 80))
        await asyncio.sleep(0.02)
        await self.manager.speak("session_1", utterance("b", 40, "INTERRUPT_LOWER_PRIORITY"))
        self.assertEqual(self.session.generation_id, 1)

    async def test_none_never_preempts_and_higher_priority_does(self):
        await self.manager.speak("session_1", utterance("current", 40))
        await asyncio.sleep(0.02)
        await self.manager.speak("session_1", utterance("none", 100, "NONE"))
        self.assertEqual(self.session.generation_id, 1)
        await self.manager.speak("session_1", utterance("higher", 80, "INTERRUPT_LOWER_PRIORITY"))
        self.assertEqual(self.session.generation_id, 2)
        self.assertEqual(self.session.current_utterance, None)

    async def test_provider_fallback_and_cleanup(self):
        self.session.llm = FailingLLM()
        await self.manager.speak("session_1", utterance("a"))
        await asyncio.sleep(0.25)
        self.assertIn("RUNTIME_WARNING", [e["eventType"] for e in self.events.events])
        await self.manager.stop_session("session_1", "trace_stop")
        self.assertEqual(self.session.state, "ENDED")
        self.assertEqual(self.session.avatar_engine.received, [])
        self.assertNotIn("session_1", self.manager.sessions)
        self.assertTrue(self.session.worker.done())

    async def test_live_session_recovers_cancelled_worker_without_stranding_queue(self):
        old_worker = self.session.worker
        old_worker.cancel()
        await asyncio.gather(old_worker, return_exceptions=True)

        await self.manager.speak("session_1", utterance("after_worker_cancel", text="继续直播"))
        for _ in range(100):
            if any(
                event["eventType"] == "UTTERANCE_COMPLETED"
                and event["utteranceId"] == "after_worker_cancel"
                for event in self.events.events
            ):
                break
            await asyncio.sleep(0.01)

        self.assertIsNot(self.session.worker, old_worker)
        self.assertFalse(self.session.worker.done())
        self.assertTrue(any(
            event["eventType"] == "UTTERANCE_COMPLETED"
            and event["utteranceId"] == "after_worker_cancel"
            for event in self.events.events
        ))


    async def test_queue_event_precedes_generation_and_terminal_interrupt_is_exclusive(self):
        queued_started = asyncio.Event()
        release_queued = asyncio.Event()
        original_publish = self.events.publish

        async def delayed_publish(event):
            if event["eventType"] == "UTTERANCE_QUEUED":
                queued_started.set()
                await release_queued.wait()
            await original_publish(event)

        self.events.publish = delayed_publish
        speaking = asyncio.create_task(self.manager.speak("session_1", utterance("ordered")))
        await queued_started.wait()
        await asyncio.sleep(0.02)
        self.assertNotIn("UTTERANCE_GENERATING", [e["eventType"] for e in self.events.events])
        release_queued.set()
        await speaking
        for _ in range(100):
            if any(e["eventType"] == "UTTERANCE_COMPLETED" and e["utteranceId"] == "ordered" for e in self.events.events):
                break
            await asyncio.sleep(0.01)
        await self.manager.interrupt("session_1", "trace_interrupt")
        kinds = [e["eventType"] for e in self.events.events if e["utteranceId"] == "ordered"]
        self.assertEqual(kinds[0], "UTTERANCE_QUEUED")
        self.assertIn("UTTERANCE_COMPLETED", kinds)
        self.assertNotIn("UTTERANCE_INTERRUPTED", kinds)

    async def test_mock_streams(self):
        from app.models import SpeechPlan, VoiceConfig
        from app.providers import GenerationContext
        tokens = [t async for t in MockLLMProvider().stream(SpeechPlan(action="SPEAK", text="one two", priority=1))]
        chunks = [c async for c in MockTTSProvider().synthesize_stream("hello", VoiceConfig(voiceId="v"), GenerationContext(1, "t", "s", "u"))]
        self.assertEqual("".join(tokens).strip(), "one two")
        self.assertTrue(chunks and all(c.generation_id == 1 for c in chunks))

    async def test_sentence_stream_and_redis_envelope(self):
        async def tokens():
            for token in ["第一句。", "第二句！"]:
                yield token
        self.assertEqual([x async for x in sentence_stream(tokens())], ["第一句。", "第二句！"])

        class FakeRedis:
            def __init__(self):
                self.calls = []
            async def xadd(self, stream, fields):
                self.calls.append((stream, fields))

        redis_publisher = RedisEventPublisher.__new__(RedisEventPublisher)
        redis_publisher.client = FakeRedis()
        redis_publisher.retries = 1
        event = envelope("SESSION_READY", "session_1", "trace_1")
        await redis_publisher.publish(event)
        stream, fields = redis_publisher.client.calls[0]
        self.assertEqual(stream, STREAM)
        self.assertEqual(json.loads(fields["event"]), event)

    async def test_api_contract_shape(self):
        app = create_app(Settings(), MemoryEventPublisher())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
            health = await client.get("/internal/v1/health")
            self.assertEqual(set(health.json()), {"status", "runtimeVersion", "gpu", "activeSessions", "providers"})
            create = await client.post("/internal/v1/sessions", json=CREATE)
            self.assertEqual(create.status_code, 202)
            self.assertEqual(set(create.json()), {"accepted", "operationId"})
            invalid = await client.post("/internal/v1/sessions", json={**CREATE, "extra": 1})
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(invalid.json()["code"], "INVALID_ARGUMENT")
            no_context = await client.post("/internal/v1/sessions", json={key: value for key, value in CREATE.items() if key != "context"})
            self.assertEqual(no_context.status_code, 422)
            missing_provider = await client.post("/internal/v1/sessions", json={**CREATE, "sessionId": "session_invalid", "voice": {"voiceId": "voice_1"}})
            self.assertEqual(missing_provider.status_code, 422)
            await asyncio.sleep(0.01)
            start = await client.post("/internal/v1/sessions/session_1/start", json={"commandId": "cmd_2", "traceId": "trace_2"})
            self.assertEqual(start.status_code, 202)
            speak = await client.post("/internal/v1/sessions/session_1/utterances", json=utterance("api").model_dump(mode="json"))
            self.assertEqual(speak.status_code, 202)
            no_source = utterance("missing_source").model_dump(mode="json", exclude={"source"})
            self.assertEqual((await client.post("/internal/v1/sessions/session_1/utterances", json=no_source)).status_code, 422)
            path = "/internal/v1/sessions/session_1/webrtc/offer"
            self.assertEqual((await client.post(path, json={"type": "answer", "sdp": "test"})).status_code, 422)
            missing = await client.post("/internal/v1/sessions/missing/webrtc/offer", json={"type": "offer", "sdp": "test"})
            self.assertEqual((missing.status_code, missing.json()["code"]), (404, "SESSION_NOT_FOUND"))
            failed = await client.post(path, json={"type": "offer", "sdp": "test"})
            self.assertEqual((failed.status_code, failed.json()["code"]), (503, "WEBRTC_FAILED"))
            interrupt = await client.post("/internal/v1/sessions/session_1/interrupt", json={"commandId": "cmd_4", "traceId": "trace_4", "reason": "OPERATOR_INTERRUPT"})
            self.assertEqual(interrupt.status_code, 202)
            stop = await client.post("/internal/v1/sessions/session_1/stop", json={"commandId": "cmd_3", "traceId": "trace_3"})
            self.assertEqual(stop.status_code, 202)
            await app.state.manager.close()

    def test_event_schema(self):
        schema = json.loads((ROOT / "contracts/events/runtime-event.schema.json").read_text())
        event = envelope("SESSION_READY", "session_1", "trace_1")
        self.assertEqual(set(event), set(schema["required"]))
        self.assertEqual(event["schemaVersion"], "1.0")
        self.assertIn(event["eventType"], schema["properties"]["eventType"]["enum"])


class OpenAICompatibleStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, body: str):
        async def handler(request):
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        provider = OpenAICompatibleLLMProvider(
            "https://provider.test", "secret", "model", transport=httpx.MockTransport(handler)
        )
        return [part async for part in provider.stream(LLMRequest("hi", "system", "facts"))]

    async def test_content_stop_and_done(self):
        body = 'data: {"choices":[{"delta":{"content":"你好"},"finish_reason":null}]}\n\n' \
               'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n' \
               'data: [DONE]\n\n'
        self.assertEqual(await self.collect(body), ["你好"])

    async def test_content_stop_and_clean_eof(self):
        body = 'data: {"choices":[{"delta":{"content":"完成"},"finish_reason":null}]}\n\n' \
               'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        self.assertEqual(await self.collect(body), ["完成"])

    async def test_eof_without_terminal_fails(self):
        with self.assertRaisesRegex(RuntimeError, "without terminal finish"):
            await self.collect('data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n')

    async def test_length_fails(self):
        with self.assertRaisesRegex(RuntimeError, "length"):
            await self.collect('data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n')

    async def test_error_packet_fails(self):
        with self.assertRaisesRegex(RuntimeError, "returned an error"):
            await self.collect('data: {"error":{"message":"bad"}}\n\n')

    async def test_keepalive_and_event_lines_are_ignored(self):
        body = ': keepalive\nevent: message\ndata: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        self.assertEqual(await self.collect(body), ["ok"])

    async def test_malformed_json_fails(self):
        with self.assertRaises(json.JSONDecodeError):
            await self.collect('data: {broken}\n\n')

    async def test_reasoning_content_is_not_spoken(self):
        body = 'data: {"choices":[{"delta":{"reasoning_content":"secret","content":"visible"},"finish_reason":null}]}\n\n' \
               'data: {"choices":[{"delta":{"reasoning_content":"hidden"},"finish_reason":"stop"}]}\n\n' \
               'data: [DONE]\n\n'
        self.assertEqual(await self.collect(body), ["visible"])
