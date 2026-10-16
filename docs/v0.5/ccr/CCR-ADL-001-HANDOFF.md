# CCR-ADL-001 migration and Agent 2/3/4 handoff

Candidate only; **CCR BLOCKED** pending explicit owner ACKs. No production handler, generated implementation DTO constant, database migration or default feature flag is changed by this architecture PR.

## Agent 2 — required ACK and implementation

ACK exact artifact/receipt immutability, atomic text+hash+snapshot+fact storage, separate inbox/answer revisions, lock order, once-only global START and continuation grants, freshness observations and migration/retention/rollback.

Add **000007_answer_stream.sql** only if still the next free number at implementation; preserve 000006 byte-for-byte and coordinate any reservation with integration owner. All new rows use tenant/owner/run/session/command/attempt/epoch/producer and contract_revision; composite FKs prevent cross-run linking.

| Additive change | Constraints / migration semantics |
| --- | --- |
| dl05_answer_streams | PK answer_id; UNIQUE(command_id), command/attempt/run composite FK; contract_revision=durable-live-2; OPEN/SEALED/COMPLETED/INTERRUPTED/UNKNOWN; answer_revision CAS; prepared_count/drained_prefix/total_characters; seal manifest/final hash nullable until SEALED; max32/2000 and explicit deadline |
| dl05_answer_segments | PK artifact_id; FK answer; UNIQUE(answer_id,sequence), UNIQUE(command_id,idempotency_key); exact text/text_hash, canonical artifact descriptor/hash, product_id/snapshot_version, fact_dependencies JSONB, previous_artifact_hash, immutable prepare receipt; SQL SHA256(text UTF8) check; revision2 text limit240. Descriptor and all fact metadata committed together |
| dl05_answer_segment_execution | PK artifact_id; mutable PREPARED/STARTED/DRAINED/INTERRUPTED/UNKNOWN projection separate from immutable body; one execution owner; unique grant_id; expected revision CAS; no STARTED→PREPARED. Required drain refs/ranges tied to registered observer and current artifact |
| dl05_answer_grants | append-only one row per artifact, UNIQUE(artifact_id), grantId/epoch/producer/permit/factObservation/expires_at; grant creation and state CAS in same transaction; **never persist replayable authorized=true response in generic request cache** |
| dl05_answer_fact_observations | observation_id PK; artifact_hash, authoritative snapshot/value fingerprint, verified_at/valid_until≤2sec, source revision; append-only, not artifact mutation. At most bounded verification rate and command deadline |
| existing dl05_runtime_inbox / attempts / terms / permits | additive persisted revision binding; first prepare increments inbox revision once; later mutations use answer_revision. attempt.answer_text_hash stays null until validated seal final hash; it must never hold an input/question hash or one arbitrary unit hash. Permits get nullable artifact/observation binding fields; v1 readers retain their v1 behavior |
| existing dl05_answer_artifacts | Preserve legacy one-row whole-answer artifacts as revision1 historical data. Do not reinterpret/backfill them into playable v2 units; legacy seam cannot satisfy v2 COMMENT START |

Lock order: run→lease/slot→turn→attempt→outbox→inbox→answer stream→unit/execution/grant→observation/checkpoint/progress. All unit writes share the run+stream lock, enforce prepared-undrained window≤2, only one STARTED unit, and no query-to-start shortcut. Remote fact preflight outside transaction, local version/CAS/time check inside. Partial/conflicting artifacts roll back completely. New phase/answer enums live separately from existing run/Turn/Utterance FSMs.

Data retention: inherit7-day sensitive text/30-day detailed evidence/90-day metadata defaults; never expire active/UNKNOWN evidence or dedup tombstones. Clear text may be redacted after terminal retention with descriptor hash and sealed proof retained; do not UPDATE immutable body to redact—use encrypted payload storage/key retirement or a reviewed archival/redaction path. No cascading loss of facts/grants needed to audit an ambiguous start. App rollback disables v2 admissions, stops/isolates/reconciles v2 attempts, retains additive tables; v1 must not execute v2 rows. No destructive down migration while active/UNKNOWN remains.

Required real implementation evidence: PostgreSQL rollback/invariant/concurrent duplicate transactions, one true global grant and one true per-unit grant, lost ACK, no mixed body/fact/version writes, Stop/expiry/epoch/binding races and cache authorization ordering. Reference model tests here are **not those SQL acceptance tests**.

## Agent 3 — required ACK and implementation

ACK one COMMENT Turn across all answer units; fixed product snapshot; actual-answer fact extraction; conservative self-contained semantic validation; bounded token/assembler/lookahead; no EOF gate for first unit; same fairness/TTL and no script-cursor advancement per answer unit. First complete clause may wait longer than legacy first-comma behavior; measure separately. Revalidate actual unit assertions on start/renew, no question-hash substitution and no invented missing facts. Supply paired semantic positive/negative cases (129.90元、500毫升、XL/XXL、否定/条件/价格限定), cancellation, provider frame/answer-size bounds and no hidden full-answer collect.

## Agent 4 — required ACK and implementation

ACK the expanded five-operation proposal and changed START/Permit wire; the original Issue7 proposal ACK does not cover this decision. After approval, generate isolated v2 Backend and Agent3 DTO/spec copies plus Python models from the same schema; the existing v1 generators currently hardcode paths/revision and cannot just be pointed at v2 with live constants unchanged. Wire JournalPrepareAnswer/StartAnswerSegment/ConfirmAnswerSegment/SealAnswer/QueryAnswer and exact committed-body executor; preparation returns new inboxRevision for initial START. Renew permit/facts concurrently with the one active unit, prove guardian resource isolation, keep single Turn and legacy exclusion.

Upgrade runtime ExecutionInbox.prepare_comment callback to a bounded async unit producer and explicit receipt/grant coordinator. Current `_execute` awaits prepare_comment then passes the question command to executor; simply adding a POST still leaves EOF wait and stale accepted revision. First START must atomically return unit1 grant; later units cannot call JournalStart again or call legacy speak() to bypass grants. Add real registered sink unit-drain evidence, aggregate existing clock ranges at seal; do not change SoulX, Worker/TCP, PTS or credit semantics.

Version rollout: exact match paths+body+stored revision; v2 rejects cross-version before mutation with CONTRACT_REVISION_MISMATCH (unchanged v1 rejects via its existing INVALID_ARGUMENT/404), no fallback/downgrade or mixed nonterminal run. v1 Stop/control cleanup for v1 runs remains available. Route deployment should stage disabled v2 code + additive DB first, obtain all ACKs and component gates, then explicit separate enablement after real guardian/Session/Binding/media acceptance. This PR does not authorize enablement or merge main/PR8.

## Owner ACK ledger and template

See CCR-ADL-001-ACKS.json. ACK must identify owner Agent, reviewed commit, normativeDigest from the candidate manifest, and scope. Example: `Agent 2 ACK CCR-ADL-001 durable-live-2; commit=<SHA>; normativeDigest=<sha256>; migration/immutable artifacts/transactions/grants accepted.` Agent3 cites Turn/facts/streaming; Agent4 cites wire/executor/guardian. Explicit dissent is recorded with reason; silence is PENDING. Agent1 architectural selection is recorded separately from final approval. Any normative edit invalidates the earlier digest ACKs. All required new ACKs absent at initial review.
