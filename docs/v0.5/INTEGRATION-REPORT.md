# Agent 4 integration report

**ASTRALIVE V0.5 BLOCKED**. This is a reviewable integration with implemented SQL adapters and conservative production entrypoints, not a completed real-media v0.5 deployment.

Fresh remote baseline and ordered merge strategy: INTEGRATION-PLAN.md. Original Agent 2 and Agent 3 commits are merge ancestors. Frozen durable-live-1, v1.1 DTOs/contracts, legacy migrations and Worker/media protocol files remain unchanged. CCR request: https://github.com/leileiya1/AstraLive/issues/7 (no approval recorded at initial publication).

Implemented: real 11-operation Store adapter; authorized consistent policy projection; Product Tool SQL fact source and refreshed immutable command facts; WAITING admission/claim edges; drain-to-business completion coordinator; post-gap resume and stale-epoch boundary handling; persistent legacy exclusion including late lifecycle events; actual owner-authenticated manual decisions/Stop endpoints; frontend recovery panel with stable retry decisions; default-off LIVE refusal; Runtime expiry barrier and bounded task retention. Controller composes the original Scheduler with SQL-backed Manager and an atomic gate cache. Production activation is gated.

Not implemented/accepted: production Guardian owning isolated publishing resources; full physical LiveSession/Binding lifecycle and registered service-principal composition; real SCRIPT TTS/avatar executor and all-required observers; approved cross-process COMMENT answer preparation; actual GPU/Chrome/RTMP latency and production crash recovery. These are explicit blockers, not tests skipped and declared PASS.

## Evidence

Stage Agent 2: `evidence/agent-4/stage-agent2/acceptance.json`, all recorded commands exit 0, dedicated PG/Redis services stopped. Stage Agent 3: `stage-agent3-*` logs, Go/race/vet, Runtime/Journal/contract and frontend test/build exit 0 before shared changes.

Development runs and failures remain under `evidence/agent-4/`. Initial frontend recovery test mocked away ApiError; the test fixture was fixed. The first final-run ownership-prefix probe refused its isolated directory; the runner adopted the existing safe prefix without weakening the probe. A later normal→race sweep reused the same dedicated database and exposed non-global synthetic receipt IDs in tests, and later a fixed synthetic decision ID in the new HTTP test; fixtures now include the unique run/fixture identity. No production uniqueness constraint was loosened. Expanding CONFIG_TEST_DATABASE_URL also exposed a pre-existing v0.4 audit fixture cleanup bug: it deleted a parent Utterance before the referencing receipt, ignored the FK error and left a QUEUED row. The retained isolated database confirmed one QUEUED Utterance and zero receipts. The test now deletes children first and checks cleanup errors; production TTL/busy logic was not weakened.

Final verification: `evidence/agent-4/verified/acceptance.json` and `evidence/agent-4/verification-summary.json`. All 20 recorded commands exited 0; owned PostgreSQL/Redis cleanup returned [0,0]. The 360 source-file SHA256 manifest was unchanged throughout verification and is checked against the delivered code commit. Do not mistake the pre-commit HEAD in the raw runner metadata for the new code revision; the manifest identifies the exact source tested.

| Check | Actual result |
| --- | --- |
| Go all packages, actual dedicated SQL/Redis | 141 top-level PASS, 0 FAIL, 3 SKIP |
| Go race all packages, actual dedicated SQL/Redis | 141 top-level PASS, 0 FAIL, 3 SKIP |
| Go vet | exit 0 |
| Runtime unittest | 169 total: 158 PASS, 11 explicit real-service opt-in SKIP |
| Journal pytest | 11 PASS |
| Contract unittest / schema | 17 PASS; 20 operations, 14 objects, 4 hash vectors, 5 FSMs, 44 protected baseline hashes |
| Frontend | 45 PASS; Bun build exit 0 |
| Additional legacy local aiortc | 4 PASS, `local-webrtc.log`; synthetic providers, no Chrome/GPU |
| diff --check | exit 0 |

The Go skips are the subprocess helper (exercised by parent crash tests), optional Fake request-export helper and external configuration-browser harness. CONFIG_TEST_DATABASE_URL and RUN_INTERACTION_CPU are enabled against dedicated services, so the old user configuration, Provider Binding, formal legacy CPU Session/Redis/Runtime chain and new owner/CSRF/Stop API tests actually ran. Runtime's four skipped local WebRTC cases were then separately executed and passed; remaining real model/provider/full-chain opt-ins were not run.

Local environment: Go 1.27.2 darwin/arm64, Python 3.12.13, PostgreSQL 17.11, Redis 8.10.2, Bun 1.3.14. Go test elapsed 14.446s (child user/system CPU 5.437/2.311s), race elapsed 39.315s (13.307/2.915s). Cumulative child peak RSS across the complete runner, including compile/frontend build, was 494.48 MiB. Resource measurements are local child CPU and cumulative peak RSS, not GPU usage or a steady-state production leak/soak test. Real GPU memory/utilization and real-media samples are NOT TESTED.

No shared Runtime/Worker/DB/Redis or live room was killed, no cloud GPU started and no PR was merged into main. Refer to RELEASE-GATES.md for the 15-item status matrix and the separate acceptance reports for exact limitations.
