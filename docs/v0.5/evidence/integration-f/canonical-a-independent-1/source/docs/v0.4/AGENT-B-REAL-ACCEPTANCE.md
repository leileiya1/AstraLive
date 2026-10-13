# Agent B real interaction follow-up — 2026-10-10

Baseline/main fetched again: `f62811a4b5a8ed4912ca9a6bb45677848ce9f4da` (user merged PR #1). Branch `fix/v04-real-interaction-acceptance`, original directory; no worktree. This report supersedes only the previously missing real-provider/receiver gates. The original CPU delivery and evidence remain historical records.

## Changes driven by actual findings

1. The already installed GPU Worker was not running after the server restart, although its Unix socket and READY/PID JSON remained. The old launcher refused start, and stop raised ConnectionRefused. A failing stale-socket regression was written first. Lifecycle/installer now use the kernel supervisor lock as liveness evidence, keep active-worker refusal, and never signal a stale PID. A code-only release was installed while no Worker was running; existing model/cache/config/tokens and previous release were retained.
2. A directed request without a question mark (`帮我想一句直播开场白。`) was filtered by the question-only rules. Scheduler now recognizes a small explicit set of audience requests, with a regression showing ambient statements still filtered. This is input classification, not hardcoded production dialogue.
3. The actual XiaoYa lexicon logged `Ignore OOV 'XL'`. The TTS boundary now pronounces letter sizes in explicit size labels/lists and single-size-stock references. Original answer facts stay unchanged; numeric units/product identifiers are protected by tests. No assumption that XL means a particular measurement or inventory is added.
4. Content-free trace exports now include monotonic origin age and bounded integer media identity. Go snapshots expose receipt age, receive→selected and receive→dispatch-ack. Selection clears the preceding Utterance ID while admission is in progress, avoiding incorrect trace association. Frozen APIs/FSM and the media algorithm are unchanged.

## Actual deployment and measurement

Separate owned test databases `agent_b_real_20261010` and `agent_b_regression_20261010`, separate Redis services and a local MediaMTX receiver were used. The real fixture copied the existing authorized test user's encrypted configuration into the isolated database. The Go backend ran on the supplied GPU server; Runtime/XiaoYa and disposable storage ran on the existing CPU host. SSH forwarding traversed the local workstation. This topology adds control/Tool round trips and clock-exchange uncertainty; it is not a colocated production benchmark.

REAL Provider binding pinned DeepSeek v3, XiaoYa v1, SoulX Worker v1 and Avatar v1. DeepSeek verification succeeded before inference. All comments/products/prompts in the harness are synthetic fixtures. Fact questions reuse Product Tools/resolver; six of the 20 timed normal replies contain actual DeepSeek streaming first-token spans. No Fake provider or fallback audio was counted as real GPU inference.

RTX3080 10 GiB, SoulX revision `9bc03de06bb0de82cd6bc477804512ae06144bf2`, existing official avatar/cache. A sampled live status reported 4,434,844,672 allocated bytes, 5,731,516,416 reserved bytes and 6,038,749,184 device-used bytes. These are samples, not a claimed process/RSS maximum. No weights, model window, PCM sample timeline, Avatar/Media ordering, TCP protocol, PTS, credit or FORCE algorithm changed.

The browser was actual native headless Google Chrome, running the built Live Console and native WebRTC. `requestVideoFrameCallback` reads the existing opt-in speech-marker/generation strip. An AudioContext analyser detects nonzero decoded stream audio; native inbound/playout stats substantiate reception. This proves decoded/tapped audio and browser video handling, not a physical speaker or human lip-sync assessment. The RTMP receiver separately demuxes/decodes AAC/H.264 and matches the same marker/generation and audio PTS window, with one speech admitted at a time. It does not prove a production platform accepted the stream or an audience saw it.

## Results and latency

[Normal trial](evidence/agent-b-real-browser.json): 30 Mock input comments, 9 merges, 21 selected/delivered Utterances (one merge preflight plus 20 timed replies), 0 filtered/expired/dropped/failed, candidate peak1, automatic FORCE0. All 20 timed replies completed and have Chrome plus RTMP correlations. Binding/profile versions remained unchanged. Native Chrome decoded5502 video frames, dropped0, audio/video packet loss0, audio playout duration220.1s. Bounded media queues peaked20 audio/10 video frames; no peer stall/eviction. No slow sample was removed.

| Span, 20 normal samples | P50 ms | P95 ms | Maximum ms |
| --- | ---: | ---: | ---: |
| Go receipt → selected (same clock) | 51.24 | 118.50 | 118.57 |
| Selected → first speakable text (clock exchange estimate) | 1202.82 | 2630.44 | 4966.58 |
| First speakable text → first PCM (Runtime clock) | 110.25 | 167.35 | 167.52 |
| First PCM → first GPU TALKING frame observed at Runtime | 1153.75 | 1473.06 | 1486.62 |
| GPU frame observed → Chrome video handling (estimate) | 170.93 | 187.67 | 210.98 |
| Receipt → first correlated Chrome A/V (estimate) | 2896.53 | 4176.80 | 6668.99 |
| Receipt → first correlated decoded RTMP A/V (estimate) | 2974.99 | 4228.91 | 6754.45 |

Chrome mean3246.83ms; RTMP mean3304.63ms. Normal failure/drop ratios0/20 and0/30 respectively. First video PTS matches the speech-origin PCM sample exactly in all20 samples; decoded first nonzero audio/video PTS difference reaches213ms (onset detection, including leading silence, not a lip-sync score). Retained normal RTMP video PTS has no regression and maximum40ms step. The bounded receiver retains only nonzero audio and marked video; gaps in these retained rows cannot be called transport gaps, particularly during lightweight degradation. Percentiles use empirical nearest rank; n20 is a small trial, not a sustained service guarantee. The slowest sample was a real LLM consultation: first token3158.11ms after Runtime acceptance; selected→speakable4966.58ms. Control/Tool transport and LLM response dominate the tail; no media-path rewrite or guessed fixed delay was used to hide it.

All spans use process-local monotonic clocks. An observer brackets authenticated queries and maps remote origin ages into its own clock with request/response bounds. It never subtracts different hosts' wall clocks. Receipt alignment half-width P50=223.55ms, P95=312.45ms, max367.60ms. Per-sample lower/upper bounds are retained. Applying nearest rank to those bounds gives Chrome P50 range2598.93–3193.64ms and P95 range3924.75–4428.85ms. **Nominal estimates meet the provisional3s/5s target; strict P50≤3s acceptance is BLOCKED by the measured clock uncertainty.** One reply exceeded5s; this remains visible. This is onset of a correlated reply, not time until its entire utterance finishes.

[Prior trials](evidence/agent-b-real-prior-trials.json) retain the initial2 successful samples, two interrupted five-sample trials and a zero-input setup failure. The first five-sample trial also lost SSH when the user's local network disconnected. The repeated sixth-case failure after reconnection proved a directed-request filtering gap, so it is not labeled solely a network failure. Setup/API-deploy and wrong local test-Python dependency failures were corrected; they are not counted as successful performance samples. The final20-sample phase is a new declared trial after code changes, not a replacement for failed trial evidence.

## Real fault and headless gates

[Fault trial](evidence/agent-b-real-faults.json): an operator FORCE interrupted a selected comment, completed the new Utterance and advanced business generation1→2. No old-generation Chrome frame was observed after the first new-generation frame. Seven queued old media frames were intentionally discarded by the existing fence. Automatic FORCE remained0; explicit IDLE resume was required.

The owned Worker was stopped once. A selected aggregate-stock question completed with declared lightweight degradation. SSE reported WORKER_DISCONNECTED and WORKER_RECOVERED; the formal Session changed DEGRADED→REAL. Restart reached physical GPU READY with a new epoch; the next selected size question contained an actual GPU TALKING frame. The same binding ID and all profile versions remained pinned. The diagnostic observer was kept separate from business control.

A20/s,1000-event Replay was cancelled mid-run while Operator override held automatic speech. Input became stable at45 total trial events, candidates6, peak6, selections6. Stop removed pending candidates and background activities. Real SQL checks confirmed all three final trial Sessions ENDED, released binding mappings and deleted encrypted Provider captures; Runtime health reported activeSessions0 and no owned FFmpeg processes remained.

[Headless trial](evidence/agent-b-real-headless.json): no preview peer/Chrome; one selected Mock comment traversed formal Go→bound Runtime→XiaoYa→SoulX→RTMP, completed and had independently decoded correlated audio/video. The legacy development COMMENT endpoint additionally admitted a direct priority80/INTERRUPT_LOWER_PRIORITY Utterance with202, and returned409 after Stop. It remains outside Scheduler selection. Binding stayed unchanged; normal Stop reached ENDED.

DeepSeek401/429/timeout, Tool failures, slow/cancelled native TTS, Runtime429/refusal, receipt restart, room ownership and bounded1000-event stress were injected via Fake/CPU tests. They were not claimed as real vendor incidents. The actual network interruption and actual Worker stop/restart are the real fault cases in this follow-up.

## Executed regression gates

Independent regression DB/Redis only. [Structured checks](evidence/agent-b-real-checks.json) record commands and counts.

| Command | Result |
| --- | --- |
| `go test -count=1 -json ./...` |54 top-level passed,1 opt-in skipped (70 passes including subtests) |
| `go test -race -count=1 -json ./...` |54 top-level passed,1 skipped; no race report |
| `go vet ./...` | PASS |
| Runtime unittest discovery |153 total,142 passed,11 original opt-ins skipped |
| Contract/acceptance/receiver marker tests |7 passed |
| GPU Worker unittest discovery in its test venv |21 passed,0 skipped; simulation/pinned CPU decode |
| `bun run build` / `bun run test` | PASS /40 passed in9 files |
| Mock offline / actual-wall load |5 /4 scenarios passed; Fake dispatcher, never GPU load claims |
| Acceptance Bun bundle / Python compile | PASS |
| `git diff --check`; frozen contracts/generated diff | PASS; unchanged |

Re-run load data are [offline](evidence/agent-b-followup-load.json) and [wall](evidence/agent-b-followup-load-wall.json); each includes inputs/dedup/merge/select/expire/drop/deliver/peak, sampled Go heap changes and actual elapsed time. Existing CPU release evidence is not overwritten.

## Status matrix

| Item | Status | Boundary |
| --- | --- | --- |
| PLATFORM ADAPTER | PASS | trusted framework and Mock; real official platform transport NOT TESTED |
| MOCK / REPLAY | PASS | replay/CPU loads plus actual-session cancellation |
| COMMENT SCHEDULER | PASS | selected-only formal real speech and directed requests |
| DEDUP / MERGE / TTL | PASS | CPU coverage plus real10-user merge; SKU/aggregate facts remain separate |
| PRIORITY / INTERRUPT | PASS | CPU fairness/preemption; actual operator FORCE/fence and resume |
| ANSWER ROUTER | PASS | actual Tool fast path, actual LLM streaming; SKU data not invented |
| LLM STREAMING | PASS | six actual timed streaming replies; Fake error regression retained |
| TTS BACKPRESSURE | PASS | bounded native bridge regressions and actual synthesis/cancellation path |
| LATENCY OBSERVABILITY | PASS | correlated20 Chrome/RTMP samples with explicit clock bounds |
| GO SESSION INTEGRATION | PASS | real captured providers, SSE/Redis, dual/headless media, stop/release |
| AUTHORIZATION | PASS | protected business/control routes and ownership CPU regressions; no unauthenticated path added |
| REGRESSION TESTS | PASS | gates above |

Remaining Integration Owner gates: strict latency goal (BLOCKED by P50 clock bounds), physical speaker/human Chinese pronunciation and lip-sync assessment (NOT TESTED), actual authorized platform adapter/audience observation (NOT TESTED), sustained production-load/long-run validation (NOT TESTED). The Worker is left READY on the already-started server; no cloud instance was started, stopped or retrained. Test services/databases are cleaned separately from existing business services. These fixtures are not shipped as preset user dialogue.
