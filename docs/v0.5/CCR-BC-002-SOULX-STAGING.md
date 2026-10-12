# CCR-BC-002 — negotiated immutable SoulX staging

Revision: `staging-contract-1-draft`, 2026-10-12. **User-approved direction; detailed owner review pending; NOT IMPLEMENTED; default OFF.** This additive document does not change the bytes or receipt semantics of `v0.5-frozen-1`. F is the final contract/merge owner. The user approved the concrete direction after reviewing [B's diagnostic/proposal](SOULX-SAFE-STAGING-PROPOSAL.md). Freeze this revision only after A/B/C and a named Worker implementation owner acknowledge it. No implementation may invent an alternative DTO or weaken READY.

## 1. Boundary and ownership

This is Python Runtime→GPU Worker TCP. D's Go→Python HTTP TCP/UDS and A's Python→Go authenticated journal are separate channels. QUIC is optional and not a dependency. The original TCP1.1 streaming client, framing, authentication, Credit/pose semantics and cancellation remain unchanged and testable. No auto downgrade of a selected SoulX provider to Lightweight2D, no early legacy Credit, no fake sink consumption.

| Owner | Files/responsibility | Shared change process |
| --- | --- | --- |
| A | Existing journal, durable attempt binding, commit installation/receipt references, UNKNOWN/retry audit | Review proof references; no competing migrations. New durable field needs A-owned migration, not arbitrary JSON status |
| B | Timeline installation, required-sink contiguous watermarks, sample/frame mapping | Review before implementing sink-to-pose mapping; never equate OR flow-control credit with all-required completion |
| C | Immutable PCM/video staging orchestration, command identity, cancellation, exact provider identity | Runtime staging adapter only; Session changes must be separately scoped and reviewed |
| Worker owner, to be assigned | `gpu_worker/service.py`, new owned staging protocol/controller, bounded original RGB retention and native safe-boundary signal | No model algorithm change or edits to copied validated paths without separate reviewed justification |
| D | Existing local transport/auth compatibility | No changes required by this protocol |
| F | This contract/schema, independent gates/evidence and final merge | Records exact owner ACKs and pins, never claims inference from a synthetic probe |

Implementation is gated until the Worker owner is assigned; E's QUIC role alone does not authorize rewriting native staging. Test doubles may prove control behavior but not GPU visuals or natural narration.

## 2. Negotiation and authentication

Keep the existing 8-byte network-order uint32 `(header_length,payload_length)`, UTF-8 JSON object header <=16384 bytes and payload <=2097152 bytes. Existing 1.1 authentication is sent exactly as before. Staging uses a distinct, explicitly selected authenticated connection:

```json
{"type":"Auth","protocol_version":1,"internal_version":"1.2","session_id":"session_example","token":"<private token>","requested_capabilities":["immutable_segment_staging_v1"]}
```

The token is transmitted privately and must never enter artifacts. Worker validates existing Session/Worker lease and asset rules before advertising `GPU_WORKER_READY` with `internal_version="1.2"`, `selected_capabilities=["immutable_segment_staging_v1"]`, existing asset/model/cache provenance, `worker_epoch`, `highest_generation_id` (0 when unused), and `staging_limits` from §5. Requested/selected capability sets must exactly match this initial singleton. Unsupported version/capability/auth fails closed; no staging message on 1.1, no automatic second connection/replay after ambiguous authentication or generation. Staging connection has no idle or legacy streaming generations.

Worker process keeps its global high watermark across connections. New staging `worker_generation_id` is a JSON-safe integer 1..9007199254740991 strictly greater than the authenticated Ready watermark. Worker reserves it atomically with StageBegin. Collision rejects and requires a fresh status/explicit new attempt before media input; overflow requires Worker retirement. Wall-time allocation is not accepted as proof. Original 1.1 int<2^63 allocation semantics remain unchanged; a process whose legacy high watermark is outside the new safe range cannot negotiate staging until a new incarnation.

## 3. Complete immutable identity

Every post-Auth message carries top-level `session_id` and `worker_epoch` matching its authenticated connection. Every attempt message also carries the same `identity` object; no abbreviated generation-only ACK:

```json
{"sessionId":"s","runEpoch":1,"timelineEpoch":1,"generationId":1,"narrationId":"n","beatId":"b","segmentId":"seg","interactionTurnId":null,"utteranceId":"u","commandId":"cmd","traceId":"trace","attemptId":"attempt","stageId":"stage","lane":"NARRATION","workerRef":"worker","workerEpoch":"opaque-uuid","workerGenerationId":1}
```

Business epochs/generation use the frozen safe-integer bounds and comparisons. IDs are opaque case-sensitive strings; stageId is a Runtime-created unique artifact lease ID, not authority. All identities and content fingerprints are immutable. Initial support permits NARRATION/AUDIENCE_ANSWER/RESUME_BRIDGE. `interactionTurnId` is null only for narration; narration/beat association for answer/bridge records the captured resume beat. Commands, authorization and ownership are existing A/C contracts, not new public endpoints. Worker binds the first verified identity on an authenticated StageBegin and rejects any mismatch afterward; Runtime rechecks active ownership/lease at journal/commit/sink boundaries. Worker authentication is not independently a proof that A's durable run is still authorized.

## 4. State and wire operations

One attempt at a time per exclusive authenticated Worker lease, including produced/committed artifacts awaiting release. Stage state is private transport state, never a replacement for frozen command receipts:

`STAGING → PRODUCED → COMMIT_ARMED → RELEASED`

Cancellation from any nonterminal state immediately fences publication/pose eligibility, then reaches `RELEASED` only after native safe-boundary cleanup. Connection loss, contradictory proof, or lost final ACK means Runtime `UNKNOWN`, not an automatic new attempt. New StageBegin is forbidden until terminal release is known, or the prior Worker incarnation has been explicitly retired and A/C reconcile its media tail.

| Message | Direction / payload | Meaning and required fields beyond identity |
| --- | --- | --- |
| StageBegin | Runtime→Worker / empty | `request_fingerprint`, `cache_id`, `pcm_sha256`, `original_samples`, `pad_samples`, `source_samples`, source format/fps/geometry, `lease_ms`, `limits_revision`; reserves bounded attempt only after A STARTED attempt binding |
| StageBegun | Worker→Runtime / empty | `request_fingerprint`, `audio_credit_samples`, chosen limits and current pose-history digest; no generating/READY/committed claim |
| StageAudio | Runtime→Worker / PCM bytes | `chunk_sequence`, `first_sample_index`, `sample_count`, `final_chunk`, `chunk_sha256`; same source PCM budget/contiguity as legacy AudioChunk, but no legacy message intermixing |
| StageAudioAccepted | Worker→Runtime / empty | exact chunk sequence/hash, `accepted`, remaining `audio_credit_samples`; capacity evidence only, never sink or pose evidence |
| StageVideo | Worker→Runtime / H264 bytes | `frame_sequence`, `pts_us`, `duration_us`, `sample_start`, `sample_end`, `codec`, width/height/keyframe, `payload_sha256`, `native_rgb_sha256`, source provenance |
| StageReceived | Runtime→Worker / empty | one `frame_sequence`, matching H264/native hashes, `storage_receipt_id`; sent only after validated immutable Runtime storage. Releases only a network-window slot |
| StageReceivedAck | Worker→Runtime / empty | exact same frame/hash/storage receipt; no original RGB release or consumed pose update |
| StageProduced | Worker→Runtime / empty | §6 complete descriptor. Generated EOF/final proof independent of consumption; retained RGB remains private |
| StageCommit | Runtime→Worker / empty | descriptor hash, A durable commit identity/ref, B COMMIT_INSTALLED receipt ref and output mapping/required sinks from §7; admits pose proof, never commits pose itself |
| StageCommitAck | Worker→Runtime / empty | matching descriptor/proof fingerprint; state COMMIT_ARMED only |
| StagePoseConsumed | Runtime→Worker / empty | §7 watermark and proof references; changes only the contiguous acknowledged original RGB prefix |
| StagePoseConsumedAck | Worker→Runtime / empty | exact watermark/proof fingerprint, updated pose digest and applied prefix; idempotent duplicate returns prior result |
| StageCancel | Runtime→Worker / empty | stable `control_id`, reason STOP/FORCE/EXPIRED/STALE/FAILED; immediate publication fence, cancels unconsumed eligibility |
| StageFenced | Worker→Runtime / empty | same control ID, `publication_fenced=true`, frozen applied pose prefix; **not** a safe cleanup/release ACK |
| StageRelease | Runtime→Worker / empty | control ID, reason COMPLETE/CANCELLED, latest confirmed pose watermark/proof fingerprint; requests terminal storage/native cleanup |
| StageReleased | Worker→Runtime / empty | matching control ID, `native_safe_boundary=true`, retained pose digest/prefix and `retained_artifact_bytes=0`; only definitive successful cleanup ACK |
| StageStatus | Runtime→Worker / empty | stable `nonce`; read-only current-attempt inquiry, never generation replay |
| StageStatusResult | Worker→Runtime / empty | nonce, state, descriptor hash if produced, received/applied pose watermarks, bounded resource counters, lease age, cancellation/release knowledge |
| StageError | Worker→Runtime / empty | static `code`, operation/control ID, `publication_fenced`, state; omit secrets/text/raw paths; §9 disposition |

Zero payload for all control/descriptor/ACK operations. StageAudio alone carries PCM; StageVideo alone carries H264. Legacy Health remains allowed with existing semantics. Duplicate same operation/identity/hash is idempotent; changed hash under the same identity is CONFLICT and fences the attempt. A duplicate may return prior ACK without granting capacity twice. Gapped/future ACKs never spend capacity or append pose. Replies must be serialized with cancellation so no post-fence video/final/pose side effect escapes. Same-process StageStatus on a fresh authenticated lease cannot recover a disconnected generation automatically; explicit A/C disposition is required.

## 5. Initial hard limits and source clock

`limits_revision="staging-short-1"`. These are conservative first-test caps, not a measured performance claim or an amendment of C's ordinary 2–5s planning/8s hard limit. C must replan at a semantic boundary or explicitly reject a longer segment; never silently split into arbitrary 160ms units. The capability initially supports only captured source PCM16kHz mono s16le, 25fps, 512×512 RGB24/H264. Artifact source first sample is 0. Output timeline is separately mapped after commit.

| Budget | Hard initial value / enforcement |
| --- | --- |
| source duration | 1..30720 samples including pad, <=1.92s (two native inference blocks) |
| original/pad | original_samples>0; pad_samples=(-original_samples)%640; source_samples=original+pad; explicit zero padding with provenance |
| video | source_samples/640 whole frames, <=48; sequence0..count−1, source interval `[seq*640,(seq+1)*640)`, PTS=seq*40000us, duration40000us |
| PCM input queue | existing <=32000 samples; each chunk within payload/queue limit, no audio after final; exact PCM length2*sample_count |
| video pipeline/network | existing <=24 queued native frames; <=4 network frames awaiting StageReceived; no capacity recovery via pose ACK |
| Worker original RGB retention | <=48MiB including copied artifact frames, separate nine-frame consumed pose history <=8MiB; cannot free unconsumed RGB on receive ACK |
| Runtime artifact | <=96MiB total immutable PCM/H264/decoded data plus <=24MiB transient processing, no unbounded frame copies |
| Worker additional host accounting | <=256MiB attempt buffers including native pipeline/output/encoding copies; report observed peak separately from resident model |
| GPU accounting | report preattempt baseline and incremental allocated/reserved peaks; reject before READY when incremental allocated exceeds512MiB. This monitor cannot preempt a CUDA allocation/kernel or guarantee instantaneous GPU usage; no budget compliance claim before real measurement |
| lease | <=60000ms fixed monotonic total TTL; Runtime requests no longer than conservative active A lease/policy. No renewal in first revision. expiry immediately fences; safe-boundary completion may arrive later |

A pose update/release must not block control behind PCM storage/inference. Resource overflow/lease expiry means failed stage, immediate fence, bounded safe cleanup, **no READY**, with UNKNOWN if cleanup/consumption is uncertain. Queue/budget limits do not authorize a larger frozen segment or prove GPU capacity. Runtime has at most one private staged artifact; existing max2 planned logical segments does not grant concurrent GPU speculation.

## 6. Descriptor, integrity and READY

StageProduced contains exact identity, `descriptor_revision="staging-descriptor-1"`, request fingerprint, source format/geometry, sample counts/pad, `pcm_sha256`, `frame_count`, first/last sequence and PTS, `video_bytes`, `video_stream_sha256`, `native_rgb_stream_sha256`, EOF/final markers true, chosen limits, provider provenance and resource observations. Worker emits it only after exact source EOF validated, all expected frames encoded with no reorder/flush tail, every output has a matching StageReceived, and native inference's final block is known complete. Receiver storage ACK is distinct from sink consumption.

Hash domains: PCM hash covers exact source little-endian bytes including explicit pad. Per-video payload SHA256 covers exact H264 bytes. Stream digest covers repeated uint64 network-order payload length followed by payload bytes, in sequence order. Native RGB stream SHA256 covers original contiguous512×512×3 uint8 RGB bytes in sequence order, **not decoded lossy video**. Runtime computes its own decoded RGB digest separately; it must not require equality with native RGB. Descriptor hash is SHA256 of the frozen canonical JSON algorithm already used by v0.5 command fingerprints, excluding `descriptor_sha256` itself; cross-language golden vectors must precede implementation acceptance.

Provenance includes workerRef/epoch, model source revision, weights manifest SHA256, avatar/input asset SHA256, cache/preprocessing version, selected capability, and `source="GPU_INFERENCE"` or explicit `CPU_SIMULATION`. Simulation never passes real inference. Runtime validates full H264 decode, exact frame ranges/counts/no gaps, complete PCM, content/version mapping and frozen identity/lease before journaling ready. Worker StageProduced alone is insufficient for ready. No sink sees this artifact before A/B commit installation under the current fence. Hash/file presence alone is not naturalness or audible proof.

## 7. Commit and consumed pose proof

StageCommit freezes A commit identity/ref, B installed receipt ref, immutable descriptor hash, `outputSampleRate`, output half-open interval, exact rational source→output mapping and captured required/optional sink identities. It must correspond to the authoritative installed ledger, not PENDING_INSTALL alone. Runtime verifies those references via A/B; Worker records them under the authenticated attempt and checks immutable consistency. Worker does not claim to independently query SQL or authenticate browser audibility.

StagePoseConsumed includes `pose_ack_id`, descriptor hash, commit-proof fingerprint, monotonically increasing `latest_consumed_sequence`, corresponding source/output exclusive sample positions, and an exact list of required sink receipts (`sinkId`, incarnation, receipt ID/revision, contiguous audio and video exclusive end, evidence type/ref). B computes the largest prefix whose source frame end maps within the **minimum contiguous audio AND video watermark across all captured required sinks**. Integer/rational mapping must not round a partial sample up into proof. Missing/optional peer receipt cannot weaken the required set. OR-based bound Worker Credit and mere pipe enqueue cannot satisfy this proof. Only genuine B-defined sink-consumed receipts count; these are named server/sink evidence, not proof a viewer heard it.

Worker accepts a strictly increasing contiguous prefix (batch advancement allowed after verifying every retained native frame), appends those original RGBs in sequence to nine-frame pose history, and releases only the now-proven original frames. Duplicate same pose_ack_id/fingerprint returns the stored ACK. Reuse with different proof is CONFLICT. Advance beyond generated/stored/current eligible range, out-of-order prior frame, foreign sink set or retired tuple fails closed. Runtime may send a pose ACK only after A/B prove installation and required ranges; merely generating, receiving, READY or committing produces no pose effect.

Full successful playback: apply final pose watermark, obtain matching ACK, then release; SegmentCompleted remains the existing A/B/C proof and cannot be inferred from StageReleased. Partial interrupt: Runtime sends all already-known contiguous pose proof **before** cancellation fencing when feasible, fences immediately on Stop/FORCE without waiting for proof, and treats any unconfirmed residual prefix as UNKNOWN. Once StageFenced fixes the accepted watermark, late pose ACKs cannot mutate it. No next generation may use an uncertain pose history; explicit operator/recovery disposition or new Worker incarnation is required. Original RGB retention is not a replay authorization.

## 8. Safe cancellation and lifecycle

Stop/revocation/expiry > FORCE/product switch > sink-proof work > generation/staging. StageFenced proves control/publication fencing only. Native model kernels may finish later; encoder/sender queues are discarded by tuple fence and the single inference thread confirms safe boundary before StageReleased. Worker must not start a new generation, reuse speculative latents or switch mode while that signal is missing. On next admitted attempt the model restores only the proven consumed pose history (existing portrait policy if fewer than nine), never staged/unplayed pose. Native reset/restore occurs on the owned inference thread, not concurrently in an HTTP/control thread.

StageCancel retains a fixed terminal record, followed by StageRelease/Released with the same control_id. COMPLETE release requires fully confirmed pose prefix; cancellation release may discard unconsumed RGB only after fence and safe boundary, retaining known consumed history. ACK loss/disconnect/restart leaves Runtime UNKNOWN until authenticated reconciliation; Worker high watermark/incarnation and A's run authority are separate. No STARTED speech replay, no fabricated completed cleanup, no unauthorized recovered run. Delayed old Auth/stage/video/storage/pose/final/release messages never affect a fresh tuple.

## 9. Errors, flags, rollback and gates

Static new capability codes: `STAGING_UNSUPPORTED`, `STAGING_IDENTITY_MISMATCH`, `STAGING_GENERATION_COLLISION`, `STAGING_CONFLICT`, `STAGING_SEQUENCE_GAP`, `STAGING_BUDGET_EXCEEDED`, `STAGING_LEASE_EXPIRED`, `STAGING_COMMIT_UNPROVEN`, `STAGING_POSE_UNPROVEN`, `STAGING_RETIRED`, `STAGING_CLEANUP_PENDING`. They map to existing A/C `details.integrationCode`/receipt outcome rules; no change to strict v1.1 error enums. Proven pre-effect rejection may be FAILED; started/partial/ambiguous side effects remain UNKNOWN. Auth/version failures fail closed. Missing status/ACK is not nonexecution.

New independent flags: Runtime `ASTRALIVE_SOULX_STAGING_ENABLED=false`; Worker `ASTRALIVE_WORKER_STAGING_ENABLED=false`. Either missing/false means capability unavailable; Continuity with strict SoulX must reject rather than pretend stage support. Enabling requires existing durability+Timeline+Continuity dependencies and explicit staging-capable provider; does not enable them automatically. Original TCP1.1 Speak works when staging/Continuity are off. UDS and QUIC flags remain independent.

Rollback: stop/fence admission; persist UNKNOWN tails and confirmed semantic cursor; finish or explicitly retire owned staged attempt and prove release/new Worker incarnation; seal A run and stop dispatcher; only then start a fresh legacy1.1 lease/Session with Continuity+staging off and original captured provider/release. No hot mode switch, auto resend or down migration; retain all SQL/evidence and original TCP/Redis paths. No deployment/default enable is authorized by approving this direction.

Before detailed freeze: A verifies references/retries, B verifies watermarks/hash/mapping, C verifies leases/limits/orchestration, named Worker owner verifies final/safe-boundary signal and retention. Required implementation gates: unchanged1.1 suite; deterministic duplicate/conflict/gap/auth/budget/timeout/Stop/FORCE/stale/final tests; source-pinned real GPU short no-sink stage with complete artifact and unchanged pose; cancel then next generation pose inspection; successful commit/play with all required sinks; partial interrupt/UNKNOWN/restart; actual narration→answer→resume with Chrome+RTMP and provider provenance; separate human naturalness and later long busy/SLA tests. Missing environment is NOT TESTED. Do not infer live improvement from this protocol or local IPC microbenchmarks.

## 10. Independent review HOLD — required before detailed freeze

The direction was approved by the user, but A/B/C explicitly withhold detailed ACK. This draft is **not an executable frozen contract**. The following findings take precedence over any ambiguous shorthand above; F must publish an exact revised DTO/schema and obtain scoped ACKs before production implementation. Worker implementation ownership is not assigned yet. No new flag, message or hash function is installed by this document.

| Reviewer | Concrete unresolved item | Required decision/revision |
| --- | --- | --- |
| A | Generic command Fingerprint filters fields and cannot hash a full descriptor; canonical rejects all floats, even1.0 | Exact separate command/stage/descriptor/commit/pose projections with full-object Canonical/Hash, null/missing rules and cross-language vectors; integer-only immutable observations, volatile telemetry outside hashes |
| A/B | New nested Worker integer domain and Ready high watermark | Choose explicit new1.2 safe range vs precise int63 typed paths; fail negotiation before returning an unrepresentable Ready watermark, preserve unchanged1.1 rules |
| A | Vague installation references; partial sink watermarks are not individually persisted by current SQL | Exact existing COMMIT_INSTALLED operation/command/receiptSeq/observationHash/identity/revision/interval reference; explicitly choose B transient partial proof under durable commit vs A-owned additive durable observations |
| B | Pose-to-output boundary rounding | Define absolute W=min(all required contiguous audio/video ends), start<=W<=end; latest=min(frameCount−1,floor((W−start)*16000/(outputRate*640))−1); −1 means no complete frame, never round up |
| B | RELEASED can accidentally authorize next generation after an unknown residual sink tail | Separate storage release from reusable terminal disposition PROVEN_COMPLETE/PROVEN_CANCELLED/UNKNOWN; final confirmed pose ACK required for success; UNKNOWN blocks new generation on the same incarnation even after resource release |
| B | Terminal ACK/tombstone state can grow indefinitely | Bound count/TTL/byte budget; expired identities remain retired via high watermark, cannot regain slots or effects |
| B | Adapter lacks final/native-safe signal | Assign Worker owner and authorize minimal inference-thread synchronization/final signal at safe boundaries in validated/adapter.py with reason/dependency/reviewer, no model algorithm rewrite; queue-empty is insufficient |
| C | attemptId and business generation may be confused with Inbox executor attempt | attemptId is C payload/v05_segment_attempts ID; generation comes from media-start; beat/turn/facts come from captured durable C plan/command, never renderer guesses |
| C | Source descriptor vs SEGMENT_READY output mapping | Exact mapping of sourceSampleCount/rates/pad/contentHash/videoHash/textHash/factIds/factVersion/required sinks/Worker binding; retain existing B output descriptor semantics, bind staging descriptor hash additively |
| C | Publication can race unarmed Worker/expired lease | Require StageCommitAck AND fresh A/B fence before first sink handoff; B install alone does not bypass this guard |
| C | Fixed Stage TTL vs current10s A lease/renew | Recheck conservative remaining grant after TTS; initial Stage TTL cannot be extended by A renewal. Explicit cleanup/status permissions after expiry cannot authorize fresh generation/pose effects |
| C | Current planner cannot automatically replan a captured immutable segment | First test uses capability-aware authored short segments, no4s packing; count actual synthesized samples before StageBegin. Over-cap explicitly reject; changed text/plan requires new reviewed IDs/disposition, never truncate PCM or silently mutate existing command |
| C | Flags/provider capture and precommit cancellation are unspecified | Pin staging mode in captured Session/run configuration with A/C-owned storage; do not reread env per segment. Define zero-prefix −1 and null precommit proof fields; control-before-StageBegin tombstone rejects late admission; absent state/connection is not nonexecution |

A review evidence: owner commit7995d237e7d4a4e29018de57fec8bfbe476c4a7a, six actual Go/Python canonical vectors PASS. B/C supplied read-only scoped findings through managed collaboration tasks; neither claims final detailed ACK. Existing compatibility Worker deployment and true short inference are separately recorded in [GPU evidence](evidence/integration-f/gpu-compatibility-1/manifest.json); that does not implement this capability.
