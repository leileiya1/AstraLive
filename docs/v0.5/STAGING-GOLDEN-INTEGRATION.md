# Staging implementation and true live Golden gates

Status: IN PROGRESS. Branch `exp/v0.5-soulx-staging-golden`, starting at `d69166461af5cd9f7b75179754ea4c086435e251`. User explicitly authorized completing the additive contract, implementation, real live Golden tests and pushing a new remote branch. No main merge or default enablement.

## Delegated ownership and order

| Owner | New work / branch | Shared scope and reason | Final merge owner |
| --- | --- | --- | --- |
| A (delegated F contract author and A journal owner) | exact staging DTO/schema/hash vectors; `exp/v0.5-staging-contracts` | `timeline.go` additive installed ACK observationHash/producerIncarnation, existing keys/state/receipts preserved; canonical helper is a new isolated module | F |
| B (explicitly assigned staging Worker owner, independent of QUIC) | staging TCP1.2 Worker + audio-master pose proof; `exp/v0.5-staging-worker` | service Auth raw framing; Config/supervisor captured opt-in; adapter inference-thread final/safe signal, no algorithm change; Timeline sidecar/progress helpers without sink-interface rewrite | F |
| C | Runtime staging adapter/orchestration, captured modes and actual public-API/provider Golden fixture; `exp/v0.5-staging-runtime` | durable BEGIN_RUN flags and minimal startup/Session capture; immutable source/output descriptor mapping; keep default-off and original TCP1.1 | F |
| F | schema review/freeze, independent owned PG/real GPU/Chrome/RTMP gates, faults/evidence and final new-branch push | `integration/v0.5/**`, contracts/acceptance docs and evidence | F |

No Worker implementation starts before exact contract pin and affected owner ACKs. Original frozen1 bytes are retained; CCR-BC-002 is an additive revision. Normal source-pinned merges preserve history; regression after each implementation merge before the next. Shared files are never simultaneously refactored by separate owners.

## Required evidence sequence

1. Exact DTO/canonical vectors and owner ACKs. No guessed receipt IDs, float hash values or widened global Worker integer exemptions. New1.2 safe domain is distinct from unchanged old1.1 int63.
2. Legacy TCP1.1, CPU protocol fault/duplicate/state/lease/resource/cancel tests and full Go/race/Runtime/auth/SQL/contract/frontend regression. Synthetic transport frames are labelled CPU_SIMULATION.
3. Owned true GPU short profile, complete staged immutable artifact with no sink publication and unchanged consumed pose. Fence/cancel, confirm inference+encoder safe release and future pose; collect real host/GPU resources. Fail fast before further GPU work.
4. Explicit8s profile only after the short real GPU gate is hashed and pinned by the operator. Separate real duration/resource/lease-renewal proof; short-gate existence is not8s acceptance.
5. Real Backend HTTP/SQL + production Runtime + actual DeepSeek/XiaoYa/SoulX + native Chrome/local RTMP short chain. Audience comments may be deterministic replay, never synthetic language/audio/avatar substituted as real. Approved Go fact answers remain fact-safe; report actual LLM roles/calls rather than claiming every answer is LLM generated.
6. One continuous≥600s narration with≥5 seeded questions, correct turn/beat/fact/cursor and sink/Worker tuples; real spoken audio/video artifacts and human quality findings separate from automated fact matching.
7. One continuous1800s random question/priority/product-change run; retain latency raw rows, missing/censored observations, resources/buffers/old-frame drops/UNKNOWN. Busy P50≤5s/P95≤8s remains a target until measured.
8. Separate owned restart/disconnect/duplicate/Stop-FORCE/product-switch/database/Redis-off/FFmpeg fault gates. Missing Windows/Linux host cases explicitly NOT TESTED; QUIC remains independent/optional.

Short-profile cap1.92s and explicit max8s profile require actual TTS count including declared zero padding. No truncating speech, silently changing captured facts or arbitrary160ms segment slicing. StageRenew is explicit, fresh A grant with integer RTT margins, bounded60s total age; duplicate renewal cannot reset a Worker/client deadline or revive a fenced attempt.

## Runner and credentials

`integration/v0.5/golden_gate.py` archives the exact source, starts an owned disposable PostgreSQL cluster, supplies private key/token paths to the native Golden fixture, collects source/commands/versions/hashes and stops only its own cluster. A skipped or missing Go Golden case cannot pass. It checks evidence for supplied real credential values before publication; any match marks the evidence private and the gate failed. Never serialize tokens or SSH password.

GPU SSH and deployments are performed only by F. Existing model/environment caches are reused. No dependency reinstall/model download, public inference port, paid new instance, default provider switch or unsolicited main deployment. Endpoint tunnel/authentication/file permissions and exact installed release are verified before each new run. Old compatibility release/config is preserved for rollback.

Current CPU provider preflight is real: DeepSeek streaming request and XiaoYa native speech both executed successfully. GPU compatibility Ready from the prior direct smoke is not a staging or integrated Golden PASS. All subsequent results stay RUNNING/NOT TESTED until an actual fixed-source command finishes and artifacts are checked. Failures stay in separate run directories; durations from retries are never accumulated into a successful continuous run.

## 2026-10-12 implementation checkpoint

B and C subagent turns stopped on a usage limit. F preserved their incomplete changes separately as B `28ab56d` and C `51d9a15` (WIP). After resume, the original owners continue implementation/review; F retains merge ownership. B checkpoint passed the independent full module software gate, but B subsequently found a cross-connection UNKNOWN reset (P0). Deployment is blocked until its sticky-retirement correction and reproducer pass. These software results do not establish GPU or real business acceptance.

F uses `ASTRALIVE_GOLDEN_REAL=true` for the real gate. A fixed authored catalog and separate short fixture are being prepared with actual CPU TTS duration checks. All experiments remain opt-in.

## Actual Worker deployment and first negative GPU gate

B correction `466a1ff` passed the full independent premerge gate; normal F merge is `149d323`, whose complete postmerge gate also PASSes. No conflicts or frozen DTO changes. The existing cached Linux RTX3080 10GiB Worker was upgraded to release `22ae5a29fd6207c50cd705949b545e736877c8ef16deea0bd8105511dd56306f`; old release and private config backup retained. Doctor and real model READY passed. No dependency/model download.

Actual prerecorded XiaoYa speech (29440 samples/1.84s) on negotiated short TCP1.2 produced native GPU frames but was fenced with `STAGING_BUDGET_EXCEEDED` before an immutable Produced artifact. No sink publication or pose ACK occurred. This is **FAIL**, not a live PASS. Worker was stopped safely; instance remains powered/billable. B is adding precise safe telemetry to distinguish the fixed resource limits from other exceptions hidden behind that code; no budget is increased or model changed. The failure result is retained alongside exact source/release hashes.

CPU real-provider preflight2 had one LLM failure; its result is retained. Independent same-bound-provider preflight3 passed actual DeepSeek streaming and XiaoYa speech. The fixed authored catalog has 140 independent statements, two measured durations754.88s/753.88s (separate trials, never added), longest6.52s/6.32s. Actual production BuildPlan validates long140segments and smoke10segments. Native TTS ignores the CNY acronym in approved price answers; retained as an audible currency-quality gap. No naturalness/GPU/business acceptance follows from these CPU checks.
