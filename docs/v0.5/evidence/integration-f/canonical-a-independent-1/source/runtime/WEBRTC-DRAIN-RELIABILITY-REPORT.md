# WebRTC Drain Reliability Repair

Date: 2026-10-07. Scope: `runtime/**` and ISSUE-008. Contract v1.1.0 unchanged. One-hour acceptance remains **FAIL** pending revalidation.

## Root cause and old failure

The prior drain captured all Peers and polled `audio.queue.empty() && video.queue.empty()` for up to 15 seconds. ICE/connection state can remain connected after a sender or Track stops consuming. One stalled audio or video queue therefore caused a whole Utterance failure, including when another Peer consumed the media. Queue emptiness was a momentary state rather than a target for the current generation. The retry log proves the drain timeout at generation 105, but has no per-Peer telemetry to identify the actual stalled Track. Stop's worker and Peer close waits had no upper bound.

The new dual-Peer regression explicitly runs the old queue-empty predicate with a healthy and a stalled Peer: it times out. The same setup completes under the repaired drain after the stalled Peer is evicted.

## New drain semantics and diagnostics

- Each Peer has an internal ID. Audio/video tracks count generation-specific frames enqueued and consumed; audio flush contributes its padded final frame. Drain snapshots both target counters after flush and completes when surviving Peers reach them. Interrupt changes generation and clears queues/counters, making old drain return. A newly negotiated Peer starts at the current generation.
- A disconnected, failed, closed or non-consuming Peer is evicted. The non-consumption window is 2 seconds by default; the overall drain deadline remains 15 seconds. This is bounded detection, not a playback sleep. A healthy Peer is not failed because another Peer stalls. If no Peer survives, media delivery fails explicitly rather than claiming playback success.
- Eviction and drain timeout logs include Peer ID, connection/ICE state, queue sizes/capacities, last audio/video recv UTC times, enqueue/consume counters, and generation ID. SDP is excluded. Peer eviction warnings are also published as `RUNTIME_WARNING`. All-Peer failure publishes `MEDIA_FAILED` (`MEDIA_OUTPUT_FAILED`) plus the terminal `UTTERANCE_FAILED`. TTS and Avatar failures receive their respective warning codes.
- The counters measure local Track `recv()` consumption, not browser decoded playback. Browser ICE and inbound media counters remain necessary acceptance evidence.

## Stop behavior

Stop cancels the current task, worker and preparation tasks; interrupts and clears media queues; stops Avatar/media; closes Tracks and Peers; sets `ENDED`; and emits `SESSION_STOPPING` then `SESSION_ENDED`. Worker, event, provider cleanup and Peer close operations have explicit timeouts. A bad Peer cannot keep Stop waiting indefinitely. Timeouts are logged as warnings; if the event publisher itself is unavailable, an `ENDED` event cannot be guaranteed externally even though local Session cleanup proceeds.

## Test results

| Run | Result |
| --- | --- |
| `PYTHONPATH=runtime python -m unittest discover -s runtime/tests -p 'test_*.py' -v` | 36 tests, OK, 20 skipped; system Python lacks aiortc and optional provider dependencies. |
| `RUN_WEBRTC_INTEGRATION=1 PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_*.py' -v` | 36 tests, OK, 7 unrelated provider opt-ins skipped. All 9 new deterministic regressions and 4 real aiortc tests passed. |

The deterministic regressions cover normal consumer, stopped audio, stopped video, healthy plus stalled Peer, interrupt during drain, Stop after drain failure with `SESSION_ENDED`, 300 short Utterances without queue growth, bounded Peer close, and a blocked old-generation enqueue race. The real aiortc test performs repeated drain, verifies counters, closes/reconnects a Peer in a new generation and evicts a stale Peer. This is local real WebRTC transport, not the deployed cross-host browser path.

## Remaining risk and recommendation

The production failure's exact Peer condition is unknown. No deployed browser, remote host, or one-hour workload was run in this repair stage. **Recommend a fresh one-hour browser-connected soak** with per-Peer diagnostics, ICE/inbound media evidence, zero unexpected failures, normal Stop, `SESSION_ENDED`, and Runtime Session cleanup. Do not close ISSUE-008 or mark Core MVP accepted before that run passes.
