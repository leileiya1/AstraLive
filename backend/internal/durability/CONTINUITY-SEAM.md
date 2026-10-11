# A-owned Continuity persistence seam

This additive seam follows `v0.5-frozen-1` and F's review at `053e55772385208ffe317c3e4a6a9bb0ca81d031`. It supplies persistence and authority to C and implements B's TimelineJournal HTTP adapter. It does not install B/C orchestration or alter narration transitions. C registers the projection before starting Dispatcher, Recovery or HTTP goroutines. Canonical Continuity configuration is `ASTRALIVE_CONTINUITY_ENABLED`; this increment does not enable it or introduce a second flag.

## Migration and repositories

Migration `000007_continuity_journal.sql` retains TEXT IDs and all legacy query/receipt compatibility. An existing run receives an epoch record at its existing committed sample; no completion proof is invented. C writes its own business models using the same pgx transaction and these columns:

| Table | C-owned business projections / A authority |
| --- | --- |
| `v05_narrations` | `plan_json`, `completion_cursor_json`, `resume_point_json`, `document_json`, frozen `state`, `revision`, `stop_barrier`; scoped session/run, immutable script/product hash |
| `v05_segments` | immutable beat/order/text/hash/fact IDs/product version; `status`, `document_json`, `completed_at` |
| `v05_interaction_turns` | immutable captured question/hash/source IDs/deadline; `state`, resume revision, answer summary, document |
| `v05_segment_attempts` | command/utterance/segment/lane/full run tuple; allocated generation, paired Worker reference, READY descriptor and status |
| `v05_timeline_epochs` | reservation token, expected previous epoch, origin sample; PREPARED / ACTIVE / SEALED |
| `v05_timeline_commits` | immutable half-open sample interval, full identity, descriptor, captured sink sets; PENDING_INSTALL / ELIGIBLE / SEALED and separate play state |
| `v05_timeline_observations` | unique command+operation, immutable proof hash, stored logical ACK |

Every new row carries captured tenant/user scope. SQL guards reject plan/text/version mutation, clearing a Stop tombstone, attempt generation rebinding, overlapping intervals and regression of explicit completed attempts. A narration update requires its own revision CAS. An unresolved PENDING_INSTALL interval remains reserved even after sealing: automatic reuse is deliberately unavailable without an explicit recovery policy.

Repository signatures (imports: `context`, `encoding/json`, `github.com/jackc/pgx/v5`):

```go
Store.EnqueueNarration(ctx, tx, run, kind, key, trace, utteranceID, payload, MediaMetadata) (Command, error)
Store.ReserveTimelineEpoch(ctx, tx, run, expectedPrevious, originSample, reason) (EpochReservation, error)
Store.ConfigureTimelineOutput(ctx, tx, run, sampleRate, requiredSinks, optionalSinks) error
Store.RecordTimeline(ctx, TimelineRecord) (json.RawMessage, error)
Store.RecordTimelineTx(ctx, tx, TimelineRecord) (json.RawMessage, error)
Store.FenceTimeline(ctx, tx, run, reason, stop) error
Store.TimelineProjection func(context.Context, pgx.Tx, Command, json.RawMessage) error
```

Obtain `Store.Current` in the admission transaction, write C's CAS and use `EnqueueNarration` in that same transaction. Metadata is `{NarrationID, SegmentID string; TimelineEpoch int64; Lane string}`; it is included in the immutable command fingerprint. COMMIT_SEGMENT requires `attemptId` and `utteranceId` and creates its PLANNED attempt in the same transaction. A command owns one attempt; there is no PREPARE_SEGMENT wire kind. `PREPARE_RESUME_BRIDGE` is the frozen bridge preparation kind.

`ConfigureTimelineOutput` captures a nonempty, unique required sink set and fixed sample rate before the first commit. Repeated identical configuration succeeds; changing the required set after work begins fails. Optional `nil` is normalized to an empty array. A command payload contains `leaseToken`, `expectedTimelineRevision` and C's `expectedNarrationRevision`. B's older `expectedRevision` alias is accepted only when it equals the canonical timeline revision. Never use the narration revision as the timeline revision.

## Worker wire identifier domain correction

F's `18e4ba4` review identifies a serializer boundary bug in input pin edd4e1e: it applied the business safe-JSON bound to the distinct Worker wire generation. The owner correction preserves the frozen numeric field, wire allocator, Worker credit semantics and all published migrations. Additive `000008_worker_wire_identifier_domain.sql` checks positive Worker BIGINT and nonempty incarnation; the existing paired-null constraint still applies. BIGINT's upper bound is `2^63−1`.

Go `TimelineCanonical` / `TimelineHash` and Python `timeline_canonical` accept a numeric `1..2^63−1` Worker ID only at these record paths:

- `proof.identity.workerGenerationId` and `proof.descriptor.workerGenerationId`;
- `proof.commit.identity.workerGenerationId` and `proof.commit.descriptor.workerGenerationId`;
- `proof.sinkReceipts[array index].identity.workerGenerationId`.

Every other integer, including the complete `command` and its payload, retains the original safe-JSON range. No global field-name exemption is applied. Wrong carrier shapes, bool, string, zero, negative, fractional/exponent notation and overflow Worker values are rejected. Optional Worker null remains representable; the typed READY/commit validators require the Worker epoch and generation to be present or absent as a pair. A bound Worker epoch must be nonempty. This correction does not change business runEpoch/timelineEpoch/generationId authority, command fingerprints or legacy event hashing.

Shared byte/hash vectors live in `testdata/worker-proof-v05.json`. Real PG tests exercise complete READY→intent→installed→completed, duplicate proofs, atomic cursor rollback and JSON/BIGINT round trips for `2^53−1`, `2^53`, `2^63−1` and no Worker. These are synthetic proof fixtures, not a GPU run. The private Go/Python path must retain exact integer decoding; do not decode a Worker wire ID through a JavaScript Number or convert the frozen field to a string.

## Authenticated TimelineJournal

POST `/internal/v0.5/durability/timeline-record` uses the existing private `RUNTIME_JOURNAL_TOKEN_FILE` role, separate from public and Runtime control credentials. It accepts:

```json
{"operation":"COMMIT_INTENT","command":"<full immutable 0.5 command object>","proof":"<operation-specific object>","producerIncarnation":"runtime_..."}
```

The placeholders above are objects, not actual wire strings. Success is `{durable:true,state,revision,receiptSeq}` only after PG commits. Same command+operation+proof returns the stored ACK; changing the proof returns COMMAND_CONFLICT. Retired run, lease, barrier or producer identity cannot mutate the journal. The endpoint validates fixed operations and stored immutable envelopes; it does not accept arbitrary SQL/projection writes.

| Operation | Proof / admission |
| --- | --- |
| SEGMENT_READY | `{attemptId,generationId,descriptor}` after durable Accept → StartAttempt → StartMedia; generation and Worker mapping bind once |
| COMMIT_INTENT | `{commit,revision}` where commit is B's full dataclass, descriptor, identity, interval and immutable command; READY required; inserts PENDING_INSTALL, leaves cursor unchanged |
| COMMIT_INSTALLED | `{commit}` identical to intent; advances committed sample and timeline revision only after durable installed observation |
| SUSPEND_REQUESTED | `{segmentId}` must identify the current installed boundary |
| INVALIDATE_AFTER | `{retainedPrefix,reason,...}` must preserve the current committed prefix; seals pending work |
| BEGIN_EPOCH_PREPARED / ACTIVE | `{expectedPreviousEpoch,newEpoch,originPosition,reason}` matches the immutable command's reservation token and captured origin; ACTIVE requires durable PREPARED observation |
| ANSWER_PREPARED / RESUME_PREPARED | C-defined proof, mandatory C callback validates frozen kind/captured facts and atomically enqueues the resulting COMMIT_SEGMENT; preparation is not sink completion |
| SEGMENT_COMPLETED | full identity, final position, flat sinkReceipts, `evidenceType:"sink_consumed"`, `audienceAudible:false` |
| UNKNOWN | uncertain execution observation; never converted into automatic replay |

A reservation remains PREPARED and cannot admit media. ACTIVE atomically seals the old epoch and advances the current timeline pointer. Stop and recovery seal pending reservations. Lease/barrier supervision synchronously calls C's `continuity.fence("CONTROL_BARRIER"/"LEASE_LOST")` when present, before task cancellation; default-off sessions keep existing behavior.

The flat receipt format agreed by A/B/C is:

```json
{"sinkId":"preview","media":"audio","startSample":0,"endSample":640,"finalMarker":true,"identity":{"sessionId":"s","runEpoch":1,"timelineEpoch":1,"generationId":1,"segmentId":"seg","utteranceId":"u","lane":"NARRATION"},"evidenceType":"sink_consumed","evidenceRef":"sink-observation"}
```

Every required sink needs both audio and video coverage of the complete half-open interval, with no gaps/overlaps and a final marker. Every receipt must match the commit identity including the Worker pair when present. A checkpoint from an installed retained prefix may finish in an older timeline epoch of the same live run; a retired run or Stop cannot advance it. Positions carry sampleIndex/sampleRate; any provided ptsUs must equal the derived integer time.

## Atomic C callback and proof boundary

The callback receives JSON `{operation,proof,receiptSeq}`. C owns its cursor/resume point/document/state CAS and frozen command-type validation. It may call EnqueueNarration for the next immutable command using the callback transaction. Do not open another transaction or perform external media/provider effects inside this callback.

A commits ledger proof, receipt, C projection, resulting Outbox and the replay observation together. A callback error rolls everything back. No callback means narrated SEGMENT_COMPLETED / ANSWER_PREPARED / RESUME_PREPARED fails closed. Duplicate proofs do not invoke the callback twice. Completed means required server sinks consumed the specified audio/video interval; it never proves a viewer heard the sound.

`runtime.app.durability_client.PostgresTimelineJournal(client)` implements B's `record(operation,command,proof)` and preserves computed Position.ptsUs while serializing dataclasses. A failed/missing durable ACK must keep B's entry ineligible. The adapter requires the private DurableEventPublisher created with the same client; it attaches `client.timeline_spool`. Missing disk spool fails closed. It commits the original proof packet to the existing FULL SQLite WAL before POST, using a stable command+operation ID and canonical body hash. The local pending table is upgraded additively with an endpoint column; legacy packets keep `/events`, Timeline packets use `/timeline-record`. Backend outage and ACK loss retain the raw proof for bounded-backoff retries. Process restart preserves the producing executor incarnation, not the new sender's incarnation. Conflicting or fenced proofs remain private audit records; pending capacity is shared with legacy events and a full journal fails closed. Only durable Go ACK deletes a pending body, while minimal hash/producer metadata remains. An explicit record always rechecks current Go authority, even after a previous local ACK.

Background retry commits observations only. It cannot unblock B, regenerate media, hydrate a volatile Timeline or advance C without the atomic callback. If Runtime dies after a physical effect but before it constructs and disk-commits a completion proof, PG retains STARTED/UNKNOWN and recovery remains conservative. This journal is not a guarantee of a viewer hearing sound, storage-volume survival or power-loss behavior beyond SQLite FULL/WAL and its filesystem.

## Validation and rollout

A-owned real-PG tests cover business admission rollback, immutable command replay/conflict, 006→007 upgrade retaining legacy completion, prepared-epoch token fencing and concurrent Stop/activation, terminal-session sealing, UNKNOWN-budget fencing, intent versus installed cursor, required audio/video missing/gap/identity rejection, callback+next-Outbox rollback, proof replay, immutable plan/text, overlap rejection and sticky Stop with late-proof fencing. CPU process crash tests, a separate Timeline-proof sender SIGKILL fixture, spool schema upgrade, ACK-loss/fenced retry tests and race tests are also run; see `docs/v0.5/evidence/agent-a/VALIDATION.md`.

This is an input pin for C/B/F, not whole Continuity acceptance. B's local eligibility/Stop fence, C's production callback, real Worker credit and actual sinks must be tested together on F's integration branch. A does not hydrate or auto-resume UNKNOWN media. Roll back by disabling Continuity on both processes, stopping sessions and preserving migrations/data for audit; use the pre-Continuity binary with the additive schema only after isolated deployment checks. Do not DROP the ledger or rewrite migration checksums on a live database.
