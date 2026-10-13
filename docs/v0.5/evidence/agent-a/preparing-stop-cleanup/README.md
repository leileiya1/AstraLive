# Durable PREPARING Stop: admission-only correction

Candidate: `e81a9f64335cd44eba144d41b2c21859ae7261c9`, based on actual pilot source `ada6f31f4f3693b1180cca941503b5b9a90cdee2`. Shared file authorization: F explicitly authorized the A-owned minimal durableControl Stop whitelist correction; reason is startup-failure cleanup, dependency is C's separately implemented Runtime cleanup proof, final merge owner is F. No F/C production files, SSH/GPU hosts, or frozen snapshots were changed.

## Diagnosis and change

Pilot 3 retained business Session PREPARING, run ACTIVE/control barrier 0, and a successfully released provider binding after the Runtime adapter's configure_session AttributeError. The public Stop handler reached durableControl but its LIVE/DEGRADED/STOPPING whitelist rejected PREPARING. The same-source, same-scenario negative test reproduces actual HTTP 409 / SESSION_NOT_READY. Ordinary Current/Finish/renew/takeover failing after binding release is conservative authorization behavior, not an instruction to retry ambiguous BEGIN_RUN.

Only durable STOP_SESSION admission now additionally accepts PREPARING. Existing CleanupRun ownership checks, transaction, expiry handling, immutable Stop idempotency, SQL seal, Timeline fence and barrier remain intact. Ordinary Current, FORCE/SPEAK admission, recovery, UNKNOWN and flags-off v1.1 state transitions are unchanged. The new behavior produces HTTP 202 / STOPPING, not ENDED and not a claim of completed physical cleanup.

## Fixed-source validation

The immutable candidate archive passed the full module gate (result.json): full Go plus race, owned PostgreSQL migrations/authorization/outage/Redis-off tests, 12 durable Python tests, v1.1 contract validator; Runtime 247 tests with 12 explicit skips; frontend 40 tests and build. Additional immutable staging contract/profile/hash regression: 23 tests PASS. The startup/control PostgreSQL tests use production A Accept/StartAttempt/Claim/Finish and public HTTP authorization/idempotency, with an explicitly injected failed delivery and expired leases.

The new oracle verifies unknown startup is never retried; binding release fences ordinary completion; owner-authorized Stop can renew only cleanup authority, persist one immutable STOP_SESSION and barrier, and enter STOPPING. Anonymous (401), foreign user (404), bad Origin (403), and foreign room owner (404) cannot persist Stop. Repeated public Stop keys reuse the original operation. Four concurrent Stops and four FORCE calls retain one cleanup command and admit no FORCE/generation. Existing recovery/Stop/FORCE tests also pass.

`before-negative-overlay.go.txt` is the actual earlier test overlay used against immutable ada6f31. It failed specifically at PREPARING Stop 409, not fixture setup. The final candidate adds the concurrent race case as well; its complete test source is committed in backend/internal/durability/preparing_stop_postgres_test.go. The first full-gate invocation stopped before tests because the requested F/frontend/node_modules directory did not exist; the successful run borrowed main frontend dependencies after exact lockfile verification. No source or timeout was changed for that infrastructure correction.

## Limits and remaining integration dependency

This A candidate deliberately supplies no Runtime/native completed receipt. It tests cleanup acceptance and actual A execution admission only. Absence from Runtime memory cannot establish physical release, and a cross-incarnation restarted Runtime must not infer it. C owns the strict same-incarnation pre-physical failed-create marker plus actual captured-binding release ACK and original Stop control_cleanup/SESSION_ENDED wiring. Until that seam is independently verified, real Stop-finalization is CONDITIONAL; startup failure remains a real Golden blocker, not a successful end-to-end run. No unit/software result establishes real GPU, Chrome/RTMP, natural continuation, viewer audibility, or latency acceptance.

Pilot 3 evidence has accepted + execution_started receipts but lacks full BEGIN_RUN outbox/inbox projection. Its exact UNKNOWN code should not be asserted from those two receipts alone. This test's UNKNOWN state is explicitly injected through production A journal behavior and proved in SQL. F should capture safe state/code/proof-reference projections in the next pilot.

## Reproduction

Run the module gate using the exact candidate SHA and a matching frontend lockfile, as recorded in result.json. It creates and cleans its own PostgreSQL. For the negative comparison, archive ada6f31, copy before-negative-overlay.go.txt to backend/internal/durability/preparing_stop_postgres_test.go, supply an owned PostgreSQL through DURABILITY_TEST_DATABASE_URL, and run `go test -count=1 -v ./internal/durability -run '^TestPreparingStopUnknownStartupReleasedBinding$'`. Expected failure is the preserved HTTP 409. No external provider credentials are needed.
