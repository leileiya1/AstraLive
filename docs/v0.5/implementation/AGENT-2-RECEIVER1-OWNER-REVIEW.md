# Agent 2 Receiver1 Registrar / Authority owner review

Decision: **BLOCKED — P1 R1-INSTALLATION-REVISION-DRIFT**. This is an independent review of implementation `0a67a35e5815031d4d0d0a4ca4da89882e31e079`, not production acceptance. Integration audit pin: `eb00428eeb1f0506e9b71eea47480ba4d982c7db`. The latter changes only documentation/evidence after the implementation. No owner implementation, SQL migration, wire, shared entrypoint or frozen file was edited.

## Required correction: current physical revision is discarded

`backend/internal/durableintegration/receiver1/registrar.go:177–214` observes the trusted source and checks descriptor, Guardian/observer principal, CLOSED_INSTALLED and current durable term/output. It never compares `actual.InstallationRevision` with the installation mirrored in PostgreSQL. `Register` at lines 266–282 discards the observation returned by `VerifyInstallation`. `eligible` and `Read` also accept the differing revision. Existing Authority registration SQL checks the signed receipt against the old immutable mirror; that alone cannot establish that it is still the current source revision.

The frozen `RECEIVER-BOOTSTRAP-CONTRACT.md:9` requires a preflight independent read followed by rechecking the mirrored immutable source/current revision in the short transaction. A source/mirror discrepancy must fail closed even if every descriptor field still matches. This is not a request to mutate the immutable mirror or add a wire operation.

Minimal actual event sequence:

1. Start owned native Runtime/Guardian processes, provision their independent identities/key, JournalAccept, and install an explicitly injected PhysicalSource reporting revision 1. PostgreSQL mirror is revision 1.
2. Obtain a DB-time Stage challenge and real Guardian-signed CLOSED_STAGED receipt for revision 1 through authenticated CONTROL Unix IPC.
3. The **same source object originally supplied to Install** now reports revision 2, with the same descriptor, principals and fence reference. This models source/mirror drift, not JSON enrollment. No Registry record, Pin, SQL mirror, key or production source is modified.
4. Registrar sees source revision 2 but registers the old signed receipt as ACTIVE. Prepare → Permit → START → real Guardian Authority RPC Commit succeeds with `consumeAuthorized=true`, writing one latch.

Expected: reject the inconsistent current source before granting registration/execution eligibility. Actual final log:

```text
STALE_PHYSICAL_REVISION: source=2 staged=1 mirror=1 register=*wire.RegisterReceiverBootstrapResponse ACTIVE bootstraps=1; real Authority RPC ok=true consumeAuthorized=true latches=1
```

Second variant: register legitimately at revision 1, then advance the same source to revision 2 before Query/first Consume. Actual:

```text
STALE_PHYSICAL_REVISION_AFTER_REGISTER: source=2 mirror/staged=1 queryOK=true consumeOK=true consumeAuthorized=true latches=1
```

Both variants reproduce in all three repeated real-PG/race runs. They expose one P1 safety invariant defect, not six separate findings. There is one latch per case; this review does not claim observed duplicate TTS or physical output. Production remains unmounted/default-closed, so this is an integration-blocking assembly defect, not evidence of an enabled production bypass.

Agent4 must retain/compare the exact independently installed source tuple, including installationRevision, across Stage, Register, installation read and effectful Authority eligibility. Bind the fresh observation to the existing immutable mirror and Stage receipt; propagate retirement/revocation through the existing short run-lock/CAS domain. A changed/inconsistent source must deny current proof and first Consume; an old signed receipt plus an old mirror is insufficient. Do not silently update the immutable revision, rewrite a binding, remove a latch, reconstruct a ticket, or hold SQL locks across source/IPC observation. Review the source-transition versus SQL-mirror linearization with the future physical adapter, rather than adding only a one-time registration comparison. If execution was already consumed, retain its latch and conservative UNKNOWN/revocation audit.

## Independent execution

All SQL used a newly initialized, marked, loopback-only PostgreSQL 17.11 cluster owned by this review. Final inventory confirms the exact expected port/database and fsync, synchronous_commit and full_page_writes enabled. Child processes are new dedicated local Go/Python test peers; fixed PR11 `d8eb05e79661b859547242575e0ac6d1d7303aa1` is a disposable archive, not a merge. The Python interpreter is reused read-only; each peer/credential/key is newly launched by this test. Physical installation, closed outputs and some producer business calls are explicit fixtures.

| Check | Actual result |
| --- | --- |
| Original Receiver1 tests, unchanged | 14 top-level PASS / 0 FAIL / 0 SKIP; 6 passing subtests |
| New independent owner probes | 13 top-level PASS / 2 FAIL / 0 SKIP; 7 passing subtests |
| Final combined Go/real-PG/race | 27 top-level PASS / 2 FAIL / 0 SKIP; 13 passing subtests; no race detector warning |
| Two source-revision variants × 3 repeats | 6 FAIL, same defect reproduced each time |
| Focused Go vet | PASS |
| Frozen contract regressions | 137 PASS |
| Runtime Journal | 11 PASS |
| Official wire / adapter-resource | 13 / 8 PASS |
| Candidate and frozen validators / generator check | PASS |

Passing probes cover nil PhysicalSource with no new SQL installation, eight concurrent registration-history reads without re-Stage/Grant/latch, eight concurrent revoke attempts with revision exactly 2 and UNKNOWN/latch retention, actual replacement process denial, source loss denial, source observation outside SQL run locks (NOWAIT), source/output expiry and revoke during in-flight first Consume, seven mismatched scope/source identities, historical consumption after source failure, Guardian denial of CONTROL/Journal routes, and final Consume validation delayed 220ms against output expiry of 150ms with no committed latch/positive RPC. The last test waits for the same run lock after validation, so it verifies the eventual rollback rather than an early count.

Two tenants/rooms/runs on the same Store/Registry pass repeated source lookup, real native Authority RPC and cross-tenant denial. The delivered InstallationSource is a single command-dispatched registry; no last-session-wins callback was found there. The test supplies an explicit command-dispatched Assertions verifier. **A production multi-room Assertions composition root is not delivered or accepted**; it must not assign each session's verifier to a shared Store field during later wiring.

Role checks use kernel PID/UID/birth plus independently provisioned capability and process scope, not JSON roles. CONTROL uses a distinct capability/channel. The listener exposes only the three frozen Guardian Authority operations plus the separately targeted installation read; no SQL or enrollment endpoint exists. Runtime receives no DB/Guardian/CONTROL secrets from the launcher. Registration-history confirmation carries knowledge, not a new ticket or execution right. Run/lease/slot/Attempt and shared-output checks remain in the existing Authority transaction domain. External source/process/IPC observation occurs outside that domain. Ed25519 verification is a fixed-size local operation inside the short registration transaction; no external signing or network wait holds its SQL locks.

## Evidence and reproduction

Raw evidence: [receiver1-owner-review-2026-10-18](../evidence/agent-2/receiver1-owner-review-2026-10-18/summary.json). The final supplemental test is [agent2-owner-review_test.go.txt](../evidence/agent-2/receiver1-owner-review-2026-10-18/agent2-owner-review_test.go.txt). Original tracked test/implementation files remain unchanged; the test-only constructor clones the original fixture constructor solely to inject the source at initial installation. It does not replace a Registry entry. [source-audit.json](../evidence/agent-2/receiver1-owner-review-2026-10-18/source-audit.json) independently compares all 469 original Go/Python/SQL files with the immutable implementation archive, all seven migrations and 22 normative files with their pins. Frozen digest remains `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`.

To reproduce, export fixed implementation and PR11 into disposable non-worktree directories, create a new owned PostgreSQL database, and copy only the supplemental `.go.txt` to `backend/internal/durableintegration/receiver1/agent2_owner_review_test.go` in that archive. Supply `AGENT4_RECEIVER1_DATABASE_URL`, `AGENT4_RECEIVER1_OWNED_ROOT` containing the exact test marker, `AGENT4_RECEIVER1_PYTHON`, `AGENT4_PR11_ARCHIVE`, and PYTHONPATH for that archive. Use the original fixture's dedicated-database guard. Then run from its backend directory:

```sh
go test -race -json -count=1 -timeout 120s ./internal/durableintegration/receiver1
go test -race -json -count=3 -timeout 120s ./internal/durableintegration/receiver1 -run '^TestAgent2ReviewCurrentPhysicalRevision'
```

Exact local commands, fixture scripts, final test source hash, PostgreSQL inventory, output and cleanup are retained. Exploratory failures remain in raw history: an overlong initial Unix socket path; a test-side unchecked pgx scan using custom wire.ID (corrected to string and checked); initial pointer-swapping probes superseded by the initially injected stable source; and owned PG restart commands missing explicit port options, whose connection-refused runs are harness failures, not product regressions. Final stable-source runs use an explicit loopback port/socket and successful database inventory before testing. No assertion, frozen deadline or source consistency check was weakened.

## Acceptance limits and cleanup

Production PhysicalSource remains absent; **nil actually refuses Install**. This existing default-closed limitation is correctly disclosed, not a second newly discovered bypass. Real physical installation/Generation, old publisher isolation, production Registrar/lifecycle identity source, Linux UID/group/socket/network/cgroup isolation, actual PID reuse, host restart, production Runtime once-TTS, physical Guardian fsync/output/observer/drain, GPU/RTMP/WebRTC/audience and SLA are NOT TESTED. The full Go suite and Guardian v1 regression were not rerun in this focused review; Agent4's historical original Guardian v1 4 PASS/21 fixture errors are not waived or relabeled PASS.

Only the review's own cluster and child processes were stopped; data/logs are retained and cleanup confirms the owned cluster is stopped. Existing worktrees/branches/main, other owners' code, actual databases/Redis, LIVE and GPU were not changed. Agent4 must resolve the P1 and request independent re-review before an Agent2 ACK of this assembly.
