# CCR-ADL-001: durable answer preparation

Review request: https://github.com/leileiya1/AstraLive/issues/7.

Status: **PENDING Agent 1 + affected Agent 2/3 owner ACK**. Agent 4 ACKs the proposal only. No approved contract change; active revision remains `durable-live-1`. Real COMMENT integration is **BLOCKED**.

## Evidence and legal-extension analysis

`protocol.json` defines 20 operations. No operation accepts generated answer text with its product/fact version. JournalAccept stores the immutable *question* command; its requestHash cannot be mutated after dispatch. JournalStart accepts identity/permit/CAS fields, not an answer. ConfirmCheckpoint carries evidence references/ranges, not an answer artifact. All objects reject additional properties. Repurposing `evidenceRef`, SCRIPT_TEXT or input textHash would alter frozen semantics.

`Store.RecordAnswerText` persists exact text/hash to `dl05_answer_artifacts` and `dl05_attempts.answer_text_hash` in process, but there is no authorized Python-to-Go operation and the artifact currently omits fact version. `Store.start` correctly rejects COMMENT without this artifact. Deleting that check, inventing a private endpoint under revision 1, or treating SQL permission as Runtime authorization is rejected.

## Concrete proposal for owner review (not implemented wire)

Add `JournalPrepareAnswer`, POST `/internal/v0.5/broadcast-runs/{runId}/journal/answer`, BACKEND, **RUNTIME_JOURNAL only**. Proposed version `durable-live-2`, subject to Agent 1's version decision; explicitly reject cross-version commands, do not silently reinterpret revision 1.

Request, closed object: existing schemaVersion/contractRevision/requestId/tenantId/ownerId/runId plus commandId, attemptId, sessionId, runEpoch, producerIncarnation, requestHash (original command hash), expectedInboxRevision, answerText (1..2000 characters), answerTextHash (SHA256 exact UTF-8), productId, productSnapshotVersion, factDependencies, idempotencyKey. Response, closed object: requestId, commandId, attemptId, answerTextHash, artifactId, productSnapshotVersion, revision, prepared=true. **No execution authorization field**.

Go locks run and inbox; authenticates registered scope/producer and Room/Session/product ownership; verifies current epoch, unsealed ACCEPTED inbox, active lease, nonexpired binding, deadline, current product and authoritative facts. LLM/tools run before this transaction. Store immutable answer+hash+fact version atomically, without granting START. Same identity+same artifact returns original receipt; differing text/fact version conflicts. After START only an identical previously stored receipt may be read, never overwrite/authorize execution. Authorization precedes duplicate lookup. Do not use general idempotency replay to return a prior START=true.

START independently rechecks artifact, current fact version/freshness, permit/Stop/epoch and inbox CAS. First successful START response alone grants one effect. Lost prepare ACK queries/retries the same artifact; lost START ACK stays conservative. Lost HTTP202 queries the original journal command and never allocates a new attempt. Runtime synthesizes only the committed answer text whose hash it has checked. The prepared response revision must explicitly identify the inbox revision to use for START; if preparation increments that revision, the client uses the new committed revision. Full-answer preparation can affect LLM latency and requires measurement; incremental artifacts would need separately approved semantics.

## Required changes after ACK

Agent 1 updates protocol/schema/FSM documentation, version constants, examples/hash vectors and tests together. Agent 2 adds an **additive next migration**, preserving 000006, for answer artifact metadata/immutability and the transaction; regenerate its Go DTO/spec copies. Agent 4 regenerates Agent 3 DTOs, implements Go/Python client operation and binds fact/answer resolver, tests lost ACK/duplicate/mismatched hash/Stop/expiry/cross-owner/old epoch on real PG and Python HTTP. Frozen v1.1 remains byte-identical. Rollout remains default-off with explicit version match and Guardian gate.

Acceptance must prove exact answer body + fact version + SHA256 persisted together; identical prepare does not increment attempts or authorize media; conflicting prepare rejects; START ACK loss cannot speak twice. Production media completion is a separate gate.

## Review requested

Agent 1 must ACK the operation, fields, version/compatibility rule and START freshness semantics. Agent 2 must ACK migration/transaction and immutable receipt behavior. Agent 3 must ACK adapter/fact projection impact. Silence or elapsed time is not approval. Continue independent adapter, SQL and legacy work while pending; keep real COMMENT blocked.
