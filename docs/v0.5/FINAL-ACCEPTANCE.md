# v0.5 F acceptance decision — partial sequential integration

**A+B are normally merged and pass complete postmerge software/owned-PG/frontend regression. C06b182f is delivered but its merge gate is held on a concrete lock-order/outer-commit defect and five shared-file conflicts. D remains deferred with production wiring pending.** Frozen `v0.5-frozen-1` bytes unchanged; no main merge, deployment or default-enable. [Actual ledger](evidence/integration-f/merge-ledger.json), [test report](CHAOS-TEST-REPORT.md), [owner seam review](CONTINUITY-SEAM-REVIEW.md).

## Branch and test ledger

| Order | Source branch / tip | Actual F merge | F validation |
| --- | --- | --- | --- |
| A | exp/v0.5-pg-durability / a28a4098a9014d9f7577d541048b2e110f1fc325 |89179c7da25a81dfa91e24bb7a06a8086813e3c9 | full Go/race/owned-PG faults/contract; Runtime171 total160 pass11 skips; frontend40/40/build PASS |
| B | exp/v0.5-media-timeline / dda7936faba56efe01659b6393a4d32a93322508 |10b74ca3c8a52c34f39ad152633b5784a7f94a2b | repeat A gates; Runtime202 total191 pass11 skips; frontend40/40/build PASS; real native short output regression executed separately |
| C | exp/v0.5-narration-continuity /06b182f840e0dc110a150a687e7ce016744edb3b | NOT MERGED | real SQL/Go/race cross-language premerge checks and native short PASS; corrected Runtime210 total199 pass11 skips PASS; initial jsonschema environment failure retained; owner lock-order fix pending |
| D | exp/v0.5-local-ipc /1a1bce2a1cb3f933be607998576bd64558bb11be | NOT MERGED | standalone macOS TCP/UDS/auth/restart/race PASS; production patch fails A context and requires final A+C rebase/review |

No PR URLs supplied. A and B normal merges have no conflict files. C preview conflicts: backend/cmd/server/main.go, backend/internal/app/durability.go, backend/internal/app/interaction.go, backend/internal/app/service.go, runtime/app/main.py. They have not been blindly selected or applied. F edits integration harness/docs/evidence only. A owns additive SQL and recovery, B Timeline/sinks, C FSM/orchestration, D local transport; shared changes and dependencies are recorded in the seam review. Order remains A→B→C→D.

## Feature decisions and flags

| Feature | Decision / evidence boundary | Default |
| --- | --- | --- |
| PostgreSQL durability / PostgreSQL-only | CONDITIONAL: merged SQL/CPU-process startup, restart/duplicate/old-epoch/outage/ownership gates PASS; complete production live/recovery matrix pending | durability=false; event_mode=legacy_redis |
| MediaTimeline | CONDITIONAL: merged software regressions and synthetic source native Chrome/local RTMP short tests; no integrated final-source real-GPU acceptance | ASTRALIVE_MEDIA_TIMELINE_ENABLED=false; approved V2 primary/alias conflict rules retained |
| Narration Continuity | FAIL merge gate on current06b182f locking/commit-order risk; software/native short functional path otherwise demonstrated with synthetic inference; superseding owner fix required | ASTRALIVE_CONTINUITY_ENABLED=false |
| UDS local IPC | CONDITIONAL standalone; NOT TESTED as production-wired integrated feature | ASTRALIVE_LOCAL_TRANSPORT=tcp; fallback=disabled |
| QUIC | NOT TESTED; outside A–D and optional, never Continuity release blocker | worker transport=tcp; fallback=disabled |

Complete accepted “讲解→回答→自然续讲”: **NO**. F final-pinned premerge short fixture executes Go/PG/Python/Timeline with real native Chrome/local RTMP; deterministic language, synthetic pulse TTS and Lightweight2D cannot establish human naturalness, real speech or SoulX. C retained seeded660.69s/five-question native fixture has209 media markers but lacks exact native-launch hashes and a full long SQL export. It is useful scoped evidence, not a final merged-source Golden PASS. F final merged ten-minute run awaits the corrected C pin. StrictSoulX complete-media READY staging is unavailable and fails closed before TTS/commit; CCR-BC-001 remains NOT APPROVED. Unknown-tail reconciliation/continuation API/UI and complete product retirement→cleanup/rebind acceptance are delivery gaps.

Redis failure validation: **scoped PASS** for A actual PostgreSQL-only startup/command/event path and Backend/Runtime restart with Redis unreachable/invalid, plus owned PostgreSQL stop/start; duplicate Outbox/Inbox and UNKNOWN conservative retirement tested. Killing an active Redis instance, complete integrated live Narration recovery, real Worker disconnect/reconnect remain NOT TESTED by F. No exactly-once audible speech claim.

## Actual media measurements

Environment macOS arm64, Python3.12.13, Chrome154.0.8037.98 headless native, aiortc1.15.0/PyAV17.1.0, localhost FFmpeg RTMP, synthetic440Hz pulses/RGB markers, no LLM/TTS/GPU. Sources and recordings are hashed in [steady audit](evidence/integration-f/merge-b-media-steady-1/audit.json) and [fault audit](evidence/integration-f/merge-b-media-faults-1/audit.json). Chrome performance.now, Runtime monotonic and each encoder FLV PTS are separate domains; AudioContext detection does not prove physical playout.

| V2 short trial | Chrome onset drift P50/P95/max ms | RTMP decoded onset drift P50/P95/max ms | Boundary |
| --- | --- | --- | --- |
| steady20 markers |35/112/122.1 |5/16/16 | all20 ordinal pairs; normal Stop, no drain failure or RTMP PTS regressions/duplicates |
| faults20 markers, peer/encoder reconnect |21.4/86.6/118.6 | before reconnect29/40/40 (n15); after24/35/35 (n3) | independent connection/encoder domains; two RTMP markers not observed across reconnect, tail UNKNOWN |

Steady legacy Chrome has21 audio pulses vs20 videos, so its correlation n0 remains unavailable; no browser A/B improvement claim. Fault generation-stale marker4000 was not observed, but this is a generation injection rather than proof of all run/timeline/Worker epoch fences. Injected delays cause recorded drops and unknown reconnect tails; no silent replay. Short synthetic onsets are not lip-sync, busy comment SLA or user experience improvement. Windows, Linux/remote GPU, physical audibility, browser device switches,30–60-minute live load and human visual quality remain NOT TESTED.

## Compatibility / remaining P0 and P1

Frozen contracts/platform events, frontend and SoulX Worker protocol source unchanged. Actual A+B Go/race/SQL auth/ownership and legacy interaction/Runtime tests, v1.1 validator and frontend40/40/build pass. All experimental flags default off; full default-mode native providers/live topology acceptance remains pending. D maintains distinct Go→Python transport from Python→GPU TCP/optional QUIC. A Worker63-bit ID mismatch is resolved; old negative probe remains historical evidence.

P0 integration hold: C Scheduler mutex→Session row lock versus product retirement Session row lock→Scheduler mutex, with Stop/Override before real outer commit. C/A owners are fixing and must provide concurrent realScheduler/product/price/Stop and borrowed-rollback tests, then F independently verifies. P1: unavailable strict native complete staging, operator UNKNOWN reconciliation/continuation, full cleanup/rebind and public FORCE/native-provider gate, D production wiring/auth probes, actual-GPU/human and host matrix.

**Do not default-enable any experimental feature or enter full integrated SoulX acceptance yet.** Correct C locking, rerun actual merge gates and obtain an executable strict staging provider under the frozen protocol before paid/real-provider acceptance. D can follow independently and must not block A+B+C core. Do not delete Redis/TCP.

Rollback: no deployment occurred. For experiments first stop/seal/fence new admission, retain durable receipts/UNKNOWN tails and clean captured bindings. Restore frozen flags, legacy Redis and TCP before fresh compatible Sessions; never replay ambiguous media. Source rollback uses reviewed `git revert -m 1 <merge-sha>` in reverse dependency order (B10b74ca then A89179c7). Preserve additive SQL/spools/evidence; no down migration, force reset or main push.
