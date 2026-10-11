# Agent A review of C's shared persistence and locking hook

Recorded 2026-10-12 Asia/Taipei. This is a read-only, source-owner review of C's
shared App integration, not a merge into A or main and not whole-product approval.
A production source remains `a28a4098a9014d9f7577d541048b2e110f1fc325`.
The correction lives in C's `bf66c18b3f77b71646e04e74f5e40b8d7200be32`;
an integration must consume that correction, not the initial C candidate alone.

## Reproduced failure and correction

The initial C candidate `06b182f840e0dc110a150a687e7ce016744edb3b` exposed a
lock cycle: Scheduler held its mutex while Gate waited for a Session SQL row;
the retirement transaction held that row while the borrowed App control hook
called Interaction.Stop, acquiring the controller mutex and waiting for Scheduler.
The borrowed Commit was a no-op. SQL rollback could therefore leave a LIVE
Session with its in-memory Scheduler stopped, while another room waited on the
controller mutex. This includes the shared App helper's premature memory effect;
it was not merely a C state-machine defect.

A ran the **same diagnostic bytes** on two immutable `git archive` snapshots,
using an A-owned PostgreSQL 17.11 cluster, per-test isolated schemas, and `-race`:

| C source commit | Exit | Hook duration | Gate | SQL after rollback | Scheduler stopped | Other room blocked |
| --- | --- | --- | --- | --- | --- | --- |
| `06b182f` | 1, expected diagnostic failure | 801.24625ms | Deadline exceeded | LIVE | true | true |
| `bf66c18` | 0 | 8.337625ms | No error | LIVE | false | false |

The diagnostic uses a populated controller entry and real Scheduler/Gate/shared
retirement hook. It deliberately rolls the outer SQL transaction back and has
no background worker, so it isolates pre-commit cancellation. The separate
production `Ensure` worker tests below verify committed-state projection.
These observed durations are diagnostic evidence, not a latency SLA or benchmark.
[Original failure](before.log), [corrected result](after.log),
[identical fixture](a_review_borrowed_stop_test.go.txt).

The correction uses a nonlocking advisory MVCC Gate; locked Select still checks
authority at admission. Scheduler reads Gate outside its mutex and rechecks
Stop/mode/in-flight/interval/TTL afterwards. The App hook performs only SQL work;
the existing worker projects committed Stop/FORCE outside both mutexes, before
the idle shortcut, with an epoch/sequence watermark. Concurrent product
retirement and operator Stop reuse the first immutable STOP_SESSION intent.

## Independently executed checks on the fixed archive

A also ran the following C tests against the fixed immutable archive, with real
PG and Go race detection. Six top-level tests passed, exit 0:

- `TestPostgresStartAtomicFingerprintProductStop`
- `TestPostgresFailedForceIdempotencyRollbackAndStop`
- `TestPostgresAdvisoryGateNeverWaitsForSessionLock`
- `TestPostgresBorrowedControlRollbackPreservesActiveScheduler`
- `TestPostgresActiveSchedulerProductRetirementAndConcurrentStop`
- `TestBlockedGateDoesNotBlockStopAndRechecksAfterRead`

[Complete focused log](fixed-focused.log). The public response-write failure is
an intentional database trigger fault, not a service test failure. The populated
production worker/queue cases cover Stop/FORCE before commit, rollback, actual
commit, historic FORCE not overriding a later permitted local mode change,
price/product retirement with concurrent manual Stop, and another-room snapshots.

```sh
# In a git archive of bf66c18, backend/:
go test -race ./internal/narration ./internal/interaction \
  -run 'Test(Postgres(StartAtomicFingerprintProductStop|FailedForceIdempotencyRollbackAndStop|AdvisoryGateNeverWaitsForSessionLock|BorrowedControlRollbackPreservesActiveScheduler|ActiveSchedulerProductRetirementAndConcurrentStop)|BlockedGateDoesNotBlockStopAndRechecksAfterRead)$' \
  -count=1 -v
```

Use `DURABILITY_TEST_DATABASE_URL` for an isolated test PostgreSQL database.
No shared PostgreSQL/Redis service or C/F source was changed. The owned manual
cluster is stopped after the review. Source comparison returned exit 0 for A's
migrations, durability/recovery packages, Runtime durability client/event spool,
and private HTTP durability handler between A `a28a409` and C `bf66c18`.
Callback attachment occurs before the dispatcher/coordinator/HTTP startup.

**Agent A scoped ACK:** C `bf66c18` shared transaction/locking integration only.
This does not replace F acceptance, assert native/GPU/audibility success, approve
default enablement, or close C's documented UNKNOWN-tail continuation API gap.
C's native/long-run reports remain C-owned evidence. No C FSM or public contract
was changed in this A review.

## Reproduce the independent diagnostic

Python with `tarfile` data-filter support, Go, the C repository's Git objects and
an isolated PostgreSQL test database are required. The runner archives the exact
commit, overlays only the test fixture in its temporary directory, prints the
source commit and fixture hash, and removes that directory on completion. It
does not check out, modify, or merge C's branch.

```sh
python3 docs/v0.5/evidence/agent-a/c-shared-review/reproduce.py \
  --repo ../AstraLive-agent-c --revision bf66c18b3f77b71646e04e74f5e40b8d7200be32
```

Set `DURABILITY_TEST_DATABASE_URL` in the environment. Substitute `06b182f` to
reproduce the original exit-1 failure. Keep both logs; do not reinterpret the
original failure as a PASS.

SHA-256:

```text
ed7aa2326a07e85a298337b96c0814cd3d94b33854f169076ee64924f7908f55  a_review_borrowed_stop_test.go.txt
b9230dc371be0d7162d79b9376085c4de654e370b48843484b669a11e42e2fb9  before.log
05535089a225287f2d0285a7ff91963a9b3c74574f4574e2ac9cdfd59f5412ea  after.log
2b0c176bc5bc4aab6dbeba0ffe803cf29485a5311559c6db1a31d0991ab83ee0  fixed-focused.log
857b0b78730de508574463ce11943c2a1801814c9a5d995e71a8a7bbb7f3a934  reproduce.py
```
