# AstraLive v0.5 Architecture Contracts

- Contract revision: `v0.5-frozen-1`, 2026-10-11, authority: Agent F.
- Repository: `leileiya1/AstraLive`; baseline: `cf6540bdcc788c037929836480812dfaa78362a2`.
- Branch: `exp/v0.5-integration-chaos`; worktree: `../AstraLive-agent-f`.
- Status: **FROZEN FOR IMPLEMENTATION; A/B/C/D/E ACK PENDING; IMPLEMENTATION NOT ACCEPTED**.
- Phase gate: after this freeze, stop integration and wait for A/B/C implementation results. This document does not authorize merging five branches or running faults against shared services.

Normative terms MUST/MUST NOT below define the new opt-in v0.5 implementation. They do not describe features already present in the baseline. A change to an ID, state, signature, ordering rule, default or shared-file boundary needs a numbered contract change request (CCR), affected owners' acknowledgements, and F's revision before dependent implementation merges. No assumption of consensus from silence. QUIC is optional and cannot block Continuity release.

## 0. Baseline review and authority

The following sources were inspected at the pinned baseline. Source code is authoritative for existing behavior; earlier reports are evidence of their stated environments, not fresh v0.5 results.

| Area | Source anchors | Confirmed baseline and gap |
| --- | --- | --- |
| Go Service / Interaction / Scheduler | `backend/internal/app/{service,interaction}.go`, `backend/internal/interaction/{scheduler,config}.go` | Speak/Interrupt/Stop share a process mutex; selected comments recheck ownership/product/TTL. Mutex is not distributed fencing. Receipt PK(session,trace), RESERVED/ACCEPTED/FAILED suppress redispatch with loss/ACK ambiguity. No continuous narration coordinator. |
| Runtime HTTP / Session / Utterance | `contracts/runtime-api.openapi.yaml`, `runtime/app/{models,main,session}.py` | v1 commands have commandId/traceId; strict models reject extra fields. Utterance equality/dedup is memory-only; generation_id cancels stale work. No durable run/timeline epochs or v0.5 Inbox. |
| SQL / Redis / startup | `backend/db/migrations/000001..000005*.sql`, `backend/db/migrate.go`, `backend/internal/eventbus/consumer.go`, `backend/cmd/server/main.go`, `backend/internal/httpapi/server.go`, `runtime/app/events.py` | SQL atomically stores runtime events with FSM changes; Redis stream `dh.runtime.events.v1`, group `astralive-go`, ACK after ApplyEvent, five failures then DLQ. Backend readiness pings PostgreSQL AND Redis; consumer startup failure stops Backend. Migration runner has no cross-process migration lock. No Outbox/Inbox/recovery lease. No PostgreSQL-only acceptance. |
| WebRTC / RTMP | `runtime/app/{webrtc_media,rtmp_media,media_fanout,bound_media}.py`, `gpu_worker/validated/{runtime_avatar,paired_rtmp}.py` | generation/sample-derived PTS, bounded fanout, drain, per-generation consumer credit. Bound credit can be released by WebRTC OR RTMP; this is flow control, not all-sinks segment completion. recv/pipe writes are not audience audibility. |
| GPU transport | `gpu_worker/{client,service,runtime_adapter}.py`, `gpu_worker/validated/{wire,async_link,prefetch}.py` | authenticated private TCP, Worker incarnation/session/generation checks, bounded frame/audio credit, future-boundary reconnect promotion. No QUIC acceptance. Wire generation is not business run epoch. |
| Auth / binding | `docs/v0.4/AUTHORIZATION-BOUNDARY.md`, `backend/internal/{httpapi,userconfig}/`, `runtime/app/session_binding.py` | tenant AND user ownership, exact Origin, internal roles, immutable captured product/provider binding, expiry and Stop/release. Room product switch requires a new Session in v0.4. Preserve these rules. |
| Independent v0.4 real evidence | `docs/v0.4/{INDEPENDENT-ARCHITECTURE-REVIEW,INTERACTION-REVALIDATION,LATENCY-REVALIDATION,NEXT-PHASE-READINESS}.md`, `docs/v0.4/evidence/independent/` | Source reports accept short low-load real Chrome/local RTMP/provider tests. Final product LLM20 Chrome P50/P95=2644.14/3656.62 ms (upper bounds 2656.23/3695.77). Busy long speech wait about17–19s; high-rate wait P95 about14.25s. No long busy SLA, durable restart, full Redis-off, official-platform audience or v0.5 Golden acceptance. Do not reuse low-load PASS for busy goals. |

Existing authoritative frozen surfaces: `contracts/CONTRACTS.md`, v1.1 OpenAPI and event schemas, `contracts/SECURITY-BOUNDARY.md`, existing user-config/personal-assets contracts, v0.4 Session-binding contracts. v0.5 extends a separate versioned surface; it never silently edits them.

## 1. Identifier hierarchy and fencing

Opaque IDs are nonempty, case-sensitive strings generated with existing random-ID helpers or UUIDs, immutable and never recycled. No lexical/time ordering of opaque IDs, including traceId/workerEpoch. ID lookup ALWAYS includes trusted tenant+user+session scope. Client-supplied identifiers never grant ownership.

| Identifier | Creator | Scope / lifetime | Durable location (v0.5 logical tables) | Comparison |
| --- | --- | --- | --- | --- |
| sessionId | Go Session Service | one captured authorized live lifecycle; terminal Session never resurrected; product change creates new Session | existing `live_sessions`, `resource_owners`, `session_provider_bindings` | exact equality with owner/binding |
| narrationId | Go narration coordinator (C) | one immutable script/product version within Session; may span answer/resume and recovery runs | `v05_narrations` | exact equality, never script position |
| beatId | C's deterministic planner when script version is captured | semantic beat inside narration, stable across segmentation/recovery; ordered by explicit beatOrdinal | narration plan JSON + `v05_segments` | equality; order by beatOrdinal |
| segmentId | Go C planner | one immutable semantic segment revision; stable for transport retries, new ID when text/facts/boundary changes | `v05_segments`, Outbox/Inbox/receipts | equality; order by segmentOrdinal, not ID |
| interactionTurnId | trusted Go selection/admission coordinator C | one selected audience answer incl merged source IDs; TTL/rejection explicit; not each raw comment | `v05_interaction_turns` and input source-identity mapping | equality; source IDs scoped by adapter/platform/room |
| utteranceId | Go Service/C | one Speak attempt; ordinary v1 unchanged. One segment attempt maps to one utterance; regeneration after fencing gets a new utterance with same logical segment when content unchanged | existing `utterances` + `v05_segment_attempts` | equality, immutable content fingerprint |
| commandId | Go command issuer (A repository called by C/Service) | one immutable action; assigned BEFORE transaction/dispatch; stable through all retries | `v05_outbox`, `v05_inbox`, receipt log | equality plus requestFingerprint; mismatch CONFLICT |
| traceId | trusted Go ingress/planner | correlation only, inherited across operation; retries reuse; no authority/dedup/order guarantee | commands, attempts, receipt/events | equality for correlation only |
| runEpoch | Go A durability repository | positive monotonic Session incarnation/control-owner term; increments on authorized initial run/recovery takeover, never on each segment or transport reconnect | `v05_session_runs` + current Session run pointer + lease | integer order ONLY within same Session; exact active match for effects |
| timelineEpoch | Go C via A transactional CAS | positive monotonic media edit version within `(sessionId,runEpoch)`; changes on invalidate/answer/resume/FORCE, not clock reset | current run media cursor + `v05_timeline_epochs` + attempts/commits | integer order ONLY in same run; active exact match for new admission |
| generationId | Python Runtime B/C allocation at new media attempt or cancellation fence | positive business generation within active run; changes on cancellation AND new segment/answer attempt; never derived from runEpoch/timelineEpoch | attempt's media binding; volatile next counter restored from high watermark or new run | integer order ONLY same session+run; exact active binding at publication |
| workerEpoch | GPU Worker at process/model-service incarnation | opaque UUID per Worker process; may change without new Session/run; reconnect to same process may preserve it | attempt binding + sanitized Worker status | equality ONLY; reconnect never trusts a retired link |

Epoch/generation business integers are `1..9007199254740991` (safe exact JSON integer); refuse overflow, bool, negative, float or string. Initial timelineEpoch/generationId start at1 in each new run; compare complete tuples, never compare values across runs. A authorizes the run fence; Runtime installs it before run activation; C authorizes/reserves the next timeline revision; B installs the timeline publication fence; E checks Worker binding. None can substitute its counter for another's.

Media identity: `(sessionId, runEpoch, timelineEpoch, generationId, segmentId, utteranceId)` plus optional `(workerRef, workerEpoch, workerGenerationId)` for GPU frames. Immutable frames carry attempt identity or are attached by the adapter to an immutable generation mapping. Recheck at decode/dequeue, commit and immediately before sink handoff. Reject retired run/timeline/generation/Worker without spending current-generation credit. Previously committed intervals before an edit boundary remain immutable ledger entries; a new epoch cannot erase their evidence.

**Worker wire compatibility:** current Worker process maintains `highest_generation` across connections. Its existing `generation_id` uses an int <2^63 allocated by `RemoteAvatarEngine._job()` (`gpu_worker/validated/runtime_avatar.py`, currently wall-time microseconds) and carried by `PrefetchPipeline`, not the Runtime business generation. Freeze the explicit name `workerGenerationId` for this wire value; record both values in attempts. E must preserve strictly increasing wire IDs within workerEpoch, including reconnects and Session changes. Never put runEpoch into wire generation_id or reset the wire counter to1 on reconnect. Use a coordinated allocator/Worker-reported high watermark extension via CCR if needed; unchanged TCP allocator behavior remains the compatibility baseline. Current wall-time allocation is not a proof of cross-host monotonicity; E must test clock rollback/collision and propose an additive allocator seam rather than claiming this is already solved.

STOP durably seals the current run with a tombstone; it does not start a new run or revive a terminal Session. Revocation/binding expiry prevents future runs. Authorized nonterminal recovery increments runEpoch and installs it in Runtime before admitting media; old processes must be fenced/leases expire before takeover effects. A stale request cannot advance any epoch. Timeline reservations have PREPARED/ACTIVE/SEALED status: A/C reserves previous+1 while the prior installed epoch remains authoritative; B installs the barrier, then A/C activates the reservation by CAS. If install/activation acknowledgement is lost, block new commits and reconcile; never admit both epochs. Only BEGIN_EPOCH may carry the reserved future timelineEpoch and must match expectedPreviousEpoch and reservation token. BEGIN_RUN uses the analogous authorized management exception for a new run; arbitrary future commands fail closed.

## 2. Unified v0.5 Command contract

New private endpoint: `POST /internal/v0.5/sessions/{sessionId}/commands`. Separate models from v1, no extra v0.5 fields injected into strict v1 DTOs. GET `/internal/v0.5/sessions/{sessionId}/commands/{commandId}/receipt` reconciles knowledge; authenticated absence does NOT itself prove no side effect.

```json
{
  "schemaVersion": "0.5",
  "commandId": "cmd_example",
  "sessionId": "session_example",
  "runEpoch": 1,
  "traceId": "trace_example",
  "commandType": "COMMIT_SEGMENT",
  "idempotencyKey": "segment_example:commit:1",
  "requestFingerprint": "sha256:<64 lowercase hex>",
  "commandSeq": 4,
  "createdAt": "2026-10-11T00:00:00.000Z",
  "narrationId": "narration_example",
  "segmentId": "segment_example",
  "timelineEpoch": 1,
  "lane": "NARRATION",
  "payload": {}
}
```

The example is a shape illustration, not a valid CommitSegment payload/fingerprint. Required base fields: all through payload shown above including commandSeq. Required Narration/Media fields: narrationId, segmentId, timelineEpoch, lane. For narration-wide lifecycle actions, segmentId is explicitly null; ordinary Speak uses base fields plus its frozen utterance payload. For media-bearing audience/operator commands, narrationId/segmentId may be null only if no active narration; timelineEpoch and lane are still required. Never manufacture a segment ID for Stop.

- Lanes: `NARRATION`, `AUDIENCE_ANSWER`, `RESUME_BRIDGE`, `OPERATOR`, `SYSTEM`. Lane is scheduling metadata, not permission or a second PTS clock. Narration-wide Stop/Suspend uses NARRATION; Session Stop/FORCE uses OPERATOR (or authorized SYSTEM recovery policy), segmentId=null.
- commandType: `BEGIN_RUN`, `START_SESSION`, `SPEAK`, `FORCE_INTERRUPT`, `STOP_SESSION`, the Timeline/Narration names in §§5–6 expressed in UPPER_SNAKE_CASE. `BEGIN_RUN` is a management handshake authenticated and CAS-checked against expected prior run; ordinary commands cannot establish a future run by supplying a bigger number.
- commandSeq is a Go-allocated positive per-run durable ordering number; gaps/priority cancellation are explicit, not inferred from createdAt. Safety Stop/FORCE barriers may supersede queued lower-priority commands (§6).
- createdAt is UTC RFC3339 with Z, informational; timeout/deadline is separate payload field validated against durable TTL/binding. No ordering by wall clock.
- Fingerprint: SHA256 of UTF-8 JSON of `{schemaVersion,sessionId,runEpoch,commandType,narrationId?,segmentId?,timelineEpoch?,lane?,payload}`; recursively sorted keys, separators `,`/`:`, unescaped Unicode, no duplicate keys, no floats/nonfinite values. Numeric fractional quantities in this DTO use decimal strings. Optional absent fields stay absent, explicit null stays null. Go/Python must ship shared golden bytes/hash vectors before A/C integration. commandId/traceId/createdAt/commandSeq/idempotencyKey are excluded from semantic fingerprint; once stored the complete envelope is immutable.
- Idempotency uniqueness: `(tenant_id,user_id,session_id,run_epoch,command_type,idempotency_key)`; commandId also unique per Session/run. Same key/hash returns the EXISTING command/receipt without allocating another effect. Same key or commandId with different hash is409 `COMMAND_CONFLICT` on v0.5. Trace alone is never a durable idempotency key. A retry with an existing commandId must also preserve its stored traceId/createdAt/commandSeq/key and complete envelope; semantic-key replay returns that stored envelope even if a caller proposed different correlation metadata.
- HTTP202 means a durable ACCEPTED receipt under §3, not speech played. Receipt updates arrive asynchronously; errors carry static codes and correlation only. v0.5 codes: `STALE_RUN_EPOCH`, `STALE_TIMELINE_EPOCH`, `COMMAND_CONFLICT`, `RUN_SEALED`, `LEASE_LOST`, `BOUNDARY_CONFLICT`, `SEGMENT_CONFLICT`, `DEPENDENCY_UNAVAILABLE`, `RECOVERY_UNKNOWN`. Retain frozen v1 codes/envelope; map new reasons into existing static `details.integrationCode` when a legacy route needs a reason.
- Stop requests are accepted only from authorized owners/control services, independent of lane. Authentication and current resource ownership occur BEFORE receipt/idempotency replay; revocation cannot replay private status.

## 3. Receipt contract and evidence levels

Wire states are lowercase `accepted`, `generating`, `ready`, `committed`, `sink_consumed`, `completed`, `interrupted`, `unknown`. A receipt has commandId/sessionId/runEpoch/traceId, monotonic receiptSeq, state, observedAt UTC, producer incarnation, evidenceType/evidenceRef, attempt identity where applicable, and sink/range fields where applicable. Store append-only observations plus a CAS projection; do not discard earlier proof on a timeout. Failure is a separate terminal `outcome=FAILED` with static reason, never fake completed/unknown if nonexecution is proven.

| State | Required proof | Does NOT prove |
| --- | --- | --- |
| accepted | A's transaction committed immutable command/Inbox acceptance and active lease/authority checks; Runtime ACK cites durable receipt revision | in-memory queue admission alone, generation or playback |
| generating | persisted EXECUTION_STARTED attempt marker BEFORE provider/media side effects; Runtime trace identifies actual provider/mode and generation binding | successful real LLM/TTS/GPU; simulation must say simulation |
| ready | complete immutable segment PCM/video descriptor available, sample count/ranges/content hash/provider provenance, no sequence gaps, final marker and validated format | any sink handoff or committed fact completion |
| committed | B serialized the segment's audio-master range into authoritative timeline ledger under current fence, before it becomes sink eligible; durability ACK recorded | sink recv, browser rendering or audibility |
| sink_consumed | a named sink consumed an explicit committed contiguous audio/video range with epoch/generation match: WebRTC track recv counter or RTMP completed pipe-write watermark | browser speaker output, platform decoder/viewer hearing |
| completed | SegmentCompleted proof: final PCM range plus all frozen REQUIRED sinks' contiguous terminal range receipts, no pending/ambiguous tail; C/A persisted semantic completion cursor | all viewers heard it, natural answer/resume quality |
| interrupted | current fence/cancel barrier installed; last committed range, per-sink consumed range, invalidated tail and reason recorded | a CUDA kernel was preempted; already transmitted media retractable |
| unknown | missing/conflicting execution/playout proof after crash/ACK loss, explicit lastKnownState/ranges/reason and reconciliation owner | failure, permission to replay, or a newer pipeline stage |

States are evidence observations, not one universal linear enum. STOP/control commands can accepted→completed when their own fence/cleanup proof is durable without generating media. interrupted/failed terminate an attempt; unknown suspends knowledge, while reconciliation can restore a proven prior/completed/interrupted state. Late ready/generating cannot regress terminal proof. Contradictory completed/interrupted ranges become reconciliation-required, never last-writer-wins.

`requiredSinks` and `optionalSinks` are frozen per run/output binding and captured on each commit. Headless RTMP: required=[rtmp]. WebRTC-only: required=[a named connected preview peer]; missing peer cannot prove playback completion. Dual publication: required=[rtmp], preview optional unless explicitly configured required at run start. Tests requiring real Chrome AND RTMP collect both even if preview is operationally optional. Peer departure does not silently weaken a segment's required set; report interrupted/unknown/failure and apply explicit policy. Existing OR-based Worker credit remains a flow-control signal, separate from this all-required-sinks completion.

Browser evidence records native RTP playout estimate, AudioContext status, requestVideoFrameCallback presentation, decoded media markers, and optional physical speaker loopback separately. `track.recv` is SERVER SINK clock. Chrome correlated software AV is OBSERVER clock. Remote platform audience is another clock/domain, NOT TESTED unless measured. No claim of exactly-once audible speech.

## 4. Transactions, events and recovery (A owner)

Logical table names/columns below are frozen; A chooses SQL types/index implementation consistent with constraints. Add versioned additive migrations AFTER000005; never rewrite old migrations. New state tables include trusted tenant_id/user_id with FK to config_principals and Session mapping checks. Secrets/raw tokens never enter commands, events, evidence or SQL payloads; only captured binding IDs/private asset references. Limit retained comment content under configured retention.

### 4.1 Outbox / Inbox / receipt storage

| Table | Minimum schema and constraints |
| --- | --- |
| `v05_outbox` | PK command_id; tenant_id,user_id,session_id,run_epoch,command_seq,command_type,idempotency_key,request_fingerprint,trace_id,created_at,payload_envelope jsonb; delivery_state PENDING/CLAIMED/ACKED/UNKNOWN/CANCELLED/FAILED; attempt_count,next_attempt_at,last_error_code,lease_owner,lease_token,lease_expires_at,acked_at. UNIQUE(session_id,run_epoch,command_seq) and scoped idempotency tuple in §2. ACKED means durable remote acceptance, not completed media. |
| `v05_inbox` | PK(session_id,run_epoch,command_id); trusted scope,request_fingerprint,command_type,command_seq,accepted_at,operation_id,execution_state ACCEPTED/STARTED/TERMINAL/UNKNOWN/CANCELLED,execution_attempt_id,executor_incarnation,execution_lease_token,execution_started_at,terminal_at,last_receipt_seq. Same identity/hash immutable; conflicting retry rejected. This is the Runtime consumer Inbox, not Redis PEL. |
| `v05_receipts` | PK(session_id,run_epoch,command_id,receipt_seq); trusted scope,attempt_id,state,outcome,observed_at,producer_incarnation,evidence_type,evidence_ref,range/sinks JSON,reason_code. Append-only; same revision different hash is corruption/conflict. |
| `v05_recovery_leases` | PK session_id; trusted scope,owner_id,lease_token bigint monotonic,run_epoch,expires_at,renewed_at. Lease identity distinct from commandId/generation. DB-time CAS renewal/acquisition, no process mutex as lease. |
| `v05_session_runs` | PK(session_id,run_epoch); trusted scope,owner_id,lease_token,status ACTIVE/STOPPING/SEALED/RECOVERY_REQUIRED,provider_binding_id,started_at,sealed_at,current_timeline_epoch,current_command_seq,generation_high_watermark,required/optional_sinks,output_sample_rate,current_committed_sample. Timeline epoch rows have PREPARED/ACTIVE/SEALED status and unique reservation token; commit intents have PENDING_INSTALL/ELIGIBLE/SEALED status. Current run pointer in a locked Session-associated row. |
| `v05_events` | PK event_id; trusted scope,session_id,run_epoch,event_seq,producer_incarnation,producer_seq,event_type,command_id,trace_id,occurred_at,envelope_hash,envelope jsonb; UNIQUE(session_id,run_epoch,event_seq), UNIQUE(session_id,run_epoch,producer_incarnation,producer_seq). Consumer projection/ACK is transactional. |
| `v05_narrations`, `v05_segments`, `v05_segment_attempts`, `v05_interaction_turns`, `v05_timeline_epochs`, `v05_timeline_commits` | C-defined records in §§1,5,6; A owns migrations/repos. Immutable plan/fact/version data, CAS revision/state, complete identity tuple, run-independent logical completion cursor and per-run media proof, no cursor advancement solely on planning/generation. Commit PK(session_id,run_epoch,timeline_epoch,segment_id,attempt_id), unique nonoverlapping audio intervals within run. |

Go owns PostgreSQL writes. Python durable journaling uses a separate authenticated Backend endpoint family `/internal/v0.5/durability/` implemented by A (accept Inbox, claim/start attempt, append receipt/event, query reconciliation state, commit timeline proof). Token role `RUNTIME_JOURNAL_TOKEN_FILE` is distinct from Runtime control, Tool, binding/identity and GPU tokens; neither browser cookies nor user-provided scopes are accepted. Endpoint derives owner/run from stored command and checks supplied expected revision/lease. No unrestricted SQL proxy or arbitrary event creation. A owns `runtime/app/durability_client.py` and the publisher adapter; C calls it. D's Go→Python UDS choice does not automatically alter this Python→Go journal channel.

### 4.2 Atomic boundaries and retry

1. Authorize Session AND Room and current immutable binding/product; lock Session/run row; allocate stable command/sequence, task/attempt intent and Outbox in ONE SQL transaction. Return durable enqueue status only after commit.
2. Dispatcher claims with SKIP LOCKED + bounded lease; recheck owner/binding/TTL/run/tombstone immediately before delivery. Stop/FORCE barriers are not stuck behind media FIFO. Lost lease cannot ACK/write current state with an old fencing token.
3. Runtime persists Inbox acceptance through A before returning202; retries same identity/hash return stored receipt, not duplicate work. Before any side effect, persist STARTED and immutable executor/attempt/media binding; only one active execution claim. If journaling unavailable, do not acknowledge durable acceptance or start fresh generation.
4. B prepares timeline CommitIntent after fence validation, A commits ledger intent (PENDING_INSTALL) atomically, then B installs eligibility under the same serialized fence. New epochs seal pending intents, and installation rechecks the fence. After installation B appends committed proof through A before sink handoff; intent alone must not expose a committed receipt. Crash at any install/receipt/handoff gap is UNKNOWN play state, not automatic replay. SQL cannot atomically commit with audio or a GPU kernel.
5. Completion range evidence and C's semantic cursor update share A transaction/CAS. An interrupted partial segment cannot mark its whole fact set completed. Stop tombstone cancels pending Outbox and removes eligibility before binding release; slow external cleanup uses durable finalization retries and never resumes speech.

Emergency Stop during a DB outage still applies an authenticated internal local publication fence immediately; it must report non-durable/UNKNOWN status rather than return durable202 before the tombstone can be written. Never admit a resume while that Stop disposition is unresolved. Public authorization cannot be bypassed because PostgreSQL is down.

Initial bounded policy (configurable downward per test, not an SLA): Outbox max5 attempts; backoff250ms,500ms,1s,2s with jitter≤20%; each local control attempt≤8s, also bounded by TTL/binding/lease. Exhaustion is UNKNOWN if request may have reached Runtime, FAILED if proved not accepted. No retry after expiry, Stop, owner revocation or superseding run. No hidden HTTP library replay of POST. Reconciliation has an independent max30s active probe budget then durable RECOVERY_REQUIRED/manual review; pending knowledge is retained after budget.

Recovery lease initial TTL10s, renewal≤3s, based on DB time; Runtime converts grant's conservative remaining validity to its own monotonic deadline using request RTT bounds. No cross-host monotonic timestamp subtraction or trusting local wall-clock skew. Journal/renewal outage fences NEW generation and publication at expiry; already delivered sink buffers may remain. Takeover requires DB CAS + new run installation AND retiring the old executor/output route (or proof its lease expired); old events/frames never advance new-run state. CPU fault tests must cover paused old executor waking after takeover.

### 4.3 UNKNOWN reconciliation

- Probe current authorized Runtime Inbox/attempt receipt, Worker epoch/generation status, timeline ledger and per-sink watermarks with identity/revision evidence. Worker GenerationComplete only proves its acknowledged frame scope, not utterance audibility or all sinks.
- Durable completion proof: apply it idempotently, do not replay. Proven unstarted command with no commit and old executor fenced: execute once under a NEW authorized run/attempt command linked by `supersedesCommandId`; never mutate an old run envelope. Old envelope delivery retry is allowed only while its original run/lease remains active.
- STARTED, committed, partial consumption, missing history, legacy memory-only receipt or conflicting proof: preserve UNKNOWN tail; require explicit operator/policy disposition (skip ambiguous segment or submit a reviewed continuation). Never restart the full paragraph or call it exactly-once. Known completed beats survive run takeover; an ambiguous partial beat remains visible.
- Recovery authorization is fresh: Session+Room owner, active state, captured product/version and binding validity, Worker/Avatar ACL, output ownership. Release/revoke/terminal Stop means NO recovery. Product switch fences/stops old Session before a new captured Session starts; no hot context mutation in this revision.

### 4.4 Events / Redis optionality

New durable event envelope `schemaVersion=0.5` includes eventId,sessionId,runEpoch,eventSeq,producerIncarnation,producerSeq,commandId (nullable for run-level observations),traceId,occurredAt,source,payload and relevant timeline/attempt IDs. Backend allocates eventSeq transactionally per run on ingestion; producerSeq is Runtime-incarnation monotonic. Duplicates same ID/hash are no-op; different hashes are conflicts. Apply semantic prerequisites as well as sequence: delayed generating cannot regress completed; missing producer stages are reconciled/buffered within a bounded window, not guessed from event arrival time. Record gaps; do not require every stage to arrive before Stop can fence.

PostgreSQL is truth in durability mode. Runtime journals events to Go/A; SQL projection + durable event are atomic. Redis is an optional wakeup/mirror, never receipt truth, necessary startup dependency or recovery coordinator in postgres_only mode. Redis duplicates/reordering cannot change cursor twice. PostgreSQL polling catches lost wakeups, resumes persisted projection cursors, and preserves SSE authorization/revocation. After DB failure, fail readiness and fresh mutations/renewal; do not degrade to MemoryEventPublisher while claiming durability. Migration application uses one DB-wide migration lock for empty/concurrent startup.

Legacy v1 stream/envelope remains unchanged in compatibility mode. Durability mode may project its stable legacy payload into the existing `runtime_events`/SSE names, deduplicated by eventId; v0.5 epoch metadata travels on its separate envelope, never unrecognized v1 top-level keys. Existing legacy events must match their captured originating run mapping; unmapped old events cannot mutate a new v0.5 run. Stale-run events may be retained for audit but never applied to current state. No Redis or TCP removal.

## 5. Audio-master Timeline API (B implements; C invokes; A persists)

All APIs use the complete command envelope, active lease, and expected revision. Local Python signatures below are normative DTO operations; private HTTP dispatch uses the commandType names. No bare PTS without clock/rate/run identity. A TimelinePosition is `{sessionId,runEpoch,timelineEpoch,sampleIndex,sampleRate,ptsUs}`. sampleIndex is an integer in the fixed run output audio sample rate; ptsUs=floor(sampleIndex*1000000/sampleRate), half-open `[startSample,endSample)`. Run audio sample rate is captured at start; GPU PCM16k and sink resampling use explicit rational mapping, never frame count as audio clock.

| Operation / inputs | Return style and proof |
| --- | --- |
| `SuspendAtBoundary(command, boundarySegmentId, expectedRevision)` | synchronous durable acceptance; async `BOUNDARY_SUSPENDED` with exact cut TimelinePosition, lastCompletedSegmentId, per-sink positions and invalidated tail. Finish the agreed semantic segment only; no indefinite full narration drain. Cannot return success before the boundary proof. |
| `InvalidateAfter(command, cutPosition, reason, expectedRevision)` | synchronous fence receipt after publishing the fence and durable ledger intent; returns retainedPrefix/invalidatedAttempts and residualInFlight ranges. Async per-sink acknowledgement. cut≥immutable consumed/committed prefix policy below; cannot retract transmitted audio. |
| `BeginEpoch(command, expectedPreviousEpoch, newEpoch, originPosition, reason)` | synchronous fence/ledger-install receipt. newEpoch must be previous+1 already PREPARED durably by C/A; B never allocates authority. Complete ACTIVE CAS after fence installation; report success only after both. Media admission is blocked at an ambiguous install/activation gap. seal previous future eligibility, validate no overlap/reset, carry retained prefix. Repeat same command is idempotent. |
| `CommitSegment(command, attemptId, generationId, descriptor, startPosition, expectedRevision)` | synchronous committed receipt AFTER A ledger transaction and B eligibility installation. descriptor includes sample count/hash/video timing/fact-version, lane, final marker and sink binding; no overlapping live intervals. Same identity/hash returns prior receipt; changed content/range CONFLICT. |
| `CurrentCommittedPTS(sessionId, runEpoch)` | synchronous read-only snapshot: activeTimelineEpoch, committedExclusiveEnd TimelinePosition, revision, perSinkConsumedExclusiveEnd, lastSemanticCompletedSegmentId. Snapshot is not new ACK or audience position. |
| `SegmentCompleted(identity, finalPosition, sinkReceipts)` | asynchronous B event to C/A; deduplicated by commit/attempt+receiptSeq; all required contiguous ranges proven, final marker seen, current or retained-prefix identity matched. C persists completion before planning cursor advances. |

Boundary transaction order: C requests suspension → B completes current agreed segment/proof and blocks later narration commits → C/A records resume point → C/A allocates next timeline epoch → B InvalidateAfter/BeginEpoch → answer commits. Prefetched narration is never sink eligible until committed. On FORCE/Stop no natural-boundary wait is required; fence immediately, persist interrupted/ambiguous partial range. Control must not await CUDA completion before dropping stale publications.

InvalidateAfter retains all already committed prefix through the cut. A cut inside already committed media is a FORCE interruption with explicit partial consumption/unknown tail; it cannot be treated as a clean semantic suspend. Invalidate uncommitted/unsent tail, retire old attempt mapping, choose the next start at or beyond committed exclusive end (silence gap if necessary) to preserve monotonic sink clocks; never replay/overwrite committed sample indexes. Report residual sink-buffer audio/video separately. Same-run epochs never reset PTS to0. Recovery into a new run has a new clock and must establish a new sink connection or a persisted explicit offset mapping for a surviving RTMP connection; never silently reset a surviving muxer timestamp.

Audio is the pacing master. Video scheduling derives from audio sample position; controlled duplicate/held video and bounded late-frame drop are explicit metrics. Audio overlap is rejected; audio gaps are explicit inserted silence with provenance. No independent lane clocks, video-driven audio acceleration or unexplained fixed delay. SegmentCompleted is separate from WorkerCredit and ordinary `UTTERANCE_COMPLETED`.

## 6. Narration API and state machine (C, with A/B seams)

Go C owns business plan/selection/state decisions; Python C owns segment orchestration, calling B and A's journal. Freeze state names: `IDLE`, `PLANNING`, `NARRATING`, `SUSPEND_REQUESTED`, `SUSPENDED`, `ANSWERING`, `BRIDGE_READY`, `RESUMING`, `STOPPING`, `STOPPED`, `RECOVERY_REQUIRED`, `FAILED`. CAS `narrationRevision`; event/command retry never advances twice. Session FSM and v0.4 interaction mode remain separate projections.

| API / required payload | Completion semantics |
| --- | --- |
| `StartNarration` / captured scriptVersion/productSnapshotHash, immutable beats+requiredFactIds, requiredSinks, policy |202 durable plan+state PLANNING; async first segment commit→NARRATING. New narrationId; cannot use live mutable product facts to change captured script. |
| `PlanNextSegment` / narrationId,expectedNarrationRevision,beatId,expectedCompletionCursor | synchronous durable plan result `{segmentId,beatId,segmentOrdinal,textHash,factIds,boundary,durationHint}` or NO_MORE_SEGMENTS. No TTS/playback ACK; bounded prefetch, max2 uncommitted planned segments initially. |
| `RequestSuspend` / interactionTurnId,selected source IDs/questionHash,priority,deadline,expectedNarrationRevision |202 state SUSPEND_REQUESTED; calls B SuspendAtBoundary; async boundary event→SUSPENDED. Ordinary comments never FORCE by themselves; reject with explicit reason when TTL/binding/boundary budget expires. |
| `CommitResumePoint` / boundary proof,completedSegmentIds/factIds,partialSegmentDisposition,nextBeatId,nextSegmentId,expectedRevision | synchronous durable CAS receipt. Cursor advances only from B completion proof; partial facts are not all marked done. Freeze point before any answer admission. |
| `StartAudienceAnswer` / interactionTurnId,resumePointRevision,capturedProductHash,utteranceId,answer plan/provenance |202 after suspension and next epoch installation; state ANSWERING; related segment uses lane AUDIENCE_ANSWER. Recheck ownership/TTL/product/binding. No placeholder filler counted as correlated answer. |
| `CompleteAudienceAnswer` / turnId,answer SegmentCompleted proof,expectedRevision | synchronous durable completion CAS; failed/unknown/interrupted answer cannot masquerade as finished. A failed answer yields explicit recovery/continuation disposition. |
| `PrepareResumeBridge` / turnId,resumePointRevision,nextBeatId,completedFactIds,answerSummaryHash |202 bounded generation; async bridge ready→BRIDGE_READY. Bridge may be empty with reason; it references captured facts and must not restate completed claims as new facts. Human naturalness still needs review. |
| `ResumeNarration` / resumePointRevision,bridge descriptor,nextBeatId,nextSegmentId,expectedRevision |202 after new epoch fence; state RESUMING, bridge uses RESUME_BRIDGE, next original narration commit→NARRATING. Exact resume cursor/idempotent command; no blind full-beat restart. |
| `StopNarration` / reason,expectedRevision |202 after durable STOPPING tombstone/eligibility fence; async cleanup receipt→STOPPED. Cancels pending plans/answer/bridge; no auto resume. Session Stop supersedes it and releases binding through existing flow. |

Required records: immutable beat/fact order and versions, completed segment/fact ledger, resume-point revision with boundary proof, turn source IDs and selected/rejected reasons, each attempt text/fact hash and media binding, state CAS revision, stop barrier, recovery disposition. Answer facts do not automatically satisfy narration's required-fact ledger; only an explicitly mapped proof under the same captured version may do so, with a recorded policy decision. Tests must retain duplicate/omitted facts and human quality findings even if lexical matching passes.

**Priority / races:** Session Stop/revocation/expiry > authorized operator FORCE (or product-switch Stop) > operator control > selected audience suspension > resume/bridge > narration prefetch. Stop is sticky for the run/narration and supersedes FORCE/Resume even when its HTTP ACK is delayed. A SQL barrier CAS, Runtime fence and bounded separate control path enforce this; a mutex/FIFO alone is insufficient. Concurrent Stop/FORCE outcomes: one durable terminal Stop, stale FORCE rejected/cancelled, no new output. FORCE interrupts now, marks partial segment, enters operator override and requires explicit authorized resume; never infer a natural resume point from last generated word. Product switch follows Stop old Session/new captured Session (§4), cancelling old candidates/turns; no answer or resume with a mismatched product hash. Pending resume and selection recheck barrier/revision at final commit, not just request arrival.

Initial policy: semantic segments target2–5s with configurable hard cap8s based on measured synthesized sample duration; estimates are not timing evidence. Over-cap segments must be replanned before commit or explicitly rejected. Suspension deadline is bounded by the selected comment's TTL and binding/lease; lateness is recorded, not concealed by resetting selection timestamp. Configurable answer/narration fairness budget limits consecutive answers; pending candidates remain bounded. These are design defaults, not proof of the P50≤5s/P95≤8s busy objective.

## 7. Two transport links (D/E independent)

```text
Go Backend -- Runtime HTTP (TCP or local UDS; D) --> Python Runtime
Python Runtime -- authenticated durable journal HTTP (A) --> Go Backend / PostgreSQL
Python Runtime -- Worker binary media/control (TCP or QUIC; E) --> GPU Worker
Redis: optional notification/mirror in v0.5 durability mode; not either media link
WebRTC / RTMP: separate output sinks; neither is the Worker transport
```

### 7.1 Go → Python local control (D)

HTTP methods/routes/status/envelopes/timeouts/auth remain identical on TCP and UDS. Freeze config `ASTRALIVE_LOCAL_TRANSPORT=tcp|uds` (default tcp), existing `AI_RUNTIME_URL` for TCP, `ASTRALIVE_RUNTIME_UDS_PATH` absolute private socket path for UDS, `ASTRALIVE_LOCAL_FALLBACK=disabled|tcp` (default disabled). Config validated once and captured per run; switching a live connection requires fencing pending ambiguous commands, never replaying them.

UDS is Linux opt-in; Windows loopback uses TCP. Socket parent0700, socket0600 or a documented dedicated group0660; check ownership and reject symlink/non-socket/unowned preexisting path. Cleanup only own inode/process lifecycle. No Browser/Worker endpoint exposure. Preserve `RUNTIME_CONTROL_TOKEN_FILE` role authentication over UDS; peer/local filesystem access is not user authorization. D composes custom DialContext/UDS transport INSIDE existing TokenTransport; don't overwrite auth wrapper. Disable proxies/redirects as existing protected transport does. Retain request cancellation, bounded connect/read/write, health and WebRTC-offer30s exception. No transport-level automatic POST retry. TCP fallback only when explicitly configured and endpoint has the same authenticated service identity; first reconcile sent/ambiguous commands. Invalid credentials/permission/version never trigger downgrade.

### 7.2 Python → GPU remote transport (E)

Freeze `ASTRALIVE_WORKER_TRANSPORT=tcp|quic` (default tcp), `ASTRALIVE_WORKER_FALLBACK=disabled|tcp` (default disabled). Worker endpoint/credentials come from trusted registry/captured binding; add distinct QUIC endpoint/certificate identity there through E+shared-file CCR. Preserve management token vs inference token, Worker/Avatar ACL, one logical Worker admission, Ready-only warmup, session/epoch/generation validation, PCM sample sequencing, H264 packet metadata, cancellation and four-frame credit. No weakly authenticated auto-discovery.

Existing TCP wire: 8-byte network-order uint32(header_length,payload_length), UTF-8 JSON object header≤16384 bytes, payload≤2097152 bytes. Auth `protocol_version=1,internal_version=1.1,session_id,token`; GPU_WORKER_READY establishes worker_epoch/cache/asset identity. Preserve BeginGeneration, AudioChunk/AudioAccepted, Credit contiguous sequence, CancelGeneration/GenerationCancelled, Health and GenerationComplete semantics. Credit remains consumption flow control, not human playback. New metadata that needs wire extension requires explicit negotiated capability and CCR; legacy TCP decoder stays usable.

QUIC v0.5 profile: reliable authenticated TLS1.3 QUIC streams, certificate identity/pin validation plus existing application Auth/ACL; no0-RTT state-changing commands. Separate ordered control stream, ordered PCM stream and ordered encoded-video stream; each uses the same bounded packet framing. BeginGeneration ACK before media; bounded audio/frame credits globally shared, so parallel streams cannot multiply buffers. Cancel fence applies across streams at receive/dequeue/publication, even when media arrives before delayed control; stale packets cannot replenish current credit. No unreliable datagram video profile in frozen-1. QUIC is NOT a public WebRTC replacement.

Disconnect: retire old link and attempt mapping, bound reconnect by lease/TTL/recovery policy, reauthenticate Ready/session/Worker epoch. Recovery candidate promotes only on future clean generation boundary; current interrupted job is never silently replayed or mixed with fallback audio. Existing explicit Lightweight degradation is preserved and recorded. QUIC→TCP fallback uses fresh authenticated connection/generation after reconciliation/fence; never resends an unknown AudioChunk into an existing generation. Certificate/Auth/version failures fail closed. Record chosen transport/fallback reason/workerEpoch; redact endpoints/tokens. Microbenchmark and real busy Chrome/RTMP comparison are separate acceptance rows.

## 8. File ownership and shared modification register

A/B/C/D/E own implementation/testing in their areas. F owns contract/review/integration gates and does not implement their subsystems. Newly suggested filenames reserve ownership, not an assertion those files exist. Existing shared files cannot be refactored concurrently without the register below.

| Owner | Exclusive primary files / directory boundary |
| --- | --- |
| A | `backend/db/migrations/000006+`, `backend/db/queries/durability*.sql`, `backend/internal/durability/**`, `backend/internal/httpapi/durability*.go`, `runtime/app/durability_client.py`, `runtime/app/durable_events.py`; Outbox/Inbox/Recovery tests. Owns ALL new SQL migrations incl C/B schema. |
| B | `runtime/app/media_timeline.py`, `runtime/app/webrtc_media.py`, `runtime/app/rtmp_media.py`, `runtime/app/media_fanout.py`, `runtime/app/bound_media.py`; Timeline and sink regression tests. |
| C | `backend/internal/narration/**`, `backend/internal/httpapi/narration*.go`, `runtime/app/narration.py`, `runtime/app/segment_orchestration.py`; narration/segment state tests. Does not create competing DB migrations. |
| D | `backend/internal/runtime/local_transport.go`, its tests; `runtime/app/local_listener.py`, transport-specific deployment wrappers/tests. Owns Go→Python transport, not Worker binary protocol. |
| E | `gpu_worker/transport/**`, `gpu_worker/client.py`, Worker-transport tests; QUIC deployment/config additions via register. Owns Python→GPU transport; does not rewrite sinks or C state machine. |
| F | `docs/v0.5/**`, `integration/v0.5/**`, `scripts/v0.5/**` (future harness); contract fixtures/validation, fault injection, independent evidence, merge ledger and acceptance. |

Shared-file register below freezes primary editor/final merge executor. Each actual modification adds CCR/commit/line-purpose, dependency SHA, peer acknowledgement and F merge SHA to INTEGRATION-PLAN. This table is a reservation; no modification is made by this contract commit.

| Shared file(s) | Reason / dependency | Primary editor; reviewers; final merge executor |
| --- | --- | --- |
| `backend/internal/app/service.go`, `interaction.go`, `session_integration.go` | A routes durable commands/barriers, then C hooks narration selection/suspend; preserve ordinary Speak/Stop/ownership | A for durability commit, C for subsequent narration commit; A+C; F |
| `backend/db/queries/resources.sql`, `backend/generated/dbgen/**`, `backend/db/migrate.go` | additive durable queries/serialized migrations/generated sqlc | A only; C/B review schema seam; F |
| `backend/cmd/server/main.go`, `backend/internal/config/config.go`, `backend/internal/httpapi/server.go`, `.env.example` | A optional Redis/readiness/journal wiring; C coordinator; D dialer after A hooks | staged A→C→D, no concurrent edits; affected owners; F |
| `backend/internal/runtime/client.go` | A v0.5 durable envelope/status methods before D transport composition; C consumes API | A first, D afterward; C+auth owner; F |
| `runtime/app/session.py`, `main.py`, `models.py`, `config.py`, `.env.example` | A journal/publisher hooks, B Timeline interface, C orchestration, D listener hook | staged A→B→C→D; all affected owners; F |
| `runtime/app/providers.py`, `session_binding.py` | B media identity adapter; C immutable plan/binding check; E transport selection | B→C→E; A for lease/auth; F |
| `gpu_worker/runtime_adapter.py`, `config.py`, `service.py`, deployment config/registry | E transport factory/capability, B immutable media identity mapping, C generation seam | E drafts changes after B/C seam ACK; B+C+auth reviewer; F |
| `gpu_worker/validated/**` | pinned validated media/protocol; avoid changing. Any necessary edit isolated, documented provenance+real regression required | E transport-only or B media-only via CCR, sequential; B+E; F |
| `contracts/**`, `backend/generated/{runtimeapi,controlapi}/**`, `frontend/src/api/generated*` | frozen v1.1 untouched. New v0.5 schema if needed is versioned and F-owned; no hand-editing generated code | F schema review; codegen issuer designated per CCR; F |
| `frontend/**`, `scripts/interaction-*`, existing acceptance tests/reports | preserve regressions and existing evidence. New UI outside A–E scope needs separately assigned owner | no unassigned edits; F integration hooks only via CCR; F |

No agent deletes failing legacy tests, overwrites historical evidence, changes another owner's core file to resolve a conflict, or accepts a Git auto-resolution without semantic review. Conflict returns to each owning agent; F reruns gates on the reviewed result. No bulk five-PR merge.

## 9. Compatibility, feature flags and rollback

These NEW flags are frozen names/defaults, **not implemented** in baseline:

| Feature / owner | Config / default | Dependencies / invalid combinations | Default-enable decision now |
| --- | --- | --- | --- |
| durable delivery A | `ASTRALIVE_DURABILITY_ENABLED=false` | true requires migrated PostgreSQL + journal auth/lease; no memory fallback | NOT TESTED; keep off |
| PostgreSQL-only A | `ASTRALIVE_EVENT_MODE=legacy_redis` (`legacy_redis` or `postgres_only`) | postgres_only requires durability=true; failure to reach PostgreSQL is fail closed. Legacy retains original Redis requirements | NOT TESTED; keep legacy |
| MediaTimeline B | `ASTRALIVE_MEDIA_TIMELINE_ENABLED=false` | standalone experimental baseline comparison allowed; v0.5 durable completion/recovery claims require A. False preserves existing sinks/PTS behavior | NOT TESTED; keep off |
| Continuity C | `ASTRALIVE_CONTINUITY_ENABLED=false` | true requires durability+MediaTimeline+authenticated binding; does not require UDS or QUIC | NOT TESTED; keep off |
| Local IPC D | `ASTRALIVE_LOCAL_TRANSPORT=tcp`, `ASTRALIVE_LOCAL_FALLBACK=disabled` | uds needs private absolute socket path + supported host; independent of Continuity | NOT TESTED; keep tcp |
| remote QUIC E | `ASTRALIVE_WORKER_TRANSPORT=tcp`, `ASTRALIVE_WORKER_FALLBACK=disabled` | quic requires capability/cert/authorized endpoint; independent of Continuity. Failure cannot force Continuity rollout to wait | NOT TESTED; keep tcp |

Effective flags/contract revision/captured provider version/transports are recorded per run and in benchmark metadata. Validate incompatible config at startup; no silently enabling dependencies. Feature config switches only before new runs or after controlled Stop/drain/fencing, never hot-switch unknown media attempts. With all flags at defaults, existing compatibility mode must match baseline.

Compatibility checklist (all must regress at each relevant merge):

- [ ] Frozen v1.1 OpenAPI/event schemas/examples and generated DTOs unchanged; `contracts/validate_v1_1.py` and existing guards pass.
- [ ] `/api/v1/dev/platform-events`: COMMENT direct priority80/INTERRUPT_LOWER_PRIORITY,202/409 behavior preserved; explicitly separate from new Scheduler Selection path.
- [ ] ordinary Speak/Utterance priorities, source/interrupt enums, stop/start FSM, error envelopes, WebRTC offer/answer routes preserved.
- [ ] Cookie/Origin auth, tenant+user AND Room/Session ownership before dedup, ACL, token-role separation, expiry/release/internal-ingress isolation preserved on TCP/UDS/QUIC and recovery.
- [ ] SoulX TCP frame/PCM/credit/cancel/cache/session/epoch semantics preserved; CPU_SIMULATION never real GPU evidence.
- [ ] Accepted generation fence, sample-derived PTS, headless/dual WebRTC/RTMP, drain/backpressure and bounded reconnect/degradation regressions retained.
- [ ] Existing tests/history retained, each failure/skipped real environment explicitly reported; no default model/provider/paid-GPU changes.

Rollback per feature: freeze new admission → authorized Stop/fence owned runs → record remaining UNKNOWN tails and durable cursor → wait/prove output cleanup and release binding → start a NEW compatible run with relevant feature off. Do not replay unknown old-run Outbox during rollback. Keep additive SQL/evidence/receipts; old binary cannot consume v0.5 pending rows. Drain/cancel v0.5 dispatchers and seal runs before binary rollback; never downgrade migrations or delete rows to make old code start. Restore original Redis stream/config and TCP endpoint only after compatibility checks. If Redis is unavailable, rollback to legacy_redis is not operational; remain stopped or repair Redis rather than silently use memory. UDS rollback restores TCP with same control token; QUIC rollback uses TCP at a new safe generation. Timeline/Continuity rollback does not remove ordinary Speak support; requires a new clean output run. Backup, restore test and schema compatibility evidence precede deployment.

## 10. Acceptance contract and handoff stop point

A/B/C must return contract revision ACK or numbered CCR, implementation commit SHA, owned/shared file list, migrations/flags/rollback, exact automated commands/logs and unresolved real-environment gates. D/E do the same independently. F does not declare implementation consensus until these ACKs exist. No active A–E agent channels were present at freeze; the companion `AGENT-HANDOFF.md` is the reviewable dispatch packet, and live delivery/ACK remains pending.

Next stage (not executed by this freeze): build old-code-compatible deterministic narration/comment fixtures, owned-process crash harness, stale epoch frames, duplicate/reordered events, Redis-off startup, Chrome AV measurement, RTMP record/ffprobe and benchmark schema BEFORE any implementation merge. Each unimplemented capability is NOT TESTED/unsupported, not a mock PASS. Integrate A→B→C→D→optional E one reviewed commit/PR at a time with merge SHA ledger; Go/race/Python/contracts/frontend/migrations/auth/interaction/media gates per merge.

True Golden gates remain:10-minute factual narration with≥5 randomized comments and per-turn semantic resume;30–60-minute random busy inputs/product switches with raw P50/P95/P99 and resource/buffer/fence/recovery metrics; all specified crash/race injections; real Chrome+RTMP quality and clock-domain audit; single-host local/remote GPU, Windows if available, UDS/TCP, QUIC/TCP, Redis-off and original compatibility. Busy selected-comment→first CORRELATED Chrome audio AND video target P50≤5s/P95≤8s is a TARGET, not a current result. Include timeouts/missing matches as censored failures, do not drop outliers or use filler as the first related sample. Preserve random seed, input/selection/decision time, answer/resume IDs and full raw artifacts; human semantic/naturalness assessment remains separate from automated fact matching.

Final decisions per feature are PASS / CONDITIONAL / FAIL / NOT TESTED with scope. Unit PASS is not GPU PASS; QUIC microbenchmark is not audience-latency improvement; automated coverage is not perfect natural continuity. **At this phase: no v0.5 feature can be enabled by default. Integration is paused awaiting A/B/C, not a completed final acceptance.**
