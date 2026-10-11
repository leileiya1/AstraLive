# v0.5 F acceptance decision — partial sequential integration

**Overall: complete A+B+C+D acceptance remains incomplete; A merged with postmerge software/SQL gate PASS.** This is a progress decision, not final release approval. Frozen contract `v0.5-frozen-1` is unchanged. [Actual merge ledger](evidence/integration-f/merge-ledger.json), [test report](CHAOS-TEST-REPORT.md), [current reviews](CONTINUITY-SEAM-REVIEW.md). Historical first-review risks/failures remain preserved in PREMERGE-RISKS and their pinned artifacts.

Current A tip a28a409 includes the six-table journal, persistent proof spool and independently verified typed Worker wire-domain fix. F normally merged it at89179c7 and reran all Go/race/owned-PG/process-fault/contract and Runtime checks, frontend40/40 and build on that actual merge commit: PASS. Runtime160 pass/11 skip; durable Python12/12. No conflict file was manually resolved. B dda7936 is next; C is actively implementing after consuming A/B but has no final accepted implementation pin; D production wiring remains pending. Strict SoulX full precommit READY/credit/history remains unavailable under the current contract.

Retained standalone gates: C Scheduler draft selection/legacy race PASS; B install-order code at09f06f2 Runtime179 pass/11 skip, latest dda7936 source identical. F verified the user-approved B flag alias (CCR-B-001). C corrected its canonical flag/source overflow and has a source-reviewed whole-Session product retirement hook; final pinned joint acceptance is pending. Standalone/owner fixture results do not prove natural narration or actual audience hearing.

Experimental defaults remain off. No deployment or main merge has occurred; frontend and frozen/Worker protocol source remain unchanged. Each next branch requires its own postmerge gate before progressing.

## Actual branch/merge ledger

| Order | Branch | Reviewed source SHA | Merge SHA / status |
| --- | --- | --- | --- |
| A | exp/v0.5-pg-durability | a28a4098a9014d9f7577d541048b2e110f1fc325 |89179c7da25a81dfa91e24bb7a06a8086813e3c9; postmerge gate PASS |
| B | exp/v0.5-media-timeline | dda7936faba56efe01659b6393a4d32a93322508 | NONE; next in order, standalone review/tests passed |
| C | exp/v0.5-narration-continuity | final implementation pin pending | NONE; owner implementation/testing in progress, dependency-only commits are not delivery |
| D | exp/v0.5-local-ipc |1a1bce2a1cb3f933be607998576bd64558bb11be | NONE; standalone validated, shared patch context conflict, deferred |

No PR URLs supplied. A was merged normally with branch history; no main merge/reset/force push. Actual conflicts resolved: NONE. D's old patch failure at `backend/cmd/server/main.go` remains an unapplied proposal. F's manual edits are only integration harness/review/evidence; owner implementation is incorporated by normal merges. Order remains A→B→C→D.

## Per-feature decisions

| Feature | Decision | Evidence / limit | Default enable |
| --- | --- | --- | --- |
| PostgreSQL durability / PG-only | CONDITIONAL | A actual merge software/real-PG/CPU process and frontend PASS; full C media recovery not yet accepted | NO |
| Audio-master MediaTimeline | CONDITIONAL | B standalone179 Runtime tests passed and install-order fix reviewed; historical real-GPU media uses test-double journal; actual joint merge pending | NO |
| Narration Continuity | NOT TESTED by F as a final merged candidate | C active draft/owner fixture tests; final commit and independent naturalness/inference acceptance pending | NO |
| Local IPC UDS | CONDITIONAL | D actual macOS standalone TCP/UDS/auth/restart/race passes; Backend/probe entry patch needs rebase, core integration untested; Windows runtime untested | NO, keep TCP |
| Remote QUIC | NOT TESTED | outside this A–D phase and optional; not a Continuity release blocker | NO, keep TCP |

Complete accepted “讲解→回答→自然续讲”: **NOT YET**. C reports five-question10-minute synthetic-inference/native-Chrome/local-RTMP fixture runs; final source/evidence and F independent joint review are pending. Naturalness, real TTS/SoulX and long randomized Golden acceptance remain NOT TESTED by F. Automatic fact coverage is not human semantic-quality proof.

Redis fault recovery: **scoped A PostgreSQL-only startup and Backend/Runtime restart validated with Redis unreachable/invalid; integrated Narration recovery and killing an active Redis service NOT TESTED**. Unknown playback is kept conservative by A; no audible exactly-once claim.

A/V environment/metrics: **F did not run real GPU/Chrome/RTMP this phase; no new A/V metrics**. B's archived ledger soak is independent media evidence with a test-double journal, not completed SQL or narration acceptance. Linux/remote GPU/Windows/full-host UDS modes remain NOT TESTED by F.

## Compatibility and feature flags

This checklist records current source invariants and executed scope. A postmerge frontend40/40/build and software/SQL regressions pass. Full joint flag-off real live acceptance remains pending.

| Existing behavior | Evidence / remaining gate |
| --- | --- |
| v1.1 platform/Runtime contract | `contracts/**` unchanged in A/B/D; A frozen v1.1 validator PASS; old event schemas preserved |
| ordinary Speak/Utterance and interaction | A full Go/race with real SQL and ordinary CPU Runtime tests PASS; B legacy Runtime suite PASS; combined live regression pending |
| authentication / ownership | A real SQL HTTP/config security regressions PASS; D actual local Runtime token/auth checks PASS; combined core binding/UDS wiring pending |
| SoulX TCP binary protocol | no `gpu_worker/**` implementation delta in A/B/D; no new real GPU transport run by F |
| WebRTC / RTMP | B CPU sink/drain regression PASS; real Chrome/RTMP and combined output NOT TESTED by F |
| frontend | source untouched; A actual merge frontend40/40 and build PASS with matching installed lockfile |

Frozen names and rollout defaults are preserved below; these are recommended settings, not a claim that every pending implementation consumes them.

| Setting | Keep default | Current implementation / limitation |
| --- | --- | --- |
| `ASTRALIVE_DURABILITY_ENABLED` | `false` | A ordinary durable mode independently tested |
| `ASTRALIVE_EVENT_MODE` | `legacy_redis` | `postgres_only` requires durability and valid PG/journal; A postmerge scoped CPU/SQL tests pass |
| `ASTRALIVE_MEDIA_TIMELINE_ENABLED` | `false` | B user-approved V2 primary/frozen-name alias; conflicting explicit values reject startup |
| `ASTRALIVE_CONTINUITY_ENABLED` | `false` | C final joint acceptance pending; requires durability+Timeline+authorized binding, no QUIC dependency |
| `ASTRALIVE_LOCAL_TRANSPORT` / `ASTRALIVE_LOCAL_FALLBACK` | `tcp` / `disabled` | D standalone UDS tested; production entry patch pending |
| `ASTRALIVE_WORKER_TRANSPORT` / `ASTRALIVE_WORKER_FALLBACK` | `tcp` / `disabled` | QUIC not included in current phase |

## Remaining P0/P1 and release recommendation

Current core blockers: C final committed candidate and actual combined regression gate pending; strict SoulX precommit READY/credit/history remains unavailable. A's missing tables/journal and Worker ID mismatch are resolved and independently verified at its merged pin. P1: final pinned public FORCE, cursor/media recovery, Stop/product-switch lifecycle tests; D production wiring/rebase; full joint flag-off live regression and Golden/host matrix gaps. Earlier malformed C product Stop is replaced in its latest source-reviewed App hook, but final tests must prove Runtime cleanup/binding release as well as SQL STOPPING.

**Do not enter full integrated real-GPU acceptance yet.** Continue B then C gates, obtain a verified strict-ready native staging path under the frozen protocol or an explicitly approved amendment, and accept the actual public-route/SQL/Timeline/Narration scenarios. D follows reviewed production wiring and must not block the core. Historical B isolated GPU results remain scoped to their own source/journal fixture, not the final integration.

Rollback: no deployment occurred. If rolling back experimental live runs, first stop/seal/fence admission, retain receipts/UNKNOWN tails and release captured bindings; preserve additive SQL and spool evidence. Restore frozen defaults, working legacy Redis and original TCP before starting fresh compatible Sessions; never replay ambiguous media. For an integration-source rollback, revert the selected normal merge with `git revert -m 1 <merge-sha>` (A89179c7) after reviewing downstream dependencies. No force reset/main push or database down migration is authorized. Do not delete Redis/TCP or deployed evidence tables.

## Current integration follow-up

A89179c7 and B10b74ca normal sequential merges both pass F complete postmerge software/PG/frontend gates; [ledger](evidence/integration-f/merge-ledger.json). A Worker wire integer-domain mismatch is fixed. C final06b182f is delivered and awaits five owner-resolved shared-file conflicts and pinned F gates. C default StrictSoulX complete-media staging is unavailable and fails closed; operator UNKNOWN-tail reconciliation/continuation and full cleanup/rebinding acceptance remain delivery gaps. Historical C native synthetic runs cannot replace final merged-source verification or real-provider/human acceptance. D production wiring remains pending. Keep all experimental defaults off; no main merge or deployment occurred.
