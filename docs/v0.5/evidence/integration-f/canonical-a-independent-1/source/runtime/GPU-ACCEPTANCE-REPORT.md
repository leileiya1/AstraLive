# AstraLive v0.1 GPU Acceptance / Deployment Validation

Date: 2026-10-06; ICE and browser stability follow-up: 2026-10-07. Contract: frozen v1.1.0. Current one-hour verdict: **FAIL**. The earlier GPU/30-minute stage reached **READY FOR ONE-HOUR SOAK**. Recommendation for v0.1: **LIGHTWEIGHT_AVATAR_FOR_V0.1**. This is not Release GO.

The later one-hour gate on 2026-10-07 **FAILED**; see [One-hour Production Stability](#one-hour-production-stability--2026-10-07) below. The original GPU and 30-minute results remain historical evidence.

## Environment

| Item | Observed on `ssh ubuntu-server` |
| --- | --- |
| OS | Ubuntu 26.04.1 LTS, Linux `7.0.0-38-generic`, x86_64 |
| Python | `python3` / acceptance venv: 3.14.4; bare `python` command is absent |
| GPU | NVIDIA GeForce RTX 2060, 6,144 MiB total; initial free 5,736 MiB, temperature 42 °C |
| Driver / CUDA | NVIDIA driver 595.91.07; `nvidia-smi` CUDA 13.2 |
| PyTorch | System Python 2.9.1+cu128, CUDA runtime 12.8; `torch.cuda.is_available() == True` |

The initial repository copy at `/tmp/astralive-gpu-acceptance-20261006` excluded macOS `.venv`, `.local`, `node_modules` and bytecode. A fresh Ubuntu `runtime/.venv` installed the Runtime, real TTS/Avatar/Media and test requirements; the pinned development TTS model was downloaded with the repository SHA-256 checking script. After an Ubuntu reboot cleared `/tmp`, the browser follow-up used `/home/sapiece/astralive-browser-acceptance-20261007` with a fresh venv and model. These remote deployment artifacts were not copied into source.

## Baseline and GPU Avatar benchmark

Default Runtime discovery: 25 tests, 16 passed, 9 real-provider opt-ins skipped, 0 failures. Root Contract discovery: 5 passed, 0 failures. Relevant real TTS and WebRTC opt-ins: 25 tests, 21 passed, 4 unrelated real-LLM opt-ins skipped, 0 failures. An attempted combined opt-in run correctly required an unavailable real LLM key; it is excluded from the Mock-LLM acceptance gate. See [Runtime baseline](../integration/evidence/gpu-runtime-baseline.log), [Contract baseline](../integration/evidence/gpu-contract-baseline.log) and [real-provider results](../integration/evidence/gpu-real-tests-supported.log).

`python3 runtime/tests/gpu_avatar_benchmark.py --frames 250 --size 512` on RTX 2060, three-repeat median:

| Path | 250 frames | Nominal benchmark FPS |
| --- | ---: | ---: |
| Pillow CPU draw + RGB export | 0.0802 s | 3,117 |
| Torch CPU mask + RGB export | 0.5768 s | 433 |
| CUDA compute only | 0.0111 s | 22,523 |
| CUDA compute + RGB readback | 0.0952 s | 2,626 |

Torch CPU/CUDA pixels matched for all 39 distinct mouth openings. Peak CUDA tensor allocation was 2.8 MiB. These are isolated drawing microbenchmarks, **not** end-to-end media FPS. CUDA compute FPS excludes RGB readback and cannot prove real-time avatar delivery; the current Lightweight Avatar actually uses the CPU Pillow path.

[Machine-readable benchmark](../integration/evidence/gpu-avatar-benchmark.json).

## Lightweight Avatar

The Ubuntu RTX2060 smoke used real sherpa-onnx TTS, Lightweight Avatar, Mock LLM and Mock Media. Session READY, FORCE interrupt, old-generation discard and cleanup passed. The initial run generated 54 video frames for 2.172 s of audio, **24.86 audio-clock FPS**, within the required 20–30 range. A repeat after the stability run generated 59 frames for 2.342 s, **25.19 FPS**, with interrupt and cleanup PASS. In that repeat, `nvidia-smi` showed **6 MiB at every stage**: idle, Runtime/TTS loaded, Avatar ready, speaking, after interrupt, after Session Stop and after manager close. The initial run showed 4 MiB before and after. The real TTS opt-in measured 199 ms to first chunk for its test sentence and 337 ms total; this is a separate single-sentence measurement. [Stage samples](../integration/evidence/gpu-smoke-stages.json).

The public Go chain on this deployment used Mac Go, isolated PostgreSQL/Redis, an Ubuntu Runtime, real TTS, Lightweight Avatar and real WebRTC media with Mock LLM. Go→Runtime Speak, COMMENT, Product Tool, XL question, SSE and Stop passed in the earlier non-browser run. A [test-browser E2E](../integration/evidence/gpu-e2e-stun-final.log) with test-only STUN also passed complete SDP signaling and inbound audio/video. The formal frontend STUN build passed cross-host ICE and the later browser-connected 30-minute gate.

Lightweight Avatar real-time throughput passed, but **this is not GPU generative avatar model validation**. VRAM stayed flat within each smoke run (4 MiB initially, 6 MiB on repeat), consistent with the CPU implementation; these results cannot support a claim that RTX 2060 ran an AI digital-human model.

## Cross-host WebRTC

The original default frontend ICE configuration **failed** across hosts: Chrome stayed `checking`/`connecting` despite track callbacks. Its offer carried mDNS host candidates; disabling local-IP masking alone still failed. A direct UDP probe from Mac to Ubuntu private address timed out. [Default failure log](../integration/evidence/gpu-e2e-default-failure.log).

The earlier test-only STUN diagnostic connected and observed 24 new audio packets, positive audio energy and 12 decoded frames, with first combined media observation **581.3 ms** after Speak. The formal frontend STUN build then passed the same cross-host path through `useLivePreview()`. Its accepted run kept ICE connected for 1,826 seconds, with audio and video growth at every periodic and Runtime-cycle sample. [ISSUE-005](../integration/issues/005-cross-host-webrtc-udp-reachability.md) is closed for ICE deployment; no TURN was needed on this network.

## Production Frontend ICE Configuration

`frontend/src/config/webrtc.ts` parses comma-separated `VITE_WEBRTC_STUN_URLS` and `VITE_WEBRTC_TURN_URLS` and optional TURN username/credential into standard `RTCConfiguration`. `useLivePreview()` passes it to `RTCPeerConnection`. Empty configuration yields `{}` for same-host development; invalid URLs are ignored with browser warnings. If the browser rejects a configured ICE URL, the hook retries with `{}` and warns. The example STUN service is configurable, not hard-coded. `frontend/.env.example` and `infra/.env.example` document build-time values; Compose passes them into the frontend image build. Static TURN credentials in a browser bundle are suitable for MVP validation only; production should issue short-lived credentials. Contract v1.1.0, public SDP route and direct Browser ↔ Runtime media remain unchanged. Frontend `bun run test` (24 tests) and `bun run build` passed.

## Cross-host Browser Result

Mac Chrome loaded the normal AstraLive Live Console frontend built with `VITE_WEBRTC_STUN_URLS=stun:stun.l.google.com:19302`, created and started a Session through the UI, and used its actual `useLivePreview()` peer. The harness observed the peer configuration and `getStats()` without substituting a peer or injecting ICE servers. The accepted run kept ICE and `connectionState` connected for 1,826 seconds; all 60 regular samples and all 52 Runtime-cycle samples showed rising audio packet/byte/energy and video packet/decoded-frame counters. The last cycle sample had 91,043 audio packets, 15,229,807 audio bytes, `totalAudioEnergy=0.004689`, 46,737 video packets and 45,519 decoded frames. The final peer state changed to `closed` only after Session Stop. [Browser evidence](../integration/evidence/browser-connected-soak-30m.json). STUN worked on this Mac ↔ Ubuntu path; it cannot guarantee traversal of other NAT/firewall configurations.

## Latency

The non-browser stability runner measures `event_to_speech_ms` from Mac COMMENT submission to receipt of Runtime `UTTERANCE_PLAYING` via Go SSE. It estimates `tts_first_chunk_ms` from Runtime `SYNTHESIZING` to `RENDERING` timestamps and `avatar_first_frame_ms` from `RENDERING` to `PLAYING`. These event gaps include event publication/orchestration overhead; they are not instrumented directly inside the TTS callback or renderer. `browser_media_start_ms` is a separate Chrome `getStats()` observation with test-only STUN and 100 ms polling resolution.

| Measure | Median across 376 COMMENT cycles | Maximum / observed browser sample |
| --- | ---: | ---: |
| `event_to_speech_ms` | 474.5 ms | 837.3 ms |
| `tts_first_chunk_ms` (event-gap proxy) | 133.0 ms | 224.0 ms |
| `avatar_first_frame_ms` (event-gap proxy) | 50.5 ms | 148.0 ms |
| `browser_media_start_ms` (test-only STUN) | one measured sample: 581.3 ms | 100 ms polling resolution |

## MuseTalk PoC

**NOT RUN.**

| PoC item | Result |
| --- | --- |
| Model load / peak VRAM | NOT RUN |
| Avatar preprocessing and cache | NOT RUN |
| Recommended input and 512px output FPS | NOT RUN |
| First frame / continuous 60-second FPS | NOT RUN |
| OOM / interrupt / cleanup | NOT RUN |

No MuseTalk weight was downloaded and no MuseTalk development was performed. This run cannot label MuseTalk as a candidate, degraded candidate or not viable on RTX 2060.

## Stability

A 30-minute public Go→Ubuntu Runtime **non-browser** pre-run completed in **1804.1 seconds**, with 376 cycles of Speak, COMMENT/XL Product Tool, FORCE interrupt, NONE queue and idle, followed by Session Stop. It observed 1,504 completed utterances, 376 intended interrupts, **0 failure events**, a maximum of one waiting utterance, zero waiting at Stop, and Stop PASS. [Run summary](../integration/evidence/gpu-partial-soak-30m.json) and [Redis event audit](../integration/evidence/gpu-partial-soak-events.json).

GPU use was 4 MiB before the run, 6 MiB after Stop and at the sampled peak; temperature 43–45 °C, sampled utilization 0%. The same-stage isolated smoke was flat at 6 MiB across all stages, so there is no evidence of a growing VRAM leak. The Runtime process RSS was 321.2 MiB before this Session, peaked at 889.1 MiB, and was 723.2 MiB after Stop; later 50-cycle segment averages were about 831–836 MiB. Process `%CPU` from `ps` was 91.7 at the final sample (cumulative percentage, not a phase peak). The large RAM warm-up and retained post-Stop RSS need longer observation or heap/native allocator inspection; neither PyTorch caching nor an object leak is established by these RSS numbers. Per-cycle render FPS and browser media were not sampled in this non-browser run; the separate smoke measured 24.86–25.19 FPS.

This pre-run **does not count as browser-connected acceptance**.

## 30-minute Browser-connected Stability

**PASS.** The accepted run monitored the normal Chrome `useLivePreview()` peer for **1,826 seconds**, with 60 regular 30-second `getStats()` samples and browser media paired with all **52/52** Runtime cycles. ICE and `connectionState` stayed connected until Stop. Audio packets, audio bytes, positive `totalAudioEnergy`, video packets and decoded frames increased at every regular and cycle sample; there were no stagnant or disconnected samples. The Runtime completed 52 rounds of Speak, COMMENT, Product/XL question, FORCE interrupt, NONE FIFO and idle over 1,821.8 seconds, with zero driver errors and Session Stop PASS. Redis contained **1,884 schema-valid events**, including 261 completed utterances, 52 intended interrupts and one `SESSION_ENDED`; `SESSION_FAILED` and `UTTERANCE_FAILED` were zero. All **156** Product Tool requests returned 200. The live Tool facts had sizes M/L/XL and aggregate stock 27; the established [TTS-boundary fact-safety check](../integration/evidence/fact-safety-v1.1.json) confirms the XL answer does not invent per-size stock. [Browser media](../integration/evidence/browser-connected-soak-30m.json), [Runtime run](../integration/evidence/browser-connected-runtime-30m.json), [event audit](../integration/evidence/browser-connected-audit-30m.json), [raw events](../integration/evidence/browser-connected-events-30m.json), and [Tool proxy](../integration/evidence/browser-connected-runtime-tool.jsonl).

During this accepted run, GPU VRAM stayed at **4 MiB**, temperature was **41–43 °C**, and sampled GPU utilization was 0% on the CPU Lightweight path. Runtime RSS began at **388.0 MiB**, peaked at **839.2 MiB**, and was **704.4 MiB** after Stop. The previous ten active samples averaged **819.5 MiB** and the last ten averaged **813.3 MiB**; RSS fluctuated and was not monotonic. The 30-minute data show no obvious unbounded increase, while a one-hour soak is still required for a longer trend. Runtime `%CPU` is cumulative process usage and was **56.0%** at the last sample. [Resource audit](../integration/evidence/browser-connected-audit-30m.json).

For comparison, an earlier run kept the normal STUN-configured frontend Chrome peer connected for **1,801 seconds** with 60 `getStats()` samples, but browser stats were paired with only **57 of 58** Runtime cycles because the final Runtime round finished after the monitor window. That run was partial evidence, not the accepted gate. [Earlier browser samples](../integration/evidence/browser-soak-last-cycle-unmonitored-media.json), [Runtime run](../integration/evidence/browser-soak-last-cycle-unmonitored-runtime.json), and [event audit](../integration/evidence/browser-soak-last-cycle-unmonitored-audit.json).

A subsequent runner added per-cycle browser acknowledgment. Its muted **45-second preflight** completed two Runtime cycles with corresponding browser samples, zero Runtime errors and Session Stop PASS, but browser `totalAudioEnergy` stayed 0 while the user had intentionally muted output because playback was too loud. After output mute was off, an independent Chrome audio clock advanced normally. A new **45-second preflight** at 1% browser element volume, without muting, passed: ICE stayed connected, audio packets, positive audio energy and decoded video frames increased, both Runtime cycles had paired browser samples, and Session Stop passed. The muted runs are inconclusive for product audio. [Muted browser preflight](../integration/evidence/browser-audio-playout-fail-45s.json), [quiet preflight media](../integration/evidence/browser-preflight-quiet-45s-media.json), [quiet Runtime result](../integration/evidence/browser-preflight-quiet-45s-runtime.json), and [diagnostic](../integration/evidence/browser-audio-and-host-diagnostic-20261007.md).

Separate long attempts were interrupted by Ubuntu reboots at approximately 00:11 and 01:52 local time; the available journal gives boot boundaries but not their causes. A later run reached about 17 minutes with 28/28 Runtime cycles paired to browser media and 84/84 Product Tool requests returning 200, then stopped when the user manually rebooted Ubuntu at approximately 07:59 local time. This user-initiated shutdown does not indicate spontaneous host instability. None of these interrupted runs satisfies the continuous 30-minute gate. [17-minute browser evidence](../integration/evidence/browser-soak-17m-host-restart-media.json) and [ISSUE-006](../integration/issues/006-browser-connected-stability.md). ISSUE-005 remains closed because the formal frontend STUN configuration established cross-host ICE; TURN was not required on the tested network.

An initial short browser preflight exposed `WebRTC audio queue overloaded` during long speech. `runtime/app/webrtc_media.py` now applies async queue backpressure; its regression test and real WebRTC integration tests passed. The later zero-energy browser samples occurred while Mac output was intentionally muted; the non-muted preflight and accepted 30-minute run showed increasing positive audio energy.

For the earlier 1,824-second partial run, GPU VRAM remained 4 MiB, temperature 41–43 °C, sampled utilization 0%; the Lightweight path is CPU-based. Runtime RSS began at 456.5 MiB, peaked at 933.1 MiB, and fell to 752.7 MiB after Stop. The final active samples rose to roughly 857–933 MiB but fluctuated and then declined; this is not evidence of monotonic, unbounded growth in that interval. It does not establish one-hour behavior or prove a memory leak. The accepted non-browser run remains separate from the browser-connected PASS.

## One-hour Production Stability — 2026-10-07

**FAIL.** A separate 5-minute preflight passed. The formal Mac Chrome → Go → Ubuntu Runtime monitor then ran for **3,632 seconds** with 87 complete mixed business cycles and 87/87 cycle media samples. The final periodic sample changed to `connectionState=failed`, `iceConnectionState=disconnected` before normal Session Stop. The remote Runtime SSH connection closed; subsequent host probes failed, and the initiating cause is unconfirmed. Redis had 4,738 valid events, 176 expected interrupts, no `SESSION_FAILED`/`UTTERANCE_FAILED`, and 524/524 Product Tool requests returned 200, but `SESSION_STOPPING` and `SESSION_ENDED` were absent. Stop, Runtime cleanup and post-Stop resource return were not verified. GPU VRAM remained 4 MiB in all 60 valid samples; Runtime RSS peaked at 1,263.6 MiB and fluctuated. [Full one-hour report](../integration/ONE-HOUR-SOAK-REPORT.md), [failure evidence](../integration/evidence/browser-connected-soak-60m.json), and [ISSUE-007](../integration/issues/007-one-hour-host-connection-loss.md). This later result leaves the v0.1 Core Technical MVP **not accepted**.

An independent retry after Ubuntu recovery also **FAILED**. Its 330-second preflight passed, but after 51 complete cycles and 2,232 seconds of driver time, Runtime emitted `UTTERANCE_FAILED` for `WebRTC playback drain timed out`; normal Stop returned `INTERNAL_ERROR`. This is [ISSUE-008](../integration/issues/008-webrtc-playback-drain-timeout.md). The [retry report](../integration/ONE-HOUR-SOAK-REPORT.md#independent-retry-after-ubuntu-recovery) and [Redis events](../integration/evidence/browser-connected-events-60m-retry-1.json) preserve the result. No Runtime production code was changed during acceptance.

## Recommendation

**LIGHTWEIGHT_AVATAR_FOR_V0.1** remains the implementation recommendation: real TTS and Lightweight Avatar met the 25 FPS audio-clock smoke gate with interrupt and cleanup. Formal frontend STUN resolved cross-host ICE, and the uninterrupted 30-minute browser-connected gate passed. ISSUE-005 and ISSUE-006 are closed. The one-hour gate **FAILED** in the initial host-loss run and the independent Runtime-failure retry (ISSUE-007/008); do not mark Core Technical MVP accepted or Release GO. MuseTalk remains **NOT RUN**.
