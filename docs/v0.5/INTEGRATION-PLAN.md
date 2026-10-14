# AstraLive v0.5 Integration Plan

## Latest execution — 2026-10-14 one-hour run

F serially merged C renewal-drain repair as `b816ac0`, private compact bridge
policy as `a1583df`, and explicit bridge indices as `88a6824`. Each exact merge
passed the full software/owned-PG gate before the next real attempt. Frozen1
bytes and experimental defaults are unchanged. [Complete attempt ledger and
evidence](ONE-HOUR-GOLDEN-PROGRESS.md). Original A→B→C→D history is preserved.

Hour-7 is running from immutable `88a68246d46a3942515d9895247a3ebfe15e2e07`
after verified cached GPU restart. No live code replacement or Chrome peer
recreation is allowed. After normal Stop, independently audit closed SQL,
native Chrome/RTMP recordings and resource samples. F separately merged B's
post-run-only metrics tool `34d978e` as `f378e96`; its 21 rejection tests pass.
This adds no production changes and cannot upgrade an original failed gate.
Then record remaining acceptance gaps and push the authorized new F branch;
never main. Earlier sections are historical plans/checkpoints.

## Latest source / next execution

Final local repair source `25f58511cb6b46e4783a25b018487ebda0237e30` passes
full regression. Real pilot11 failed before narration due to missing first RTP
stats baseline; cloud was then switched off by the user. The acceptance-only
sampling/cleanup fix and two preserved FK-fixture failures are in
[the scoped report](BROWSER-AUDIO-PREREQUISITE-REPAIR.md). F owns these test files;
no production owner files/frozen contracts/defaults were changed.
Wait for cloud availability to execute a new complete short real business run,
then G1/G2/fault/A/V gates. Local browser readiness is not live acceptance.

## Current phase — 2026-10-14

F branch is `exp/v0.5-soulx-staging-golden`; final software source
`609ee76cec0924a44d683152d8e3d0285966a4ea` passes the full local integration
gate. Approved additive staging, canonical-price proof repairs and profile
agreement are integrated serially. [Exact followup merge/source table, ownership,
evidence, flag matrix and rollback](LOCAL-REPAIR-CHECKPOINT.md).
No frozen1 bytes or experimental defaults changed. Current work needs a new real
GPU/Chrome/RTMP business run; G1/G2/full crash and host acceptance remain pending.
The user was notified to start the cloud only after local gates/preflight passed.
Push the authorized new branch after the real-testing checkpoint; never main.

Original v0.4 baseline `cf6540bdcc788c037929836480812dfaa78362a2`; Phase 2 shared baseline `5a24478126211cbcde5a9565d0c6063748426527`; branch `exp/v0.5-integration-chaos`; worktree `../AstraLive-agent-f`; contract revision `v0.5-frozen-1`.

**Historical pre-staging gate: A→B→C→D normal merges PASS; separately reviewed C lifecycle incrementbb8d8ef also full merged-source PASS. Runtime225 total/12 skipped and frontend40/build; actual PostgreSQL/Backend/Python TCP+UDS/cleanup-fault gates executed. Previous6095989 native synthetic659.662s/five-question run remains pinned to that source. Real GPU compatibility Worker was installed/READY with two direct inference generations PASS; strict SoulX Continuity was NOT TESTED. CCR-BC-002 direction was approved; detailed contract review was HOLD before implementation.** [Ledger](evidence/integration-f/merge-ledger.json), [acceptance](FINAL-ACCEPTANCE.md), [CCR](CCR-BC-002-SOULX-STAGING.md). Frozen1 bytes unchanged; flags default off. The old review pins/tables below are historical discovery, not current delivery status or cloud powered-state checks.

## 1. Delivery sequence and merge ledger

Actual current merges and postmerge proof are in [merge-ledger.json](evidence/integration-f/merge-ledger.json). The following table retains the **initial review pins**, not current implementation or merge state.

| Order | Owner / delivery | Entry gate | PR / implementation SHA / F merge SHA | Current state |
| --- | --- | --- | --- | --- |
| 0 | F contract freeze | baseline/source review, no implementation edits | local freeze commit recorded in AGENT-HANDOFF; no PR yet | contract frozen, peer ACK pending |
| 1 | A PostgreSQL durability | ordinary isolated Go/PG/Runtime checks pass; B/C journal/schema still absent | no PR supplied / e5f14a14a04fdd4968af3c8dc3530bb22202e8b6 / NOT MERGED | reviewed; core merge gate held |
| 2 | B Audio-master Timeline | standalone media tests pass; real TimelineJournal adapter missing | no PR supplied / cf43e2d3dd6a9223648eaced2526d13e0ccbf8e1 / NOT MERGED | reviewed; core merge gate held |
| 3 | C Narration continuity | implementation required; current C is documentation baseline | no PR / 5a24478126211cbcde5a9565d0c6063748426527 / NOT MERGED | NOT IMPLEMENTED; user confirmed |
| 4 | D Go→Python local IPC | actual macOS independent TCP/UDS/race passes; shared patch fails on A main.go | no PR supplied / 1a1bce2a1cb3f933be607998576bd64558bb11be / NOT MERGED | deferred until core stable and wiring rebased |
| 5 | E Python→GPU QUIC | optional, separate capability/TLS/credit/fence/fallback proof | PENDING / PENDING / NOT MERGED | optional; NEVER C release blocker |

F freeze commit must be ancestor/cherry-picked reference of implementation results, or an explicit mapping must prove equivalent contract revision. Pin supplied commits before testing; no floating branch acceptance. Before each merge, record source SHA, dependencies, shared-file CCR approvals, exact commands and artifact hashes. Each implementation PR merges independently after its gate, not a five-branch combined merge. Conflicts return to owners with file/semantic explanation. F never accepts unreviewed automatic conflict resolution.

## 2. Phase 2 harness work, before implementation merges

The following remain the planned full harness interfaces. Phase2 now includes `integration/v0.5/premerge_probe.py` and a F-owned Go fixture to expose missing real SQL/journal seams; it does not replace the full deterministic narration/Chrome/RTMP Golden harness. Phase1 created no skeleton. Baseline capability discovery must explicitly label narration/epochs/Redis-off/UDS/QUIC UNSUPPORTED/NOT TESTED, while ordinary Speak/interaction and media measurement can run. An unsupported old API is not a successful chaos test. Preserve all legacy tests and evidence.

| Harness | Determinism / required oracle | Baseline path |
| --- | --- | --- |
| narration fixture | versioned product snapshot, required facts/beat ordinals, stable segment hashes,2–5s target segments, seed and expected cursor; no invented SKU inventory | ordinary AUTO_SCRIPT Speak chunks; no continuity claim |
| comment replay | random seed/time/priority/content,≥5 in10min, bounded burst, product-switch schedule; selected/refused reasons and source IDs | trusted v0.4 Mock/Replay entry; legacy dev COMMENT tested separately |
| crash harness | only owned PID/start-time/service/container identity, injection timestamp, prerequisite safety gate, bounded recovery/cleanup | isolated Backend/Runtime/Worker/Redis/FFmpeg topology; never kill shared services |
| stale epoch frames | full run/timeline/business/Worker mapping, inject at queue/decode/commit/sink seams; counters and no current credit leakage | existing generation/worker fence tests; run/timeline unsupported |
| duplicate/reorder events | fixed permutations, duplicates/conflicting hashes, delayed/missing stages; final durable projection invariants | existing ApplyEvent+Redis replay; v0.5 producer/order tests await A |
| Redis-off startup | Redis URL unreachable AND process absent; SQL migrations/start/readiness/events/SSE/ownership/recovery without Redis | baseline records expected unsupported/readiness failure, never masks it |
| Chrome AV | real native Chrome+actual providers/GPU, marker correlation, first related audio AND video, clock uncertainty, stall/device-switch probes | reuse `scripts/interaction-browser-acceptance.ts`, `interaction-real-scenarios.ts`, observer tests after audit; never Fake acceptance |
| RTMP record/ffprobe | local recorder ownership, complete output, packet/frame PTS/DTS/time_base, decode errors/drift/reconnect and correlated answer | audit `scripts/interaction-rtmp-observer.py`, existing RTMP tests; not platform audience |
| benchmark schema | run/contract/all SHAs/config/seed/topology/versions/raw artifact hashes, clock domains/bounds, modes/providers, failures/censored samples, percentiles/resources | separate baseline and candidate evidence; mock/unit/microbenchmark/real scopes explicitly typed |

Do not launch paid GPU/cloud instances, download/retrain weights, switch default avatar/provider or destroy other agents' Sessions during harness preparation. Real acceptance needs an available isolated owned topology; absent environments are NOT TESTED. Compare baseline/candidate on the same topology and immutable inputs; reruns stay separate and failure artifacts remain.

## 3. Gates per implementation merge

Record command exit status, duration, environment, raw log/hash, passed/failed/skipped and actual scope. Missing environment skips cannot become PASS. New migrations require clean-schema AND upgrade-from-baseline AND concurrent-start tests on disposable PostgreSQL. Auth/ownership needs real SQL and routes, not just a schema validator.

| Gate | Reproducible command / requirement |
| --- | --- |
| Go unit + race | in backend: `go test ./...` and `go test -race ./...`; isolated DB tests enabled, original skips listed |
| Python | `PYTHONPATH=runtime <test-python> -m unittest discover -s runtime/tests -v`; Worker discovery in pinned CPU/media environment; preserve real opt-in skips |
| frozen contracts | `<contract-python> contracts/validate_v1_1.py`; new v0.5 golden canonical bytes/hashes/schema validation; no frozen generated diff |
| frontend | in frontend: `bun run test`, `bun run build`; inspect generated diff before accepting |
| SQL/migrations | A disposable clean/upgrade/concurrent-run migration commands + invariant queries + restore/rollback evidence; no production DB cleanup |
| ownership | existing `backend/internal/httpapi/authorization_integration_test.go`, userconfig security/ownership tests plus journal/recovery/revocation/Room-owner cases |
| existing interaction | `scripts/interaction-test.sh` only with disposable caller DB+Redis; redirects historical output paths to F-owned evidence in new wrapper before use. Existing script writes docs/v0.4 evidence, so do NOT run it unchanged for v0.5 |
| media | B WebRTC drain/fanout/RTMP/bound-media/generation regressions; E unchanged TCP protocol/credit tests; then required scoped real media regression |
| diff/ownership | `git diff --check`; owned/shared file ledger, no deleted regression/history/secret payload; pinned validated provenance preserved |

Phase 1 checked document/source invariants and frozen-contract validation. Phase 2 independently ran A full Go/race/DB, B Runtime and D transport checks plus a failing cross-service seam probe. The complete matrix on an actually merged candidate, including frontend and real media, remains pending; independent source snapshots cannot pass that gate.

## 4. Golden gates and measurement rules

| Gate | Required execution / evidence |
| --- | --- |
| G1 | one continuous10-minute product narration,≥5 seeded comments at random positions; selection/refusal, natural semantic boundary/relevance/next Beat, duplicate/omitted fact ledger, no stale audio/video. Human assessment beside automated fact matching |
| G2 | one uninterrupted30–60-minute random comments/priorities/content/product switches; busy selected→Chrome related AV P50/P95/P99; interruption→last narration sample; answer-end→first resume audio; drift/GPU memory/CPU/RAM/buffers/stale drops/resume/crash evidence |
| G3 | owned Go/Python/Worker/Redis/RTMP FFmpeg kills; transient PostgreSQL failure; duplicate Outbox+Inbox; delayed ACK; stale Worker frame; disconnect; Stop/FORCE and product-switch races. Durable recoverability, fresh authorization, no old epochs, UNKNOWN not replayed; complete PG-only without Redis |
| G4 | real Chrome+RTMP monotonic PTS/drift P50/P95/max, visible jumps/old lip frames/audio overlap, reconnect timestamps, browser device change/stall; server/sink/observer clock domains separate |
| G5 | Linux single-host local GPU and remote GPU; Windows loopback if present; UDS/TCP; QUIC/TCP; no Redis; all-default compatibility. Each unrun cell NOT TESTED |

Busy latency starts at durable selected decision, with separate arrival→selected queue delay reported; starts are never reset at dispatch/answer generation. First correlated AV requires BOTH related audio and video, not any GPU frame/idle motion/filler. Percentiles nearest-rank `ceil(n*p)-1` with n/raw samples/outliers/timeouts; uncertainty upper bounds must meet targets P50≤5s/P95≤8s to PASS. At least20 measured selections for a percentile gate; P99 with small n is exploratory, not a service SLA. Report selected-input completion ratio and TTL rejections to prevent selection bias. Keep Fast/LLM paths and busy/idle cohorts separate. Do not sum stage percentiles. Match actual product-answer markers/facts, not generic talking animation.

Capture decision and audio boundaries within their true clock domains; cross-host exchange bounds/ages/drift explicit. Native estimated playout, decoded Chrome recording, AudioContext and physical loopback are distinct evidence; RTMP pipe credit is not decoded/platform playback. No accumulation of durations across restarts/retries into G1/G2. Crash runs have separate IDs.

## 5. Decision documents and rollback ownership

`CHAOS-TEST-REPORT.md` and `FINAL-ACCEPTANCE.md` now record the failed premerge core gate and explicit NOT TESTED Golden/host cases; they are not a final successful release report. They must include run manifest, environment and raw evidence index, faults/windows/outcomes, actual PR/source/merge SHAs, compatibility checklist, flag matrix, rollback command/evidence, and per-feature PASS/CONDITIONAL/FAIL/NOT TESTED. Report full untested mode matrix. Baseline archived evidence cannot pass a new v0.5 gate.

Rollback follows contract §9; A owns durable sealing/receipt preservation and migration compatibility; B output fence/clean clocks; C narration UNKNOWN cursor disposition; D TCP restoration; E TCP/Lightweight safe boundary; F records evidence and decision. Any unknown tail prevents automatic replay during either recovery or rollback. Current per-feature decisions and tested scope are in FINAL-ACCEPTANCE: no new feature may be enabled by default; leave durability/MediaTimeline/Continuity disabled and local/remote transports TCP. No implementation deployment occurred in this review.

## 6. Shared edit / CCR ledger

F's manual edits remain docs/harness/evidence only; A-owned implementation/shared entry edits are now incorporated through the normal A merge. Frozen contract is unchanged. Reserved ownership is contract §8; source/merge SHA and shared reviews are recorded below and in the actual ledger.

| CCR | File / reason | Owner | Dependency SHA | Peer ACK | Implementing SHA | Final merge SHA |
| --- | --- | --- | --- | --- | --- | --- |
| none | documentation-only freeze; no shared implementation edits | F | baseline cf6540b | A/B/C/D/E PENDING | freeze commit in handoff | NOT MERGED |
| A integration | A durability startup/dispatch/idempotency/Runtime hooks in reserved shared files | A; F reviewed/merged | baseline5a24478 | F pinned independent/postmerge gate PASS; C consumes owned seams, D follows | a28a409 |89179c7 |
| CCR-B-001 | B V2 flag primary plus frozen-name alias; inconsistent values reject startup | B; F acknowledges explicit user decision | B task user confirmation2026-10-11T00:43:32.780Z | user answer “可以就照你说的做” to the exact flag rule; F verified original B task message | dda7936 | pending B merge |

### Pending A/B/C seam review

[CONTINUITY-SEAM-REVIEW](CONTINUITY-SEAM-REVIEW.md) records A's proposed six-table/journal increment and the unresolved B pre-install proof ordering. Neither unprovided DDL/DTOs nor shared implementation diffs are approved as a whole. C may continue its own FSM and deterministic SQL/CPU integration; real-media gates remain pending.

| Proposed CCR | Scope / reason | Owners / dependency | Status |
| --- | --- | --- | --- |
| CCR-BC-001 | B private full-segment staging would return Credit before actual sink consumption; current Credit also updates native published-pose history | B+C and Worker/TCP reviewer; B Runtime cf43e2d, docs-only f769e3b | PROPOSED / NOT APPROVED; concrete credit/history preservation or protocol proposal required; any frozen semantic amendment needs user confirmation |
| CCR-C-001 | C staged Session/API/startup/interaction hooks; precise Scheduler gate diff now reviewed | C after A/B; dependency-only C HEAD7924f7f plus retained uncommitted patch/hash | minimal Scheduler scope/selection ACK; isolated legacy+F CPU probes/race PASS; complete production routing pending. Correct canonical Continuity flag and merged-source overflow mapping before final acceptance |
| CCR-C-002 | requested `ASTRALIVE_NARRATION_CONTINUITY_ENABLED` alias | C config in both services | NOT APPROVED; canonical `ASTRALIVE_CONTINUITY_ENABLED` only; explicitly reject known unsupported alternate setting, document and test operator behavior |

This is a proposed-request ledger, not an amendment of `v0.5-frozen-1` or an implementation merge. Task connector delivery is unavailable; peer ACK remains pending.

A subsequently delivered ee5500b/edd4e1e and then the Worker fix/final evidence tip a28a409. F independently validated the final pin, merged A at89179c7 and passed the complete postmerge gate. B Runtime85bec11/latest evidence dda7936 has the installation-order fix. Latest C owner progress, FORCE and whole-Session product retirement review are in CONTINUITY-SEAM-REVIEW; C final candidate/combined acceptance and D production wiring remain pending.

## Current followup (2026-10-12)

D source2837bef merged85d7654; C lifecycle source4d5a0f8/implementationb028f5a mergedbb8d8ef. Both merge gates are archived under integration-f. D actual production startup/protected probes and C primary/alias helper now integrated. A independently scoped ACKs both owner sources. F remains sole final merge owner. No main changes.

Compatibility GPU deployment is a separate operator action at user request, source85d7654 and release04c2be21, cached environment/models, no downloads. It remains READY/running and charged instance remains on. This does not unblock strict immutable staging. CCR detailed DTO/hash/release/lease/canonical issues in its section10 must be resolved and owners ACK before capability implementation; no simultaneous refactor of shared Session/Worker entrypoints.
