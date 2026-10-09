"""Independent integration acceptance guards for ISSUE-003 and ISSUE-004."""
import asyncio
import json
from pathlib import Path
import unittest

from runtime.app.config import Settings
from runtime.app.events import MemoryEventPublisher
from runtime.app.models import CreateSession, Utterance
from runtime.app.providers import AudioChunk, MockAvatarEngine, MockMediaOutput
from runtime.app.session import SessionManager

ROOT = Path(__file__).resolve().parents[1]


class BadLLM:
    def __init__(self):
        self.calls = []

    async def stream(self, request):
        self.calls.append(request.text)
        yield "XL有27件"


class CapturingTTS:
    def __init__(self):
        self.inputs = []

    async def synthesize_stream(self, text, voice, ctx):
        self.inputs.append((ctx.utterance_id, text))
        yield AudioChunk(ctx.generation_id, 0, b"\0" * 320)


class ProductTools:
    def __init__(self):
        self.calls = []

    async def get_product(self, product_id):
        self.calls.append(("product", product_id))
        return {"ok": True, "data": {"productId": product_id, "name": "卫衣", "sizes": ["M", "L", "XL"], "stock": 27, "price": 129}}

    async def get_product_stock(self, product_id):
        self.calls.append(("stock", product_id))
        return {"ok": True, "data": {"productId": product_id, "stock": 27}}

    async def get_product_price(self, product_id):
        self.calls.append(("price", product_id))
        return {"ok": True, "data": {"productId": product_id, "price": 129}}


class AcceptanceGuards(unittest.IsolatedAsyncioTestCase):
    async def test_bad_llm_cannot_claim_variant_stock_at_tts_boundary(self):
        pub, bad, tts, tools = MemoryEventPublisher(), BadLLM(), CapturingTTS(), ProductTools()
        manager = SessionManager(Settings(), pub, lambda: bad, lambda: tts, MockAvatarEngine, MockMediaOutput)
        manager.tool_client = tools
        create = json.loads((ROOT / "contracts/examples/runtime-create-session-v1.1.json").read_text())
        create["sessionId"] = "session_fact_safety"
        create["context"]["activeProductId"] = "product_hoodie"
        await manager.create_session(CreateSession(**create))
        try:
            for _ in range(100):
                if manager.get_session(create["sessionId"]).state == "READY":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(manager.get_session(create["sessionId"]).state, "READY")
            await manager.start_session(create["sessionId"], "trace_fact")
            cases = (
                ("size", "有 XL 这个尺码吗？", ("product",), ("有 XL 尺码",), False),
                ("stock", "库存多少？", ("stock",), ("整体库存", "27 件"), True),
                ("variant", "XL 还有库存吗？", ("product", "stock"), ("有 XL 尺码", "商品整体还有库存", "没有 XL 单独库存数据"), False),
            )
            results = []
            for uid, question, expected_tools, phrases, allows_27 in cases:
                start = len(tools.calls)
                item = Utterance(commandId=f"cmd_{uid}", traceId="trace_fact", utteranceId=uid,
                                 text=question, priority=80, interruptPolicy="NONE", source="PLATFORM_EVENT",
                                 voice={"voiceId": create["voice"]["voiceId"]})
                await manager.speak(create["sessionId"], item)
                for _ in range(200):
                    if any(e["eventType"] == "UTTERANCE_COMPLETED" and e["utteranceId"] == uid for e in pub.events):
                        break
                    await asyncio.sleep(0.01)
                sent = [text for utterance_id, text in tts.inputs if utterance_id == uid]
                self.assertEqual(len(sent), 1, (uid, sent, pub.events))
                self.assertEqual(tuple(name for name, _ in tools.calls[start:]), expected_tools)
                self.assertEqual(bad.calls, [], "Bad LLM must be bypassed for supported product facts")
                for phrase in phrases:
                    self.assertIn(phrase, sent[0])
                self.assertNotIn("XL有27件", sent[0])
                if not allows_27:
                    self.assertNotIn("27", sent[0], "aggregate stock must not become XL stock")
                results.append({"question": question, "ttsInput": sent[0], "toolCalls": [name for name, _ in tools.calls[start:]]})
            # Prove the injected provider is live: a plain chat utterance reaches it.
            chat = Utterance(commandId="cmd_chat", traceId="trace_fact", utteranceId="chat", text="你好",
                             priority=80, interruptPolicy="NONE", source="OPERATOR",
                             voice={"voiceId": create["voice"]["voiceId"]})
            await manager.speak(create["sessionId"], chat)
            for _ in range(200):
                if any(e["eventType"] == "UTTERANCE_COMPLETED" and e["utteranceId"] == "chat" for e in pub.events):
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(bad.calls, ["你好"])
            self.assertEqual([text for uid, text in tts.inputs if uid == "chat"], ["XL有27件"])
            path = ROOT / "integration/evidence/fact-safety-v1.1.json"
            path.write_text(json.dumps({"badLlmReply": "XL有27件", "badLlmCallsForProductQuestions": 0,
                                        "answers": results}, ensure_ascii=False, indent=2) + "\n")
        finally:
            await manager.close()

    async def test_only_supported_mock_runtime_is_in_integration(self):
        self.assertTrue((ROOT / "integration/mock_runtime/app.py").is_file())
        legacy = ROOT / "backend/cmd/mock-runtime"
        self.assertFalse(legacy.exists() and any(legacy.iterdir()), "Backend Go mock still has runnable files")
        readme = (ROOT / "backend/README.md").read_text()
        self.assertIn("integration/mock_runtime", readme)
        self.assertNotIn("go run ./cmd/mock-runtime", readme)
        compose = (ROOT / "infra/compose.yaml").read_text()
        self.assertIn("infra/mock-runtime.Dockerfile", compose)
        dockerfile = (ROOT / "infra/mock-runtime.Dockerfile").read_text()
        self.assertIn("COPY integration/mock_runtime", dockerfile)


if __name__ == "__main__":
    unittest.main()
