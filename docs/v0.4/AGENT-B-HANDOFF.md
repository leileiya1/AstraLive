# Agent B Handoff v0.4

Baseline HEAD: `f2f6bdbdc291c2587cdf2eb5b2359b20db2c1696` (fetch and final recheck). Branch: `feat/v04-realtime-interaction`. User requested original-directory branch development; no separate worktree remains.

Implementation commit SHA: pending implementation commit.
Final delivery commit SHA/PR URL: recorded in the final delivery receipt/PR after commit. A tracked document cannot contain its own future Git hash; implementation SHA will be pinned here, final delivery SHA is the PR head/final response. No main merge or force push is authorized/performed.

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
