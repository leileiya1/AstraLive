# durable-live-2 — CCR-ADL-001 candidate

**PENDING OWNER ACK / CCR BLOCKED.** The active revision remains `durable-live-1`. This directory is an isolated machine-readable candidate, not a registered production service. No generated Backend/Runtime constant or default feature flag is changed.

Read [decision](../../../docs/v0.5/ccr/CCR-ADL-001.md), [normative answer semantics](../../../docs/v0.5/ccr/ANSWER-PREPARATION-CONTRACT.md), [migration/owner handoff](../../../docs/v0.5/ccr/CCR-ADL-001-HANDOFF.md) and [ACK ledger](../../../docs/v0.5/ccr/CCR-ADL-001-ACKS.json). Candidate normative file digest is in `manifest.json`. ACKs must cite it and the reviewed commit; mutable ACK/evidence records are excluded from that digest.

- `receiver-protocol.json`: 13 closed private installation/registration/authority/receiver operations, separate from the25 core operations. [Receiver normative contract](../../../docs/v0.5/ccr/RECEIVER-BOOTSTRAP-CONTRACT.md) defines trust roles, ticket eligibility, DB latch and two-hop timing.
- `examples/receiver-protocol.json`, `receiver-trace.json`: all private request/responses and signed, unregistered-to-unit2 separate-participant trace.
- `examples/go/receiver/interfaces.go`: typed interface sample; no production handlers/SQL.
- `schema.json`: inherited version2 object closure plus answer artifacts/stream/grants and five added operations. All objects closed; actual-answer vs question identity remains separate.
- `protocol.json`: 25 operations, exact revision2 paths, roles, status/error mappings. RUNTIME_JOURNAL owns writes to existing commands; Python never connects to SQL.
- `state-machines.json`: inherited FSMs plus AnswerStream, AnswerArtifactStatus, AnswerGrantStatus and AnswerExecutionStatus. Only a validated sealed/all-drained answer can complete its existing Turn.
- `examples/protocol.json`: a complete independent request/response for every operation; these are shape snapshots, not a real-time trace. `comment-start.json` adds one-shot COMMENT START and duplicate-denial examples.
- `examples/objects.json`, `hash-vectors.json`: immutable two-unit answer with real answer hashes, distinct question hash, snapshot/facts, chain and sealed manifest; canonical Unicode/control/decimal-string cases.
- `examples/go/canonical.go`, `examples/python/canonical.py`: runnable cross-language canonical/hash examples. `examples/go/lifecycle.go` and Python `--lifecycle` validate the same five-second renewal trace. `examples/python/reference.py` is a bounded **test oracle only**, not an in-memory production repository or a substitute for PostgreSQL fault tests.
- `protected-files.json`: hashes at integration `546ad9aa40bfe6949f32b55fb8ab6dc25d30dcb7` for existing contracts, Backend, Runtime, Worker and Guardian code. They verify this design PR preserves all active wire/implementation files. During approved implementation, the single Agent4-authorized migration-test enhancement is registered under `authorizedImplementationChanges`; its original hash/source and exact postimage are retained in [the audit record](../../../docs/v0.5/implementation/protection-changes/PR13-MIGRATION-TEST.json). The unchanged validator still checks all313 current expected hashes; unrelated entries are not refreshed. This non-normative inventory adjustment changes no frozen Schema/Protocol/manifest.

Version dispatch must use the route, exact body revision and persisted run/command revision together. A revision2 service receiving revision1 returns409 CONTRACT_REVISION_MISMATCH before mutation. Existing revision1 handlers are intentionally unchanged: wrong revision/extra fields returns their existing422 INVALID_ARGUMENT, and unregistered revision2 routes return404. Neither response authorizes fallback. New answer operations under revision1 have no route. Body-compatible requests are not sufficient to mix versions within an active run.

Candidate validation:

```sh
python3 scripts/validate-answer-contract.py
python3 -m unittest tests.test_durable_answer_contracts tests.test_answer_contract_repairs -v
go run contracts/v0.5/durable-live-2/examples/go/canonical.go contracts/v0.5/durable-live-2/examples/hash-vectors.json
python3 contracts/v0.5/durable-live-2/examples/python/canonical.py contracts/v0.5/durable-live-2/examples/hash-vectors.json
```

All true START/unit grants are one-use responses with first-response-only consumeTicket and remaining-time proof; server persists only the verifier. Receiver IDs/query/metadata cannot reconstruct eligibility. Prepare/query/seal receipts never authorize TTS; lost START/continuation ACK does not permit replay. Production SQL/Runtime/guardian/real-provider latency acceptance remains separate.

Repair evidence and owner re-review scope: [repair result](../../../docs/v0.5/ccr/REPAIR-2026-10-17.md). Initial Grant expiry gates first consumption only; current artifact-bound Permit/append-only fact proofs gate every later handoff. Query/renewal cannot grant another START.

Agent4 direction acceptance is not final ACK. Review order: Agent4 receiver interface first, then Agent2/3 new-digest confirmation, then Agent1 final decision; remain CCR BLOCKED.
