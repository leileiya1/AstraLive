# CCR-ADL-001 — Durable incremental answer preparation

**Decision: SELECT INCREMENTAL SEMANTIC ARTIFACTS. Approval: CCR BLOCKED (owner ACK pending).**

Candidate wire revision: `durable-live-2`, schemaVersion `0.5`. Agent 1 accepts the architecture described here for owner review; this is not approval to implement/enable the revised wire before the required ACKs. Active deployed/frozen revision remains `durable-live-1`.

## Verified review basis

2026-10-16 (Asia/Taipei), fetched both remote refs and queried GitHub, before editing:

| Item | Current state / full SHA |
| --- | --- |
| main | `7fe5d24810e2df348c58dd7748e97ffbe5cff384` |
| Draft PR #8 | OPEN / Draft, head `integration/v05-durable-live` = `01a752baf79c25d4d268167d016c8c62e754cfdf`; base main as above |
| Issue #7 | OPEN; no comments/owner ACKs at initial review |
| Agent 2 handoff branch | `55c4dad81545a04946b4d58b706fc6abb14e67fa`, ancestor of PR #8 |
| Agent 3 handoff branch | `ed2ebb235cb89e4b10b8a6f9670c6a1be00b1511`, ancestor of PR #8 |
| Agent 4 tested code | `597ece2840c9a56b3998739cd86a4c749588bdeb`; handoff head is PR #8 SHA above |

Read all seven durable-live-1 design documents, its closed schema/protocol/FSM/examples/hash vectors and Agent 2/3/4 handoffs. Current integration is authoritative for analysis; no worktree owned by another Agent was edited. Snapshot provenance and protected-file hashes are delivered beside the candidate contract.

## Findings against current source

| Source | Finding |
| --- | --- |
| `runtime/app/durable_live_journal.py:ExecutionInbox._execute` | awaits `prepare_comment(command)` **before** permit and `JournalStart`; then invokes executor with the unchanged question command. Missing prepare callback fails closed. The callback currently has no legal answer-artifact RPC or returned prepared revision contract |
| `backend/internal/durablelive/journal.go:Store.start` | COMMENT requires a matching `dl05_answer_artifacts` / `attempt.answer_text_hash` row; one ACCEPTED→STARTED CAS; duplicate returns startAuthorized=false |
| `backend/internal/durablelive/recovery.go:RecordAnswerText` | trusted in-process seam stores bounded exact text/hash, but lacks snapshot/fact metadata, formal Python RPC and incremental segment identity. It is not an approved network API |
| `backend/db/migrations/000006_durable_live.sql` | one immutable answer row per command; no ordered artifact chain, stream seal or one-time continuation grant. Do not rewrite this migration |
| `backend/internal/durablelive/facts.go` | revalidates original command payload, not newly generated answer assertions. Existing request-cache fast path cannot be copied before answer authorization/freshness checks |
| `backend/internal/durableintegration/facts.go` and durablelive/product.go | authoritative Product Tool SQL projection is reusable. Answer assertions need their own dependency set and version, not the question's hashes |
| `runtime/app/session.py:_process` | existing LLM token stream → `sentence_stream` → `synthesize_stream` starts TTS on a complete early sentence/clause before LLM EOF. Token queue=8, slices≤64; no whole-answer requirement |
| `runtime/app/durable_live_segments.py` | exact SCRIPT helper only; does not close cross-process COMMENT preparation |

Issue #7 is necessary: closed v1 objects reject answer fields; no legal operation writes actual answer + product/facts atomically. `evidenceRef`, SCRIPT_TEXT, input textHash and command requestHash cannot be repurposed. The original issue proposal is a **whole-answer** artifact. Combined with the await-before-START wrapper, that proposal would wait for LLM EOF before any TTS. Current production COMMENT is blocked, so this is a prospective latency regression against legacy streaming, not a measured durable-live regression.

## Alternatives and latency tradeoff

| | Whole answer persisted, then single START | Immutable complete semantic units (selected) |
| --- | --- | --- |
| First TTS eligible | after LLM EOF + prepare transaction/RPC + START | after first complete safe unit + prepare transaction/RPC + START |
| Extra LLM wait vs streaming | approximately EOF time − first safe unit time | no required EOF wait; conservative semantic validation can wait longer than legacy first comma |
| Safety | simple one text/hash/fact set; still needs fact refresh while playing | one command START retained; every later unit requires a separate nonreplayable continuation grant, fresh facts/permit, ordered chain |
| Cost | fewer journal writes; poor first-audio behavior for long answers | bounded additional journal writes, per-unit drain, manifest/seal and migration complexity |
| Failure | ambiguous START never replayed | same rule, plus any ambiguous unit grant never replayed; no restart from a prepared prefix |

Let `t1` be first safe complete unit, `te` LLM EOF, `P` prepare RTT+commit, `S` START RTT+commit, `A` TTS first PCM. Let `V` be conservative semantic checking, `K` AcquireOutputPermit RTT+commit, `C` the receiver once-consumption handshake/authority check, and `F_p/F_k/F_s` the fact-validation costs at prepare/permit/START (including local version checks). Whole-answer first-PCM eligibility is `te+V+F_p+P+F_k+K+F_s+S+C+A`; selected first-unit eligibility is `t1+V+F_p+P+F_k+K+F_s+S+C+A`. This explicitly includes three Backend journal round trips, not two, plus the receiver consumption boundary. Same-value fact preflights can overlap or share a still-valid authoritative proof, but cannot be omitted from measurement or replaced by an unverified timestamp. Remaining units separately incur prepare, trusted drain confirmation, permit acquisition/renewal, continuation grant, receiver consumption, facts and optional reconciliation query; measure each, distinguishing overlapped preparation from the critical path. These expressions are pipeline reasoning, **not latency measurements or a 3-second SLA**. A deterministic blocked-EOF contract test proves first-unit eligibility before EOF; real DeepSeek/TTS/Chrome/RTMP timing remains NOT TESTED.

First global START atomically grants **unit 1 only** as well as starting the command. It does not authorize unprepared future text. Subsequent `JournalStartAnswerSegment` is a one-shot grant within the existing command/attempt/Turn, never another business START, Utterance or Turn. This preserves once-only START, Hash, fact versions, epochs, binding and Output Permit checks. The protocol is more than the single new operation proposed in Issue #7; Agent 4's ACK of that proposal does not ACK this expanded decision.

## Normative selected contract and compatibility

See [answer preparation contract](ANSWER-PREPARATION-CONTRACT.md), [migration and owner handoff](CCR-ADL-001-HANDOFF.md) and `contracts/v0.5/durable-live-2/` for the complete candidate.

This is **not** a legal additive operation under `durable-live-1`: START meaning, answer state and permit binding change, so use exact `durable-live-2` with distinct `/internal/v0.5/durable-live-2/**` routes. v1 routes/specs/DTOs/constants remain unchanged in this PR. Candidate schemas are review artifacts, not registered executable endpoints. No transparent downgrade, union-acceptance schema or version fallback. Authority checks precede duplicate receipts; a compatible-looking body with the wrong revision is rejected before any mutation. Agents implement new generated DTO/spec copies after approval, not by changing only a constant in the old executors.

Run/command/answer/receipt/grant rows persist their revision. One nonterminal run uses one revision; never mix v1/v2 attempts in the same run. Existing v1 work is stopped/isolated and reconciled under v1, with UNKNOWN retained; new v2 runs use new identities. SQL migration is additive and optional until coordinated rollout; no automatic conversion of existing whole-answer rows into segment 1 or completed streams.

## Approval rule

Approval requires Agent 1 decision plus explicit **Agent 2 ACK** (migration, artifact immutability, transactions/grants), **Agent 3 ACK** (Turn/facts/semantic streaming) and **Agent 4 ACK** (changed wire/executor/guardian integration). ACK must cite this candidate's normative digest and reviewed commit. Old durable-live-1 ACKs, Agent 4's original whole-answer proposal ACK, test passes, user silence or elapsed time are not approval. Ledger: [owner ACK status](CCR-ADL-001-ACKS.json). Until all are received: **CCR BLOCKED**; keep Durable LIVE default-off and COMMENT fail-closed.

## 2026-10-17 owner-review repair

Agent2/3/4 withheld ACK on head `4f4c95278e581bccc025323ed8534d0b2db1023e`. The repaired candidate allows trusted drain-before-prepare, reserves Prepare aliases transactionally, fingerprints complete Drain identity and separates consume-once Grant expiry from ongoing proof renewal. Grant, Observation, immutable execution binding and the5second renewal trace are now typed examples. The latest integration basis is `546ad9aa40bfe6949f32b55fb8ab6dc25d30dcb7`; historical review basis above remains evidence, not the current merge target. The new digest invalidates all earlier candidate review pins. Re-review is required; status remains CCR BLOCKED/PENDING.


## Receiver authority seam (post-direction review)

The receiver seam is frozen in [Receiver Bootstrap/Authority/Consumption](RECEIVER-BOOTSTRAP-CONTRACT.md), following [Agent4's direction acceptance and eight required details](https://github.com/leileiya1/AstraLive/pull/9#issuecomment-6227939254). Registered physical Generation/incarnation precede Prepare/Permit/START. First-response-only consume tickets prevent reference/query reconstruction of a lost START ACK. Restricted private Authority RPCs keep durable latch writes in Backend; Guardian never gets business SQL write permission. Unit2 switches execution/Artifact identity in the same Attempt/Generation and rejects old traffic.

Latency term C includes Query→Commit→fsync→current-proof/barrier→first ACK plus the Runtime's final proof/deadline exchange; trusted install read/challenge/stage/register also costs time when not already ready. Count every RPC/DB commit/signature/verification and any overlapped preflight; do not present these extra calls as free or claim3second SLA. Real authority/SQL/process/media acceptance remains future work. Final Agent4 ACK is still pending; after it, Agent2/3 must re-confirm the new digest before Agent1 approval.
