"""Contract v1.1 checks for the independent integration Mock Runtime."""
import asyncio
import json
from pathlib import Path
import unittest

import httpx
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from integration.mock_runtime.app import create_app, Publisher
from runtime.app.config import Settings
from runtime.app.events import MemoryEventPublisher
from runtime.app.main import create_app as create_real_app
from runtime.app.providers import AudioChunk, MockAvatarEngine, MockLLMProvider, MockMediaOutput, MockTTSProvider

ROOT = Path(__file__).resolve().parents[1]
EVENT_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "contracts/events/runtime-event.schema.json").read_text()),
    format_checker=FormatChecker(),
)
CREATE = json.loads((ROOT / "contracts/examples/runtime-create-session-v1.1.json").read_text())
COMMENT = json.loads((ROOT / "contracts/examples/runtime-comment-utterance-v1.1.json").read_text())


class SlowTTS(MockTTSProvider):
    async def synthesize_stream(self, text, voice, ctx):
        for sequence in range(30):
            await asyncio.sleep(0.01)
            yield AudioChunk(ctx.generation_id, sequence, b"\0" * 320)


def real_app(pub):
    return create_real_app(Settings(), pub, (MockLLMProvider, SlowTTS, MockAvatarEngine, MockMediaOutput))


async def wait_event(pub, kind, uid=None, timeout=3):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        for event in pub.events:
            if event["eventType"] == kind and (uid is None or event["utteranceId"] == uid):
                return event
        await asyncio.sleep(0.01)
    raise AssertionError(f"missing {kind} for {uid}: {pub.events}")


class ContractTests(unittest.TestCase):
    def test_machine_contracts_and_examples(self):
        for name in ("platform-event", "runtime-event", "speech-plan"):
            schema = json.loads((ROOT / f"contracts/events/{name}.schema.json").read_text())
            Draft202012Validator.check_schema(schema)
            example = json.loads((ROOT / f"contracts/examples/{name}.json").read_text())
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
        for name in ("control-api", "runtime-api"):
            spec = yaml.safe_load((ROOT / f"contracts/{name}.openapi.yaml").read_text())
            self.assertEqual(spec["info"]["version"], "1.1.0")
            self.assertTrue(spec["paths"])

    def test_mock_v11_validation_events_and_webrtc(self):
        async def run():
            pub = Publisher(); pub.url = None
            app = create_app(pub)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
                health = await c.get("/internal/v1/health")
                self.assertEqual(health.status_code, 200)
                missing = {k: v for k, v in CREATE.items() if k != "context"}
                resp = await c.post("/internal/v1/sessions", json=missing)
                self.assertEqual((resp.status_code, resp.json()["code"]), (422, "INVALID_ARGUMENT"))
                self.assertEqual((await c.post("/internal/v1/sessions", json=CREATE)).status_code, 202)
                self.assertEqual((await c.post("/internal/v1/sessions", json=CREATE)).status_code, 409)
                self.assertEqual(app.state.sessions[CREATE["sessionId"]]["context"].model_dump(), CREATE["context"])
                sid = CREATE["sessionId"]
                await wait_event(pub, "SESSION_READY")
                command = {"commandId": "cmd_start", "traceId": "trace_01"}
                self.assertEqual((await c.post(f"/internal/v1/sessions/{sid}/start", json=command)).status_code, 202)
                await wait_event(pub, "SESSION_STARTED")
                no_source = {k: v for k, v in COMMENT.items() if k != "source"}
                resp = await c.post(f"/internal/v1/sessions/{sid}/utterances", json=no_source)
                self.assertEqual((resp.status_code, resp.json()["code"]), (422, "INVALID_ARGUMENT"))
                for source in ("OPERATOR", "PLATFORM_EVENT", "AUTO_SCRIPT", "SYSTEM"):
                    body = {**COMMENT, "utteranceId": f"utt_{source}", "source": source}
                    self.assertEqual((await c.post(f"/internal/v1/sessions/{sid}/utterances", json=body)).status_code, 202)
                    await wait_event(pub, "UTTERANCE_COMPLETED", body["utteranceId"])
                invalid = await c.post(f"/internal/v1/sessions/{sid}/webrtc/offer", json={"type": "offer", "sdp": "invalid"})
                self.assertEqual((invalid.status_code, invalid.json()["code"]), (503, "WEBRTC_FAILED"))
                invalid = await c.post(f"/internal/v1/sessions/{sid}/webrtc/offer", json={"type": "offer", "sdp": ""})
                self.assertEqual((invalid.status_code, invalid.json()["code"]), (422, "INVALID_ARGUMENT"))
                self.assertEqual((await c.post(f"/internal/v1/sessions/{sid}/stop", json=command)).status_code, 202)
                for event in pub.events:
                    EVENT_VALIDATOR.validate(event)
        asyncio.run(run())

    def test_mock_and_real_priority_and_fifo(self):
        async def scenario(factory, policy, new_priority, interrupted):
            pub = Publisher() if factory is create_app else MemoryEventPublisher()
            if isinstance(pub, Publisher): pub.url = None
            app = factory(pub)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
                sid = CREATE["sessionId"]
                await c.post("/internal/v1/sessions", json=CREATE)
                await wait_event(pub, "SESSION_READY")
                await c.post(f"/internal/v1/sessions/{sid}/start", json={"commandId": "start", "traceId": "trace"})
                await wait_event(pub, "SESSION_STARTED")
                def body(uid, priority, policy):
                    return {**COMMENT, "utteranceId": uid, "priority": priority, "interruptPolicy": policy}
                await c.post(f"/internal/v1/sessions/{sid}/utterances", json=body("first", 80, "NONE"))
                await wait_event(pub, "UTTERANCE_PLAYING", "first")
                await c.post(f"/internal/v1/sessions/{sid}/utterances", json=body("second", new_priority, policy))
                if interrupted:
                    await wait_event(pub, "UTTERANCE_INTERRUPTED", "first")
                else:
                    await wait_event(pub, "UTTERANCE_COMPLETED", "first")
                await wait_event(pub, "UTTERANCE_COMPLETED", "second")
                terminals = [(e["eventType"], e["utteranceId"]) for e in pub.events if e["eventType"] in ("UTTERANCE_COMPLETED", "UTTERANCE_INTERRUPTED")]
                self.assertEqual(terminals, [("UTTERANCE_INTERRUPTED" if interrupted else "UTTERANCE_COMPLETED", "first"), ("UTTERANCE_COMPLETED", "second")])
                for event in pub.events:
                    EVENT_VALIDATOR.validate(event)
                await c.post(f"/internal/v1/sessions/{sid}/stop", json={"commandId": "stop", "traceId": "trace"})
        async def run():
            for factory in (create_app, real_app):
                for policy, priority, interrupted in (("NONE", 100, False), ("INTERRUPT_LOWER_PRIORITY", 79, False), ("INTERRUPT_LOWER_PRIORITY", 80, False), ("INTERRUPT_LOWER_PRIORITY", 81, True), ("FORCE", 1, True)):
                    await scenario(factory, policy, priority, interrupted)
            for factory in (create_app, real_app):
                pub = Publisher() if factory is create_app else MemoryEventPublisher()
                if isinstance(pub, Publisher): pub.url = None
                app = factory(pub)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
                    sid = CREATE["sessionId"]
                    await c.post("/internal/v1/sessions", json=CREATE); await wait_event(pub, "SESSION_READY")
                    await c.post(f"/internal/v1/sessions/{sid}/start", json={"commandId": "start", "traceId": "trace"})
                    await wait_event(pub, "SESSION_STARTED")
                    for uid in ("first", "second", "third"):
                        await c.post(f"/internal/v1/sessions/{sid}/utterances", json={**COMMENT, "utteranceId": uid, "priority": 80, "interruptPolicy": "NONE"})
                    await wait_event(pub, "UTTERANCE_COMPLETED", "third")
                    self.assertEqual([e["utteranceId"] for e in pub.events if e["eventType"] == "UTTERANCE_COMPLETED"], ["first", "second", "third"])
                    for event in pub.events:
                        EVENT_VALIDATOR.validate(event)
                    await c.post(f"/internal/v1/sessions/{sid}/stop", json={"commandId": "stop", "traceId": "trace"})
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
