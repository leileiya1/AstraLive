# Receiver-1 contract repair result

Historical8bca277/607c receiver-interface report. Agent4 and Agent3 subsequently ACKed that exact pin; Agent2 then blocked its Stop A/B/C model defects. The [current Stop repair result](STOP-REPAIR-RESULT.md) supersedes this report for current status/digest.

**CCR BLOCKED — final Agent4 interface ACK pending.** Agent4's [DIRECTION ACCEPTED](https://github.com/leileiya1/AstraLive/pull/9#issuecomment-6227939254) permits this candidate freeze and does not approve implementation. The [minimal direction request](https://github.com/leileiya1/AstraLive/pull/9#issuecomment-6227780199) was posted before final normative submission. This repair targets only the [round2 Receiver gap](https://github.com/leileiya1/AstraLive/pull/9#issuecomment-6227620414).

Normative digest: `607c0dd00755556bb2b6daec75f19fda41642fd6bac7472523ca3c048118b81b`, covering21 files in [manifest](../../../contracts/v0.5/durable-live-2/manifest.json). Prior candidate `283f3b4578e8d8c98357ffb38301c959e5664509` / `54d5d5e2fa4d1c135d186c1031f68e657f03c332e2473c61c6527be23d8bef57` remains the historical Agent2/3 ACK pin, not approval of these changed bytes.

## Agent4 pre-review conditions implemented

| Requirement | Delivered contract / model |
| --- | --- |
| Trusted source before registration | Independent CONTROL Registrar/Supervisor physical-install read interface; no Runtime enrollment. Closed stage reads physical provenance without registration/Artifact/Permit/latch; signed versioned receipt binds challenge, full scope/hash, install revision and pinned process key. Register rechecks Stop/current term/lease/Binding/output binding and source/CAS under run lock |
| Bootstrap before START | ACTIVE parent registration precedes first Prepare; Prepare atomically adds immutable Artifact child binding. First registered-Generation observation/Permit works in ACCEPTED. Ongoing proofs remain separate; existing PR10 STARTED-only v1 SQL is not reused |
| Cannot rebuild lost first START from IDs | First true START/continuation response alone includes cryptographic256-bit consumeTicket and remaining-time proof. Backend stores only domain-separated verifier. Private queries/receipts contain no ticket; missing/fake ticket cannot consume, including after lost continuation ACK |
| Unique consumption | Backend-owned unique grant latch, immutable scope/FKs/request identity, exact peer/channel/nonce, current proofs and active unit. Same exact request returns false/null; reassignment conflicts. Guardian gets no business SQL/CONTROL write privilege; Runtime has no SQL or Authority credential |
| Two ACKs / time | Distinct Backend commit ACK, local fsync, first Guardian ACK and Runtime once-TTS latch. Lost ACK/crash/late response is not rearmed. DB remaining budget is anchored before RPC on local monotonic+suspend clocks with100ms margin per hop; Query/arrival cannot reset TTL |
| Same Generation Unit2 | New Artifact/grant/execution in same Attempt/Turn/Generation after trusted predecessor drain. Media/renew/finish bind execution+Artifact/hash, continuous ordinal; finish closes old unit immediately. Delayed old traffic fails before/after unit2 switch. Source adapter must preserve original asynchronous work lineage, never relabel it from current slot |
| Stop / restart / isolation | Separate registration, grant, execution and Room-barrier FSMs. Stop/CAS races reject or consume-then-revoke without replay. New process credentials/incarnation/fence/registration required; old grants are not migrated. New v2 transport never falls back to PR10 v1 |
| Implementable handoff | [Normative receiver contract](RECEIVER-BOOTSTRAP-CONTRACT.md),13 private operation definitions/closed schemas/examples, Go interfaces, Python separate actors,68-message trace,13 hash vectors, storage/permissions/lock/error rules and Agent2/3/4/5 responsibilities |

## Actual validation

Commands, exit codes, timings and raw output are in [evidence](evidence/receiver-2026-10-17/).

| Check | Actual result |
| --- | --- |
| `/tmp/astralive-agent2-python/bin/python -m unittest tests.test_contracts tests.test_durable_live_contracts tests.test_durable_answer_contracts tests.test_answer_contract_repairs tests.test_receiver_contracts -v` | **99 PASS**, original61 retained +38 new Receiver regressions; no final gate deferred. [command](evidence/receiver-2026-10-17/contracts.json), [raw log](evidence/receiver-2026-10-17/contracts.log) |
| Candidate validator | PASS:132 definitions /25 core +13 private operations /12 FSMs /13 vectors /313 protected hashes. Also checks signature, operation closure, causal trace and consumption-ticket/identity hashes. [log](evidence/receiver-2026-10-17/candidate-validator.log) |
| Existing durable-live-1 validator | PASS:44 frozen files,20 operations,4 vectors. [log](evidence/receiver-2026-10-17/frozen-v1-validator.log) |
| Existing Runtime Journal pytest | **11 PASS**. [command](evidence/receiver-2026-10-17/runtime-journal.json), [log](evidence/receiver-2026-10-17/runtime-journal.log) |
| `cd backend && go test ./...` | exit0, cached; no dedicated DB/Redis service provisioned. [log](evidence/receiver-2026-10-17/backend-go.log) |
| `GO111MODULE=off go test ./contracts/v0.5/durable-live-2/examples/go/receiver` | typed interface sample compiles (no Go test files). [log](evidence/receiver-2026-10-17/receiver-go.log) |
| Go/Python parity | Existing tests compare all13 canonical golden vectors and the registered five-second renewal trace; wrong binding/deadline is rejected. New participant tests use separate clock bases and injected suspension/delay |

The38 new tests start unregistered (Generation/incarnation absent), execute physical-install/stage/register and exchange typed private messages across Backend Authority, Runtime and Guardian. They cover wrong identity/signature, two same-principal connections and different Runtime principals, Backend latch competition, both ACK-loss hops, local fsync failure points, Stage/Register and Consume/Stop ordering, process restart, ticket confidentiality/non-reconstruction, Runtime double-ACK rejection, long-unit proof renewal and old-unit traffic. Python locks and mock fsync/observer/PCM fixtures are contract evidence only.

**NOT TESTED:** real PostgreSQL transactions/competing connections/crash durability, live private IPC/OS isolation, real fsync failure/restart, real receiver decoder/continuous publisher, DeepSeek/XiaoYa/GPU, Chrome/WebRTC/RTMP, official audience or latency SLA. No paid GPU or provider was started. The first-audio cost includes physical install/stage/register when needed, source reads, signature/CAS, Prepare/Permit/START, Authority Query/Commit, fsync, ACK and final proof/deadline exchange. None is assumed free; no3second SLA is claimed.

## Compatibility and remaining work

Remote main remains `7fe5d24810e2df348c58dd7748e97ffbe5cff384`; latest integration remains `546ad9aa40bfe6949f32b55fb8ab6dc25d30dcb7`, already an ancestor. [Compatibility evidence](evidence/receiver-2026-10-17/compatibility.json) confirms zero changes versus integration under backend/runtime/output_guardian/infra/guardian/gpu_worker and frozen contract paths; all313 protected hashes match. Existing Agent1 worktree was reused; no new worktree, force push, main change, merge or LIVE enablement.

Production implementation remains future approved work: Agent2 additive migration/repository/atomic ticket+latch/SQL tests; Agent4 trusted Registrar/Runtime coordination and isolated DTOs; Agent5 under Agent4 the actual Guardian authority/receiver/observer integration; Agent3 related streaming/fact/Turn confirmation and later implementation. PR10 remains a disabled attempt-scoped v1 component, not v2 acceptance.

Formal review order: request **Agent4 final interface review first** on this repair commit/digest. Only after Agent4 accepts, request Agent2/3 confirmation of the changed digest; then Agent1 may decide formal CCR approval. [ACK ledger](CCR-ADL-001-ACKS.json) preserves the real prior ACKs and this direction acceptance separately. PR9 remains Draft/unmerged and production Durable LIVE closed throughout.
