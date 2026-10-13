"""Contract v1.1 public API E2E. Requires a running Go/Redis/Postgres/Runtime stack."""
import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
from uuid import uuid4
from jsonschema import Draft202012Validator, FormatChecker

BASE = os.getenv("ASTRALIVE_BASE_URL", "http://127.0.0.1:18080")
EVIDENCE = os.getenv("ASTRALIVE_EVIDENCE_FILE")


def request(method, path, data=None, key=None):
    raw = None if data is None else json.dumps(data, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"} if raw is not None else {}
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, raw, headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)
    except urllib.error.URLError:
        return 0, {}


def wait_for(check, label, timeout=35):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.1)
    raise AssertionError(f"timeout: {label}")


def evidence():
    if not EVIDENCE or not Path(EVIDENCE).exists():
        raise AssertionError("ASTRALIVE_EVIDENCE_FILE with observable Runtime/Tool proxy records is required")
    return [json.loads(line) for line in Path(EVIDENCE).read_text().splitlines() if line]


def observed(path, predicate=lambda _: True):
    return [row for row in evidence() if row["path"] == path and predicate(row)]


def iso_utc(value):
    return value.endswith("Z") and datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset().total_seconds() == 0


def fault(mode, path):
    file = Path(os.environ["ASTRALIVE_FAULT_FILE"])
    file.write_text(json.dumps({"mode": mode, "path": path}))


def clear_fault():
    Path(os.environ["ASTRALIVE_FAULT_FILE"]).unlink(missing_ok=True)


async def webrtc_signaling(sid):
    from aiortc import RTCPeerConnection, RTCSessionDescription
    peer = RTCPeerConnection()
    tracks = set()
    @peer.on("track")
    def on_track(track):
        tracks.add(track.kind)
    peer.addTransceiver("audio", direction="recvonly")
    peer.addTransceiver("video", direction="recvonly")
    try:
        await peer.setLocalDescription(await peer.createOffer())
        offer = peer.localDescription.sdp
        assert "a=candidate:" in offer, "offer lacks gathered ICE candidates"
        status, answer = await asyncio.to_thread(request, "POST", f"/api/v1/live-sessions/{sid}/webrtc/offer", {"type": "offer", "sdp": offer})
        assert status == 200 and answer["data"]["type"] == "answer", answer
        assert "a=candidate:" in answer["data"]["sdp"], "answer lacks gathered ICE candidates"
        await peer.setRemoteDescription(RTCSessionDescription(sdp=answer["data"]["sdp"], type="answer"))
        end = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < end and (peer.connectionState != "connected" or tracks != {"audio", "video"}):
            await asyncio.sleep(0.1)
        assert peer.connectionState == "connected" and tracks == {"audio", "video"}, (peer.connectionState, tracks)
        print("PASS: browser-style full ICE offer -> Go -> Runtime -> answer; aiortc peer received audio/video tracks")
    finally:
        await peer.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-evidence", action="store_true")
    parser.add_argument("--require-tool", action="store_true")
    parser.add_argument("--heartbeat", action="store_true")
    parser.add_argument("--webrtc", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--failure", action="store_true")
    parser.add_argument("--redis-failure", action="store_true")
    args = parser.parse_args()
    wait_for(lambda: request("GET", "/health/ready")[0] == 200, "Go ready", 90)
    suffix = uuid4().hex[:8]
    status, avatar = request("POST", "/api/v1/avatars", {"name": f"test-{suffix}", "engine": "MOCK"})
    assert status == 201, avatar
    status, voice = request("POST", "/api/v1/voices", {"name": f"test-{suffix}", "provider": "MOCK", "providerVoiceId": "mock-female-01"})
    assert status == 201, voice
    status, product = request("POST", "/api/v1/products", {"name": "卫衣", "description": "集成测试商品", "price": 129, "currency": "CNY", "stock": 27, "sizes": ["M", "L", "XL"]})
    assert status == 201, product
    pid = product["data"]["productId"]
    status, kb = request("POST", "/api/v1/knowledge-bases", {"name": f"test-{suffix}"})
    assert status == 201, kb
    kid = kb["data"]["knowledgeBaseId"]
    prompt = f"你是一名服装主播。测试标识 {suffix}。"
    status, room = request("POST", "/api/v1/live-rooms", {"name": f"test-{suffix}", "avatarId": avatar["data"]["avatarId"], "voiceId": voice["data"]["voiceId"], "activeProductId": pid, "knowledgeBaseId": kid, "systemPrompt": prompt})
    assert status == 201, room
    rid = room["data"]["roomId"]
    comment = lambda text: {"eventType": "COMMENT", "roomId": rid, "user": {"externalId": "mock-user-01", "nickname": "测试用户"}, "payload": {"text": text}}
    status, no_session = request("POST", "/api/v1/dev/platform-events", comment("有 XL 吗？"))
    assert (status, no_session.get("code")) == (409, "SESSION_NOT_RUNNING"), no_session
    status, session = request("POST", "/api/v1/live-sessions", {"roomId": rid})
    assert status == 201, session
    sid = session["data"]["sessionId"]
    seen = []
    ready = threading.Event()
    stop_reader = threading.Event()

    def read_sse():
        req = urllib.request.Request(BASE + f"/api/v1/live-sessions/{sid}/events")
        try:
            with urllib.request.urlopen(req, timeout=70) as stream:
                ready.set()
                name = None
                for line in stream:
                    if stop_reader.is_set():
                        break
                    line = line.decode().strip()
                    if line.startswith("event: "):
                        name = line[7:]
                    elif line.startswith("data: ") and name:
                        seen.append((name, json.loads(line[6:])))
                        name = None
        except Exception as exc:
            seen.append(("reader.error", str(exc)))

    thread = threading.Thread(target=read_sse, daemon=True)
    thread.start()
    assert ready.wait(10), "SSE not connected"
    try:
        status, started = request("POST", f"/api/v1/live-sessions/{sid}/start", key=f"start-{suffix}")
        assert status == 202, started
        duplicate_status, duplicate = request("POST", f"/api/v1/live-sessions/{sid}/start", key=f"start-{suffix}")
        assert duplicate_status == 202 and duplicate["data"] == started["data"], duplicate
        wait_for(lambda: any(n == "session.live" for n, _ in seen), "session.live")
        invalid_status, invalid = request("POST", f"/api/v1/live-sessions/{sid}/webrtc/offer", {"type": "offer", "sdp": "invalid sdp"})
        assert invalid_status in (500, 503) and invalid.get("code") == "WEBRTC_FAILED", invalid
        print("PASS: invalid WebRTC offer -> WEBRTC_FAILED")
        if args.webrtc:
            asyncio.run(webrtc_signaling(sid))
            if args.require_evidence:
                rows = observed(f"/internal/v1/sessions/{sid}/webrtc/offer", lambda r: r["status"] == 200)
                assert rows and rows[-1]["request"]["sdp"].startswith("v=0"), rows
                print("PASS: Go forwarded complete SDP to Runtime internal endpoint")
        if args.browser:
            from browser_webrtc import verify
            verify(BASE, sid)
            print("PASS: headless Chrome RTCPeerConnection -> Go -> Runtime, audio/video tracks received")
        if args.require_evidence:
            wait_for(lambda: bool(observed("/internal/v1/sessions", lambda r: r.get("request", {}).get("sessionId") == sid)), "Runtime Create capture")
            contexts = [r["request"]["context"] for r in observed("/internal/v1/sessions", lambda r: r.get("request", {}).get("sessionId") == sid)]
            assert any(c.get("roomId") == rid and c.get("systemPrompt") == prompt and c.get("activeProductId") == pid and c.get("knowledgeBaseId") == kid for c in contexts), contexts
            print("PASS: Go actually sent roomId, systemPrompt, activeProductId, knowledgeBaseId")
        status, utterance = request("POST", f"/api/v1/live-sessions/{sid}/utterances", {"text": "欢迎大家进入直播间。", "priority": 100, "interruptPolicy": "NONE", "source": "OPERATOR"}, f"speak-{suffix}")
        assert status == 202, utterance
        uid = utterance["data"]["utteranceId"]
        wait_for(lambda: any(n == "utterance.completed" and e.get("utteranceId") == uid for n, e in seen), "manual utterance completion")
        for name in ("session.preparing", "session.ready", "session.live", "utterance.queued", "utterance.generating", "utterance.synthesizing", "utterance.rendering", "utterance.playing", "utterance.completed"):
            assert any(n == name for n, _ in seen), (name, seen)
        print("PASS: manual Speak Runtime events -> Redis -> Go -> SSE")
        status, answer = request("POST", "/api/v1/dev/platform-events", comment("有 XL 吗？"))
        assert status == 202, answer
        cid = answer["data"]["utteranceId"]
        wait_for(lambda: any(n == "utterance.completed" and e.get("utteranceId") == cid for n, e in seen), "COMMENT completion")
        assert any(n == "utterance.queued" and e.get("utteranceId") == cid for n, e in seen)
        if args.require_evidence:
            rows = observed(f"/internal/v1/sessions/{sid}/utterances", lambda r: r.get("request", {}).get("utteranceId") == cid)
            assert rows, "Go did not forward COMMENT to Runtime"
            delivered = rows[0]["request"]
            assert (delivered["source"], delivered["priority"], delivered["interruptPolicy"], delivered["text"]) == ("PLATFORM_EVENT", 80, "INTERRUPT_LOWER_PRIORITY", "有 XL 吗？"), delivered
        print("PASS: COMMENT -> Go -> PLATFORM_EVENT priority 80 -> Runtime QUEUED -> COMPLETED")
        for text, tool_suffix in (("库存多少？", "/stock"), ("有 XL 这个尺码吗？", ""), ("XL 还有库存吗？", "")):
            status, answer = request("POST", "/api/v1/dev/platform-events", comment(text))
            assert status == 202, answer
            uid = answer["data"]["utteranceId"]
            wait_for(lambda: any(n == "utterance.completed" and e.get("utteranceId") == uid for n, e in seen), f"{text} completion")
            if args.require_tool:
                path = f"/internal/v1/tools/products/{pid}{tool_suffix}"
                wait_for(lambda: bool(observed(path, lambda r: r.get("response", {}).get("data", {}).get("productId") == pid)), f"Tool call {path}")
                row = observed(path)[-1]
                assert row["response"]["data"].get("stock" if tool_suffix else "sizes") == (27 if tool_suffix else ["M", "L", "XL"]), row
            print(f"PASS: {text} completed" + ("; Product Tool response captured" if args.require_tool else ""))
        if args.heartbeat:
            wait_for(lambda: any(n == "heartbeat" for n, _ in seen), "explicit SSE heartbeat", 25)
            for n, data in seen:
                if n == "heartbeat":
                    assert set(data) == {"timestamp"} and iso_utc(data["timestamp"]), data
            print("PASS: explicit UTC heartbeat is not a Runtime Event envelope")
        if args.failure:
            offer_path = f"/internal/v1/sessions/{sid}/webrtc/offer"
            for mode, expected_status in (("500", 500), ("unavailable", 503), ("timeout", 503)):
                fault(mode, offer_path)
                try:
                    status, err = request("POST", f"/api/v1/live-sessions/{sid}/webrtc/offer", {"type": "offer", "sdp": "fault-offer"})
                    assert (status, err.get("code")) == (expected_status, "WEBRTC_FAILED"), (mode, status, err)
                finally:
                    clear_fault()
            print("PASS: Runtime 500, unavailable and timeout map to stable public WebRTC failures")
            tool_path = f"/internal/v1/tools/products/{pid}/stock"
            fault("unavailable", tool_path)
            try:
                status, answer = request("POST", "/api/v1/dev/platform-events", comment("库存多少？"))
                assert status == 202, answer
                uid = answer["data"]["utteranceId"]
                wait_for(lambda: any(n == "runtime.warning" and e.get("utteranceId") == uid for n, e in seen), "Tool failure warning")
                wait_for(lambda: any(n == "utterance.completed" and e.get("utteranceId") == uid for n, e in seen), "Tool failure fallback completion")
            finally:
                clear_fault()
            print("PASS: Tool unavailable produced RUNTIME_WARNING and completed fallback")
        if args.redis_failure:
            import redis
            rc = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
            stream = os.getenv("REDIS_RUNTIME_EVENT_STREAM", "dh.runtime.events.v1")
            originals = [row[1].get("data", row[1].get("event")) for row in rc.xrevrange(stream, count=200)]
            original = next((raw for raw in originals if raw and json.loads(raw).get("eventType") == "UTTERANCE_COMPLETED" and json.loads(raw).get("utteranceId") == uid), None)
            assert original, "cannot locate completed event in Redis stream"
            event_id = json.loads(original)["eventId"]
            before = sum(e.get("eventId") == event_id for _, e in seen)
            duplicate_id = rc.xadd(stream, {"data": original})
            time.sleep(2)
            assert not rc.xpending_range(stream, "astralive-go", duplicate_id, duplicate_id, 1), "duplicate event remained pending"
            assert sum(e.get("eventId") == event_id for _, e in seen) == before, "duplicate event was sent twice over SSE"
            print("PASS: duplicate eventId ACKed without duplicate SSE fact")
            poison_id = rc.xadd(stream, {"data": "{invalid-json"})
            def retried():
                rows = rc.xpending_range(stream, "astralive-go", poison_id, poison_id, 1)
                return rows and rows[0]["times_delivered"] >= 2
            try:
                wait_for(retried, "Redis event retry", 25)
                print("PASS: rejected Redis event retried via consumer pending claim")
            finally:
                rc.xack(stream, "astralive-go", poison_id)
                rc.xdel(stream, poison_id)
                rc.close()
    finally:
        status, ended = request("POST", f"/api/v1/live-sessions/{sid}/stop", key=f"stop-{suffix}")
        assert status == 202, ended
        wait_for(lambda: any(n == "session.ended" for n, _ in seen), "session.ended")
        schema = json.loads((Path(__file__).resolve().parents[1] / "contracts/events/runtime-event.schema.json").read_text())
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for name, event in seen:
            if isinstance(event, dict) and event.get("source") == "AI_RUNTIME":
                validator.validate(event)
        stop_reader.set()
        print("PASS: stop cleanup and all observed Runtime Events match JSON Schema")


if __name__ == "__main__":
    main()
