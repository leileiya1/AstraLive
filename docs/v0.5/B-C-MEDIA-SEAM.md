# Agent B → C media integration handoff

Runtime pin: `cf43e2d3dd6a9223648eaced2526d13e0ccbf8e1`, pushed to `exp/v0.5-media-timeline`, based on `5a24478`. Final actual GPU-tested runtime file hashes are in [source.json](evidence/agent-b/real-gpu/ledger-soak-1/source.json), clean tested source `e2a8fa2`. This document adds no signature, enum, protocol or runtime change. C can introduce A then B into its own integration branch; B does not merge other branches or main.

`runtime/app/session.py`, `runtime/app/providers.py` and all `gpu_worker/**` are unchanged from B's baseline. Session orchestration remains C-owned. B's owned implementation files are media_timeline.py, media_fanout.py, bound_media.py, webrtc_media.py and rtmp_media.py. Frozen revision is `v0.5-frozen-1`; answer lane is `AUDIENCE_ANSWER`.

## Initialization and authority

Enable `ASTRALIVE_MEDIA_TIMELINE_V2_ENABLED=true` before constructing outputs. Default is false; F's `ASTRALIVE_MEDIA_TIMELINE_ENABLED` is an approved compatibility alias, and conflicting explicit values reject construction. Do not switch an existing sink in place.

```python
from runtime.app.media_timeline import MediaTimeline, TimedAudioChunk, TimedVideoFrame
from runtime.app.bound_media import BoundConsumptionMediaOutput
from runtime.app.media_fanout import FanoutMediaOutput

# journal_adapter is A/C's real authenticated durable adapter, not a test journal.
timeline = MediaTimeline(session_id, run_epoch, sample_rate=16000,
                         journal=journal_adapter)
fanout = FanoutMediaOutput([("webrtc", web_output), ("rtmp", rtmp_output)])
media = BoundConsumptionMediaOutput(fanout, avatar)
media.bind_timeline(timeline)     # delegates to fanout; before media.start()
```

The constructor starts at timelineEpoch1/sample0/revision0. It has no durable rehydration API; do not reconstruct a previously active run and call that recovery. An ambiguous old run needs A/C reconciliation/UNKNOWN. A new authorized run needs A's BEGIN_RUN/lease/Stop policy, not a client-provided higher runEpoch.

`TimelineJournal.record(operation, command, proof)` is the existing dependency seam and must return `{"durable": True}` only after authoritative transaction success. A/C validates complete frozen command envelope, authentication/ownership, lease, CAS, command sequence, reservation, TTL, immutable binding and persistent dedup. B's minimal local checks are not those authority checks. Serialize dataclasses/enums recursively; TimelinePosition's computed ptsUs must be included explicitly on a frozen wire DTO because dataclasses.asdict does not include properties. Do not change public signatures to carry a private adapter's arguments.

Operations currently sent to this journal: COMMIT_INTENT, COMMIT_INSTALLED, SUSPEND_REQUESTED, INVALIDATE_AFTER, BEGIN_EPOCH_PREPARED, BEGIN_EPOCH_ACTIVE and SEGMENT_COMPLETED. Map internal observation names into A's approved transactions/events; they are not additional public commandType values. COMMIT_INSTALLED durability ACK precedes local eligibility installation; missing ACK leaves media blocked and requires reconciliation. BEGIN_EPOCH_PREPARED must validate C/A's existing reservation, and BEGIN_EPOCH_ACTIVE must perform the activation CAS after B's fence. B never allocates a reservation.

## Generated → ready → commit: explicit integration gap

Frozen §3 requires complete immutable segment PCM/video descriptor, final marker, validated format/provenance and no sequence gaps before READY. B currently checks sampleCount>0, finalMarker=true, contentHash present and media identity/range; it does not generate assets, verify hashes against stored bytes or persist READY. C/A must implement and validate that readiness proof, fact/version binding and artifact lifetime before calling CommitSegment.

The real fixture [timeline_gpu_soak.py](../../runtime/tests/timeline_gpu_soak.py) lines140–180 is runnable and exercises B's actual APIs, typed native source mapping and both required sinks. However, its PCM is already known while SoulX video is generated incrementally AFTER commit. Its journal explicitly returns testDouble=true. Therefore its222 boundaries prove the B media seam, not the complete frozen generated→READY pipeline or A durability.

A strict precommit SoulX generator cannot simply run indefinitely behind an in-memory staging queue: the existing24-frame native credit window is bounded and credits also append published-pose history. B releases native credit only after an actual server sink consumes a frame. Precommit media is ineligible for those sinks, and a spool write is not their consumption proof. Complete long-segment speculative GPU video needs an evidenced provider/staging solution consistent with that protocol, or an approved F contract/protocol decision. Do not call PCM-only readiness complete video readiness, invent credit or silently change frozen semantics. This is an open integration dependency, separately from CCR-B-002's all-consumer-discard issue.

`SpeculativeMediaBuffer` is an optional C staging seam, not an installed Session generator: default1500ms PCM,38 frames at25fps,8MiB/frame. offer_audio/offer_video returning false requires producer backpressure; take_* returns media only after its committed identity/range is eligible. C may reference an external bounded spool for a complete segment, with explicit disk/retention/admission bounds. That alone does not resolve native precommit credit.

## Actual commit and required-sink completion calls

This media-side sketch assumes C already has a valid durable READY proof. `commit_command` is A's complete immutable frozen envelope, commandType=COMMIT_SEGMENT, current session/run/timeline, real segmentId and lane. Bind sink identities using the run's frozen required/optional policy; never promote an optional preview just because it exists. A WebRTC sink ID is the connected `peer.peer_id`; RTMP is `rtmp:<connection_incarnation>`. A reconnect creates a new identity and cannot silently replace a required sink on an existing segment.

```python
snapshot = timeline.CurrentCommittedPTS(session_id, run_epoch)
start = snapshot["committedExclusiveEnd"]  # TimelinePosition, not bare PTS
# Include immutable fact/version/provenance and artifact refs from C's READY proof.
descriptor = dict(validated_ready_descriptor)
descriptor.update(sampleCount=actual_source_sample_count,
                  utteranceId=utterance_id, contentHash=content_hash,
                  finalMarker=True, requiredSinks=frozen_required_sink_ids,
                  videoTiming={"fps": 25})
receipt = await timeline.CommitSegment(commit_command, attempt_id,
                                       business_generation_id, descriptor,
                                       start, snapshot["revision"])
identity = receipt["identity"]            # MediaIdentity dataclass
media.bind_attempt(identity, start)        # BEFORE native attempt submission
```

Optional descriptor workerEpoch and workerGenerationId must be supplied as a pair if used, and identify the actual native link/job. Business generationId is not Worker job ID, timelineEpoch or runEpoch. `bind_attempt` captures the current native source origin and rebases PCM/video to the committed run range. Binding an already generated native attempt with a later origin is not the tested path. For a previously generated immutable artifact replay, feed explicitly typed media with its own ranges into fanout, rather than pretending it is the current native attempt:

```python
# Bounded replay iterators are supplied by C's validated artifact adapter.
# Native generation/credit for creation of these artifacts is a separate open seam.
await fanout.push_audio(TimedAudioChunk(
    business_generation_id, sequence, pcm16, source_rate, 1, identity,
    absolute_start_sample, absolute_end_sample, timeline.sample_rate))
await fanout.push_video(TimedVideoFrame(
    business_generation_id, native_pts_us, width, height, rgb, identity,
    absolute_source_sample, timeline.sample_rate))
```

For the current incremental native test path, use avatar.stream_audio → avatar.push_audio → media.push_audio/media.push_video as in the fixture, then `await media.drain(business_generation_id)`. This drains media; it is not a standalone semantic completion proof. Queue admission, native EOF, drain or browser observation must not independently advance C's completion cursor.

```python
end = timeline.position(start.sampleIndex + descriptor["sampleCount"])
progress = timeline.CurrentCommittedPTS(session_id, run_epoch)
# Production adapter serializes the named sink/range snapshot and its evidence.
proof = await timeline.SegmentCompleted(identity, end, sink_receipts)
# C/A persists semantic cursor/facts/resume point from this proof, idempotently.
```

SegmentCompleted checks the internally observed contiguous audio AND video end for EVERY descriptor.requiredSinks entry before journalling. Caller-supplied sinkReceipts cannot fill a hole. `CurrentCommittedPTS()["perSinkConsumedExclusiveEnd"]` maps segment IDs to `(sinkId, mediaType)` tuple keys in Python; convert those keys explicitly for JSON/storage, preserving identities. Internal `observe_sink_progress` is called by successful WebRTC recv/RTMP completed pipe writes. There is no new public ObserveSinkProgress signature to call. WebRTC consumption and FFmpeg handoff are server-side evidence, never audienceAudible=true.

B does not schedule completion callbacks automatically: C drives SegmentCompleted after the terminal contiguous ranges are observed, under a bounded deadline. It returns SEGMENT_COMPLETED or BOUNDARY_SUSPENDED proof. C emits/persists its approved event/receipt projection and cursor; on missing/disconnected/ambiguous tail it follows explicit failure/UNKNOWN policy. Do not busy-loop or change requiredSinks to force completion.

## Natural suspend, epoch switch and Stop

1. C calls `await timeline.SuspendAtBoundary(suspend_command, boundary_segment_id, revision)`. The boundary segment must be the current committed exclusive end. This accepts a request and blocks later commits; it does not report completed interruption.
2. Finish that segment's required sink proof and call SegmentCompleted. Require event=BOUNDARY_SUSPENDED. Persist resume point/completed facts through A/C before planning cursor advances.
3. C/A durably prepares the next epoch reservation. Call `InvalidateAfter(invalidate_command, cut, reason, revision)`, then `BeginEpoch(begin_command, previous_epoch, previous_epoch+1, cut, reason)`. begin_command.timelineEpoch is NEW; cut still carries the OLD epoch. After activation use the returned new position or CurrentCommittedPTS for the next commit.
4. Cancel/fence the old native attempt with the next independently allocated business generation, retire output attempt bindings via media.interrupt, then commit AUDIENCE_ANSWER. After proven answer completion, C applies its next epoch/RESUME_BRIDGE/NARRATION policy.

InvalidateAfter accepts the committed end for natural cuts. It fences sinks and journals retained prefix/per-sink observations, but is not a full frozen receipt projector: invalidatedAttempts, residualInFlight ranges, receiptSeq/incarnation correlation and async per-sink ACK must be represented truthfully by C/A or a coordinated B addition. Existing proof says residual audience buffers are unobservable; do not invent empty residual buffers.

`timeline.fence_now(reason)` immediately seals the entire run without waiting on CUDA/journal; it is a local emergency Stop seam, not a durable Stop ACK. It cannot implement FORCE followed by resume inside the same run. FORCE inside a committed paragraph needs explicit partial/UNKNOWN evidence and agreed C/A disposition; current natural-cut API does not retract that prefix. Record/report this gap before any signature or semantic revision. ACK-loss/restart replay, durable cursor restore and product-switch cancellation are not complete in B.

## Acceptance and remaining work

B runtime unit checks176 passed/11 skipped; real final ledger run1806.81s,222 natural boundaries,222/222 waveform matches, zero stale marker in Chrome/RTMP, no backward/duplicate PTS. [Detailed comparisons, regressions, failures and rollback](AUDIO-MASTER-TIMELINE.md) remain authoritative. Default remains OFF. Neither these tests nor this integration sketch proves SQL lease authority, strict precommit complete video READY, FORCE partial semantics, product switching, crash continuity, live LLM/TTS, physical speaker or official-platform audience completion.
