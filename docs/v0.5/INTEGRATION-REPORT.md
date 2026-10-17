# Agent 4 integration report

**ASTRALIVE V0.5 BLOCKED**. This is a reviewable integration with implemented SQL adapters and conservative production entrypoints, not a completed real-media v0.5 deployment.

Fresh remote baseline and ordered merge strategy: INTEGRATION-PLAN.md. Original Agent 2 and Agent 3 commits are merge ancestors. Frozen durable-live-1, v1.1 DTOs/contracts, legacy migrations and Worker/media protocol files remain unchanged. CCR request: https://github.com/leileiya1/AstraLive/issues/7 (no approval recorded at initial publication).

Implemented: real 11-operation Store adapter; authorized consistent policy projection; Product Tool SQL fact source and refreshed immutable command facts; WAITING admission/claim edges; drain-to-business completion coordinator; post-gap resume and stale-epoch boundary handling; persistent legacy exclusion including late lifecycle events; actual owner-authenticated manual decisions/Stop endpoints; frontend recovery panel with stable retry decisions; default-off LIVE refusal; Runtime expiry barrier and bounded task retention. Controller composes the original Scheduler with SQL-backed Manager and an atomic gate cache. The strict source-member cap is opt-in for durable mode so legacy overflow counters retain their old behavior; both member lists remain bounded. Production activation is gated.

Not implemented/accepted: production Guardian owning isolated publishing resources; full physical LiveSession/Binding lifecycle and registered service-principal composition; real SCRIPT TTS/avatar executor and all-required observers; approved cross-process COMMENT answer preparation; actual GPU/Chrome/RTMP latency and production crash recovery. These are explicit blockers, not tests skipped and declared PASS.

## 2026-10-17 review and stage update

PR #9 was reviewed at full head `4f4c95278e581bccc025323ed8534d0b2db1023e` / digest `aff229823418408e843d962e332ba3c8f71e20d5e25465bf54f5b3d37d5e4744`; Agent 4 withheld ACK and posted two blocking findings. It is not merged. PR #10 original head `84738b37c2ee39cc4b8f3a1d449802171ba0a7e0` was merged **disabled** with a separate conservative process-group cleanup fix. Guardian suite is 25 PASS after one retained failed run; full regression repeats Go/race 142 PASS each, Runtime 158 PASS/11 SKIP, Journal 11 PASS, contracts 17 PASS and frontend 45 PASS/build. Final tested source is `5fb16e6315b56ad8c5398e4417456b21d4c7eaff`; latest evidence is `evidence/agent-4/pr-review-2026-10-17/`. See [review report](PR-9-10-REVIEW.md) for exact gates and source/command manifests. Source integration is not production Guardian acceptance. Both LIVE guards remain closed; real GPU/Chrome/busy latency remain untested.

## Baseline evidence (2026-10-16)

Stage Agent 2: `evidence/agent-4/stage-agent2/acceptance.json`, all recorded commands exit 0, dedicated PG/Redis services stopped. Stage Agent 3: `stage-agent3-*` logs, Go/race/vet, Runtime/Journal/contract and frontend test/build exit 0 before shared changes.

Development runs and failures remain under `evidence/agent-4/`. Initial frontend recovery test mocked away ApiError; the test fixture was fixed. The first final-run ownership-prefix probe refused its isolated directory; the runner adopted the existing safe prefix without weakening the probe. A later normal→race sweep reused the same dedicated database and exposed non-global synthetic receipt IDs in tests, and later a fixed synthetic decision ID in the new HTTP test; fixtures now include the unique run/fixture identity. No production uniqueness constraint was loosened. Expanding CONFIG_TEST_DATABASE_URL also exposed a pre-existing v0.4 audit fixture cleanup bug: it deleted a parent Utterance before the referencing receipt, ignored the FK error and left a QUEUED row. The retained isolated database confirmed one QUEUED Utterance and zero receipts. The test now deletes children first and checks cleanup errors; production TTL/busy logic was not weakened.

Final verification: `evidence/agent-4/verified-release/acceptance.json` and `evidence/agent-4/verification-summary.json`. All 20 recorded commands exited 0; owned PostgreSQL/Redis cleanup returned [0,0]. The 360 source-file SHA256 manifest was unchanged throughout verification and is checked against the delivered code commit. Do not mistake the pre-commit HEAD in the raw runner metadata for the new code revision; the manifest identifies the exact source tested.

| Check | Actual result |
| --- | --- |
| Go all packages, actual dedicated SQL/Redis | 142 top-level PASS, 0 FAIL, 3 SKIP |
| Go race all packages, actual dedicated SQL/Redis | 142 top-level PASS, 0 FAIL, 3 SKIP |
| Go vet | exit 0 |
| Runtime unittest | 169 total: 158 PASS, 11 explicit real-service opt-in SKIP |
| Journal pytest | 11 PASS |
| Contract unittest / schema | 17 PASS; 20 operations, 14 objects, 4 hash vectors, 5 FSMs, 44 protected baseline hashes |
| Frontend | 45 PASS; Bun build exit 0 |
| Additional legacy local aiortc | 4 PASS, `local-webrtc.log`; synthetic providers, no Chrome/GPU |
| diff --check | exit 0 |

The Go skips are the subprocess helper (exercised by parent crash tests), optional Fake request-export helper and external configuration-browser harness. CONFIG_TEST_DATABASE_URL and RUN_INTERACTION_CPU are enabled against dedicated services, so the old user configuration, Provider Binding, formal legacy CPU Session/Redis/Runtime chain and new owner/CSRF/Stop API tests actually ran. Runtime's four skipped local WebRTC cases were then separately executed and passed; remaining real model/provider/full-chain opt-ins were not run.

Local environment: Go 1.27.2 darwin/arm64, Python 3.12.13, PostgreSQL 17.11, Redis 8.10.2, Bun 1.3.14. Go test elapsed 18.496s (child user/system CPU 7.373/2.745s), race elapsed 43.104s (14.472/3.092s). Cumulative child peak RSS across the complete runner, including compile/frontend build, was 570.17 MiB. Resource measurements are local child CPU and cumulative peak RSS, not GPU usage or a steady-state production leak/soak test. Real GPU memory/utilization and real-media samples are NOT TESTED.

No shared Runtime/Worker/DB/Redis or live room was killed, no cloud GPU started and no PR was merged into main. Refer to RELEASE-GATES.md for the 15-item status matrix and the separate acceptance reports for exact limitations.

## Baseline Git delivery (2026-10-16)

Tested integration code commit: `597ece2840c9a56b3998739cd86a4c749588bdeb`. The 360-entry verification manifest matches this commit byte for byte. Original PR #6 and PR #5 delivery SHAs remain ancestors through ordered merge commits. The subsequent delivery metadata commit only records reports and raw logs. Verified-release evidence commit: `ea6d53ef9e66615d0d3dad8ad75b3bad6f85734a`. Draft integration PR: https://github.com/leileiya1/AstraLive/pull/8. No auto-merge is configured or performed.
