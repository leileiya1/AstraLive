# AstraLive v0.5 — frozen interface dispatch packet

To: Agent A / B / C / D / E. From: Agent F. Date:2026-10-11.

**Contract frozen:** `v0.5-frozen-1`, commit **`227decdb4b5d3ecc58302db7f6f19008e3a647ca`**, baseline `cf6540bdcc788c037929836480812dfaa78362a2`. Read [ARCHITECTURE-CONTRACTS.md](ARCHITECTURE-CONTRACTS.md) before shared-core edits. Plan: [INTEGRATION-PLAN.md](INTEGRATION-PLAN.md).

Local Git branch: `exp/v0.5-integration-chaos`; worktree `/Users/sapiece/innovationProject/AstraLive-agent-f`. The branch/commit is available in this repository's shared Git object store; implementations can inspect `git show 227decdb4b5d3ecc58302db7f6f19008e3a647ca:docs/v0.5/ARCHITECTURE-CONTRACTS.md` without changing their worktrees. Cherry-pick or explicitly reference the contract commit; do not merge F's branch into main without integration review.

Delivery status: **LOCAL DISPATCH PACKET COMMITTED; LIVE DELIVERY/ACK PENDING**. Only `/root` (F) was present in the agent registry during Phase1. No A–E agent channel/ID or implementation branch/worktree was available. No messages, PR comments, email or chat notifications to absent recipients were sent. This packet is not a peer acknowledgement or an implementation result. Do not treat pending ACK as consent.

## Owner-specific handoff

| Recipient | Required frozen seams / implementation result |
| --- | --- |
| A — PostgreSQL | own all new migrations/repos; command+Outbox transaction; Runtime Inbox/STARTED/receipt journal API+distinct role token; SQL event truth and optional Redis; recovery lease/run fence/Stop tombstone; UNKNOWN reconciliation; migration serialization. Provide shared fingerprint bytes/hash vectors with C. Persist B/C records via A repos; don't invent another narration/timeline authority. |
| B — MediaTimeline | implement six Timeline operations exactly per §5, sample-master half-open ranges/clock mappings, PREPARED→installed→ACTIVE epoch handshake, commit intent/eligibility proof, required-sink completion distinct from OR-based Worker credit. Keep v1 ordinary media and pinned regression paths; review C suspension/resume point seam before editing Session core. |
| C — Continuity | implement nine Narration operations/state/revision/cursor/fact ledger; selected comment suspend→durable resume point→answer→bridge→resume; captured product/version; Stop/FORCE/TTL/ownership final checks. Use A repositories/migrations, B boundaries, business vs wire generation mapping. Product switch stops old Session/starts a new captured Session in frozen-1; no silent hot swap. |
| D — Local IPC | Go→Python HTTP TCP/UDS transport composition inside existing auth wrapper; fixed names/defaults; private socket lifecycle; cancellation/timeout/redirect/proxy controls; explicit TCP fallback without replay. Does not change Python→GPU or A's Python→Go journal link. |
| E — Remote QUIC | Python→GPU reliable TLS QUIC stream profile/certificate+Auth+ACL, same bounded packet/credit/cancel semantics, independent default-off config and explicit safe-boundary TCP fallback. Preserve TCP and workerGenerationId high watermark across reconnect/clock rollback; any Worker capability extension requires CCR. QUIC is optional, not a Continuity dependency. |

Critical rules for all owners: `runEpoch != timelineEpoch != generationId != workerGenerationId`; opaque workerEpoch equality only; no success before required proof; UNKNOWN is not replay permission; recv/pipe credit is not viewer hearing; no exactly-once audible claim; no shared-file concurrent refactor; no deleted old regressions or mutated old evidence; all new flags retain legacy defaults.

## Required ACK / return format

Each owner returns the following reviewable fields (PENDING until actually received):

```text
agent: A|B|C|D|E
contractRevision: v0.5-frozen-1
contractCommit: 227decdb4b5d3ecc58302db7f6f19008e3a647ca
ack: ACK | CCR_REQUIRED
CCR: none | numbered reason/signature change + affected owners
implementationPR: URL | NOT CREATED
implementationCommit: full SHA | NOT IMPLEMENTED
dependencyCommits: full SHAs
ownedFiles: list
sharedFileEdits: CCR + reason + final merge owner
migration/flag/rollback: exact commands and constraints
testEvidence: commands + exit/result + logs/artifact hashes + actual scope
remainingGates: NOT TESTED / CONDITIONAL / FAIL with reason
```

| Owner | ACK | Implementation PR/SHA | Shared edits approved | Real acceptance |
| --- | --- | --- | --- | --- |
| A | PENDING | PENDING | NONE | NOT TESTED |
| B | PENDING | PENDING | NONE | NOT TESTED |
| C | PENDING | PENDING | NONE | NOT TESTED |
| D | PENDING | PENDING | NONE | NOT TESTED |
| E | PENDING | PENDING | NONE | NOT TESTED |

**F's stop point:** Phase1 contract review/freeze is complete; integration is PAUSED until A/B/C implementation results are available. No implementation merges, fixture/harness construction, crash injection or real-media reruns are performed by this packet. Phase2 builds baseline-capable integration fixtures before the first merge. Later order A→B→C→D→optional E and per-merge gates remain mandatory. The runtime tests/Golden reports are future work, not implied by document verification. Default-enable decision for PostgreSQL-only, MediaTimeline, Continuity, UDS and QUIC: **NO at this phase; all NOT TESTED**.
