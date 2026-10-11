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

Each sink has independent dispatch tasks, queues and clock. V2 BoundConsumptionMediaOutput uses exact video disposition and per-range audio observers, avoiding the legacy wait for every preview/RTMP admission join; a stalled preview does not hold the producer for the publishing sink. All-sink-full V2 dispatch waits at most500ms plus bounded grace, then retires that sink's stale item. An active frame receives Worker credit only after ANY actual sink consumed it. Existing service.py Credit also appends native published-pose history; therefore all-consumer drops cannot release that credit. They emit `FrameDiscardedWithoutCredit`, cancel/degrade the current native job through the existing path, and require a future clean generation. They never become sink-consumed proof or cacheable idle frames. Transparent all-consumer-drop recovery is an unapproved protocol extension, recorded as CCR-B-002. Disposition entries are bounded weak references and require the same live frame object; reused Python addresses cannot inherit consumed/drop receipts and RGB is not retained. Real-GPU trial `v2-short-1` exposed address-reuse false credits, was intentionally stopped, and is invalid evidence. `b19e537` fixes this with a deterministic regression; the isolated Worker was restarted to reset the invalid trial pose history. Earlier candidate test logs expecting discarded-frame credit are retained but superseded; those candidates had no actual GPU job and must not be released. Old Worker generation/epoch results cannot credit the replacement link. Completion requires ALL frozen required sinks, separately from Worker ANY-consumer credit.

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

C sequence: durable execution/ready descriptor → CommitSegment intent/install durable ACK → `output.bind_timeline(timeline)` before start, `BoundConsumptionMediaOutput.bind_attempt(identity, startPosition)` before submitting attempt → publish typed PCM/video → collect named contiguous audio/video progress → SegmentCompleted and C/A durable semantic cursor. Descriptor includes sampleCount, utteranceId, contentHash, finalMarker, requiredSinks and optional native Worker binding. A/C adapters must serialize dataclass proof fields before journal storage. Named WebRTC sink IDs are actual `peer.peer_id`; RTMP is `rtmp:<connectionIncarnation>`. C freezes those IDs on each commit, rather than passing a generic unmatched label. A required encoder reconnection requires explicit policy/reconciliation; it cannot silently transfer an unfinished proof to a different incarnation. No new public HTTP signature is introduced.

Suspend acceptance only records `SUSPEND_REQUESTED` and stops later commits. `BOUNDARY_SUSPENDED` arrives only after the committed paragraph's final contiguous sink proof. InvalidateAfter accepts only the committed exclusive end for a natural cut, fences old tail and records per-sink progress plus unobservable audience residual buffers. BeginEpoch preserves that committed prefix and requires exactly the reserved next epoch; it fences old pending media before activation. C then commits AUDIENCE_ANSWER, RESUME_BRIDGE and next NARRATION. An attached ledger suppresses uncommitted native idle jobs through the existing internal consumer gate and cancels waiting idle generation at drain; transport silence and one retained consumed image provide comfort without source/semantic advancement. RTMP retains only confirmed pipe-written imagery, excluding an invalidated in-flight write. Native EOF source padding outside the committed actual PCM range is ineligible; sink flush padding advances output PTS only to the actual semantic endpoint. The real-GPU ledger fixture exercises non-frame-aligned109369-sample utterances; its journal is explicitly a test double, not A durability. `fence_now()` is the synchronous emergency run-sealing Stop seam and does not wait for CUDA/journal; its local result is not a durable Stop ACK. FORCE within a run and product-switch authorization remain C/A policy, using their explicit partial UNKNOWN evidence; B does not silently retract committed prefixes or alter §5 signatures.

Progress is generated → queued → sink_consumed, with browser rendering/audibility separate. WebRTC recv proves server track consumption. Complete FFmpeg pipe write proves encoder handoff, not platform audience hearing. Contiguous holes, drops, disconnected required peers and ambiguous in-flight writes block SegmentCompleted. Reconnect does not silently weaken requiredSinks. An observer receipt cannot fill a missing server range.

CCR-B-001: task calls the flag `ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED`; F frozen-1 calls it `ASTRALIVE_MEDIA_TIMELINE_ENABLED`. User approved V2 primary, F-name alias; both absent=false; if explicitly inconsistent, construction raises. This is recorded for F acknowledgement; frozen docs themselves are not modified. B is authorized to develop independently, not to merge other branches.

## Real local A/B evidence

Evidence: [agent-b](evidence/agent-b/SHA256.json). Earlier trial manifests record baseline HEAD while testing an uncommitted B working tree; they do not identify a clean tested implementation commit. Final harness captures dirty state and source file hashes. Native installed Chrome headless, AudioContext analyser + requestVideoFrameCallback in one browser performance clock; FFmpeg localhost RTMP FLV + PyAV decode + ffprobe packet PTS. Fixture: synthetic 440Hz 80ms pulses with RGB markers every800ms. No real TTS/LLM, physical speaker loopback or platform viewer evidence. Sequential A→B order can bias warm-up and CPU/RAM. Parent-driver RSS/CPU includes harness/decoding; it is not full Runtime/system resource accounting. Compare raw evidence and failure logs, not only favorable runs.

Historical [v0.4 real acceptance](../v0.4/AGENT-B-REAL-ACCEPTANCE.md) used actual XiaoYa/SoulX and business comments: first PCM→GPU TALKING P50/P95/max1153.75/1473.06/1486.62ms; receipt→Chrome correlated AV2896.53/4176.80/6668.99ms; decoded onset difference reached213ms. Its20-audio/10-video-frame queue ceilings, no stalls and retained slow cases are baseline evidence. The synthetic v0.5 fixture below does not reproduce provider/business latency, so its tens-of-ms injection latency is not a measured improvement over those end-to-end seconds.

Absolute onset drift P50/P95/max, milliseconds:

| Run | Chrome baseline | Chrome V2 | RTMP baseline | RTMP V2 |
| --- | --- | --- | --- | --- |
| trial1, steady |38.2/100.3/148.8|12.9/92.8/127.2|627/637/637|29/40/40|
| steady2 |14.6/75.3/125|40.8/120.1/150.3|29/40/40|3/13/13|
| faults2, browser reconnect |19.7/125.6/154.2|18.8/96.9/137.3|37/77/77|16/32/32|
| reconnect3, both sink reconnect |13.8/120.2/131.2|26.7/97/118|48/72/72|11/35/35|
| candidate 9b55b16, steady |15.4/87.5/131.9|10.7/92/127.3|40/51/51|24/35/35|
| candidate 9b55b16, faults |19.5/92.2/123|21.5/85.2/120.7|40/80/80|5/16/16|

All paired Chrome rows above have20 markers; reconnect3 RTMP first encoder has15, later encoder reported separately. Candidate reconnect post-reconnect domain has only3 matched markers: baseline64/75/75ms, V224/35/35ms. Original n=0 analysis assumed markers restarted at1; a separately stored reanalysis pairs chronological equal-count onsets inside each encoder. Coverage loss at reconnect is retained. Packet PTS is audited per encoder domain. trial1 RTMP startup outlier is retained. steady2 regresses Chrome drift and first AV latency: baseline65.94/126.67/163.53ms versus V276.55/152.67/186.08ms; RSS132005888 versus141606912 bytes. These small samples do not establish P95 busy interaction or first-frame nonregression. Browser marker/onset correlation is not a lip-sync score.

Fault fixture includes 4 FORCE generations, old-generation marker4000 injection (not observed), 5 producer underruns80ms, 5 delayed videos250ms, Chrome peer reconnect, owned FFmpeg terminate/reconnect and normal Stop. Initial faults1 reconnect pairing had n=0: harness failure retained. Initial reconnect hangs/timeouts and reconnect2 drain warning are retained. reconnect3 uses explicit source sample ranges so intentionally lost audio does not corrupt later source mapping; queued reconnect tail is retired, not consumed. `normalStop=true` says process stopped cleanly, not all semantic segments completed. Full business Stop/FORCE/product switching needs C/A integration.

## Checks and remaining acceptance

Initial existing media tests35 passed4 skipped3 subtests. Existing opt-in WebRTC4 passed; Python3.14 aiortc teardown warning retained. Runtime final176 passed11 skipped40 subtests. New timeline28 passed, including mapping/44.1k cumulative rounding, stale epoch dequeue/in-flight injection, idempotency/CAS/ACK-loss fences, bounded PCM/speculation, underrun, late drops, reconnect clock wait and attempt retirement. Focused final regression43 passed. Frozen v1.1 contract validation passed. Relevant Worker CPU tests16 passed; broad Worker attempt16 failed9 passed because missing historical fixtures/assets and initially missing Torch, retained as nonacceptance evidence.

All7 fixed official files, total8162010707 bytes, are verified on Mac and GPU under user's explicit download instruction. Mac backup: `/Users/sapiece/Library/Caches/AstraLive/v05-agent-b/official-weights`; GPU lab: `/root/autodl-tmp/astralive-avatar-lab`. This later user authorization supersedes INTEGRATION-PLAN §2's no-weight-download gate for B's isolated test instance; it does not approve model/version/protocol changes. Base Python3.12.3/Torch2.8.0+cu128/CUDA12.8/ABItrue and FlashAttention2.8.3 are verified. Official Hugging Face download from Mac and its official CDN redirect on GPU are used because the GPU instance cannot reach huggingface.co; pinned Python dependencies use TUNA PyPI transport with unchanged constraints. Source import preflight passed; its TORCH_CUDA_ARCH_LIST warning is retained. GPU preflight, paired short A/B and two independent continuous30min real-GPU runs are complete below; their different source/scope pins are retained. Product switching/busy-interaction P95 and golden C/A durability remain untested. Default stays OFF; no broad release or end-to-end continuity PASS is claimed.

## Real GPU short A/B and continuous soak

RTX3080 10GB, fixed official Lite/source/environment, same prerecorded6.8355625s16k mono PCM repeated incrementally, no live LLM/TTS/business controller. Mac Runtime → SSH tunnel → authenticated isolated GPU Worker; native installed Chrome headless and local FFmpeg RTMP recording. Each valid run is one Worker connection and one browser peer. FORCE cancels every fourth clip after3s; normal clips drain before continuing. Required A/C durable continuity and product-switch business policy are not simulated as success.

Evidence: [real-gpu](evidence/agent-b/real-gpu). Baseline clean source `738f152`; corrected V2 short clean source `b19e537`; continuous soak clean candidate `3dff41e77d65ee4aa3100bbc1f5dc71f5bd1fc8c`. Media implementation file hashes accompany each run. The baseline flag-off path is unchanged by the frame-reference fix. Worker was explicitly restarted between the invalid V2 trial and corrected short run; startup/runtime warnings, stopped trial and partial waveform coverage remain in evidence.

| Metric | Baseline short | Corrected V2 short |
| --- | --- | --- |
| Continuous playback seconds |127.24|127.30|
| Speech cycles / FORCE |18 /4|18 /4|
| Real GPU enqueued frames / fallback |2619 /0|2616 /0|
| Chrome RTC estimated playout difference P50/P95/max ms |5 /36 /44|8 /38 /48|
| Chrome heuristic source-adjusted onset P50/P95/max ms |10.76 /101.44 /101.44|12.74 /118.74 /118.74|
| RTMP verified content onset P50/P95/max ms |19.63 /39.63 /39.63|19.69 /59.69 /59.69|
| RTMP waveform verified / expected speech markers |17 /18|18 /18|
| First PCM→first GPU frame P50/P95/max ms |924.46 /1208.29 /1208.29|914.71 /1437.36 /1437.36|
| Driver CPU seconds over sampled120s |38.93|37.24|
| Driver peak RSS bytes |204357632|200933376|
| WebRTC audio/video queue peaks ms |220 /200|160 /200|
| Video fence retirements / enqueued |11 /2623 (0.42%)|13 /2620 (0.50%)|
| Audio/video backward or duplicate packet PTS |0 /0|0 /0|
| Full strict FFmpeg decode / normal Stop |exit0 /true|exit0 /true|

This pair does not demonstrate universal improvement: V2 has higher short-run first-frame P95 and AV percentiles. Busy-interaction nonregression remains unproved. RSS is the driver process, excluding Chrome/FFmpeg/GPU Worker; its samples are not total deployment memory. Baseline missing waveform marker16 has correlation0.549 and is excluded explicitly, not counted as a passed AV sample. V2 all18 correlations pass the fixed0.8 threshold.

`timeline_gpu_audit.py` correlates the first500ms known PCM against decoded16k AAC in a ±2s search around each native speech marker, identifying source sample zero. It records every expected/observed/verified marker and all signed drift values; uncovered or unverified markers remain gaps. It measures the correspondence of source PCM and instrumented image onset, not facial lip quality. Chrome's nearest threshold onset pairing is heuristic and recorded separately; RTC estimatedPlayoutTimestamp compares receiver statistics, not matched content or physical speaker audibility. Neither substitutes for real audience or official-platform receipts.

Both continuous runs finished and passed their stated media checks, each using one uninterrupted Worker connection and Chrome peer. They are two independent30min runs, not one60min acceptance. The second run pins final runtime source `e2a8fa20a804fb03500ef29d751ed98a48f21f78`; subsequent review053e557 identified a control-ordering correction: local blocked installation now precedes COMMIT_INSTALLED journalling. That increment has separate tests; the historical GPU recordings are not a long-run test of this changed ordering.

| Metric | V2 clock soak, 3dff41e | Ledger-bound soak, e2a8fa2 |
| --- | --- | --- |
| Continuous seconds |1807.83|1806.81|
| Speech cycles / FORCE / completed semantic segments |260 /65 /not bound|222 /0 /222|
| GPU frames / fallback |36885 /0|37962 /0|
| Chrome RTC estimated drift P50/P95/max ms |4 /11 /49|6 /13 /48|
| Chrome heuristic onset P50/P95/max ms |24.96 /71.66 /99.94|14.76 /36.06 /89.64|
| RTMP verified content drift P50/P95/max ms |19.69 /59.69 /59.69|19.69 /19.69 /39.69|
| RTMP waveform coverage |257 /260|222 /222|
| First PCM→GPU frame P50/P95/max ms |924.85 /1458.95 /1529.41|890.89 /963.40 /1143.28|
| WebRTC audio/video queue peaks ms |160 /200|160 /160|
| Sampled RTMP audio/video peaks ms |160 /160|160 /160|
| Late video drops / peer stalls / evictions |0 /0 /0|0 /0 /0|
| Driver CPU seconds, sampled1800s |579.16|584.28|
| Driver RSS first/peak/last bytes |163151872 /226230272 /225984512|133120000 /218054656 /217923584|
| Worker RSS first/peak/last bytes |3226804224 /3292798976 /3292786688|3236179968 /3299151872 /3237265408|
| Worker sampled CPU seconds |1515.42|1335.50|
| Worker audio queue samples / video frames peak |16960 /24|16960 /24|
| GPU reserved / device-used peak bytes |5731516416 /6038749184|5731516416 /6038749184|
| RTMP video/audio packets |45242 /84829|45215 /84779|
| Backward or duplicate PTS / strict decode / normal Stop |0 /exit0 /true|0 /exit0 /true|

The clock soak retains three unverified waveform markers48/120/432. Its verified percentiles meet the proposed150ms gate, but the coverage gap prevents a universal content-sync PASS. There is no confirmed severe persistent mismatch in the observed evidence. Driver RSS grows during both runs; these measurements do not establish leak-free operation. Different FORCE and silence patterns explain different workloads, so the two long-run resource totals are not a paired A/B improvement claim.

The final ledger fixture rotates NARRATION → AUDIENCE_ANSWER → RESUME_BRIDGE, keeps runEpoch1, advances timelineEpoch1–222, and independently advances business generation1–1548 by7. Native job IDs and Worker epoch remain separate. It completes222 Suspend/Invalidate/BeginEpoch boundaries through B's frozen methods, deliberately crosses the128-entry ledger cap, and injects222 old-epoch frames using the current envelope generation. Neither Chrome nor RTMP sees stale marker4095. All four required server sink ranges end at actual PCM source samples:222×109369=24279918, with no accumulated EOF padding drift. At the final WebRTC snapshot75924 audio and37962 video frames are enqueued and consumed, with0 unexpected drops. The script's journal is a TEST_DOUBLE: this is B seam/consumption evidence, not SQL durability, real audience interruption, product switching, or A/C golden continuity acceptance.

[Complete ledger receipts and scope](evidence/agent-b/real-gpu/ledger-soak-1/receipt-audit.json), [recording packet checks](evidence/agent-b/real-gpu/ledger-soak-1/summary.json), [content coverage](evidence/agent-b/real-gpu/ledger-soak-1/content-audit.json), and [resource samples](evidence/agent-b/real-gpu/ledger-soak-1/resources.json) are archived with raw compressed logs. Start/middle/end MP4 excerpts are review aids. Complete recordings, including the invalid trial, persist outside Git under `/Users/sapiece/Library/Caches/AstraLive/v05-agent-b/runs/`; each recording.json stores size, SHA256 and absolute path. They are not replaced by excerpts.

After normal Stop, the isolated Worker remains READY/UP with activeGenerationId=null, zero queued media, the same Worker epoch and process5213. Test clients and owned forwarding are closed; the paid cloud instance is left running under the user's control. No GPU protocol, validated source or shared service was changed.

## Run and rollback

```bash
PYTHONPATH=runtime:. python -m pytest runtime/tests/test_media_timeline.py
PYTHONPATH=runtime:. python runtime/tests/timeline_media_benchmark.py --output /tmp/unique-ab-dir
PYTHONPATH=runtime:. python runtime/tests/timeline_media_benchmark.py --output /tmp/unique-fault-dir --faults
# Requires the pinned real Worker, private token file, SSH forwarding and installed Chrome.
PYTHONPATH=runtime:. python runtime/tests/timeline_gpu_soak.py --output /tmp/unique-gpu-run \
  --token-file /path/to/private-worker-token --port 18087 --wave /path/to/short_10s_16k_mono.wav \
  --duration 1800 --v2 --ledger
PYTHONPATH=runtime:. python runtime/tests/timeline_gpu_audit.py --directory /tmp/unique-gpu-run \
  --wave /path/to/short_10s_16k_mono.wav
# On the user's GPU host; reuses verified models/environment, no new download:
/root/autodl-tmp/astralive-v05-b-worker/bin/astralive-worker status
/root/autodl-tmp/astralive-v05-b-worker/bin/astralive-worker start
/root/autodl-tmp/astralive-v05-b-worker/bin/astralive-worker probe
```

Output directories are unique; preserve FLV, raw JSON, driver logs and hashes. Reset/restart the owned Runtime with both flags false (or unset); this restores original paths, buffers and clocks. Do not toggle the flag on a running sink. Finish or explicitly fence the active attempt through C first; transmitted audio cannot be recalled. Close owned test clients, receiver processes and SSH tunnel after tests; leave the user's isolated Worker READY and idle for reuse. To roll back its lifecycle, use `/root/autodl-tmp/astralive-v05-b-worker/bin/astralive-worker stop`; retain verified weights/environment for cached restart. Never shut down the user's GPU instance, rotate shared credentials or merge A/C/F branches as rollback.


## Post-acceptance F review: local installation order

F review053e557 and C requested an existing-contract correction. CommitSegment now installs its local immutable ledger entry while blocked BEFORE journalling COMMIT_INSTALLED. Durable installed ACK and final fence validation are required before advancing committedExclusiveEnd/revision or opening eligibility. ACK loss, cancellation, or Stop during the installed ACK retains the entry as blocked/UNKNOWN with the previous public cursor; retry cannot manufacture a committed receipt. Missing authoritative lease/authority validation remains an A adapter failure, not a B in-memory fallback. The frozen API and default-off media paths are unchanged. [C handoff](B-C-MEDIA-SEAM.md) includes the exact sequence and A's canonical receipt adapter.

Targeted ordering regressions31 passed; full Runtime179 passed/11 skipped/40 subtests passed. The final full Runtime result is stored separately in [install-order-runtime.log](evidence/agent-b/install-order-runtime.log). No additional30min GPU run was performed for this control-only increment, and the prior long recordings retain their original source hashes. No strict precommit SoulX READY or early-Credit semantics are accepted by this correction.
