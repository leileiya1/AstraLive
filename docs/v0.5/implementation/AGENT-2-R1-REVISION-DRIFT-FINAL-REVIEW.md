# Agent 2 — R1 revision drift final security review

**Layer A: AGENT 2 FINAL ACK — R1-INSTALLATION-REVISION-DRIFT SOURCE FIX.**

The original P1 is resolved in Registrar source `58cbc59042c70f9010a368f963257fdad5154b91`, under the supported **genuinely coordinated, immutable physical-source lifecycle**. Actual no-overlay test archive: fixture/protection commit `08af1049250d2657d7afb5e303d97a02e9761570`. Latest integration pin `a0a05071d3eae1cc918fc7d7c2c56604fea380da` changes only documentation/evidence after that tested commit; the six relevant Registrar production files match all three pins byte-for-byte. This ACK covers code and existing SQL permission boundaries, not deployment/media acceptance.

**Layer B: BLOCKED — production PhysicalSource / Linux / Publisher / Sink isolation.** No positive production source exists. Implementing the Go capability does not prove that a physical process obeys it. No main/PR8/PR11 merge, LIVE/GPU enablement or real platform push is authorized by this review.

## Original P1 independently retested

The original 623-line Agent2 source is byte-identical to the prior evidence and the submitted test: SHA256 `db675df45a7bd9ce0cce4dd40ade107d19609b8137873e73e00570eb79914463`. No original assertion, observation behavior, timing, concurrency or deadline was edited. Agent4's separate test-only capability method and immutable fixture gate are explicitly synthetic; they do not establish physical coordination.

| Check | Independent actual result |
| --- | --- |
| A: Install/Stage1 → observed source2 → old Register, three repetitions | 3 PASS; old registration refused |
| B: Register1 → observed source2 → Query/Consume, three repetitions | 3 PASS; old proof/first consumption refused |
| All original owner probes | 15 top-level PASS, 7 subtests PASS, 0 SKIP |
| Latest Agent4 Receiver1 real-PG/race group | 22 top-level PASS, 6 subtests PASS, 0 SKIP |

The old review's six real failures remain historical evidence; they are not overwritten or attributed to this new source. The fix compares the complete observed installation, immutable gate snapshot, SQL mirror/native process identities and pinned Guardian public key, rather than comparing only the descriptor or an old receipt with an old mirror.

## Lifecycle / SQL conclusions

- Nil and Observe-only sources cannot install. Nine additional gate/snapshot subcases reject a nil gate or mismatching revision, Session, Generation, output Binding version, Runtime incarnation, Guardian principal, observer principal or fence reference. They create no new mirror/registration. The gate snapshot is a complete value object, not a caller-supplied success boolean.
- Positive Install, StageRequest, CONTROL Stage, Register, installation read and Authority Query/Consume obtain an installation reader before the relevant SQL operation. Readers span `Store.Handle`'s final commit and response construction. The actual native response-writer test confirms retirement cannot finish while the handler still holds its reader at response emission.
- CloseAdmission is irreversible and immediately denies new readers. Already admitted work can finish only against the unchanged old physical tuple; an uncertain committed latch is spent, never reset. Retire waits without SQL or a held gate mutex, then locks the existing Run first, retires the immutable mirror with `retired_at`, and performs the official revoke CAS. Physical replacement is allowed only after the entire barrier succeeds.
- The Run-first mirror transaction and subsequent official revoke transaction do not invert Authority's Run/lease/slot/Attempt order. The closed local gate and retired mirror cover the gap between them. A rollback, cancellation, database outage or CAS conflict never reopens admission. CAS conflict is success only after accurate durable REVOKED readback; an ACTIVE readback remains an error.
- PhysicalSource observation, IPC/network, reader drain and fsync do not execute while holding SQL transactions or the gate mutex. NOWAIT from another connection succeeds during reader-drain wait; existing source-observation tests also pass. Store's existing short transaction continues to enforce Stop, epoch, binding, unique latch and earliest output deadline.
- Retired/revoked/current-source mismatch paths deny new registration/read/proof/Consume. Immutable installation, registration, consumption and original Grant records are retained. Consumed execution becomes UNKNOWN on revoke; no new ticket or replay right is created. Fresh native identities/key/Generation cannot reuse an old installation. Historical Confirm/consumption queries remain knowledge only.

### In-flight ACK is not a new authorization

The response-writer probe deliberately pauses **after the SQL consume committed and final observation passed**, then closes admission before allowing the HTTP write. It observes an already committed `consumeAuthorized=true` arriving after CloseAdmission. The reader remains held through that write, so Retire cannot yet complete or legally change the physical tuple. This is an in-flight acknowledgement of a pre-close linearization, not a new post-retirement grant. Claims that *no positive bytes can ever arrive after CloseAdmission* would be too strong and should be clarified in handoff prose/comments.

A separate test delays that committed Backend reply until Retire has durably completed and the source revision changes, then delivers it to the actual fixed-PR11 Receiver with official transport/DTOs. Receiver's final proof query rejects it: no ACTIVE gate and zero positive Receiver ACKs; SQL latch remains exactly one and execution UNKNOWN. Transport ACK alone must never start TTS/output. Reader lifetime, Receiver's final proof/gate, and a physical Sink fence are separate required boundaries.

This clarification does not reopen the source-drift P1: the supported physical owner cannot change the tuple until reader drain and durable retirement complete. No additional P0/P1 code correction is requested from Agent4 for Layer A. The in-flight ACK qualification should remain explicit in future wiring and acceptance.

## New independent adversarial verification

New tests are separate `agent2r1review` build-tag files in the disposable archive; no Agent4 production or original test file was modified. The native peer extension is a separate test fixture, not a production operation or transport change.

| Check | Result |
| --- | --- |
| New adversarial group | 12 top-level PASS, 13 subtests PASS, 0 FAIL |
| Owned SIGKILL helper's direct top-level entry | 1 SKIP; actually executed by its passing parent, which verifies SIGKILL |
| Forty-call withdrawal, pre-commit withdrawal, delayed ACK, CAS groups ×3 | 12 top-level PASS, 6 subtests PASS, 0 FAIL |
| Full unchanged Backend Go test | 267 top-level PASS, 204 subtests PASS, 0 FAIL, 13 SKIP |
| Full unchanged Backend Go race | 267 top-level PASS, 204 subtests PASS, 0 FAIL, 13 SKIP |
| Full Go vet / tagged probe vet | PASS |
| Frozen contracts / Journal / official wire / adapter-resource | 137 / 11 / 13 / 8 PASS |
| Both validators / generator check | PASS |
| Approved-fixture original Guardian v1 | 25 PASS |

These groups overlap and must not be summed into a unique total. Full Go tests use normal tags and unmodified source. The additional test files do not replace the 267-test suite with an overlay.

Coverage includes:

1. **40 real native Query/Consume calls versus Retire** while the Run row is locked. The unchanged bounded listener admitted 16 active readers and refused/timed out excess work; all 40 were submitted, no positive result crossed withdrawal, and at most one spent latch remained UNKNOWN. No concurrency/timeout was reduced or widened.
2. **Retire before first Consume SQL commit**, followed by drain and durable revoke. No positive gateway result; any committed latch stays spent/UNKNOWN.
3. **Backend Commit before ACK, ACK delivery after durable Retire**, with actual Receiver final proof denial, no ACTIVE unit and no positive Receiver ACK.
4. **Stop or output expiry while readers drain**, with independent Run NOWAIT acquisition proving no SQL lock is held by the drain wait.
5. **Cancelled retirement** with a held reader, then explicit retry: admission stays closed and source unchanged until successful retirement.
6. **CAS conflict with accurate durable readback**, both already REVOKED and still ACTIVE; only the former may complete. The latter stays closed and requires explicit retirement retry.
7. **Real partial SQL failure**: a test-only trigger in the owned database rolls back revoke after mirror retirement committed. Old mirror is retired, registration remains ACTIVE, latch unchanged, no reader can enter; removal of the fault followed by retirement retry yields REVOKED/UNKNOWN.
8. **Actual whole owned PostgreSQL shutdown/restart** during retirement. Failure keeps gate closed and source revision1. Restart can surface an old idle connection's exact `57P01`; that error is asserted closed and permits at most three explicit retirement-only retries. No Consume retry or new authorization is attempted. Successful recovery preserves latch1/UNKNOWN.
9. **Owned Backend SIGKILL after CloseAdmission with an undrained reader**, before mirror retirement. The parent verifies actual SIGKILL and cleans only its native children by PID+creation identity. Fresh Registry cannot reconstruct old capability; latch survives. Explicit authenticated CONTROL reconciliation marks UNKNOWN, not automatic recovery/replay.
10. **Stable two-unit continuation through real native Authority RPC** with independent Grant/execution/latch per unit. Observer/drain evidence is an explicit fixture, not proof of physical media drain. Existing long consumed-proof renewal and earliest-output-deadline tests also pass in the full suite.
11. **Reader held through response construction/write**, with the exact late-ACK qualification above.
12. **Complete immutable tuple enforcement**, including the nine gate/snapshot subcases.

Existing 22/15 groups additionally exercise registration/Consume ACK loss, Stop before final proof, source withdrawal, old epoch/key/Binding, replacement native processes, same-Room coexisting Generations, dual Tenant/Room dispatch and unique-latch retention. Actual PID reuse is NOT TESTED; replacement and creation-identity checks are not presented as PID-reuse evidence.

## Production source assumption — still BLOCKED

The lifecycle assumption is potentially implementable on Linux only if a single independently trusted owner controls **every** relevant physical Generation/source/process/key/fence transition and actual Publisher/Sink access. The owner must close admission before change, retain the old physical tuple until readers drain and SQL retirement/revoke succeeds, fail closed on crash/partial failure, and prevent untrusted Runtime/Worker or an old publisher from independently changing or publishing outside this path.

Agent5 must demonstrate actual ownership/credential isolation (UID/group/socket/network/cgroup or equivalent reviewed profile), revoke old publisher credentials/connections, fence real Sink acceptance and in-flight old media, and prove restart behavior from independent evidence. PID liveness, an interface implementation, an immutable SQL row, a CLOSED boolean, mocks or a final Backend ACK are insufficient. A physical process that can bypass the barrier invalidates the assumption and keeps production BLOCKED. The frozen co-located profile is not approval for a new remote lifecycle protocol.

No real Linux PhysicalSource, physical Session/Generation installation, malicious bypass resistance, old Publisher credential revocation/Sink isolation, production once-TTS/fsync/Observer/drain, GPU/RTMP/WebRTC/audience/SLA acceptance was performed. Production multi-room Assertions/lifecycle composition is also not accepted by these fixtures. Layer A's ACK must not enable LIVE or waive any of these gates.

## Evidence, SKIP, provenance and cleanup

[Summary and all SKIPs](../evidence/agent-2/r1-revision-drift-final-2026-10-18/summary.json), [final adversarial raw output](../evidence/agent-2/r1-revision-drift-final-2026-10-18/owner-final-signal-verified.txt), [exact final probe source](../evidence/agent-2/r1-revision-drift-final-2026-10-18/agent2_gate_adversarial_test.go.txt), [raw original six repetitions](../evidence/agent-2/r1-revision-drift-final-2026-10-18/original-revision-repeat3.txt), [source audit](../evidence/agent-2/r1-revision-drift-final-2026-10-18/source-audit.json) and command files retain actual outputs/exit codes. Dedicated PostgreSQL17.11 used fsync/synchronous_commit/full_page_writes ON. Only this run's marked cluster and newly created processes were controlled; data/logs are retained and the cluster is stopped.

The full suite's 13 SKIPs include opt-in SQL/config/browser/export/Redis tests, the legacy owned-cluster outage test and two subprocess helper entries. They are listed verbatim in `go-skips.json`; no missing opt-in was counted as PASS. The new owned-cluster outage test and actual helper execution are separate evidence and do not relabel those legacy SKIPs.

Two test-development failures are preserved: direct type assertion initially misclassified correctly rejected wrapped `OUTPUT_FENCE_UNPROVEN` errors (fixed to `errors.As` without changing the expected code); immediate post-restart Ping failed on a terminated idle PG connection (final test asserts fail-closed on that exact error and bounded retirement-only retry). Neither changes the original 623-line probe or suppresses a production failure. No deadline, safety margin or concurrency assertion was weakened.

All **474** original tracked Go/Python/SQL files remain byte-identical to tested commit08af. All seven migrations match the Agent2 delivery, all 22 normative files and manifest match freeze `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`, and independently recomputed digest is `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`. The sole registered protection change between58cbc and08af is the approved Guardian fixture postimage; no other protected expectation was changed. Review evidence is submitted only on the existing Agent2 branch, with no new worktree/agent/branch or production implementation edits.
