# v0.5 F acceptance decision — premerge gate

**Overall: FAIL for complete A+B+C+D integration; implementation merges held.** This is the current premerge decision, not a declaration that the original multi-stage task is complete. Frozen contract `v0.5-frozen-1` is unchanged. [Risk/action list](PREMERGE-RISKS.md), [test report](CHAOS-TEST-REPORT.md), [raw seam result](evidence/integration-f/seam-1/result.json).

Subsequent implementation progress and pending CCR decisions are in [CONTINUITY-SEAM-REVIEW](CONTINUITY-SEAM-REVIEW.md). C has started an uncommitted FSM/plan after consuming A/B dependencies, and A has an uncommitted persistence draft. The pinned delivery/test ledger below is the original reproducible review, not a claim that those newer worktrees still have zero changes. No new final C/A increment has been independently accepted or merged; strict GPU precommit READY/credit/history remains unresolved.

Follow-up standalone gates: F's C Scheduler draft selection/legacy tests pass race; its canonical flag correction and source-overflow mapping remain owner actions. B Runtime85bec11 corrects installation order; F tested09f06f2 (179 pass/11 skip); latest docs/log pin dda7936 has identical Runtime source. These scoped ACKs do not pass A journal integration, completed C delivery or strict GPU READY. Full-core decision remains FAIL/premerge held.

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

P0: C implementation absent; A/C durable narration/timeline tables+journal/CAS missing; Runtime command handlers/epoch reservations missing for frozen core operations. P1: typed media orchestration/sink proof/cursor recovery and Stop/FORCE/product races untested; D wiring patch context failure/peer review; complete combined flag-off live regression,10min/long-run real-media and host matrix absent. Full details and owner actions are PREMERGE-RISKS F-001..F-009.

**Do not enter full integrated real-GPU acceptance yet.** First obtain C implementation and A/B/C seam agreement, add A-owned migrations/adapter/handlers, re-run the retained negative gate until legitimate positive scenarios pass, then independently merge/test A→B→C; D follows after a reviewed rebased patch. Existing isolated B GPU acceptance may continue within its own authorized scope, but F does not launch more paid GPU work here.

Rollback: no implementation merges/features/deployments were applied, so no production rollback is needed. F artifacts are additive; preserve failure evidence. Future implementation rollback remains frozen contract §9: seal/fence own runs, record UNKNOWN tails, release binding, preserve additive SQL, and start new compatible runs on original Redis/TCP only once dependencies are operational. No deleting Redis/TCP/migrations or replaying unknown Outbox.
