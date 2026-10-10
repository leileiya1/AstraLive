# Agent B Handoff v0.4

Historical CPU delivery record. Current real-provider/Chrome/RTMP results and remaining boundaries: [2026-10-10 follow-up](AGENT-B-REAL-ACCEPTANCE.md). Earlier NOT TESTED statements below refer to the initial CPU delivery.

Baseline HEAD: `f2f6bdbdc291c2587cdf2eb5b2359b20db2c1696` (fetch and final recheck). Branch: `feat/v04-realtime-interaction`. User requested original-directory branch development; no separate worktree remains.

Implementation/code-and-test commit SHA: `52ea86631552298a030de7dd56da3a30e7b4b8ab`.
PR: [Draft PR #1](https://github.com/leileiya1/AstraLive/pull/1). The final delivery SHA (including this receipt-only update) is the PR head and is supplied in the final response; `git rev-parse origin/feat/v04-realtime-interaction` resolves it after fetch. A tracked document cannot contain its own future Git hash. Code/test SHA above is immutable and all subsequent changes are documentation only. No main merge or force push was performed.

## Modules and integration

- platform.Adapter/Event/EventSink/Mapping/Capabilities/Connection/ErrorClass; mock.Adapter/Record/Scenario/Load and fixed replay JSON.
- interaction.Scheduler/Config/Selection/Dispatcher/Gate/Limiter; independent Normalize/dedup/merge/rank/TTL/fairness and telemetry.
- app.InteractionController and trusted dispatcher created in server/main; protected `/api/v0.4/interaction/{sessionId}` snapshot/mode + nonproduction Mock/Replay controls.
- Dispatch reuses Service's shared speech implementation under the same command lock. Ownership, live state, captured product, existing queue/FSM/policy/providers/fence remain authoritative. Stop/terminal/Operator hooks are minimal additive changes.
- Migration000005 adds content-free persistent dispatch receipts. Apply through existing migration runner. Future official adapters use trusted mappings, never browser Runtime APIs.
- Existing Runtime resolver/LLM/TTS/Media reused. Eight-slot token/PCM buffers and non-echo fallback added; monotonic trace cache/control export and TALKING/generation observation added. No Worker protocol or neural/media algorithm rewrite.
- Frontend InteractionPanel follows Tailwind/responsive layout and explicitly identifies Mock, sample window and missing full A/V latency. Legacy developer card/API remains compatible.

## Checks and evidence

See [AGENT-B-ACCEPTANCE.md](AGENT-B-ACCEPTANCE.md), [COMMENT-LOAD-TEST.md](COMMENT-LOAD-TEST.md) and evidence/agent-b-checks.json for exact commands/counts/skips. Reproduction: `scripts/interaction-test.sh` with explicitly independent disposable CONFIG_TEST_DATABASE_URL and INTERACTION_TEST_REDIS_URL; it runs actual formal CPU fixture, all gates and wall/offline load, never starts paid inference. Go/Python/Bun dependencies must already be installed (including NumPy for the native bridge fake tests).

The formal normal phase selects2/11 comments (9 merges), delivers2. A fault phase intentionally exercises restart receipt rejection and Runtime429; these attempts are separate, explained failures rather than hidden from evidence. Real SQL identity/ownership/capture/control HTTP/Redis/SSE are exercised; provider verification, management readiness and all inference are Fake test injection. Stop cleans actual Runtime Session/lease/candidates/Replay/binding. Legacy COMMENT202/409 is checked.

1/5/20/s and burst100 have both real-wall Mock Adapter results and deterministic offline results;1000 mixed is offline/test-clock. All scene tables include queue/resource/wall-time/P50/P95/sample denominator, failure/drop ratios and FORCE0. Exact full synchronized-reply P50/P95 have0 real samples and are NOT TESTED. Runtime-local selected trace decomposition is CPU/Mock only; see INTERACTION-LATENCY-TRACE.md/evidence/interaction-latency.json. No unsynchronized cross-host timestamp subtraction is used.

## Agent A / Integration Owner final gates

Real captured DeepSeek+installed XiaoYa+RTX3080 SoulX, genuine Chrome first-correlated A/V and speaker observation boundary, headless/dual RTMP decoded receiver correlation (then actual platform viewing), interruption/fence/recovery and Chinese segmentation listening. Preserve Agent A's provider/version capture and stop cleanup. Do not automatically start a paid GPU or hour soak. Production platform adapters require separate official authorization. Real end-to-end3s/5s target is BLOCKED, with Mock backlog already showing long waits. Full implementation risks are explicitly listed in acceptance.

## Changed files

- `backend/cmd/comment-load/main.go`
- `backend/cmd/comment-load/wall.go`
- `backend/cmd/server/main.go`
- `backend/db/migrations/000005_interaction_receipts.sql`
- `backend/internal/app/interaction.go`
- `backend/internal/app/service.go`
- `backend/internal/httpapi/interaction.go`
- `backend/internal/httpapi/interaction_integration_test.go`
- `backend/internal/httpapi/server.go`
- `backend/internal/httpapi/sessions.go`
- `backend/internal/interaction/config.go`
- `backend/internal/interaction/metrics.go`
- `backend/internal/interaction/scheduler.go`
- `backend/internal/interaction/scheduler_test.go`
- `backend/internal/platform/mock/replay.go`
- `backend/internal/platform/mock/replay_test.go`
- `backend/internal/platform/mock/testdata/reconnect-duplicates.json`
- `backend/internal/platform/platform.go`
- `backend/internal/platform/platform_test.go`
- `docs/v0.4/AGENT-B-ACCEPTANCE.md`
- `docs/v0.4/AGENT-B-HANDOFF.md`
- `docs/v0.4/ANSWER-ROUTER.md`
- `docs/v0.4/COMMENT-LOAD-TEST.md`
- `docs/v0.4/COMMENT-SCHEDULER-DESIGN.md`
- `docs/v0.4/INTERACTION-LATENCY-TRACE.md`
- `docs/v0.4/PLATFORM-ADAPTER-DESIGN.md`
- `docs/v0.4/STREAMING-BACKPRESSURE.md`
- `docs/v0.4/evidence/agent-b-checks.json`
- `docs/v0.4/evidence/comment-load-wall.json`
- `docs/v0.4/evidence/comment-load.json`
- `docs/v0.4/evidence/formal-session-cpu.json`
- `docs/v0.4/evidence/interaction-latency.json`
- `frontend/src/features/live-console/InteractionPanel.tsx`
- `frontend/src/features/live-console/LiveConsole.tsx`
- `frontend/tests/interaction.test.tsx`
- `runtime/app/bound_media.py`
- `runtime/app/interaction_trace.py`
- `runtime/app/main.py`
- `runtime/app/real_tts.py`
- `runtime/app/session.py`
- `runtime/tests/interaction_cpu_server.py`
- `runtime/tests/test_bound_media.py`
- `runtime/tests/test_interaction_faults.py`
- `runtime/tests/test_interaction_streaming.py`
- `scripts/interaction-test.sh`

## Delivery receipt

The branch push succeeded using the existing Git credential channel. Local gh authentication/device-code refresh remained unavailable (EOF), so the already connected GitHub application created the Draft PR; no token was copied into the workspace. All dedicated CPU test PostgreSQL/Redis containers and the SSH forwarding process were removed after successful checks. Existing services/Worker were untouched.

## Real follow-up delivery (2026-10-10)

Current baseline `f62811a4b5a8ed4912ca9a6bb45677848ce9f4da`, branch `fix/v04-real-interaction-acceptance`. User supplied an already-running GPU instance and authorized verification/fixes. The exact implementation commit and PR receipt are added after committing; final response identifies final PR-head SHA, avoiding a document containing its own future hash.

[Real acceptance](AGENT-B-REAL-ACCEPTANCE.md) and evidence/agent-b-real-*.json are authoritative for the new actual DeepSeek/XiaoYa/SoulX/native Chrome/decoded RTMP gates. Normal20-sample Chrome P50/P952.897/4.177s, max6.669s; RTMP2.975/4.229s, max6.754s. Small-sample onset estimates meet the provisional targets, but strict P50≤3s remains BLOCKED by clock-alignment bounds (upper3.194s). Every slow sample/prior failed trial is retained. Physical speaker/human lip-sync and actual authorized platform/viewer acceptance remain NOT TESTED.

New helpers: monotonic snapshot clock exchange; integer-only trace media annotations; opt-in Chrome/RTMP/headless acceptance tools; marker-decoder regression. Scheduler remains at app.InteractionController→trusted shared Service Speak, with no new bypass API. New production fixes are directed-request classification, size-label TTS pronunciation and Worker stale-socket liveness. Frozen contracts, Session FSM and media protocol/algorithm are preserved.

Uncached Go and race:54 top-level PASS,1 skip each; Runtime142 PASS/11 skip; contract/acceptance/marker7 PASS; Worker21 PASS; frontend40 PASS/9 files and build PASS. Re-run1/5/20/s/burst and offline1000-event evidence includes all counters/resources/wall-times. Provider-error, slow native-callback, ownership, receipt restart and refusal cases remain CPU/Fake. Actual Worker disconnection/recovery, operator FORCE/fence, Replay cancellation, formal binding and stop cleanup are real. Existing business DB/Redis/Runtime were not cleared or stopped. Own Sessions ended and captures were deleted; the corrected cached GPU Worker remains READY.

Agent A/Integration Owner must review the minimal liveness/trace changes and actual fence/recovery evidence, measure strict latency on a lower-uncertainty production topology, listen to Chinese size pronunciation/segmentation, and approve human lip-sync. Platform transport needs official authorization. No hour GPU soak, personal-photo/voice, training, cloud lifecycle, billing, unauthorized protocol or new gRPC work was performed.

Follow-up changed files:
- `backend/internal/interaction/scheduler.go`
- `backend/internal/interaction/scheduler_test.go`
- `docs/v0.4/AGENT-B-ACCEPTANCE.md`
- `docs/v0.4/AGENT-B-HANDOFF.md`
- `docs/v0.4/AGENT-B-REAL-ACCEPTANCE.md`
- `docs/v0.4/ANSWER-ROUTER.md`
- `docs/v0.4/COMMENT-LOAD-TEST.md`
- `docs/v0.4/COMMENT-SCHEDULER-DESIGN.md`
- `docs/v0.4/INTERACTION-LATENCY-TRACE.md`
- `docs/v0.4/STREAMING-BACKPRESSURE.md`
- `docs/v0.4/evidence/agent-b-followup-load-wall.json`
- `docs/v0.4/evidence/agent-b-followup-load.json`
- `docs/v0.4/evidence/agent-b-real-browser.json`
- `docs/v0.4/evidence/agent-b-real-checks.json`
- `docs/v0.4/evidence/agent-b-real-faults.json`
- `docs/v0.4/evidence/agent-b-real-headless.json`
- `docs/v0.4/evidence/agent-b-real-prior-trials.json`
- `docs/v0.4/evidence/agent-b-real-summary.json`
- `gpu_worker/cli.py`
- `gpu_worker/install.py`
- `gpu_worker/manage.py`
- `gpu_worker/tests/test_deployment.py`
- `runtime/app/bound_media.py`
- `runtime/app/interaction_trace.py`
- `runtime/app/real_tts.py`
- `runtime/tests/test_bound_media.py`
- `runtime/tests/test_interaction_faults.py`
- `runtime/tests/test_interaction_streaming.py`
- `scripts/interaction-browser-acceptance.ts`
- `scripts/interaction-headless-acceptance.py`
- `scripts/interaction-rtmp-observer.py`
- `tests/test_interaction_observer.py`

### Follow-up Git receipt

Implementation/tests/evidence commit: `79b63ea5682776218b6ac13970e9f26a67645d2e`.
PR: [Draft PR #2](https://github.com/leileiya1/AstraLive/pull/2), base `main`, head `fix/v04-real-interaction-acceptance`. The PR has not been merged. Final head includes this documentation-only receipt and is identified in the final response; resolve with `git rev-parse origin/fix/v04-real-interaction-acceptance` after fetch.

All three final real Sessions were ENDED, captures deleted, Runtime activeSessions0. Owned disposable databases, Redis/RTMP containers, Go/Runtime/HTTPS test processes, SSH forwards and Chrome profiles/credential copies were removed. Existing CPU Runtime PID207538 remained alive. The updated cached GPU Worker was left READY in real GPU mode with the recovered epoch, queues0 and lastError null; the already-started cloud instance was not stopped.
