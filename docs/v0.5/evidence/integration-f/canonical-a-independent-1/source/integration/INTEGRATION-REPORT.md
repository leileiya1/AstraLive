# AstraLive v1.1 Integration Acceptance Report

Date: 2026-10-06. Contract: frozen v1.1.0. Verdict: **READY FOR GPU ACCEPTANCE**. This is not Release GO.

## Acceptance results

| Gate | Status | Observed evidence |
| --- | --- | --- |
| 1. Product answer at TTS boundary | PASS | Production Runtime session path sent “这款有 XL 尺码，目前商品整体还有库存，但暂时没有 XL 单独库存数据。” to Capturing TTS. Aggregate `27` appeared only in the whole-product stock answer. [Captured TTS inputs](evidence/fact-safety-v1.1.json). |
| 2. Bad LLM containment | PASS | Injected Bad LLM returns `XL有27件` on an ordinary chat, proving it is active. It was called zero times for size/stock/product questions; its false claim never reached TTS for those questions. `tests/test_acceptance_guards.py` and Runtime's deterministic-answer test passed. [ISSUE-003 closed](issues/003-product-size-fact-routing.md). |
| 3. Backend Go Mock removed from support | PASS | `backend/cmd/mock-runtime` contains no files; `go list ./cmd/...` returns only `astralive/backend/cmd/server`. Backend README and Compose no longer start a Go Mock. |
| 4. Unique Contract Mock | PASS | `integration/mock_runtime` is the only runnable repository Contract Mock. `infra/mock-runtime.Dockerfile` copies it; Python Mock and Real Runtime passed the same priority/FIFO scenarios. [ISSUE-004 closed](issues/004-backend-go-mock-runtime-parity.md). |
| 5. Contract Tests | PASS | `unittest discover -s tests`: 5 passed, including v1.1 required fields, event schema, Mock/Real priority parity and both acceptance guards. |
| 6. Runtime Tests | PASS | Default discovery: 25 tests, 16 passed and 9 explicitly opt-in skipped. Current-stage opt-ins passed separately: real TTS 3, WebRTC media 2, lightweight Avatar clock/interrupt 1. External real LLM/full-real opt-ins were outside this acceptance stage. |
| 7. Backend Tests | PASS | `go test ./...` passed; only `cmd/server` remains in the Go command list. |
| 8. Frontend Tests | PASS | `bun run test`: 6 files, 18 tests passed; `bun run build` passed. |
| 9. Full Mock E2E | PASS | Go + isolated PostgreSQL/Redis + `integration/mock_runtime`: resources, Session, COMMENT, manual Speak, SSE heartbeat, Stop and Runtime Event JSON Schema. [Captured HTTP evidence](evidence/mock-v1.1.jsonl). Mock media returned stable `503 WEBRTC_FAILED` as contracted. |
| 10. Real Runtime + Mock AI E2E | PASS | Go + Real Runtime with Mock LLM/TTS/Avatar and WebRTC Media: COMMENT, Context, Product Tool, SSE, Chrome, failure injection, duplicate eventId and Redis retry. [Captured HTTP and Tool responses](evidence/real-v1.1.jsonl). |
| 11. Lightweight Avatar + Real TTS + Browser WebRTC | PASS | Cumulative CPU chain with Mock LLM, real local TTS, lightweight Avatar and WebRTC. Actual headless Chrome `RTCPeerConnection` completed Go→Runtime signaling and observed audio/video tracks. [Captured HTTP and Tool responses](evidence/light-v1.1.jsonl). |

## Cross-service details

The real-mode proxy captured Go sending all four Session Context fields (`roomId`, `systemPrompt`, `activeProductId`, `knowledgeBaseId`). COMMENT without a live Session returned `409 SESSION_NOT_RUNNING`; while live, Go delivered `source=PLATFORM_EVENT`, priority `80`, and `INTERRUPT_LOWER_PRIORITY` to Runtime, followed by `UTTERANCE_QUEUED` through `UTTERANCE_COMPLETED`. Product questions caused actual Runtime→Go Product and aggregate Stock Tool requests. The size-safety test separately captured the final text at the TTS boundary using the production Runtime orchestration path and a deliberately malicious LLM.

Live SSE delivered explicit UTC `heartbeat` frames, separate from business Runtime Events; every observed Runtime Event passed `runtime-event.schema.json`. A browser-style complete SDP offer traversed Go's public endpoint and Runtime's internal endpoint and returned a complete answer. A real Chrome process reported connected audio/video tracks. Failure injection passed Runtime 500, unavailable, 30-second timeout, Tool unavailable warning/fallback, duplicate Idempotency-Key, duplicate eventId, Redis pending retry, COMMENT without a live Session and invalid WebRTC offer. Test-owned processes and the injected Redis poison event were cleaned up.

## Commands and environment

```sh
runtime/.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_*.py' -v
(cd backend && go test ./... && go list ./cmd/...)
(cd frontend && bun run test && bun run build)
scripts/run-local-v11.sh
```

The local runner built a fresh Backend binary and used SSH tunnels to the existing isolated AstraLive PostgreSQL database and Redis DB 14 on `school-linux`. It did not restart existing remote containers. The Chrome test proves local browser signaling and track arrival; it does not establish cross-host ICE reachability or long-duration media stability.

## Remaining final acceptance

| Item | Status | Reason |
| --- | --- | --- |
| Docker/deployment environment | NOT RUN | Local Docker CLI unavailable; local process integration passed. |
| Cross-host ICE | NOT RUN | Browser and Runtime were on the same host. |
| RTX 2060 GPU | NOT RUN | Reserved for GPU acceptance. |
| MuseTalk | NOT RUN | Reserved for GPU acceptance; no work started here. |
| One-hour soak | FAIL in later independent gate | Not run in this original local Integration gate; the 2026-10-07 result is recorded below. |

ISSUE-003 and ISSUE-004 are closed. No remaining blocker was found in the v1.1 local Integration Acceptance gates. The verdict is **READY FOR GPU ACCEPTANCE**, not Release GO.

## One-hour Production Stability — 2026-10-07

**FAIL.** The independent Mac Chrome → Go → Ubuntu Runtime browser-connected monitor ran 3,632 seconds and completed 87 mixed business cycles. Its last sample changed to `connectionState=failed`, `iceConnectionState=disconnected` before normal Stop. The Ubuntu Runtime SSH connection closed at the same boundary; the initiating cause is unconfirmed. Redis recorded 4,738 valid events, 0 `SESSION_FAILED`, 0 `UTTERANCE_FAILED`, 176 expected interrupts and 524/524 Product Tool HTTP 200 responses, but no `SESSION_STOPPING` or `SESSION_ENDED`. Normal cleanup was therefore not verified. See [one-hour report](ONE-HOUR-SOAK-REPORT.md) and [ISSUE-007](issues/007-one-hour-host-connection-loss.md). This later gate supersedes the historical `READY FOR GPU ACCEPTANCE` status above for release readiness; v0.1 Core Technical MVP is **not accepted** by this run.

A fresh retry after Ubuntu recovery also **FAILED**: the 330-second preflight passed, but the formal run had `UTTERANCE_FAILED=1` with `WebRTC playback drain timed out` after 51 complete cycles / 2,232 seconds of driver time. Normal Stop returned `INTERNAL_ERROR`; no `SESSION_ENDED` was observed. [ISSUE-008](issues/008-webrtc-playback-drain-timeout.md) and the [retry section of the one-hour report](ONE-HOUR-SOAK-REPORT.md#independent-retry-after-ubuntu-recovery) record the separate failure. This is now the direct blocker to Core Technical MVP Acceptance.
