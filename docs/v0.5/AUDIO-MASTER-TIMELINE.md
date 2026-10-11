# Audio-Master MediaTimeline experiment — Agent B

Status: experimental, default OFF. Frozen interface revision `v0.5-frozen-1`; implementation baseline `5a24478126211cbcde5a9565d0c6063748426527` (docs-only descendant of `cf6540bdcc788c037929836480812dfaa78362a2`). This is a media implementation and C integration seam, not durable end-to-end v0.5 continuity acceptance. No session orchestration, Go schema, SoulX binary protocol or validated GPU code is changed.

## Clock and identity

`MediaIdentity` carries sessionId, runEpoch, timelineEpoch, generationId, segmentId, utteranceId, lane and optional paired workerEpoch/workerGenerationId. runEpoch fences a whole run; timelineEpoch changes at semantic transitions within it; generationId identifies the business media attempt; Worker epoch and native job generation identify a connection/job below that attempt. They are separate fields. Lanes are the frozen `NARRATION`, `AUDIENCE_ANSWER`, `RESUME_BRIDGE`, `OPERATOR`, `SYSTEM`.

The semantic clock is source audio samples. `TimelinePosition` maps an absolute sample cursor using integer floor; differences are computed from absolute endpoints, never accumulated rounded packet deltas. At 16kHz, 640 samples = 40ms = 1920 ticks at WebRTC audio 48kHz = 3600 ticks at video 90kHz. Different RTP tracks retain their own rates. `RationalResampler` maintains cumulative input/output counts across arbitrary chunks; PCM interpolation has a bounded final edge, not an unbounded deferred buffer. Padding counts as output samples but advances the source watermark only to the actual segment end. A rate change needs a fence/reset.

Each WebRTC peer and RTMP encoder owns its own AudioMasterClock. Successful track recv / completed pipe writes advance output sample time, including controlled underrun silence. The semantic source cursor advances only when real source PCM is consumed. Video selects by that source cursor: early frames wait; frames >150ms late retire; gaps hold the latest frame/idle image. It never queues extra audio to catch video up. Video ticks follow audio output progress. Idle/underrun ticks have monotone transport PTS; they do not invent a semantic narration completion.

WebRTC reconnect creates a new peer clock at the current source origin. Same peer and same run do not reset RTP PTS on generation/epoch changes. FFmpeg reconnect creates a new encoder/mux clock domain, recorded as `connectionIncarnation`; queued unknown tail is discarded and cannot be credited as consumed. The video wait exits when its encoder incarnation changes. RTP/RTCP clock mapping, browser jitter buffer, decoder and device latency still exist. Server PTS is not a claim of zero audience AV error.

## Buffers and rollback boundaries

Flag-off retains the original 400ms fanout/WebRTC queues, independent audio/video clocks and original RTMP clocks. V2 splits PCM into <=20ms packets before fanout admission; fanout queues remain 400ms per sink. Sink audio/video physical caps are 800ms, with an audio interarrival EMA target of 320–800ms. Shrinking a target applies backpressure; it does not truncate queued PCM. The Python dispatch + sink ceiling is therefore about 1200ms per sink plus one in-flight packet/frame and <=20ms pending PCM. FFmpeg's existing bounded input queues, OS pipes and browser/device queues are additional distinct buffers; 320ms is not a total audience latency guarantee.

`BufferPolicy` defaults: committed target 320ms, interruptible cap 800ms, speculative cap 1500ms. The commit ledger defines irrevocable semantic ranges; target duration does not by itself prefill 320ms. `SpeculativeMediaBuffer` is a C-facing bounded staging seam (1500ms PCM, ceil(fps*1.5) frames, <=8MiB/frame); `offer=False` requires upstream backpressure. Precommit media is never sink eligible. This staging seam is not wired into Session; C owns generation admission. GPU's existing 32000-sample prefetch, 24-frame credit and protocol remain intact.

A semantic commit can span a longer paragraph; bounded *materialized queues* limit memory while range metadata covers the paragraph. Local ledger and replay cache are capped at128, attempt bindings8 and disposition maps128. Only journalled completed ledger entries may be evicted. Successful drain retires attempt bindings; fencing clears them. Warnings should be drained through the existing warning interface.

Each sink has independent dispatch tasks, queues and clock. All-sink-full V2 dispatch waits at most500ms plus bounded grace, then retires that sink's stale item. Active video retirement may release Worker flow credit as `FrameRetiredForCredit`; it is never a sink-consumed proof or cacheable idle frame. Old Worker generation/epoch results cannot credit the replacement link. Completion requires ALL frozen required sinks, separately from Worker ANY-consumer credit.

## Agent C interface ACK and control/media/receipt boundaries

B ACKs §5 signatures unchanged:

```python
await timeline.SuspendAtBoundary(command, boundarySegmentId, expectedRevision)
await timeline.InvalidateAfter(command, cutPosition, reason, expectedRevision)
await timeline.BeginEpoch(command, expectedPreviousEpoch, newEpoch, originPosition, reason)
await timeline.CommitSegment(command, attemptId, generationId, descriptor, startPosition, expectedRevision)
timeline.CurrentCommittedPTS(sessionId, runEpoch)
await timeline.SegmentCompleted(identity, finalPosition, sinkReceipts)
```

A/C supplies `TimelineJournal.record(operation, command, proof)` with durable ACK, authentication, binding/lease checks, authoritative CAS, reservation validation, persistent command dedup and reconciliation. Missing/non-durable journal fails closed; memory is not an SQL fallback. Test journals explicitly identify themselves as test doubles. `BEGIN_EPOCH_PREPARED` validates the reserved token and `BEGIN_EPOCH_ACTIVE` activates it. B does not issue reservations or trust client epoch/authority fields alone. The bounded local retry cache complements, rather than replaces, A's durable command identity.

C sequence: durable execution/ready descriptor → CommitSegment intent/install durable ACK → `output.bind_timeline(timeline)` before start, `BoundConsumptionMediaOutput.bind_attempt(identity, startPosition)` before submitting attempt → publish typed PCM/video → collect named contiguous audio/video progress → SegmentCompleted and C/A durable semantic cursor. Descriptor includes sampleCount, utteranceId, contentHash, finalMarker, requiredSinks and optional native Worker binding. A/C adapters must serialize dataclass proof fields before journal storage. No new public HTTP signature is introduced.

Suspend acceptance only records `SUSPEND_REQUESTED` and stops later commits. `BOUNDARY_SUSPENDED` arrives only after the committed paragraph's final contiguous sink proof. InvalidateAfter accepts only the committed exclusive end for a natural cut, fences old tail and records per-sink progress plus unobservable audience residual buffers. BeginEpoch preserves that committed prefix and requires exactly the reserved next epoch; it fences old pending media before activation. C then commits AUDIENCE_ANSWER, RESUME_BRIDGE and next NARRATION. `fence_now()` is the synchronous emergency run-sealing Stop seam and does not wait for CUDA/journal; its local result is not a durable Stop ACK. FORCE within a run and product-switch authorization remain C/A policy, using their explicit partial UNKNOWN evidence; B does not silently retract committed prefixes or alter §5 signatures.

Progress is generated → queued → sink_consumed, with browser rendering/audibility separate. WebRTC recv proves server track consumption. Complete FFmpeg pipe write proves encoder handoff, not platform audience hearing. Contiguous holes, drops, disconnected required peers and ambiguous in-flight writes block SegmentCompleted. Reconnect does not silently weaken requiredSinks. An observer receipt cannot fill a missing server range.

CCR-B-001: task calls the flag `ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED`; F frozen-1 calls it `ASTRALIVE_MEDIA_TIMELINE_ENABLED`. User approved V2 primary, F-name alias; both absent=false; if explicitly inconsistent, construction raises. This is recorded for F acknowledgement; frozen docs themselves are not modified. B is authorized to develop independently, not to merge other branches.

## Real local A/B evidence

Evidence: [agent-b](evidence/agent-b/SHA256.json). Earlier trial manifests record baseline HEAD while testing an uncommitted B working tree; they do not identify a clean tested implementation commit. Final harness captures dirty state and source file hashes. Native installed Chrome headless, AudioContext analyser + requestVideoFrameCallback in one browser performance clock; FFmpeg localhost RTMP FLV + PyAV decode + ffprobe packet PTS. Fixture: synthetic 440Hz 80ms pulses with RGB markers every800ms. No real TTS/LLM, physical speaker loopback or platform viewer evidence. Sequential A→B order can bias warm-up and CPU/RAM. Parent-driver RSS/CPU includes harness/decoding; it is not full Runtime/system resource accounting. Compare raw evidence and failure logs, not only favorable runs.

Absolute onset drift P50/P95/max, milliseconds:

| Run | Chrome baseline | Chrome V2 | RTMP baseline | RTMP V2 |
| --- | --- | --- | --- | --- |
| trial1, steady |38.2/100.3/148.8|12.9/92.8/127.2|627/637/637|29/40/40|
| steady2 |14.6/75.3/125|40.8/120.1/150.3|29/40/40|3/13/13|
| faults2, browser reconnect |19.7/125.6/154.2|18.8/96.9/137.3|37/77/77|16/32/32|
| reconnect3, both sink reconnect |13.8/120.2/131.2|26.7/97/118|48/72/72|11/35/35|

All paired Chrome rows above have20 markers; reconnect3 RTMP first encoder has15, later encoder reported separately. Packet PTS is audited per encoder domain. trial1 RTMP startup outlier is retained. steady2 regresses Chrome drift and first AV latency: baseline65.94/126.67/163.53ms versus V276.55/152.67/186.08ms; RSS132005888 versus141606912 bytes. These small samples do not establish P95 busy interaction or first-frame nonregression. Browser marker/onset correlation is not a lip-sync score.

Fault fixture includes 4 FORCE generations, old-generation marker4000 injection (not observed), 5 producer underruns80ms, 5 delayed videos250ms, Chrome peer reconnect, owned FFmpeg terminate/reconnect and normal Stop. Initial faults1 reconnect pairing had n=0: harness failure retained. Initial reconnect hangs/timeouts and reconnect2 drain warning are retained. reconnect3 uses explicit source sample ranges so intentionally lost audio does not corrupt later source mapping; queued reconnect tail is retired, not consumed. `normalStop=true` says process stopped cleanly, not all semantic segments completed. Full business Stop/FORCE/product switching needs C/A integration.

## Checks and remaining acceptance

Initial existing media tests35 passed4 skipped3 subtests. Existing opt-in WebRTC4 passed; Python3.14 aiortc teardown warning retained. Runtime final171 passed11 skipped40 subtests. New timeline23 passed, including mapping/44.1k cumulative rounding, stale epoch dequeue/in-flight injection, idempotency/CAS/ACK-loss fences, bounded PCM/speculation, underrun, late drops, reconnect clock wait and attempt retirement. Focused regression40 passed before final additions. Frozen v1.1 contract validation passed. Relevant Worker CPU tests16 passed; broad Worker attempt16 failed9 passed because missing historical fixtures/assets and initially missing Torch, retained as nonacceptance evidence.

Official fixed weights + independent RTX3080 environment are being provisioned under user's explicit download instruction. GPU preflight, short run, continuous30–60min run, checkpoints, normal Stop and cleanup are required before real GPU acceptance. Product switching/busy-interaction P95 and golden C/A durability remain untested. Default stays OFF; no broad release or end-to-end continuity PASS is claimed.

## Run and rollback

```bash
PYTHONPATH=runtime:. python -m pytest runtime/tests/test_media_timeline.py
PYTHONPATH=runtime:. python runtime/tests/timeline_media_benchmark.py --output /tmp/unique-ab-dir
PYTHONPATH=runtime:. python runtime/tests/timeline_media_benchmark.py --output /tmp/unique-fault-dir --faults
```

Output directories are unique; preserve FLV, raw JSON, driver logs and hashes. Reset/restart the owned Runtime with both flags false (or unset); this restores original paths, buffers and clocks. Do not toggle the flag on a running sink. Finish or explicitly fence the active attempt through C first; transmitted audio cannot be recalled. Stop the isolated B Worker/tunnel after tests; retain verified weights/environment for cached restart. Never shut down the user's GPU instance, rotate shared credentials or merge A/C/F branches as rollback.
