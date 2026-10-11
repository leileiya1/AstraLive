# v0.5 F acceptance decision — premerge gate

**Overall: FAIL for complete A+B+C+D integration; implementation merges held.** This is the current premerge decision, not a declaration that the original multi-stage task is complete. Frozen contract `v0.5-frozen-1` is unchanged. [Risk/action list](PREMERGE-RISKS.md), [test report](CHAOS-TEST-REPORT.md), [raw seam result](evidence/integration-f/seam-1/result.json).

Subsequent implementation progress and pending CCR decisions are in [CONTINUITY-SEAM-REVIEW](CONTINUITY-SEAM-REVIEW.md). C has an uncommitted implementation after consuming A/B dependencies; A delivered ee5500b and edd4e1e, which F independently tested. The pinned delivery/test ledger below is the original reproducible review, not the latest owner source or merge acceptance. No final C implementation or implementation merge is accepted yet; strict GPU precommit READY/credit/history remains unresolved.

Follow-up standalone gates: F's C Scheduler draft selection/legacy tests pass race; its canonical flag correction and source-overflow mapping remain owner actions. B Runtime85bec11 corrects installation order; F tested09f06f2 (179 pass/11 skip); latest docs/log pin dda7936 has identical Runtime source. These scoped ACKs do not pass A journal integration, completed C delivery or strict GPU READY. Full-core decision remains FAIL/premerge held.

A then delivered ee5500b with the six-table/journal increment; F full Go/race/owned-PG faults/frozen validator/durable Python8 and full A Runtime (156 pass/11 skip) independently passed. C consumed that seam and corrected the canonical flag; final committed C integration and bound-output FORCE behavior still require validation. The original missing-table/adapter finding applies to the old pinned source, not ee5500b. Full-core/default-enable decision remains unchanged pending the real combined gate.

## Actual branch/merge ledger

| Order | Branch | Reviewed source SHA | Merge SHA / status |
| --- | --- | --- | --- |
| A | exp/v0.5-pg-durability | e5f14a14a04fdd4968af3c8dc3530bb22202e8b6 | NONE; reviewed/independently tested, core gate held |
| B | exp/v0.5-media-timeline | cf43e2d3dd6a9223648eaced2526d13e0ccbf8e1 | NONE; reviewed/independently tested, A/C journal missing |
| C | exp/v0.5-narration-continuity |5a24478126211cbcde5a9565d0c6063748426527 | NONE; shared baseline, no implementation; user confirmed |
| D | exp/v0.5-local-ipc |1a1bce2a1cb3f933be607998576bd64558bb11be | NONE; standalone validated, shared patch context conflict, deferred |

No PR/implementation merge commits exist in F for this review. No main merge/reset/force push. No production conflict file modified; D patch failure is `backend/cmd/server/main.go`, not an applied edit. F changes only integration harness and review/evidence under `integration/v0.5/**` and `docs/v0.5/**`. The planned A→B→C→D ordering remains mandatory once these gates are resolved.

## Per-feature decisions

| Feature | Decision | Evidence / limit | Default enable |
| --- | --- | --- | --- |
| PostgreSQL durability / PG-only | CONDITIONAL | A independent full Go/race with real PG+CPU Runtime/faults passed. Real B/C timeline/narration persistence absent | NO |
| Audio-master MediaTimeline | CONDITIONAL | B standalone176 executed Runtime tests pass; historical real-GPU media evidence exists with test-double journal. F real A client cannot CommitSegment | NO |
| Narration Continuity | NOT TESTED / NOT IMPLEMENTED | C equals shared baseline; no NarrationPlan/SemanticCursor or answer/resume implementation | NO |
| Local IPC UDS | CONDITIONAL | D actual macOS standalone TCP/UDS/auth/restart/race passes; Backend/probe entry patch needs rebase, core integration untested; Windows runtime untested | NO, keep TCP |
| Remote QUIC | NOT TESTED | outside this A–D phase and optional; not a Continuity release blocker | NO, keep TCP |

Complete “讲解→回答→自然续讲”: **NO**. Five-question10-minute and long randomized Golden runs are NOT TESTED because C is not implemented. No automatic fact or mock sequence is substituted for naturalness/human review.

Redis fault recovery: **scoped A PostgreSQL-only startup and Backend/Runtime restart validated with Redis unreachable/invalid; integrated Narration recovery and killing an active Redis service NOT TESTED**. Unknown playback is kept conservative by A; no audible exactly-once claim.

A/V environment/metrics: **F did not run real GPU/Chrome/RTMP this phase; no new A/V metrics**. B's archived ledger soak is independent media evidence with a test-double journal, not completed SQL or narration acceptance. Linux/remote GPU/Windows/full-host UDS modes remain NOT TESTED by F.

## Compatibility and feature flags

This checklist records source invariants and independent regression scope. No combined flag-off live session or frontend test/build was run at the blocked premerge gate.

| Existing behavior | Evidence / remaining gate |
| --- | --- |
| v1.1 platform/Runtime contract | `contracts/**` unchanged in A/B/D; A frozen v1.1 validator PASS; old event schemas preserved |
| ordinary Speak/Utterance and interaction | A full Go/race with real SQL and ordinary CPU Runtime tests PASS; B legacy Runtime suite PASS; combined live regression pending |
| authentication / ownership | A real SQL HTTP/config security regressions PASS; D actual local Runtime token/auth checks PASS; combined core binding/UDS wiring pending |
| SoulX TCP binary protocol | no `gpu_worker/**` implementation delta in A/B/D; no new real GPU transport run by F |
| WebRTC / RTMP | B CPU sink/drain regression PASS; real Chrome/RTMP and combined output NOT TESTED by F |
| frontend | untouched by F and A/B/D implementation diffs; test/build NOT EXECUTED this review |

Frozen names and rollout defaults are preserved below; these are recommended settings, not a claim that every pending implementation consumes them.

| Setting | Keep default | Current implementation / limitation |
| --- | --- | --- |
| `ASTRALIVE_DURABILITY_ENABLED` | `false` | A ordinary durable mode independently tested |
| `ASTRALIVE_EVENT_MODE` | `legacy_redis` | A `postgres_only` requires durability and valid PG/journal; core Narration not implemented |
| `ASTRALIVE_MEDIA_TIMELINE_ENABLED` | `false` | B canonical flag supported; V2 alias conflicts fail startup; real durable adapter absent |
| `ASTRALIVE_CONTINUITY_ENABLED` | `false` | C implementation absent; requires durability+Timeline+authorized binding |
| `ASTRALIVE_LOCAL_TRANSPORT` / `ASTRALIVE_LOCAL_FALLBACK` | `tcp` / `disabled` | D standalone UDS tested; production entry patch pending |
| `ASTRALIVE_WORKER_TRANSPORT` / `ASTRALIVE_WORKER_FALLBACK` | `tcp` / `disabled` | QUIC not included in current phase |

## Remaining P0/P1 and release recommendation

Current core blockers: final committed C candidate/public-route FORCE transaction and actual combined regression gate pending; strict SoulX precommit READY/credit/history remains unavailable under the current contract. A's earlier missing tables/journal finding is resolved at the new pin. P1: A Worker wire-ID domain mismatch; completed cursor/media recovery and Stop/FORCE/product races require final pinned tests; D production wiring/rebase; complete combined flag-off live regression,10min/long-run real-media and host matrix absent. Initial PREMERGE-RISKS F-001..F-009 are historical; current owner actions are in CONTINUITY-SEAM-REVIEW.

**Do not enter full integrated real-GPU acceptance yet.** Obtain the final C implementation pin, repair the known identifier boundary and pass actual positive public-route/SQL/Timeline/Narration scenarios, then merge/test A→B→C sequentially; D follows after reviewed rebased production wiring. Retain historical negative evidence with its original pins, not as a purported test of the new adapter. Existing isolated B GPU acceptance may continue within its own authorized scope, but F does not launch more paid GPU work here.

Rollback: no implementation merges/features/deployments were applied, so no production rollback is needed. F artifacts are additive; preserve failure evidence. Future implementation rollback remains frozen contract §9: seal/fence own runs, record UNKNOWN tails, release binding, preserve additive SQL, and start new compatible runs on original Redis/TCP only once dependencies are operational. No deleting Redis/TCP/migrations or replaying unknown Outbox.

## Latest premerge follow-up

A edd4e1e's persistent observation spool passed F's pinned independent Go/race/owned-PG fault, durable Python and full Runtime checks. An additional actual B identity→A SQLite staging diagnostic fails for frozen-valid Worker wire IDs above2^53−1; A must repair the typed domain before that compatibility gate can pass. C's opt-in FORCE Speak may atomically persist a failed speech result plus a durable FORCE command/barrier using the existing202 FAILED DTO, conditional on public auth/SQL/rollback/idempotency/race tests. HTTP acceptance does not prove Runtime fence completion. C implementation is now in progress; the original pinned baseline-only C ledger above is not current delivery status. No final C implementation SHA or implementation merge is accepted yet. D remains independently delivered with production wiring pending. No default-enable decision changes.
