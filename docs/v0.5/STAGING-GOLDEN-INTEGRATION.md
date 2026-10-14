# Staging implementation and true live Golden gates

Status: IN PROGRESS. Branch `exp/v0.5-soulx-staging-golden`, starting at `d69166461af5cd9f7b75179754ea4c086435e251`. User explicitly authorized completing the additive contract, implementation, real live Golden tests and pushing a new remote branch. No main merge or default enablement.

## 2026-10-14 local repair checkpoint

Tested source `609ee76cec0924a44d683152d8e3d0285966a4ea` full local regression
PASS: Go/race/owned PostgreSQL/contract, Runtime280 total/12skip, frontend40/build;
64 CPU oracle tests. Price coverage now uses original SQL proofs, explicit
nonempty target hashes and a finite new-plan CNY policy; profile parsing agrees
across Go/Python. Acceptance reads actual checkpoint `sink` separately from
media receipt `sinkId`. Fresh complete V3 CPU speech synthesis totals753.2
padded seconds, each segment≤8s; no historical durations were added.
[Merge order, scope, raw evidence and rollback](LOCAL-REPAIR-CHECKPOINT.md).

No SSH/GPU or real Chrome/RTMP live run occurred in this checkpoint. Local PASS
does not upgrade historical failed real pilots. User notification to start GPU
precedes the next complete short business fixture; only after its machine and
human review proceed to G1/G2/fault acceptance. No default flags or frozen1
contracts changed, no branch push or main merge yet.

## 2026-10-13 actual integration checkpoint

Each production increment below was separately reviewed, normally merged, and followed by a complete immutable-source Go/race/owned-PG/Runtime/frontend gate before the next production merge. No frozen1 bytes, public DTOs, default flags or old TCP1.1 semantics changed.

| Owner/source | F merge | Result / evidence |
| --- | --- | --- |
| C `51e40fc` staging CNY speech/audit | `51e119321026282adb8598f6055c353a5ebef235` | [Complete PASS](evidence/integration-f/cny-postmerge-1/result.json) |
| C `6b2c44b` Golden profile probe pacing | `ada6f31f4f3693b1180cca941503b5b9a90cdee2` | [Complete PASS](evidence/integration-f/probe-spacing-postmerge-1/result.json) |
| C `c639cb0` Avatar configure lifecycle | `8be7374f1250d265ae704572140290d8915e907b` | [Complete PASS](evidence/integration-f/avatar-lifecycle-postmerge-1/result.json) |
| B `30915d8` passive WebRTC diagnostics | `2b77887d7874685c39acc47863a8f21560f8e30c` | [Complete PASS](evidence/integration-f/webrtc-diagnostics-postmerge-1/result.json) |
| A `63ca661` authorized PREPARING Stop | `7e2fb23011a670d580d62d6775202db530cef904` | [Complete PASS](evidence/integration-f/preparing-stop-a-postmerge-1/result.json) |
| C `e3b6aad` strict prephysical cleanup proof | `adb03b54ad03e8f9498a9c9de8c9123070fd169e` | [Complete PASS](evidence/integration-f/prephysical-stop-c-postmerge-1/result.json) |
| C `9669f3a` authenticated readonly StageHealth ticker | `81affc9dec48017ee2b83d90bf35d4f246dbbaff` | [Complete PASS](evidence/integration-f/heartbeat-c-postmerge-1/result.json) |
| C `3225bcd` observer-only safe LLM metadata | `4f61a97d8cf5642f0d94b409e91277a000fb5936` | [Complete PASS](evidence/integration-f/llm-diagnostics-c-postmerge-1/result.json), Runtime275 total/12skip |

F `e36d790` adds a passive SQL authority snapshot before the Golden Narration start only; C ACKed this test-only shared dependency. C `deb0efc` handoff/evidence merged at `a6215b5`; B `809c2b9` diagnostic evidence merged at `b8cd0bc`. These last two merges add documentation/evidence only; production/test source is identical to tested `4f61a97`.

Real pilot2 failed the existing shared provider cooldown; pilot3 exposed missing Avatar configure and unavailable PREPARING Stop; pilot4 exposed missing actual peer diagnostics; pilots5/6 diagnosed a 5s idle Worker-control disconnect during Chrome offer. Owner fixes above retain original limits/authority. Pilot7 then completed real narration and answer but failed bridge preparation. Pilot8 never created a Session after SSH forwarding disappeared; the authenticated tunnel was restored with SSH keepalive and Worker READY rechecked. No model download/reinstall.

Pilot9 at `4f61a97` recorded bridge LLM completion (HTTP200/stop,1835ms), resumed real narration, six staged artifacts/installed SQL commits (five COMPLETED, one UNKNOWN Stop tail), and normal ENDED/SEALED/released Stop. The selected bridge was empty, not played bridge media. Resumed narration repeated the answered price fact. It **FAILed overall**: actual Chrome audio RMS remained zero, AudioContext did not advance, recording bytes zero. Received RTP/track consumption are not audience playback proof. Owner diagnosis is pending. [All raw source/hashes](evidence/integration-f/real-golden-pilot-tcp-9/result.json). No accepted busy latency/drift, complete 10min/30min run, human naturalness, live crash matrix or real live UDS/platform matrix yet.

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

## Approved GPU profile and genuine business preflight checkpoint

CCR-BC-003 was explicitly approved by the user. Freeze2 adds distinct short/8s 1GiB incremental GPU profiles, preserving freeze1/old512MiB profiles, protocol1.1 and every other bound. B source `1f50a4e` is installed as release `a9a6231a9e2c3a83f2ce4ebdf76574d521dca70ad482cb5ed94adbccda16aad5` on the existing cached Linux RTX3080 10GiB. New short gate3 executed two real46-frame1.84s attempts; its immutable gate manifest digest is `sha256:65ed66fa77a2de18b4730918c9ca7628a8ca6d69b48ee4a5dbd3bade344f7fe9`. After physical profile restart, new8s gate1 executed two real158-frame6.32s attempts. Both are `PASS_REAL_GPU_STAGING_NO_SINKS`: artifact integrity, safe cancel/release and unchanged consumed pose only. They do not prove business completion, live sink consumption or full8s maximum acceptance.

F first real public-API business pilot at `a654502` failed before creating a Session: the actual LLM profile test returned `PROVIDER_TEST_FAILED`. macOS proxy DNS returned benchmark-range `198.18.1.13`; production Go SSRF validation correctly blocked it. Failure artifacts remain `/private/tmp/astralive-f-real-golden-pilot-tcp-1`. F adds only an opt-in test-process DNS wire relay to real authenticated Cloudflare HTTPS DNS. Actual Go resolution returns public `3.173.21.63`; production IP validation, pinned dialing, TLS/SNI, authentication and OS DNS are unchanged. F owns `golden_dns_test.go` as a shared test-only dependency and final merge owner. This environment preflight is not a business PASS.

Catalogv2 uses production canonical builtin fact IDs and trusted template substitution (`name`, `price`, `stock`, `sizes`), with exact fixture bytes/hash saved per gate. v1 CPU duration evidence is historical and is not attributed to v2. The independent live auditor has17 rejection cases passing; its fixtures exercise refusal paths only and cannot establish GPU or naturalness acceptance. C's explicitly captured staging-only CNY speech correction and safe observer identity fields require independent review/normal merge before the next real pilot.
