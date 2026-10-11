# AstraLive v0.5 Integration Plan

Original v0.4 baseline `cf6540bdcc788c037929836480812dfaa78362a2`; Phase 2 shared baseline `5a24478126211cbcde5a9565d0c6063748426527`; branch `exp/v0.5-integration-chaos`; worktree `../AstraLive-agent-f`; contract revision `v0.5-frozen-1`.

**Current gate: Phase 2 premerge review BLOCKED by missing C implementation and A/B/C persistence/orchestration seams. No implementation branches merged; F independently reran A/B/D checks and a failing actual SQL/Go/Python/Timeline seam probe. No new real GPU/Chrome/RTMP runs. See [PREMERGE-RISKS](PREMERGE-RISKS.md), [CHAOS-TEST-REPORT](CHAOS-TEST-REPORT.md) and [FINAL-ACCEPTANCE](FINAL-ACCEPTANCE.md).** [Frozen contract](ARCHITECTURE-CONTRACTS.md) governs interfaces, shared edits, flags and rollback. [Dispatch packet](AGENT-HANDOFF.md) lists owner-specific actions. Unexecuted tests remain NOT TESTED; legacy report PASS applies only to its stated scope.

## 1. Delivery sequence and merge ledger

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

Actual shared implementation edits: NONE at Phase1 or the current blocked Phase2 review. F adds docs/harness/evidence only; frozen contract is unchanged. Reserved ownership is contract §8. Append each actual change here before accepting its PR:

| CCR | File / reason | Owner | Dependency SHA | Peer ACK | Implementing SHA | Final merge SHA |
| --- | --- | --- | --- | --- | --- | --- |
| none | documentation-only freeze; no shared implementation edits | F | baseline cf6540b | A/B/C/D/E PENDING | freeze commit in handoff | NOT MERGED |

### Pending A/B/C seam review

[CONTINUITY-SEAM-REVIEW](CONTINUITY-SEAM-REVIEW.md) records A's proposed six-table/journal increment and the unresolved B pre-install proof ordering. Neither unprovided DDL/DTOs nor shared implementation diffs are approved as a whole. C may continue its own FSM and deterministic SQL/CPU integration; real-media gates remain pending.

| Proposed CCR | Scope / reason | Owners / dependency | Status |
| --- | --- | --- | --- |
| CCR-BC-001 | B private full-segment staging would return Credit before actual sink consumption; current Credit also updates native published-pose history | B+C and Worker/TCP reviewer; B Runtime cf43e2d, docs-only f769e3b | PROPOSED / NOT APPROVED; concrete credit/history preservation or protocol proposal required; any frozen semantic amendment needs user confirmation |
| CCR-C-001 | C staged Session/API/startup/interaction hooks; precise Scheduler gate diff now reviewed | C after A/B; dependency-only C HEAD7924f7f plus retained uncommitted patch/hash | minimal Scheduler scope/selection ACK; isolated legacy+F CPU probes/race PASS; complete production routing pending. Correct canonical Continuity flag and merged-source overflow mapping before final acceptance |
| CCR-C-002 | requested `ASTRALIVE_NARRATION_CONTINUITY_ENABLED` alias | C config in both services | NOT APPROVED; canonical `ASTRALIVE_CONTINUITY_ENABLED` only; explicitly reject known unsupported alternate setting, document and test operator behavior |

This is a proposed-request ledger, not an amendment of `v0.5-frozen-1` or an implementation merge. Task connector delivery is unavailable; peer ACK remains pending.
