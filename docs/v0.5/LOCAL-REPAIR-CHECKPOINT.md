# Local repair checkpoint — 2026-10-14

Scope: F integration on `exp/v0.5-soulx-staging-golden`, macOS arm64; local
repairs only. No SSH, cloud GPU inference, or paid-host deployment occurred in
this checkpoint. Real business Golden remains **FAIL / IN PROGRESS** pending
new fixed-source execution. Historical failures remain valid evidence.

## Integrated increments and exact verification

| Increment | Owner source/delivery | F merge or implementation | Evidence |
| --- | --- | --- | --- |
| Finite CNY price coverage, actual prepared proof and nonempty target-hash membership | C `c07658836c489105d33d56650c45c775152a351e` / `c4ddc43` | `87748c70d1e9805a4f2d6feea86067f3d8187f72` | [Full postmerge PASS](evidence/integration-f/canonical-final-postmerge-1/result.json); Runtime279 total,12 skipped; frontend40/build |
| Reject enabled explicit-empty/whitespace profile equally in Go and Python | C `0ccc25c0cfc0c25cb0f723e04949fcc1e83978a7` / `96182b1d191d4f352935a7dc88faf908bc0f0658` | `a9fd701620f34dca8f5f20e2601d479d84eb41bd` | [Full postmerge PASS](evidence/integration-f/explicit-profile-c-postmerge-1/result.json); Runtime280 total,12 skipped; frontend40/build |
| Independent canonical coverage oracle | Delegated B, F-owned acceptance `7d10c314aa690caf8325815139d7b8be05a1fcff` / `5b732cb` | `95fe1ad3e60e214b45c0180884412e5acde63cd9` | Initial58 synthetic oracle tests PASS; subsequently found actual checkpoint-shape incompatibility; superseded below |
| Safe original PostgreSQL projections and main-oracle wiring | F `378d978d5e64bf060e351cfb4362b285c02aeba4` | same | [Full local PASS](evidence/integration-f/canonical-wiring-postcommit-1/result.json); actual new projection test PASS in both Go suites; initial63 synthetic oracle tests PASS |
| Correct checkpoint `sink` versus media receipt `sinkId` | Delegated B `7a7055e9515c2f9d5f5401d0da1dc1694b662556` / `667f0ebfa5c52f01d1f9d4a095f92dd97b6160a1` | `609ee76cec0924a44d683152d8e3d0285966a4ea` | [F64 oracle tests PASS](evidence/integration-f/canonical-oracle-wiring-1/result.json); [full postmerge PASS](evidence/integration-f/local-repair-final-postmerge-1/result.json), Runtime280 total/12skip, frontend40/build |

Normal merges retained owner history, without conflicts or file replacement.
No obsolete test was removed. The four-stage A→B→C→D production integration
history remains in the earlier reports; this table records subsequent repairs.

## What changed and why

C's private immutable policy supports exactly two approved pure singleton-price
templates for new captured-staging CNY plans. It never upgrades old plans or
uses fuzzy language matching. Coverage now requires an explicit target-hash
entry, a nonempty hash, the original admitted `START_AUDIENCE_ANSWER`, actual
`ANSWER_PREPARED` observation/receipt, matching full sink completion and fresh
product version before advancing the cursor. Reserved turn decision evidence
survives subsequent saves and Stop. These repairs close the reproduced
nil/missing-map equality bug and reliance on a nonempty stored prepared hash.
[C handoff](CANONICAL-CNY-PRICE-COVERAGE-HANDOFF.md).

F's acceptance wiring reads the immutable policy and original safe SQL proof
before allowing the finite canonical mapping to replace an old substring check.
It still rejects unknown/partial playback, replayed mapped facts, foreign
ownership, changed final product values and failed observer/gate results.
`fixture-completion-smoke` additionally requires all fixture facts/questions,
FINISHED before Stop and no unfinished attempt/reference; it remains NOT_FORMAL
and cannot pass G1's ten-minute/140-fact/five-question requirements.

An independent A source review found that B's first checkpoint expectation and
synthetic fixture both used the wrong `sinkId` key. Actual C `SinkRange` uses
`sink`; media receipts separately use `sinkId`. The oracle and fixture were
corrected, the erroneous shape now has an explicit rejection test, and the old
synthetic PASS is not treated as PostgreSQL compatibility proof.
[Oracle handoff and correction](CANONICAL-COVERAGE-AUDIT-HANDOFF.md).

## Ownership and proof boundaries

| Shared/test file | Reason/dependency | Final merge owner |
| --- | --- | --- |
| `backend/internal/narration/golden_postgres_test.go` | F-owned live test extracts existing query map; adds prepared-command/observation/owned-product safe projection through helper; A reviews actual field/privacy compatibility | F |
| `backend/internal/narration/golden_safe_projection_test.go` | F-only evidence queries plus actual owned-PG syntax/hash/privacy/foreign-owner test; edited fixture command is never delivered | F |
| `integration/v0.5/canonical_coverage_audit.py` and tests | F-owned acceptance helper delegated to B; A checks actual source/SQL compatibility | F |
| `integration/v0.5/real_golden_audit.py` and wiring tests | F-only integration; preserve old failure and no-replay gates | F |
| `integration/v0.5/pg_canonical_projection_gate.py` | F-owned gate delegated to A, then independently rerun by F; source-pinned test overlay and actual owned PG→Python evidence | F |

Safe queries export selected business fields, never whole command payloads,
binding tokens, vault records or provider credentials. Product projection is a
final-table observation: its recomputed seven-string-key hash must equal the
captured version. It does not establish product-switch history. Timeline hashes
are joined to actual SQL journal/receipt hashes, not reconstructed from
incomplete safe projections. These checks are not hardware attestation or
audience audibility.

A's [independent actual-PG/race review](evidence/integration-f/canonical-a-independent-1/result.json)
passes23 canonical scenarios plus original missing-map regression coverage,
with controlled boundary/sink fixtures. D's [actual transport evidence](evidence/integration-f/d-focused-8fa-1/result.json)
is scoped to source `8fa0eb27b132234be9bd2afcccfeb8980ad4ca7a`; its
[final nineteen-file dependency mapping](evidence/integration-f/d-compatibility-mapping-609ee76-1/mapping.json)
is a source review, not a fresh execution at each target. Actual macOS TCP/UDS,
Runtime auth/error handling, owned-PG startup and Backend restart passed there;
Python47 total with one root/foreign-UID skip. Linux/Windows/live-UDS/performance
remain NOT TESTED.

The [fresh complete V3 CPU speech preflight](evidence/integration-f/catalog-v3-tts-preflight-1/summary.json)
synthesized all140 authored statements at the final609ee76 source:750.2934375
original seconds,753.2 padded seconds, individual padded durations4.12–6.36s,
zero oversize/failures. Canonical price answer3.92s and bridges3.64/5.40s. This
new full synthesis uses no historical time and demonstrates duration/framing
only, not a continuous live session, GPU or human naturalness.

A's [independent actual SQL→Python oracle gate](evidence/integration-f/canonical-pg-oracle-independent-1/manifest.json)
then F's [fresh final609ee76 rerun](evidence/integration-f/canonical-pg-oracle-final-1/result.json)
both PASS in their controlled component scope. Actual A/C transactions under
Go race generated the safe SQL, then the same unchanged bytes failed old7d10c31
with `CANONICAL_CHECKPOINT_SINK_RANGES` and passed fixed7a7055e with one coverage
target. Both helper SHA and SQL-before/after hashes are asserted; owned PG stops
with exit0. Initial boundary/sink receipts are controlled, Worker fields are
null, and no actual Runtime/GPU consumption is claimed. Earlier runner TypeError
and import-path failures are retained and excluded from PASS.

Reproduce with `integration/v0.5/pg_canonical_projection_gate.py`, supplying
`--repo`, `--source 609ee76cec0924a44d683152d8e3d0285966a4ea`,
`--old-oracle 7d10c314aa690caf8325815139d7b8be05a1fcff`,
`--fixed-oracle 7a7055e9515c2f9d5f5401d0da1dc1694b662556`, a new nonexistent
`--output` directory, `--python` and `--pg-bin`. The derived success-only overlay
and parent/query hashes are retained; no C source is edited or assertion removed.

## Flags, compatibility and rollback

| Capability | Default / decision |
| --- | --- |
| PostgreSQL-only durability | Experimental/default off; software tests PASS, full real-media Redis-kill recovery NOT TESTED |
| MediaTimeline | Experimental/default off; real fixed-source A/V regression pending |
| Continuity and staging | Experimental/default off; finite policy additionally requires new captured staging/CNY/approved pure price template |
| 1 GiB staging profile | Explicit approved opt-in; original512MiB profile and all other caps retained |
| Local transport | TCP default; UDS explicit opt-in; Windows loopback execution NOT TESTED |
| Remote transport | Original SoulX TCP retained; QUIC optional/default off/NOT TESTED; not a Continuity release blocker |

Frozen `ARCHITECTURE-CONTRACTS.md` SHA256 remains
`969d2e82d41f20084196d68a77bb3d1a6158a596a9ca63d47de9f6c1a78e8360`.
No public DTO, migration, profile name/budget, authentication, legacy event or
TCP binary semantics changed in these repairs. Preserve additive DB evidence,
old Redis/TCP paths and original negative regressions.

Rollback begins with normal authorized Stop/seal/fence and retaining UNKNOWN
records. Disable experimental admission for fresh sessions; never blindly
replay ambiguous speech. For the private price repair, preserve the reserved
turn-decision key even if disabling new policy creation/application; a full
pre-fix save rollback can discard decision evidence. Acceptance-only commits
can be reverted separately from C production increments. Use reviewed ordinary
reverts, never reset/force-push or destructive down-migrations. Reverting the
profile correction restores the known Go/Python explicit-empty mismatch.

## Remaining real acceptance

Historical tcp9 price replay/Chrome clock stall and tcp10 recorder parsing
failure remain FAIL until a new real run verifies the local fixes. Direct real
GPU1GiB staging component evidence already exists, but it does not prove the
business chain or cloud's current powered state.

Next: notify the user to start the cloud GPU, then run one fixed-source complete short business fixture
with real Chrome/RTMP before G1. G1/G2, real crash/recovery including Redis kill,
GPU disconnect, complete A/V metrics and host/device matrix remain NOT TESTED.
No busy-comment SLA, natural-continuation perfection, exactly-once audible
speech or default-enable decision follows from unit/software PASS. Push the
authorized new branch after the real-testing checkpoint; never merge main.
