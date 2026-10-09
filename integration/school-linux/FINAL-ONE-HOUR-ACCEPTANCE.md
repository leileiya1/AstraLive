# AstraLive v0.1 — School-Linux Final One-Hour Acceptance

## Final Verdict

**ASTRALIVE V0.1 CORE MVP ACCEPTED**

The final qualifying run used the formal frontend and STUN configuration, Go Backend, School-Linux Python Runtime, real DeepSeek-compatible LLM, real CPU TTS, Lightweight Avatar, and one Mac Chrome/WebRTC Peer. The same Session and Peer remained connected through the full hour. The browser monitor ran for 3,671 seconds; the T+3,601-second sample remained `connected/connected` with 180,061 audio packets, 90,031 decoded video frames, and zero browser-dropped frames.

## Runtime Fixes

ISSUE-008's generation-scoped enqueued/consumed drain targets were retained. ISSUE-009 adds bounded asynchronous audio/video pushes, per-Peer concurrent delivery, generation/interrupt/Stop checks during waits, time-based buffers, and progress-aware stalled-Peer detection. A session worker self-recovery guard also prevents an accepted utterance from being stranded if a LIVE worker exits.

## ISSUE-009 Root Cause

The former synchronous video push treated a full fixed 125-frame queue as proof of a stalled Peer. On the i9-13900, rendering was much faster than the 25 FPS playback clock, so a healthy, recently consuming Peer filled the queue and was falsely evicted.

## Dynamic Backpressure

Queue full plus continuing consumed-counter and `lastRecv` progress is healthy backpressure: the producer waits. Eviction requires queue full, no consumption progress, and a stale receive timestamp. Peer delivery is concurrent, so a stalled Peer cannot block a healthy Peer. Waits continuously check generation, Session state, Track state, Peer state, progress, and stale bounds.

## TARGET_FPS Semantics

`TARGET_FPS` is the target playback/media clock, not the producer render rate. It is configurable for 20, 25, and 30 FPS and defaults to 25. Fast rendering produces more bounded wait time, not more live latency. v0.1 does not implement adaptive FPS/resolution/avatar quality.

## Time-Based Buffer

Queue capacity is `ceil(TARGET_FPS × BUFFER_MS / 1000)`, capped by the configured maximum time. The final configuration used 25 FPS and 400 ms: video peaked at 10 frames / 400 ms; 20 ms audio peaked at 20 frames / 400 ms.

## ISSUE-010 Root Cause

The original stream handling did not robustly model OpenAI-compatible terminal semantics, and the deployed 128/256 token limits could be exhausted by hidden DeepSeek reasoning tokens. Runtime now accepts `finish_reason=stop` followed by `[DONE]` or clean EOF, while rejecting unterminated EOF, `length`, `content_filter`, error packets, non-2xx responses, malformed JSON, and connection resets. Only `delta.content` is spoken; `reasoning_content` is discarded. The deployed maximum is 1024; strict `length` failure remains.

## Automated Tests

- Required Runtime discovery: 52 tests passed, 11 opt-in tests skipped, 0 failures.
- Streaming semantics: eight cases passed, including DONE, clean EOF, missing terminal, length, error packet, keepalive/event lines, malformed JSON, and reasoning exclusion.
- Dynamic-backpressure regressions cover 20/25/30 FPS, fast/slow producers, healthy full queues, genuine stalls, healthy plus stalled Peers, interrupt/Stop while blocked, generation leakage, and 300 cycles.
- Real aiortc integration: 4 passed, 0 failed.
- Real DeepSeek integration: 1 passed, 0 failed.
- Full Real LLM → sentence stream → CPU TTS → Lightweight Avatar → aiortc: 1 passed, 0 failed.

## Checkpoints

| Checkpoint | ICE / connection | Audio packets | Frames decoded | Browser dropped |
| --- | --- | ---: | ---: | ---: |
| T+90s | connected / connected | 4,508 | 2,251 | 0 |
| T+5m | connected / connected | 15,012 | 7,504 | 0 |
| T+15m | connected / connected | 45,018 | 22,508 | 0 |
| T+30m | connected / connected | 90,031 | 45,014 | 0 |
| T+45m | connected / connected | 135,046 | 67,523 | 0 |
| T+60m | connected / connected | 180,061 | 90,031 | 0 |

The per-checkpoint JSON files contain the matching queue/counter and host-resource snapshot.

## WebRTC and Backpressure

The final Peer stayed connected through T+60 minutes without refresh, Runtime restart, Session restart, or reconnection. Runtime observed 103,552 backpressure events and 2,749,816.9 ms cumulative producer wait. Video totals were 43,251 enqueued and 43,251 consumed. `peerStallEvents=0`, `peerEvictions=0`, and WebRTC drain timeouts were zero. Generation cleanup dropped 1,480 obsolete queued frames across intentional interrupts; no old-generation media leaked.

## Queues

Video was bounded at 10 frames / 400 ms and audio at 20 frames / 400 ms. Queue latency did not grow across the run. The final media counters continued increasing, and Stop cleared Track queues and producer waits.

## LLM

Unexpected provider protocol failures were zero. Two isolated DeepSeek `ConnectTimeout` warnings occurred at 13:14:35.955Z and 13:30:26.172Z and used the existing input-text fallback; they are explicitly classified as external upstream network failures, not hidden. There were no `length`, malformed terminal, malformed JSON, or reasoning-content leaks, and no `UTTERANCE_FAILED` resulted.

## Product Safety

The run repeatedly exercised stock, XL, XXXL, price, and product-description questions. The TTS-boundary audit found zero false per-size stock claims such as `XL有27件`. Aggregate stock was only described as whole-product stock, with per-size stock reported unavailable.

## Interrupt

The driver completed 37 FORCE interrupts, 37 lower-priority interrupts, and 37 NONE FIFO checks. Redis recorded 334 queued/generating/synthesizing/rendering/playing utterances, 260 completed utterances, and 74 intended interrupted terminals, with zero failed terminals.

## Resources

Sixty-one resource samples were captured. Runtime RSS warmed from 116.3 MiB, peaked at 1,310.5 MiB, and was 994.5 MiB after Stop; the series fluctuated rather than increasing monotonically. Minimum available RAM was 43.2 GiB class and ended higher than that minimum. Backend remained about 23 MiB. Swap was stable. CPU temperature was around 60–61°C in checkpoints. The Quadro K2200 remained display-only at about 303–304 MiB and 0% compute utilization. No clear memory leak was observed.

## Host Stability

The boot ID remained `2c39c26e-0e68-4c2d-947f-3a211f5af075`. No host reboot occurred.

## Stop / Cleanup

The same run ended through normal Stop: `SESSION_STOPPING` → `SESSION_ENDED`. Backend status is `ENDED`; Runtime returns Session Not Found, the Browser Peer is closed, and no queued utterance, stale generation, or pending producer wait remains.

## Errors

`SESSION_FAILED=0`, `UTTERANCE_FAILED=0`, `MEDIA_FAILED=0`, drain timeout=0, false eviction=0, worker failure=0, and unexpected LLM protocol failure=0. The two external DeepSeek `ConnectTimeout` warnings are preserved in the audit and Runtime events.

## Evidence

- [Final summary](../evidence/school-linux-final/final-soak-summary.json)
- [Audit](../evidence/school-linux-final/audit.json)
- [Browser stats](../evidence/school-linux-final/browser-stats.json)
- [Runtime events](../evidence/school-linux-final/runtime-events.json)
- [Resource stats](../evidence/school-linux-final/resource-stats.json)
- [T+90s](../evidence/school-linux-final/checkpoint-90s.json), [T+5m](../evidence/school-linux-final/checkpoint-5m.json), [T+15m](../evidence/school-linux-final/checkpoint-15m.json), [T+30m](../evidence/school-linux-final/checkpoint-30m.json), [T+45m](../evidence/school-linux-final/checkpoint-45m.json), [T+60m](../evidence/school-linux-final/checkpoint-60m.json)

ISSUE-008 is **CLOSED — REVALIDATED ON SCHOOL-LINUX**. ISSUE-009 is **CLOSED — REVALIDATED ON SCHOOL-LINUX**. ISSUE-010 is **CLOSED**. RTMP, RAG, and MuseTalk were not started.
