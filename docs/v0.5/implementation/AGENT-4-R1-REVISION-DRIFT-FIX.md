# R1-INSTALLATION-REVISION-DRIFT — Agent2 layer A FINAL ACK received

**Source-fix layer A FINAL ACK received; layer B remains BLOCKED. ASTRALIVE V0.5 BLOCKED / OUTPUT_FENCE_UNPROVEN.**
Agent2's review of `0a67a35e5815031d4d0d0a4ca4da89882e31e079` correctly identified a
real trusted-source integration bug. Prior real-process/SQL results do not waive
it. Starting integration is `eb00428eeb1f0506e9b71eea47480ba4d982c7db`.
No Authority-owned source, schema, production Session, Runtime once-TTS or media
entrypoint is modified. No PR11 merge, main change, LIVE, GPU or platform push.

## Independent reproduction and fixed boundary

Agent2's623-line probe is retained byte-for-byte as
`backend/internal/durableintegration/receiver1/agent2_owner_review_test.go`, SHA256
`db675df45a7bd9ce0cce4dd40ade107d19609b8137873e73e00570eb79914463`, from
`2d7e107b2d21550cd6e32e3f7c412ff4ef8ff028`. Both original revision cases ran3 times
on an unmodified baseline git archive with only that test input: **6 FAIL**,
source2 with mirror/Stage1 still returned true and one latch. This was real Darwin
native Go/Python IPC and new dedicated PostgreSQL, with physical/source/Runtime
fixtures explicitly identified. No shared database or process was used.

The original probe bytes are unchanged after the fix. The fixture's immutable
`physicalFixture` now explicitly supplies the local lifecycle gate required by
the fixed repository seam. A separate `_test.go` compatibility method does the
same for Agent2's named synthetic `reviewSource`; it changes no original tests,
assertions, observation behavior or production source. Adversarial mutable
revisionSource changes still violate that fixture's claimed immutability and
are explicitly tested as adapter faults. Both original cases x3 now PASS;
Agent2's15 owner probes PASS. Real physical coordination is not inferred from
these synthetic readers.

## Implementation and linearization

`installation_gate.go` adds a **local trusted host lifecycle capability**,
`CoordinatedPhysicalSource.InstallationGate`, with a pinned complete immutable
`ReceiverPhysicalInstallation`. No wire field/route, role, registration protocol
or DTO changes. Observe-only and nil sources fail Install before SQL mirroring.
Merely constructing a gate is not a physical installation or fence proof.
A production source may implement this seam only if its actual physical changes
are controlled by the before-change barrier below; there is no automatic wrapper
that can turn an arbitrary mutable reader/JSON receipt into a coordinated source.
Production has no positive implementation and remains blocked.

`registrar.go` compares every official observation field (revision, complete
Binding, observer/Guardian principal, closed-fence proof/state), not just Binding.
The composite immutable tuple also pins native Runtime/Guardian UID/PID/birth,
incarnations and Guardian keyId/public key from trusted process creation.
`installation_repository.go` compares the entire SQL mirror and both immutable
process identities/public key. Stage request/read, actual CONTROL Stage, signed
receipt, Register, installation reads and Authority effectful transport all use
the same pinned tuple. No historical revision, Stage receipt or Grant is rewritten.

Positive Install/Stage/Register/read/Query/Consume paths acquire a local gate
reader **before** physical preflight and retain it through Authority Store.Handle's
final SQL commit and response construction. There is no mutex held across SQL,
physical observation, IPC, fsync or network waiting; the gate tracks active users
using a short mutex and a drain notification. Server requests remain bounded.
Existing Authority Run/output locks, DB-time deadlines and Stop tombstones are
unchanged. Post-SQL external observation is a conservative adapter-fault check,
not a substitute for coordinated physical lifecycle.

The independently trusted physical owner must call
`Registry.RetireInstallation(ctx, registrar, command)` **before changing any
physical revision/Generation/process/key/fence or replacing the source**:

1. `CloseAdmission` irreversibly closes the local gate without waiting for SQL or
   IPC. No later reader can enter. A Backend response already committed and
   checked before closure may still reach the network Writer after closure;
   its Reader still blocks Retire and physical replacement. This historical
   reply cannot directly start TTS: Receiver final proof/short gate and actual
   sink fencing remain mandatory. Gate closure itself proves no physical stop.
2. Wait for existing users outside SQL. The old physical tuple must stay unchanged
   until this barrier returns successfully. A timeout/error keeps the gate closed
   and does not permit replacement. Concurrent SQL users can finish only against
   that unchanged old tuple; a committed-but-unacknowledged latch is retained.
3. Lock the existing scoped Run row first, then set only the old mirror's mutable
   `retired_at` tombstone. Its immutable tuple remains unchanged. This serializes
   with Authority's Run-first transaction domain and makes even later direct
   Authority SQL readers reject the old mirror. No external source read is made
   inside this transaction.
4. Invoke the existing official RevokeReceiverBootstrap CAS operation, read back
   REVOKED after a concurrent CAS loss, retain latch/audit, revoke issued Grants
   and mark active executions UNKNOWN. Physical replacement is allowed only
   after the whole method succeeds; neither a local boolean nor an early SQL
   snapshot is sufficient. Partial failure is closed and retryable as retirement,
   never replay/Consume authorization.

The source owner cannot legally change its resources and announce the change
later. An adapter that cannot enforce this ordering must not implement the
capability and remains fail-closed. This assumption is explicit and needs Agent2
and the future real Agent5/Linux source owner's review; the current production
source is missing. Unexpected native death, observed drift/withdrawal or durable
Session/Binding/output invalidity also closes admission; the bounded private
supervisor retries durable retirement/CAS. No cleanup deletes dedup evidence.

## Evidence and remaining gates

[Run summaries/raw logs/cleanup/resources](../evidence/agent-4/receiver1-revision-drift-2026-10-18/)
keep the original6 failures, intermediate fixes, exact probe and owner input.
The focused final native group has22 real-PG race PASS; it includes Run-lock
Consume/Register retirement races, actual concurrent Query+Commit connections,
consumed history/UNKNOWN, unsupported source denial, Session expiry reconciliation
and coexisting native Generation replacement rejection. Original14 tests retain
ACK loss, Stop-before-final-ACK, current deadline, long consumed proof renewal,
actual Runtime IPC, process/key/channel/scope and strict DTO checks. Original
Agent2 probes retain dual Tenant/Room and source observation outside SQL locks.

A separate controlled archive candidate includes only Agent5's exact approved
v1 fixture postimage and one protection expectation; full Go/race, streaming18,
137 contracts/11 Journal/13 wire/8 adapter, both validators/generator and Guardian
v1/v2 are tested there. Final committed integration results and exact source SHA
are recorded separately; candidate PASS is never called integrated-source PASS.
The first candidate predates two additional native tests; its full run is retained
as such. Final integration must rerun the complete suite without overlay.

Original cold LEASE_LOST and RTMP-tail failures remain in earlier evidence and
Agent5's owner review. Subsequent repeated success does not establish universal
stability. Linux UID/ACL/network/cgroup/old publisher and real WebRTC/RTMP/GPU,
production PhysicalSource/Session assembly, once-TTS and media remain NOT TESTED
or BLOCKED. The existing sources can deny all production admission; this fix
cannot create a physical output proof. Agent2 subsequently independently reviewed this exact SHA and granted the
scoped FINAL ACK recorded below.

## Final committed integration validation

Registrar fix: `58cbc59042c70f9010a368f963257fdad5154b91`.
Exact Agent5 fixture/protection change: `08af1049250d2657d7afb5e303d97a02e9761570`.
The original worktree was clean for the full no-overlay committed-source run on
that latter SHA. All command exit codes are0. Real dedicated PostgreSQL17.11
used fsync/synchronous_commit/full_page_writes on; all four owned databases were
dropped and the instance stopped. No shared service was touched.

| Check | Committed-source actual result |
| --- | --- |
| Receiver1 native/real PostgreSQL race |22 PASS,0 SKIP |
| Original revision probes x3 |6 PASS (before:6 FAIL) |
| Original Agent2 owner probes |15 PASS |
| Streaming PostgreSQL race |18 PASS |
| Full Go test / race |Each267 top-level PASS,0 FAIL,13 SKIP |
| Go vet |PASS |
| Contracts / Journal / official wire / adapter |137 /11 /13 /8 PASS |
| Both validators / generator --check |PASS |
| Original Guardian v1 / fixed PR11 v2 CPU candidate |25 /69 PASS,0 SKIP |
| Latest PR11 extended CPU / READY group |82 PASS,1 Linux SKIP /5 PASS |
| Linux amd64 compile |PASS, compile only |

[Exact postcommit results/all SKIP reasons](../evidence/agent-4/receiver1-revision-drift-2026-10-18/postcommit-summary.json)
and [frozen/source/ownership audit](../evidence/agent-4/receiver1-revision-drift-2026-10-18/final-source-audit.json)
remain separate from the earlier archive candidate. All22 frozen files and the
manifest/digest retain original bytes; all seven migrations, official DTO trees,
validators, Authority/Agent3 source and public production entrypoints are unchanged.
Of313 protection expectations, only the explicitly approved Agent5 fixture entry
changes. Its pre/post bytes, owner approval, exact diff and user authorization
are retained in [the governance record](protection-changes/RECEIVER1-GUARDIAN-FIXTURE.json).
Both deliberate mutations (approved postimage and unrelated protected model)
are rejected by the unchanged validator; restoration passes all313 checks.

PR11 itself remains Draft/unmerged. Only its exact approved v1 fixture is copied,
with owner commit provenance, never its unreviewed Guardian core. Its fixed
`9b969d099b7a3b6b85f3595d26c36fb953d47263` code is tested as an isolated archive.
The source gate coordinates SQL eligibility, not physical media output; no
production PhysicalSource, Linux isolation or media acceptance is implied.
**Agent2 FINAL ACK is now formally received for the exact source/constraints;
old pending flags in captured test summaries are historical snapshots.**

A further20 fresh pytest/native CPU child processes independently passed the
900ms pre-Grant startup/two-unit continuity test at fixed PR11 `9b969d0`.
[Every iteration and resources](../evidence/agent-4/receiver1-revision-drift-2026-10-18/cold20/summary.json)
are retained. This is CPU/Mock Authority evidence only; it does not explain away
the original LEASE_LOST or intermittent RTMP-tail failure or establish a production
SLA. The real host source must keep the physical tuple unchanged through the
retirement barrier; queued/in-flight network responses are not proof that an old
physical output remains current. Receiver final checks and real sink fencing
remain separate mandatory later work.

[Formal scope and ACK-boundary receipt](AGENT-4-R1-FINAL-ACK-RECEIPT.json) records the
owner FINAL ACK and unchanged six production blobs. The separate PR11 cgroup
scope P1 does not revoke this source-fix ACK or clear physical layer B.
