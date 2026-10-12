# Narration UNKNOWN review and cleanup finalization proposal

Status: design for F/A review; operator mutation API is **NOT IMPLEMENTED**.
Frozen `v0.5-frozen-1` is unchanged. No proposal grants speech replay, hot
Timeline unbinding, same-Session legacy media, or audible completion authority.

## Current evidence and safe behavior

The existing authenticated `GET /api/v0.5/narration/{sessionId}/` returns the
durable document, completed-fact cursor, ambiguous segment IDs, segment statuses, Stop
barrier and recovery reason. Session AND Room ownership precede this read.
An empty local Runtime map after restart is not nonexecution evidence.
The normalized A attempt/proof ledger is not currently a public operator view;
it must be reconciled separately rather than trusting an old document's
EXECUTING label after run takeover.

The continuity Stop guard preserves STOPPING and the physical Worker reservation
when native cleanup fails. A confirmed binding DELETE is required before that
reservation disappears. The Go semantic Stop projection also requires the
existing control_cleanup completion receipt and binding release, in the same
event transaction that applies SESSION_ENDED. An early event is retryable pending
proof; it does not itself prove cleanup or audience consumption.

Current limitations: failed STARTED cleanup is not automatically retried; a
Runtime restart cannot prove the old native sink closed. A's event projection
retry budget is thirty failures with one-second backoff; prolonged missing
cleanup proof can leave a DEAD event requiring explicit reconciliation. No
operator recovery mutation route or persistent reviewed-continuation link exists.

## Proposed control-only finalizer within existing authority

An alive Runtime may retain the original accepted/STARTED STOP_SESSION command
and repeat ONLY its idempotent native cleanup and binding release, then submit
the identical completion receipt. It must not call accept/start again, synthesize
audio, start a Worker generation, clear Stop, or resume Narration. Each attempt
rechecks the current authorized run/barrier and original command identity.

A review is required for lease expiration, terminal event ordering and bounded
finalization retry. Existing command IDs, fingerprints, producer incarnation,
receipt sequence and states remain unchanged. Across restart the missing task
context is not proof: preserve UNKNOWN until authenticated observation establishes
old output fencing/cleanup. Do not create a completed receipt for absent Session.

## Operator continuation decision requiring interface review

The initial mutation design is a versioned recovery-review operation, not a
normal comment, FORCE shortcut, or automatic ResumeNarration. Before implementing
it, F must approve the concrete request/response and A must ACK the transactional
authorization/audit seam.

Proposed request fields:

- source Session/narration/run/revision and exact ambiguous segment IDs;
- stable request ID/fingerprint, current snapshot fingerprint and evidence refs;
- explicit SKIP_UNKNOWN or REVIEWED_CONTINUATION disposition and reason;
- operator-reviewed remaining statements/fact IDs, fresh product snapshot hash;
- target fresh captured Session and required sinks, when continuation is requested.

Actor tenant/user come from the authenticated operator Session. Check current
ownership of BOTH source and target Session AND Room, provider/Worker ACL,
binding/output ownership, product/version, Stop barriers, revision and lease.
Changed-body replay or changed source evidence is a conflict. Audit disposition,
actor, source revision and reviewed plan in one PostgreSQL transaction with CAS;
no client-authored epoch, receipt, completed fact or media proof is accepted.

SKIP_UNKNOWN preserves the unknown attempt and all ambiguity evidence. Skipped
facts remain unverified, never silently added to completedFacts. Reviewed
continuation cannot claim an unknown sentence was heard; its quality report must
show intentionally skipped/unverified facts separately from required coverage.

Conservative first rollout requires the old Session to be durably stopped,
native-cleanup confirmed and binding released before a NEW captured Session
admits the reviewed plan through existing StartNarration/Outbox semantics. The
new run/epoch/generation are assigned by their existing authorities. A product
switch uses fresh facts and cannot inherit the old captured plan. Keep old
completed facts as historical evidence, not proof of completion under a changed
product/version.

## Required gates before approval/implementation

Real PostgreSQL and authenticated Go/Python tests must cover stale revision,
cross-owner Session/Room, revoked Worker/Avatar, released/expired binding,
changed product, Stop/FORCE race, response rollback, duplicate request,
delayed completion proof, Runtime restart and old-epoch frames. Assert no
generation/Outbox execution before the decision commits and no old paragraph
replay. Native Chrome/RTMP and human review remain separate quality gates.

All defaults stay off; the unsupported route returns no simulated success.
