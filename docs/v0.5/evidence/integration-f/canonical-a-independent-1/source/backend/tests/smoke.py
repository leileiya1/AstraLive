#!/usr/bin/env python3
"""GPU-free HTTP/Redis/PostgreSQL smoke test against Backend and Mock Runtime."""
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.getenv("BACKEND_URL", "http://127.0.0.1:18080")

def call(method, path, data=None, headers=None):
    raw = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, raw, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)

def wait_status(path, expected):
    for _ in range(100):
        status, result = call("GET", path)
        if status == 200 and result["data"]["status"] == expected:
            return result
        time.sleep(0.1)
    raise AssertionError(f"never reached {expected}: {result}")

assert call("GET", "/health/ready")[0] == 200
avatar = call("POST", "/api/v1/avatars", {"name":"Mock Host","engine":"MOCK"})[1]["data"]["avatarId"]
voice = call("POST", "/api/v1/voices", {"name":"Mock Voice","provider":"MOCK","providerVoiceId":"mock-1"})[1]["data"]["voiceId"]
product = call("POST", "/api/v1/products", {"name":"Shirt","description":"Cotton","price":129,"currency":"CNY","stock":27,"sizes":["XL"]})[1]["data"]["productId"]
room = call("POST", "/api/v1/live-rooms", {"name":"Mock Room","avatarId":avatar,"voiceId":voice,"systemPrompt":"Speak clearly."})[1]["data"]["roomId"]
session = call("POST", "/api/v1/live-sessions", {"roomId":room})[1]["data"]["sessionId"]
assert call("POST", f"/api/v1/avatars/{avatar}/prepare", headers={"Idempotency-Key":"prepare-"+avatar})[0] == 202
status, first = call("POST", f"/api/v1/live-sessions/{session}/start", headers={"Idempotency-Key":"start-"+session})
assert status == 202 and first["data"]["status"] == "PREPARING", first
status, replay = call("POST", f"/api/v1/live-sessions/{session}/start", headers={"Idempotency-Key":"start-"+session})
assert status == 202 and replay["data"]["operationId"] == first["data"]["operationId"], replay
assert call("POST", f"/api/v1/live-sessions/{session}/start", {}, {"Idempotency-Key":"start-"+session})[0] == 409
wait_status(f"/api/v1/live-sessions/{session}", "LIVE")
assert call("POST", f"/api/v1/live-sessions/{session}/start", headers={"Idempotency-Key":"late-start-"+session})[0] == 409
status, utterance = call("POST", f"/api/v1/live-sessions/{session}/utterances", {"text":"Hello","priority":100,"interruptPolicy":"FORCE","source":"OPERATOR"}, {"Idempotency-Key":"speak-"+session})
assert status == 202, utterance
status, utterance_replay = call("POST", f"/api/v1/live-sessions/{session}/utterances", {"text":"Hello","priority":100,"interruptPolicy":"FORCE","source":"OPERATOR"}, {"Idempotency-Key":"speak-"+session})
assert status == 202 and utterance_replay["data"]["utteranceId"] == utterance["data"]["utteranceId"]
events = urllib.request.urlopen(BASE+f"/api/v1/live-sessions/{session}/events", timeout=10)
text = ""
for line in events:
    text += line.decode()
    if "event: utterance.completed" in text:
        break
events.close()
assert "event: session.live" in text and "event: utterance.completed" in text, text
status, second = call("POST", f"/api/v1/live-sessions/{session}/utterances", {"text":"Long speech","priority":100,"interruptPolicy":"FORCE","source":"OPERATOR"}, {"Idempotency-Key":"interrupt-test-"+session})
assert status == 202, second
second_id = second["data"]["utteranceId"]
events = urllib.request.urlopen(BASE+f"/api/v1/live-sessions/{session}/events", timeout=10)
event_name = ""
interrupted = False
for line in events:
    line = line.decode().strip()
    if line.startswith("event: "):
        event_name = line[7:]
    elif line.startswith("data: "):
        value = json.loads(line[6:])
        if value.get("utteranceId") == second_id and event_name == "utterance.playing":
            assert call("POST", f"/api/v1/live-sessions/{session}/interrupt", {"reason":"OPERATOR_INTERRUPT"})[0] == 202
        if value.get("utteranceId") == second_id and event_name == "utterance.interrupted":
            interrupted = True
            break
events.close()
assert interrupted, "interrupt event missing"
req=urllib.request.Request(BASE+f"/internal/v1/tools/products/{product}/stock", headers={"Authorization":"Bearer "+os.environ["INTERNAL_API_TOKEN"]})
with urllib.request.urlopen(req) as response:
    assert json.load(response)["data"]["stock"] == 27
req=urllib.request.Request(BASE+f"/internal/v1/tools/products/{product}/price", headers={"Authorization":"Bearer "+os.environ["INTERNAL_API_TOKEN"]})
with urllib.request.urlopen(req) as response:
    assert json.load(response)["data"]["price"] == 129
status,_=call("POST", f"/api/v1/live-sessions/{session}/stop",headers={"Idempotency-Key":"stop-"+session})
assert status == 202
assert call("POST", f"/api/v1/live-sessions/{session}/stop",headers={"Idempotency-Key":"stop-"+session})[0] == 202
wait_status(f"/api/v1/live-sessions/{session}", "ENDED")
print("PASS: migrations, CRUD, mock runtime, Redis events, FSM, SSE, interrupt, idempotency, product tool")
