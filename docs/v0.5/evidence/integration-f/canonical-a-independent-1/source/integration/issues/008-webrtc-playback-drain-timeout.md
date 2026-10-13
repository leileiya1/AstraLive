# ISSUE-008: WebRTC playback drain timed out during one-hour retry

Status: **CLOSED — REVALIDATED ON SCHOOL-LINUX**. Discovered in the independent retry on 2026-10-07 and revalidated by the final continuous School-Linux run completed on 2026-10-07 UTC / 2026-10-07–08 Asia/Taipei.

The fresh 5-minute preflight passed (330 seconds, 7 cycles, normal Stop). The subsequent one-hour retry used a new Session and completed 51 mixed business cycles. In the next cycle, a NONE-policy queued utterance `utt_4beb22d75ad2c01f539f1ab785fdfe22` reached `UTTERANCE_PLAYING` at **03:05:47.958 UTC** and `UTTERANCE_FAILED` at **03:06:02.986 UTC**. The Runtime log records `RuntimeError: WebRTC playback drain timed out` for the same utterance/generation. The driver then timed out waiting for `utterance.completed`; its normal Stop attempt returned Backend `INTERNAL_ERROR`. The run reached only about **2,232 seconds** and did not satisfy the 3,600-second or zero-`UTTERANCE_FAILED` gates.

Redis has **2,800** events for this Session, including exactly one `UTTERANCE_FAILED`, 104 intended interrupts, 361 completed utterances, and no `SESSION_STOPPING`/`SESSION_ENDED`. The Runtime and Backend were still sampled as live processes after this failure, so a later host/network loss is a separate event and is not needed to explain this acceptance failure. The exact queue/peer condition behind the drain timeout requires Runtime-owner investigation.

Evidence: [Runtime retry summary](../evidence/browser-connected-runtime-60m-retry-1.json), [Redis events](../evidence/browser-connected-events-60m-retry-1.json), [system samples](../evidence/browser-connected-system-60m-retry-1.json), [Runtime log](../evidence/browser-connected-runtime-60m-retry-1.log), and [Tool proxy](../evidence/browser-connected-runtime-tool-60m-retry-1.jsonl). Browser monitor output was not fully persisted because its final cleanup request hung after the local stack became unavailable; available periodic console samples had shown connected ICE through elapsed 2,131 seconds. Do not treat the missing browser JSON as evidence of browser continuity.

## Root Cause

The old `WebRTCMediaOutput.drain()` captured every Peer and waited for both queues to be empty. A Peer can remain `connected` while its audio or video sender stops calling `recv()`. One such Peer leaves queued frames forever and causes the whole Utterance to time out after 15 seconds, even when another Peer consumed normally. The queue check also had no generation-scoped completion target. The prior Runtime recorded no per-Peer queue or recv telemetry, so the precise Peer/Track responsible for the observed retry cannot be identified retrospectively. Stop also waited without a bound on worker and Peer close.

## Fix

Runtime media tracks now count frames enqueued and consumed per generation. Drain snapshots its targets after audio flush and waits for consumption of those targets. Stale/failed/disconnected Peers are evicted with structured diagnostics and a `RUNTIME_WARNING`; a healthy Peer can complete independently. If every Peer becomes unavailable, Runtime emits `MEDIA_FAILED` with `MEDIA_OUTPUT_FAILED` and a terminal `UTTERANCE_FAILED`. TTS and Avatar failures are classified separately. Stop cancels work, clears queues, closes tracks and Peers with bounded waits, and proceeds to `SESSION_ENDED` with warnings for cleanup timeouts. No SDP is logged.

## Regression Tests

`runtime/tests/test_webrtc_drain_regression.py` covers normal consumption, audio-only stall, video-only stall, healthy plus stalled Peer, interrupt during drain, Stop after media failure, 300 short utterances without queue growth, bounded Peer close, and an old-generation enqueue race. The dual-Peer test runs a short version of the old queue-empty rule and confirms it times out before the new drain succeeds. `runtime/tests/test_webrtc_media_integration.py` now exercises repeated drain, counter reset, Peer close/reconnect and stale-Peer eviction over local aiortc.

On 2026-10-07, the required system-Python discovery passed 36 tests with 20 skips (real-media dependencies and unrelated provider opt-ins absent). The Runtime venv with `RUN_WEBRTC_INTEGRATION=1` passed 36 tests with 7 unrelated provider opt-ins skipped, including all new regressions and real aiortc tests.

## Remaining Risk

Track consumption shows that aiortc accepted frames from Runtime; it does not prove browser decoding or continuous playback. The production retry's exact stalled Peer state is unknown because old diagnostics were absent. A fresh browser-connected one-hour soak, including normal Stop and post-Stop cleanup evidence, is required before closing this issue or changing the acceptance verdict.

## Final Revalidation

The final formal-frontend run used one Session and one Mac Chrome/WebRTC Peer for 3,671 seconds. Chrome stayed `connected/connected` through the T+60-minute sample, decoded 90,031 frames at T+3,601 seconds, and reported zero dropped frames. Runtime recorded zero `WebRTC playback drain timed out`, zero `MEDIA_FAILED`, and zero `UTTERANCE_FAILED`. Normal Stop emitted `SESSION_STOPPING` then `SESSION_ENDED`; Backend reported `ENDED`, and Runtime removed the Session. See [final audit](../evidence/school-linux-final/audit.json) and [final summary](../evidence/school-linux-final/final-soak-summary.json).
