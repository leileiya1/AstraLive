# Receiver-1 Stop A/B/C repair result

**CCR BLOCKED — final Agent2 review pending, followed by Agent4/3 reconfirmation and Agent1 decision.** No new final owner ACK is inferred from [Agent2 direction acceptance](https://github.com/leileiya1/AstraLive/pull/9#issuecomment-6230806802). The [minimum WIP repair](https://github.com/leileiya1/AstraLive/pull/9#issuecomment-6230750761) was published before final contract freeze, then the four requested synchronization/testing/output-boundary conditions were incorporated.

Normative digest: `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1` over **22 files**, including the new typed Stop trace. Wire fields and durable-live-2/receiver-1 versions, all13 hash golden vectors and once-only START/ticket/Backend latch/Grant/Generation/Epoch/fact/UNKNOWN rules remain unchanged. The normative descriptions, operations, state guards, Go interface comments and Python model now agree on Stop-first final admission. [Manifest](../../../contracts/v0.5/durable-live-2/manifest.json), [normative Receiver contract](RECEIVER-BOOTSTRAP-CONTRACT.md), [ACK ledger](CCR-ADL-001-ACKS.json).

## Before/after evidence

At the reviewed8bca277/607c pin, the [Agent2 report](https://github.com/leileiya1/AstraLive/pull/9#issuecomment-6230628836) was reproduced without changing actor operations or Stop order. [Raw minimal reproduction](evidence/stop-2026-10-17/before-minimal.log), [original script](evidence/stop-2026-10-17/reproduce_abc.py), [three independent failing tests](evidence/stop-2026-10-17/before-independent-tests.log) and [Agent2 original15 test failures](evidence/stop-2026-10-17/agent2-original-script.log) are preserved. The original reviewer script's fixed archive import is left intact; an additional clearly labeled copy changes only that import root for repaired-tree validation.

| Defect | Before | Repair and evidence |
| --- | --- | --- |
| A / Guardian Stop before Backend Stop | `True ACTIVE_UNIT 1` after CLOSED_FENCED | Initial and final admission check irreversible local runId tombstone and legal state; no remote dependence, restage bypass or old-Grant reopen. Regression asserts Backend registration remains ACTIVE while no latch/TTS/media is added |
| B / Stop during Authority proof query | `accepted=True`, then `FENCED 1` | External read occurs outside local gate; captured revision/full identity/proof are checked on return and at final bounded handoff under the same gate as Stop/Finish/Restart. Regression rejects and media remains0 |
| C / Stop during final Consume proof | `True FENCED 0 REVOKED 1` | Activation and first ACK occur only at the final gated commit after the last proof. Stop winning suppresses ACK, leaves Backend latch/consumed Grant intact, appends UNKNOWN local audit and never starts TTS |

Initial independent ABC tests changed3FAIL→3PASS; original Receiver38 passed. Agent2 independently pre-reviewed15 original +20 new +3 patch +38 Receiver executions with zero failures, explicitly direction-only. Our import-root-only adaptation of its15 assertions also passed ([log](evidence/stop-2026-10-17/agent2-assertions-fixed.log)); it is not counted among the137 below.

## Final actual regression

Commands/exit codes/timings and raw output are committed in [evidence/stop-2026-10-17](evidence/stop-2026-10-17/). No failed gate is omitted from a claimed final PASS.

| Command / layer | Result |
| --- | --- |
| `/tmp/astralive-agent2-python/bin/python -m unittest tests.test_contracts tests.test_durable_live_contracts tests.test_durable_answer_contracts tests.test_answer_contract_repairs tests.test_receiver_contracts tests.test_receiver_stop_races -v` | **137 PASS** in18.526s: original99 test files unchanged plus38 new dedicated Stop tests. [command](evidence/stop-2026-10-17/contracts.json), [log](evidence/stop-2026-10-17/contracts.log) |
| `python scripts/validate-answer-contract.py` using the same interpreter | **PASS:**132 definitions /25 core+13 private operations /12 FSMs /13 vectors /313 protected hashes /3 typed Stop scenarios. [log](evidence/stop-2026-10-17/candidate-validator.log) |
| `python scripts/validate-durable-live-contracts.py` | **PASS:**44 frozen files /20 operations /4 vectors. [log](evidence/stop-2026-10-17/frozen-v1-validator.log) |
| `PYTHONPATH=runtime python -m pytest -p no:cacheprovider runtime/tests/test_durable_live_journal.py -q` | **11 PASS** in0.43s. [log](evidence/stop-2026-10-17/runtime-journal.log) |
| `go -C backend test ./...` | exit0, cached; no new v2 SQL acceptance. [log](evidence/stop-2026-10-17/backend-go.log) |
| `GO111MODULE=off go test ./contracts/v0.5/durable-live-2/examples/go/receiver` | exit0, interface package compiles; **no Go test files**. [log](evidence/stop-2026-10-17/receiver-go.log) |
| Go/Python canonical/lifecycle parity | Retained in137 tests;13 vectors unchanged, existing registered five-second renewal/one-TTS semantics pass |

The38 new tests cover A/B/C; local Stop with Backend still ACTIVE; first/final proof and Commit ACK; fsync/Observer/ACK/handoff pause points; Stop-first and admission-first order; Renew/Finish; FENCED/CLOSING/UNKNOWN; authenticated channel; proof expiry; both process restarts; irreversible restage denial; consumed-but-truncated UNKNOWN audit; normal Finish→Unit2; same-Grant32-way duplicates and same-ordinal32-way media competition. Real threads execute64 model Stop races (Consume16, Media24, Renew12, Finish12); each accepted action must linearize before Stop, with no eligible event after Stop. Separate deterministic pauses show local Stop completes while external RPC/fsync/Observer is blocked. Timeouts detect deadlocks, not a measured Stop latency SLA. Negative postStop operations add neither TTS nor accepted media; valid preStop media is explicitly distinguished.

## Synchronization and remaining implementation

The gate protects final check and bounded nonblocking acceptance together; it never spans RPC, fsync, Observer, network/sink/backpressure waits. Stop records tombstone/advances barrier before cleanup; Finish advances barrier/clears only that unit, preserving Unit2. The bounded diagnostic deque stores metadata only. A real adapter must propagate barrier/execution lineage to queued transport/decoder/sink output and recheck at its own irreversible edge; model ACK return/media counter is not physical delivery. Genuine drain must bind terminating unit and exact required tail/ranges, not counters. No latch deletion, renewed true ACK, ticket reissue, Stop-order swap, delayed Stop or retry loop is used.

Compatibility: integration remains `546ad9aa40bfe6949f32b55fb8ab6dc25d30dcb7`, already an ancestor; main remains `7fe5d24810e2df348c58dd7748e97ffbe5cff384`. [Compatibility evidence](evidence/stop-2026-10-17/compatibility.json) confirms zero changes under Backend/Runtime/production Guardian/Worker and frozen paths against integration;313 protected hashes and original99 test files preserved. Existing Agent1 worktree/branch reused, ordinary pushes only. PR9 stays Draft/unmerged, production Durable LIVE closed; no GPU started.

**NOT TESTED:** real PostgreSQL competing transactions/rollback/crashes; actual private IPC/OS/process identity/isolation; physical fsync faults/restarts; true Guardian output fencing, queue/decoder/sink handoff and drain-range correlation; Runtime asynchronous GPU lineage; DeepSeek/TTS/GPU/Chrome/WebRTC/RTMP; audience audibility or latency SLA. First-audio budget still includes registration where needed, facts/Permit, Authority RPCs, fsync/ACK, final proofs and local bounded admission. No3second SLA is asserted.

No known A/B/C model failure remains in the executed suite. The remaining contract approval blocker is **new-pin final owner ACKs**: request Agent2 first; only after its ACK request Agent4/3 changed-digest confirmation, then Agent1 may decide approval. Historical8bca277/607c Agent4/3 ACKs and the targeted direction acceptance are retained separately. Production implementation and acceptance remain future explicitly approved work; this PR does not authorize them.
