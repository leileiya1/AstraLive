# AstraLive v0.5 release gates

**ASTRALIVE V0.5 BLOCKED**. PASS is scoped to the explicitly tested layer; it does not imply the next layer.

| Required final item | Status | Acceptance layer / blocker |
| --- | --- | --- |
| CONTRACT INTEGRATION | BLOCKED | 11 operations adapted; PR9 Agent4 ACK withheld (slow-provider prepare and Grant renewal semantics); owner ACKs/approval pending |
| DATABASE MIGRATION | PASS | Real dedicated PostgreSQL 17 empty install + 000001–000005 upgrade/data preservation + repeat/concurrent runner |
| DURABLE OUTBOX | PASS | Real SQL/process lost-ACK/crash/CAS tests; production media not implied |
| RUNTIME JOURNAL | PASS | Real Go/Python HTTP/journal process tests and one-use START; production COMMENT preparation blocked |
| OUTPUT GUARDIAN | BLOCKED | PR10 source staged, 25 local CPU/real-process tests passed; production OS/secret/egress/short-segment/WebRTC/bridge gates remain OUTPUT_FENCE_UNPROVEN |
| SESSION RECONCILIATION | BLOCKED | Persistent exclusion and SQL recovery implemented; actual physical Session/Binding re-creation not connected |
| CRASH RECOVERY | BLOCKED | Isolated component crashes passed; entire-host/Guardian/real-media recovery unverified |
| UNKNOWN HANDLING | PASS | Real SQL proof/CAS/gap handling and owner-authenticated UI/API source; injected isolation proof in tests |
| STOP PRIORITY | PASS | Durable tombstone/SQL races/late-event exclusion; physical silence remains Guardian gate |
| SEGMENTED SPEECH | BLOCKED | Planner/exact-text helper/SQL passed; actual authorized TTS/Avatar wrapper not connected |
| NATURAL COMMENT INTERRUPTION | BLOCKED | Real Scheduler/SQL boundary test passed; COMMENT wire + production media unavailable |
| EXPLANATION RESUME | BLOCKED | SQL next segment/gap/new term passed; actual spoken resume unverified |
| BUSY-SPEAKER LATENCY | BLOCKED | 0 real samples; thresholds unmeasured |
| WEBRTC / RTMP | BLOCKED | Durable production output not enabled; Chrome/local RTMP/official viewer NOT TESTED |
| LEGACY REGRESSION | PASS | Go/PG/Runtime/frontend/frozen v1.1 checks; 4 additional local aiortc checks passed; prior real GPU media acceptance not rerun |

## Required before release

1. Explicit Agent 1 + affected owner CCR ACK, approved revision/schema/DTO/client/examples/migration/tests, exact answer + fact version + hash persisted before START. No undocumented wire and no removed COMMENT check.
2. Deploy and verify independent output Guardian, credential/egress isolation, restart fail-closed, two publisher/epoch tests and all-required sink observations.
3. Connect authenticated formal Session/Binding creation and registration, Worker readiness, Outbox/Coordinator/LeaseKeeper/completion/Controller startup and cleanup; map real trusted ingress receipts; production SCRIPT and COMMENT executors with required drain. Main currently blocks durable LIVE rather than running these incomplete adapters.
4. Execute complete isolated production Session/host/Guardian crash matrix, then real authorized short GPU/Chrome/RTMP and latency/mixed-load samples. Keep official viewer and 24-hour gates separate.
5. Preserve new tables on application rollback, Stop/isolate durable outputs, retain tombstones/UNKNOWN and prohibit legacy adoption. No destructive migration-down was performed.

Legacy mode remains the default. Authenticated manual recovery read/decision/Stop surfaces can operate independently; recording an intent is not a media admission. No flag or UI button can bypass OUTPUT_FENCE_UNPROVEN. Do not merge or enable as a completed v0.5 release.

2026-10-17: PR #9 was not merged; PR #10 was integrated only as disabled stage code. The existing 15 status values above remain unchanged. Exact heads, digest, failure/repair and latest evidence are in [PR-9-10-REVIEW.md](PR-9-10-REVIEW.md).
