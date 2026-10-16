# durable-live-2 — CCR-ADL-001 candidate

**PENDING OWNER ACK / CCR BLOCKED.** The active revision remains `durable-live-1`. This directory is an isolated machine-readable candidate, not a registered production service. No generated Backend/Runtime constant or default feature flag is changed.

Read [decision](../../../docs/v0.5/ccr/CCR-ADL-001.md), [normative answer semantics](../../../docs/v0.5/ccr/ANSWER-PREPARATION-CONTRACT.md), [migration/owner handoff](../../../docs/v0.5/ccr/CCR-ADL-001-HANDOFF.md) and [ACK ledger](../../../docs/v0.5/ccr/CCR-ADL-001-ACKS.json). Candidate normative file digest is in `manifest.json`. ACKs must cite it and the reviewed commit; mutable ACK/evidence records are excluded from that digest.

- `schema.json`: inherited version2 object closure plus answer artifacts/stream/grants and five added operations. All objects closed; actual-answer vs question identity remains separate.
- `protocol.json`: 25 operations, exact revision2 paths, roles, status/error mappings. RUNTIME_JOURNAL owns writes to existing commands; Python never connects to SQL.
- `state-machines.json`: inherited FSMs plus AnswerStream and AnswerArtifactStatus. Only a validated sealed/all-drained answer can complete its existing Turn.
- `examples/protocol.json`: a complete independent request/response for every operation; these are shape snapshots, not a real-time trace. `comment-start.json` adds one-shot COMMENT START and duplicate-denial examples.
- `examples/objects.json`, `hash-vectors.json`: immutable two-unit answer with real answer hashes, distinct question hash, snapshot/facts, chain and sealed manifest; canonical Unicode/control/decimal-string cases.
- `examples/go/canonical.go`, `examples/python/canonical.py`: runnable cross-language canonical/hash examples. `examples/python/reference.py` is a bounded **test oracle only**, not an in-memory production repository or a substitute for PostgreSQL fault tests.
- `protected-files.json`: hashes at PR8 analysis baseline for existing contracts, Backend, Runtime and Worker code. They verify this design PR preserves all active wire/implementation files.

Version dispatch must use the route, exact body revision and persisted run/command revision together. A revision2 service receiving revision1 returns409 CONTRACT_REVISION_MISMATCH before mutation. Existing revision1 handlers are intentionally unchanged: wrong revision/extra fields returns their existing422 INVALID_ARGUMENT, and unregistered revision2 routes return404. Neither response authorizes fallback. New answer operations under revision1 have no route. Body-compatible requests are not sufficient to mix versions within an active run.

Candidate validation:

```sh
python3 scripts/validate-answer-contract.py
python3 -m unittest tests.test_durable_answer_contracts -v
go run contracts/v0.5/durable-live-2/examples/go/canonical.go contracts/v0.5/durable-live-2/examples/hash-vectors.json
python3 contracts/v0.5/durable-live-2/examples/python/canonical.py contracts/v0.5/durable-live-2/examples/hash-vectors.json
```

All true START/unit grants are one-use responses. Prepare/query/seal receipts never authorize TTS; lost START/continuation ACK does not permit replay. Production SQL/Runtime/guardian/real-provider latency acceptance remains separate.
