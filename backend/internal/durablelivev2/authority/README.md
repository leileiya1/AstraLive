# Agent2 v2 Authority domain

This package writes actual PostgreSQL rows. It mounts no HTTP/IPC route, generates
no DTO, runs no Runtime/Guardian/GPU, and creates no physical output proof.

`Store.Call(ctx, authenticatedActor, frozenOperationName, document)` is the isolated
persistence seam. `Document` is a domain value, not another wire type system.
The official Agent4 DTO delivery is pinned at
`e3302f6b2bb19e0184cde3a6cbbcaf3ea4371565`. `New` installs its strict local
validator; `Handle` decodes/returns only its generated DTOs and checks the official
operation metadata. Agent4 must construct
`Actor` and request metadata from trusted peer credentials. Never decode Role/tenant/incarnation from
an untrusted body. Missing validation, installation source, assertion verifier or
physical evidence verifier fails closed. Validation is local and bounded; it must
not perform RPC or acquire application locks.

Trusted composition seams:

- `ProvisionProcess`: deployment-owned identity/key mirror, CONTROL_REGISTRAR only.
- `RecordInstallation`, `IssueStageChallenge`: trusted installation preflight outside
  SQL, exact immutable mirror and DB-time challenge under the existing Run lock.
- `ProductProjection`: current SQL product/snapshot/source/value hashes; Agent3 must
  use this authoritative projection instead of guessing hash representations.
- `Assertions`: verify the actual answer's assertions before SQL; SQL rechecks the
  pinned authoritative values/version under shared product locks before commit.
- `RecordDrainEvidence`: independent Observer verification outside SQL; exact
  registered artifact/ranges persisted under the Run lock. Fixture callbacks are
  synthetic, never enabled by a production constructor.
- `CheckpointProof`: independent physical sink-admission/fence evidence outside SQL.
  CONTROL completion additionally requires sealed contiguous trusted unit drains.
- `ReconcileExpired`: bounded SQL scan, serial recheck under Run lock; expired lease,
  old epoch, command deadline or unused Grant becomes durable UNKNOWN, never replay.

Lock order: existing Run -> lease/slot -> Turn -> Attempt -> Session/Binding/Room ->
process identity -> Inbox -> registration/answer -> unit -> grants/latches/evidence.
Bootstrap additionally locks pinned installation/process/output rows. Every v2
mutation takes the Run row first; Agent4 identity replacement/retirement/epoch
installation must use that same Run lock domain. No network/LLM/TTS/GPU/Observer/
physical-install wait holds a transaction. Local lock/statement budgets are bounded.

The Backend database role owns only the needed business privileges; do not give
its DSN to Runtime or Guardian. Migration grants neither participant SQL access;
PUBLIC privileges on new tables are revoked. Restricted Authority RPC credentials
are not CONTROL credentials. Run Stop seals the lease/term, persists stable STOP
Outbox commands and revokes registrations/grants atomically. It does not claim
that a physical publisher has stopped; active consumption becomes UNKNOWN and the
slot/output reservation stays until independently proven safe.

`JournalAccept`, `JournalPrepareAnswer`, `AcquireOutputPermit`, `JournalStart`,
`JournalStartAnswerSegment`, `JournalConfirmAnswerSegment`, `JournalSealAnswer`,
`JournalQueryAnswer`, `QueryExecutionStatus`, `ConfirmCheckpoint`,
`MarkExecutionUnknown`, `StopBroadcastRun`, registration/revocation and the three
restricted Backend Authority operations are implemented. Runtime receiver and
transport operations remain owned by Agent4/5. No fallback to v1 is permitted.

Only the first committed START/continuation response includes a random ticket.
SQL stores only its verifier. Only the first durable Consume winner returns true.
Exact duplicate returns false/null; different identity conflicts. Commit-response
loss, lost Runtime ACK, restart and UNKNOWN require metadata/audit reconciliation.
Neither a queried Grant nor an immutable receipt is executable authorization.

Reproduce real SQL acceptance, with PostgreSQL binaries and Go on PATH:

```sh
python3 backend/internal/durablelivev2/authority/run_postgres_acceptance.py
```

This creates its own loopback cluster, runs the real race tests and stops only that
cluster. Its data/logs remain in its newly allocated temp directory. Tests refuse a
non-loopback/non-`agent2_v2_` database. The SIGKILL test kills only its own child after
SQL commit. No shared database, external provider, GPU or public stream is used.
