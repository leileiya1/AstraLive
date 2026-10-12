# v0.5 F acceptance decision — partial sequential integration

**A→B→C are normally merged and each complete postmerge software/owned-PG/frontend regression PASSes. C locking/outer-commit defect is fixed and independently verified. D remains deferred: production patch fails current core and actual wiring/auth-probe integration is pending.** Frozen `v0.5-frozen-1` bytes unchanged; no main merge, deployment or default-enable. [Actual ledger](evidence/integration-f/merge-ledger.json), [report](CHAOS-TEST-REPORT.md), [review](CONTINUITY-SEAM-REVIEW.md). Final-source native synthetic long fixture completed659.662s:209 media commits/836 named receipts,200 required facts, five completed questions; scoped PASS.

## Branch and test ledger

| Order | Source branch / tip | Actual F merge | F validation |
| --- | --- | --- | --- |
| A | exp/v0.5-pg-durability / a28a4098a9014d9f7577d541048b2e110f1fc325 |89179c7da25a81dfa91e24bb7a06a8086813e3c9 | full Go/race/owned-PG faults/contract; Runtime171 total160 pass11 skips; frontend40/40/build PASS |
| B | exp/v0.5-media-timeline / dda7936faba56efe01659b6393a4d32a93322508 |10b74ca3c8a52c34f39ad152633b5784a7f94a2b | repeat A gates; Runtime202 total191 pass11 skips; frontend40/40/build PASS; real native short output regression executed separately |
| C | exp/v0.5-narration-continuity /ea0d48e2ebddb8e07dc4f3ea8082fc4f40c306d1 (sourcebf66c18) |6095989da99af3e1c458ed92db2f0bb6dcec4769 | full actual-merge Go/race/SQL/cross-language/crash/auth/contract PASS; Runtime210 total199 pass11 skips; frontend40/40/build PASS |
| D | exp/v0.5-local-ipc /1a1bce2a1cb3f933be607998576bd64558bb11be | NOT MERGED | standalone macOS TCP/UDS/auth/restart/race PASS; production patch fails current A+B+C main context and requires owner rebase/review |

No PR URLs supplied. A and B normal merges have no conflict files. C preview conflicts: backend/cmd/server/main.go, backend/internal/app/durability.go, backend/internal/app/interaction.go, backend/internal/app/service.go, runtime/app/main.py. F resolved these with verified equivalent dependency base abb7d26 and merge-file; every resolved blob matches final C owner source. [Provenance](evidence/integration-f/c-conflict-resolution-1.json). F edits integration harness/docs/evidence only. A owns additive SQL and recovery, B Timeline/sinks, C FSM/orchestration, D local transport; shared changes and dependencies are recorded in the seam review. Order remains A→B→C→D.

## Feature decisions and flags

| Feature | Decision / evidence boundary | Default |
| --- | --- | --- |
| PostgreSQL durability / PostgreSQL-only | CONDITIONAL: merged SQL/CPU-process startup, restart/duplicate/old-epoch/outage/ownership gates PASS; complete production live/recovery matrix pending | durability=false; event_mode=legacy_redis |
| MediaTimeline | CONDITIONAL: merged software regressions and synthetic source native Chrome/local RTMP short tests; no integrated final-source real-GPU acceptance | ASTRALIVE_MEDIA_TIMELINE_ENABLED=false; approved V2 primary/alias conflict rules retained |
| Narration Continuity | CONDITIONAL: corrected sourcebf66c18 actual merge passes full software/SQL gate and independent lock/rollback oracle; final-source659.662s five-question native synthetic fixture PASS; production/provider/recovery/human acceptance pending | ASTRALIVE_CONTINUITY_ENABLED=false |
| UDS local IPC | CONDITIONAL standalone; NOT TESTED as production-wired integrated feature | ASTRALIVE_LOCAL_TRANSPORT=tcp; fallback=disabled |
| QUIC | NOT TESTED; outside A–D and optional, never Continuity release blocker | worker transport=tcp; fallback=disabled |

Complete accepted “讲解→回答→自然续讲”: **NO for production/human acceptance; scoped synthetic functional sequence PASS**. F pinned actual merge6095989 ran one continuous659.662s native Chrome/local RTMP session with200 authored required facts and five seeded questions. SQL records209 commits and836 exact named audio/video receipts, five completed turns;199 narration statements completed and one price statement satisfied by a committed answer, no metadata fact omitted/duplicated. Chrome209 unique video markers and209 pulses observed; both required sinks proved contiguous terminal end30096000@48000Hz, run1/epoch11. [Independent audit](evidence/integration-f/merge-c-native-soak-1/audit.json), [source/command/versions/raw hashes](evidence/integration-f/merge-c-native-soak-1/result.json). This retains a complete long SQL export and exact immutable launch source. Prior old C long runs remain separately scoped historical evidence, not substituted for this run. Synthetic pulse TTS/deterministic language/Lightweight2D cannot pass spoken-content, human naturalness/relevance or SoulX. StrictSoulX complete-media READY staging is unavailable and fails closed before TTS/commit; CCR-BC-001 remains NOT APPROVED. Operator UNKNOWN-tail reconciliation/continuation API/UI and complete product retirement→Runtime cleanup/rebind acceptance remain delivery gaps.

Redis failure validation: **scoped PASS** for A actual PostgreSQL-only startup/command/event path and Backend/Runtime restart with Redis unreachable/invalid, plus owned PostgreSQL stop/start; duplicate Outbox/Inbox and UNKNOWN conservative retirement tested. Killing an active Redis instance, complete integrated live Narration recovery, real Worker disconnect/reconnect remain NOT TESTED by F. No exactly-once audible speech claim.

## Actual media measurements

Environment macOS arm64, Python3.12.13, Chrome154.0.8037.98 headless native, aiortc1.15.0/PyAV17.1.0, localhost FFmpeg RTMP, synthetic440Hz pulses/RGB markers, no LLM/TTS/GPU. Sources and recordings are hashed in [steady audit](evidence/integration-f/merge-b-media-steady-1/audit.json) and [fault audit](evidence/integration-f/merge-b-media-faults-1/audit.json). Chrome performance.now, Runtime monotonic and each encoder FLV PTS are separate domains; AudioContext detection does not prove physical playout.

| V2 short trial | Chrome onset drift P50/P95/max ms | RTMP decoded onset drift P50/P95/max ms | Boundary |
| --- | --- | --- | --- |
| merged core long209 markers | n209 complete ordinal-pulse/video coverage; five comment audio proxies P50/P95=3264.2/3302.7 (n5, not busy SLA) |19/40/40 | one continuous659.662s synthetic fixture, both required sinks; normal encoder Stop, packet PTS regression/duplicate0 |
| steady20 markers |35/112/122.1 |5/16/16 | all20 ordinal pairs; normal Stop, no drain failure or RTMP PTS regressions/duplicates |
| faults20 markers, peer/encoder reconnect |21.4/86.6/118.6 | before reconnect29/40/40 (n15); after24/35/35 (n3) | independent connection/encoder domains; two RTMP markers not observed across reconnect, tail UNKNOWN |

Steady legacy Chrome has21 audio pulses vs20 videos, so its correlation n0 remains unavailable; no browser A/B improvement claim. Fault generation-stale marker4000 was not observed, but this is a generation injection rather than proof of all run/timeline/Worker epoch fences. Injected delays cause recorded drops and unknown reconnect tails; no silent replay. Short synthetic onsets are not lip-sync, busy comment SLA or user experience improvement. Windows, Linux/remote GPU, physical audibility, browser device switches,30–60-minute live load and human visual quality remain NOT TESTED.

## Compatibility / remaining P0 and P1

Frozen contracts/platform events, frontend and SoulX Worker protocol source unchanged. Actual A+B Go/race/SQL auth/ownership and legacy interaction/Runtime tests, v1.1 validator and frontend40/40/build pass. All experimental flags default off; full default-mode native providers/live topology acceptance remains pending. D maintains distinct Go→Python transport from Python→GPU TCP/optional QUIC. A Worker63-bit ID mismatch is resolved; old negative probe remains historical evidence.

The reproduced P0 locking/outer-commit defect is resolved at sourcebf66c18 and merged6095989 with A scoped ACK/F independent identical-oracle PASS and populated concurrency/rollback tests. Remaining P1: primary-only V2 Go continuity startup inconsistency (conditional configuration must also set frozen Timeline alias=true), unavailable strict native complete staging, operator UNKNOWN reconciliation/continuation, full cleanup/rebind and public FORCE/native-provider gate, D production wiring/auth probes, actual-GPU/human and host matrix.

**Do not default-enable any experimental feature or enter full integrated SoulX acceptance yet.** Obtain an executable strict staging provider under the frozen protocol before paid/real-provider acceptance. D can follow independently and must not block A+B+C core. Do not delete Redis/TCP.

Rollback: no deployment occurred. For experiments first stop/seal/fence new admission, retain durable receipts/UNKNOWN tails and clean captured bindings. Restore frozen flags, legacy Redis and TCP before fresh compatible Sessions; never replay ambiguous media. Source rollback uses reviewed `git revert -m 1 <merge-sha>` in reverse dependency order (C6095989 then B10b74ca then A89179c7). Preserve additive SQL/spools/evidence; no down migration, force reset or main push.

## D owner follow-up and communication boundary

Give D core6095989 (Backend/Runtime unchanged through current F report commits). Request actual production-wiring code, not only a patch: server main + production launcher + protected provider-status/TTS probe transport; keep C startup/A PG-only, HTTP/JSON/auth semantics and TokenTransport outside the UDS dialer; default TCP, no command replay/implicit fallback. D must normally integrate the core dependency, resolve its owned/shared files, run real TCP/UDS auth/errors/restart plus A/C compatibility, supply final SHA and evidence, and leave unavailable Windows runtime NOT TESTED. F then reviews/merges D separately and repeats the full gate. Outbound existing-task message connector failed HTTP localhost50058, so this shared/pushed handoff is recorded; successful message delivery or D ACK is not claimed.
