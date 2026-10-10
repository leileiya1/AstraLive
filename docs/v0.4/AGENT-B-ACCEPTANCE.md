# Agent B Acceptance v0.4

Baseline/main/origin/main was fetched and inspected as `f2f6bdbdc291c2587cdf2eb5b2359b20db2c1696`. The user requested branch-only development; the initially empty worktree was removed before any edits. Branch: `feat/v04-realtime-interaction`, original repository directory. Main is not force-pushed or merged.

## Status matrix and scope

| Item | Status | Validated boundary |
| --- | --- | --- |
| PLATFORM ADAPTER | PASS | Go framework/trusted mapping/error classification; only Mock adapter connected |
| MOCK / REPLAY | PASS | fixed replay, virtual-clock tests, actual-wall1/5/20/s and burst100 |
| COMMENT SCHEDULER | PASS | independent bounded CPU scheduling and actual formal Session admission |
| DEDUP / MERGE / TTL | PASS | source/primary-backup/user repeats, SKU versus overall stock, TTL/rate/full queue |
| PRIORITY / INTERRUPT | PASS | fairness, operator control, opt-in low-priority script preemption; existing FORCE/fence CPU regressions |
| ANSWER ROUTER | PASS | reuse accepted Product Tool/resolver; no raw-comment fallback; conservative routing limits below |
| LLM STREAMING | PASS | existing incremental iterator with bounded sentence prefetch; Fake network/provider tests |
| TTS BACKPRESSURE | PASS | real asyncio/native-thread bridge with fake callback engine; no real synthesis claimed |
| LATENCY OBSERVABILITY | BLOCKED | local spans/correlation implemented; required GPU/Chrome/RTMP receiver/full A/V samples absent |
| GO SESSION INTEGRATION | PASS | real SQL/binding/auth/HTTP/Redis/SSE + explicitly Fake Providers/CPU RGB media |
| AUTHORIZATION | PASS | real trusted test identities, same-tenant foreign owner, exact Origin, protected versioned routes |
| REGRESSION TESTS | PASS | checks below; frozen1.1/generated schemas and FSM unchanged |

PASS values refer only to the stated boundary. SoulX RTX3080 real interactive acceptance, genuine DeepSeek/XiaoYa and production platform adapters are NOT TESTED by Agent B. Agent A evidence is not recycled as Agent B acceptance. The provisional real end-to-end3s/5s goal is BLOCKED; Mock selection latency exceeds it under some load, openly reported.

## Actually executed checks

All SQL tests used independently created disposable PostgreSQL16; Redis7 was a separate disposable service. Business DB/Redis/recordings/models were not cleared, and existing Worker was never stopped. The full formal fixture creates actual encrypted Provider captures but substitutes Fake bundle construction only in a test-only Python launcher, with synthetic verification/management status. It cannot report REAL and does not weaken production admission.

| Command | Result |
| --- | --- |
| `go test -count=1 -json ./...` with explicit isolated DATABASE_URL/CONFIG_TEST_DATABASE_URL, RUN_INTERACTION_CPU=1 and INTERACTION_TEST_REDIS_URL | 52 top-level tests passed, 1 skipped |
| `go test -race -count=1 -json ./...` with same fixture | 52 top-level passed, 1 skipped; no race report |
| `go test -race ./internal/interaction ./internal/platform/...` | PASS |
| `go vet ./...` | PASS |
| `PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -v` |151 total,140 passed,11 skipped |
| `runtime/.venv/bin/python -m unittest tests.test_contracts tests.test_acceptance_guards -v` |5 passed |
| `bun run build` | PASS: generated frozen types, typecheck, Vite |
| `bun run test` |40 passed,9 files |
| `go run ./cmd/comment-load` |5 reproducible offline scenarios,1000 mixed included |
| `go run ./cmd/comment-load -wall` |real-wall Mock Adapter1/5/20/s and burst100; Fake dispatcher |
| `git diff --check`, frozen contracts/generated path diff | PASS / unchanged |
| `bash -n scripts/interaction-test.sh` | PASS |

The single Go skip is the opt-in configuration browser harness (not run as a headless substitute). Runtime's11 original real LLM/TTS/Avatar/WebRTC/full-chain opt-ins remain skipped. Go counts are top-level tests, not inflated subtest counts. Private logs live in temporary files outside Git; sanitized structured checks and traces are committed under evidence/.

## Formal fixture evidence

`TestInteractionFormalCPU` invokes actual Go business Session capture/start, real control-authenticated Python BoundSessionManager binding resolve, Product Tool from real SQL, Redis frozen stream `dh.runtime.events.v1`, event consumer/FSM storage, hub and SSE. Ten price comments merge into one speech; a separately selected chat exercises the Fake streaming LLM path. Unselected comments create no task. Binding summary/profile versions do not change. A restarted controller cannot submit the same source ID twice. A real loopback Runtime429 is deliberately injected and creates a FAILED Utterance/receipt, no TTS retry. Legacy direct COMMENT still returns202, and409 after Stop. Stop cancels Replay/candidates and leaves zero Runtime Sessions/leases; encrypted binding is released. These are actual service/SQL/control observations with Fake inference, not production GPU readiness.

[evidence/formal-session-cpu.json](evidence/formal-session-cpu.json) preserves normal-selection and fault phases. Synthetic CPU frame receipt is distinct from GPU-generated frame. [COMMENT-LOAD-TEST.md](COMMENT-LOAD-TEST.md) includes input/dedup/merge/select/expiry/drop/delivered/heap/wall-time and percentile denominators for every load scenario.

## Risks and follow-up gates

1. Real GPU/Chrome/RTMP correlated latency and Chinese listening quality remain Integration Owner gates. New traces do not prove physical speaker playback or platform audience delivery.
2. No real platform transport/credentials/cookie scraping. Adapter production rollout needs platform-specific authorization and reconnect/heartbeat tests.
3. Single Backend interaction controller per Session; command locking and rate limits are process-local, not distributed SaaS isolation.
4. Reserved receipt before crash is fail-closed/at-most-once: a response can be lost and needs manual reconciliation. Pending candidates are not persisted.
5. Default script boundary is full-utterance completion; optional preemption requires operator paragraph recovery. No word-position continuation or continuous script generator is added.
6. Existing fact resolver remains conservative and sometimes answers a product description deterministically; expanding natural introductions needs fact guards. General complex questions can still reach LLM with Tool context; open-ended factual hallucination beyond deterministic topics remains an existing provider limitation.
7. Native Sherpa cannot be hard-killed mid-computation; callback buffers are bounded, native engine internal allocation is not a total RSS guarantee.
8. Existing Runtime seen_utterances idempotency history is retained for the Session lease and is not converted into a new eviction policy; long-lived history memory is separate from bounded pending queues.
9. Source dedup cache is bounded/time-windowed. Persistent automatic dispatch receipts survive restarts; non-ID fallback user/text suppression is weaker and not global exactly-once semantics.

Agent A/Integration Owner should revalidate user binding startup/stop, actual XiaoYa streaming, low/high-priority speech/FORCE, Worker disconnect/recovery, headless+dual RTMP and Chrome playback after these additive changes. This branch is proposed for review, not merged into main.
