# AstraLive v1.1 Integration Testing

Contract baseline: v1.1.0. Use the frozen `contracts/` files as the source of truth. Do not edit Backend, Runtime, Frontend, or Contract from integration tests. Record module defects in `integration/issues/`.

## Gates and commands

```sh
runtime/.venv/bin/python -m unittest tests.test_contracts -v
scripts/run-local-v11.sh mock
scripts/run-local-v11.sh real
scripts/run-local-v11.sh light
```

`mock` uses Go + PostgreSQL + Redis + `integration/mock_runtime`, with v1.1 Context/source validation, priority queue, and a stable `503 WEBRTC_FAILED` for unsupported media. `real` uses Real Runtime with Mock LLM/TTS/Avatar and real WebRTC media. `light` uses Mock LLM, real local TTS, lightweight Avatar, and real WebRTC. No MuseTalk or GPU run belongs to these gates.

`tests/e2e.py` asserts public resource creation, Session/Utterance FSM, COMMENT 409/202 and Runtime delivery fields, all four Context fields captured on the Go→Runtime hop, Product Tool requests and results captured on the Runtime→Go hop, explicit SSE heartbeat, non-trickle WebRTC signaling and real headless Chrome audio/video tracks. Every observed Runtime Event is validated against `runtime-event.schema.json`; heartbeat is not treated as a Runtime Event.

The test-only `integration/observe_proxy.py` records HTTP request/response evidence under `integration/evidence/` without authentication headers. The real-mode fault file injects Runtime 500, unavailable, timeout, and Tool unavailable. The test also checks duplicate Idempotency-Key, duplicate eventId deduplication, Redis pending retry, COMMENT without a live Session, and invalid SDP. The Runner cleans up its own processes and the injected Redis poison event.

Run the frozen Contract validator separately when needed:

```sh
runtime/.venv/bin/python contracts/validate_v1_1.py
```

## Acceptance limits

A Chrome `RTCPeerConnection` track observation proves local browser media negotiation. It does not prove cross-host ICE reachability, sustained frame delivery, or one-hour stability. Tool HTTP evidence proves Runtime used Product data; safe generated wording for per-size inventory still requires output validation (ISSUE-003). The Backend-owned Go mock remains non-conformant (ISSUE-004); integration uses the Python Mock.
