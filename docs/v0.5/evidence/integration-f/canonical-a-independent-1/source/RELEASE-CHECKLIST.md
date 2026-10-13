# AstraLive v0.1 Release Checklist — Contract v1.1.0

Review date: 2026-10-08. One-hour stability verdict: **PASS**. Recommendation: **LIGHTWEIGHT_AVATAR_FOR_V0.1**.

## ASTRALIVE V0.1 CORE MVP ACCEPTED

- Primary Host: `school-linux`
- CPU: Intel i9-13900
- RAM: 64GB class
- Avatar: `LIGHTWEIGHT_AVATAR`
- Target media FPS: configurable, default 25
- Media pacing: dynamic backpressure
- Buffer: time-based
- GPU AI acceleration: not required for v0.1
- Physical sound card: not required

| Acceptance item | Status | Evidence and limit |
| --- | --- | --- |
| COMMENT | PASS | Actual Go→Runtime PLATFORM_EVENT priority 80, `INTERRUPT_LOWER_PRIORITY`, QUEUED→COMPLETED; absent live Session returned 409. |
| Product Tool | PASS | Product sizes and aggregate stock fetched through actual Runtime→Go Tool HTTP requests in Real and light modes. |
| XL size stock wording / Bad LLM | PASS | Bad LLM returned `XL有27件` on ordinary chat but was bypassed for supported product questions. [TTS-boundary evidence](integration/evidence/fact-safety-v1.1.json) shows safe XL wording; [ISSUE-003](integration/issues/003-product-size-fact-routing.md) closed. |
| WebRTC signaling | PASS | Full SDP offer passed Go→Runtime; complete answer received; invalid offer returned `WEBRTC_FAILED`. |
| Browser WebRTC (local Integration) | PASS | Actual local headless Chrome connected and observed audio/video tracks in Real and light modes. Cross-host deployment result is listed below. |
| Unique Mock Runtime / parity | PASS | Only `integration/mock_runtime` is runnable and supported; Backend Go Mock files removed. Python Mock and Real Runtime passed matching priority/FIFO cases; [ISSUE-004](integration/issues/004-backend-go-mock-runtime-parity.md) closed. |
| Session Context | PASS | Captured Go→Runtime command contained all four fields. |
| Interrupt | PASS | Mock/Real priority policies and Real Runtime generation tests passed; long-run timing remains for soak. |
| SSE heartbeat / Event schema | PASS | Explicit UTC heartbeat observed outside business Timeline; all observed Runtime Events validated. |
| Failure handling / duplicate control | PASS | Runtime 500/unavailable/timeout, Tool unavailable, duplicate Idempotency-Key/eventId, Redis retry, COMMENT 409 and invalid SDP tested. |
| Real TTS + lightweight Avatar | PASS | Real TTS opt-in 3 passed; lightweight Avatar opt-in passed; cumulative public E2E with Chrome passed. |
| Resource cleanup | PASS | Final normal Stop reached `SESSION_STOPPING` → `SESSION_ENDED`; Backend Session is ENDED, Runtime Session was removed, WebRTC closed, queues/workers were cleared, and test-owned processes/tunnels were removed. Sixty-one resource samples showed warm-up and fluctuation without clear unbounded growth. |
| Contract / Runtime / Backend / Frontend tests | PASS | Contract, Backend and Frontend gates were already confirmed. Final Runtime discovery passed 52 with 11 opt-in skips and 0 failures; real aiortc passed 4/4, real LLM 1/1, and the full real chain 1/1. |
| Docker/deployment environment | NOT RUN | No deployed Compose stack was validated; the GPU test used isolated processes and SSH tunnels. |
| RTX 2060 environment and baseline | PASS | RTX 2060 6 GiB, driver 595.91.07, system Torch 2.9.1+cu128/CUDA available; Ubuntu Runtime default 16 pass/9 skip and Contract 5 pass/0 fail. |
| GPU drawing benchmark | PASS, bounded | 512px/250 frames: Pillow CPU 0.0802 s; CUDA compute only 0.0111 s; CUDA with RGB readback 0.0952 s. This is a microbenchmark, not media throughput. |
| Real TTS + Lightweight Avatar smoke | PASS | 24.86 and 25.19 audio-clock FPS in two runs; FORCE interrupt, generation discard and cleanup PASS. VRAM flat within each run. Lightweight path is CPU Pillow, not GPU generative Avatar. |
| Cross-host ICE through formal Frontend STUN | PASS | The normal `useLivePreview()` peer reached `ICE=connected` and `connectionState=connected` with build-time STUN. [ISSUE-005](integration/issues/005-cross-host-webrtc-udp-reachability.md) closed as **RESOLVED BY DEPLOYMENT ICE CONFIGURATION**. TURN was not required on this network. |
| Cross-host Browser audio/video | PASS | Formal frontend at 1% playback volume without muting kept ICE connected for 1,826 s; 60 regular and 52 cycle samples showed growing audio packets/energy and decoded video frames. [Browser evidence](integration/evidence/browser-connected-soak-30m.json). |
| 30-minute non-browser stability | PASS, bounded | 1804.1 s, 376 public Go→Ubuntu Runtime cycles, 0 failure events, max waiting queue 1; browser was not connected. RSS warmed from 321.2 MiB to 889.1 MiB peak and 723.2 MiB after Stop. |
| 30-minute browser-connected stability | PASS | 1,826 s connected, 60 periodic samples, 52/52 cycles paired to browser media, 1,884 valid events, 0 failed events, 52 intended interrupts, 156/156 Product Tool 200, NONE FIFO and Session Stop PASS. RSS fluctuated, without obvious unbounded growth. [Audit](integration/evidence/browser-connected-audit-30m.json); [ISSUE-006](integration/issues/006-browser-connected-stability.md) closed. |
| MuseTalk PoC | NOT RUN | No model load, cached FPS, VRAM or OOM measurement; this phase explicitly excludes MuseTalk. |
| One-hour soak | **PASS** | Final School-Linux run: one Session/Peer, 3,671 s connected monitor, 37 business cycles and FORCE interrupts, T+90s/5m/15m/30m/45m/60m checkpoints, zero Session/Utterance/Media failures, zero drain timeouts, zero false Peer evictions, bounded 400 ms queues, normal Stop/Cleanup. Two DeepSeek `ConnectTimeout` warnings were recorded as external network failures; unexpected provider protocol failures were zero. [Final report](integration/school-linux/FINAL-ONE-HOUR-ACCEPTANCE.md), [audit](integration/evidence/school-linux-final/audit.json). |

[GPU Acceptance report](runtime/GPU-ACCEPTANCE-REPORT.md) records the earlier environment and bounded GPU findings; [Integration Acceptance report](integration/INTEGRATION-REPORT.md) remains the local baseline. ISSUE-008, ISSUE-009 and ISSUE-010 are now closed by the final School-Linux evidence. AstraLive v0.1 Core MVP is accepted; RAG and MuseTalk remain outside this acceptance.

## RTMP Live Output gate

| Acceptance item | Status | Evidence and limit |
| --- | --- | --- |
| Independent WebRTC/RTMP fanout | PASS | Separate bounded queues, workers, health and cleanup per sink; 115-second real browser dual-output preflight passed. |
| H.264/AAC output | PASS | H.264/yuv420p, 720x1280, 25/1 FPS; AAC 48 kHz stereo, probed during the final accepted publisher. [FFprobe evidence](integration/evidence/rtmp-final/ffprobe.json). |
| Headless output | PASS | System FFmpeg with separate anonymous audio/video pipes; no OBS, browser relay or physical sound card. |
| Five-minute idle | PASS | 300.2 seconds, continuous clocks and unchanged FFmpeg PID. [Idle evidence](integration/evidence/rtmp/idle-test.json). |
| Twenty FORCE interrupts | PASS | 20/20 with unchanged FFmpeg PID and no old-generation drain failure. [Interrupt evidence](integration/evidence/rtmp/interrupt-test.json). |
| RTMP outage isolation and reconnect | PASS | Preview continued during MediaMTX outage; bounded reconnect recovered the publisher. [Reconnect evidence](integration/evidence/rtmp/reconnect-test.json). |
| A/V sync | PASS, bounded | Captured stream exceeded ten minutes; audio/video end difference was 0.030 seconds. |
| Fifteen-minute dual-output run | **PASS** | Same Session/Runtime/FFmpeg: 911.9 seconds, browser monitor 918 seconds, 30 FORCE, 10 LOWER_PRIORITY and 10 NONE checks. Stable boot/PIDs, bounded queues, no unexpected reconnect/write/media failures, normal Stop and verified Session/infrastructure cleanup. [Final audit](integration/evidence/rtmp-final/final-summary.json). |

Current RTMP verdict: **READY FOR REAL PLATFORM RTMP** for the requested local acceptance gates. Prior 804.5-second termination is strongly supported as SSH/harness termination, with exact exit status unavailable. No real platform was connected. See [RTMP Live Output Report](runtime/RTMP-LIVE-OUTPUT-REPORT.md). The Core MVP acceptance above is unchanged.

## Real Platform RTMP production preparation

**Real Platform RTMP Readiness: PASS**

| Item | Status | Evidence and limit |
| --- | --- | --- |
| Credential/argv investigation | PASS | Fake-key school-linux probe confirms FFmpeg argv/ps exposure; default `/proc` has no hidepid. Required independent user/0600 files/host-level proc isolation documented. Current host must be isolated before loading real keys. |
| Target/profile/preflight/diagnostics | PASS | URL+key and exclusive full publish URL, generic accepted defaults, build-specific RTMPS check, non-publishing preflight, redacted health and sustained-rate drop warning policy. |
| Regression / short smoke | PASS | Runtime 79 tests: 68 passed, 11 opt-in skips, 0 failures/errors; remote targeted 24/24; short localhost full-URL FFmpeg smoke confirms codecs, stable interrupt PID, zero reconnect/write failure and normal Stop. No full 15-minute soak repeated. |
| Production system service preparation | PASS, template only | Dedicated-user system service, lock/single Session, graceful stop/restart/limits/journal and Mac-independent server path documented; syntax checked with executable-path substitution. No actual service/user/proc policy was changed. |
| Real platform publishing | NOT RUN | Platform, official URL/key, permissions, official media/TLS requirements, deployment isolation verification and Mac-off platform test remain required. |

Preparation verdict: **READY FOR PLATFORM CREDENTIALS**. See
[Real Platform RTMP Readiness](runtime/REAL-PLATFORM-RTMP-READINESS.md) and
[Stream Key Security](runtime/RTMP-SECRET-SECURITY.md). This PASS covers preparation;
it does not claim real-platform live acceptance. RAG and MuseTalk remain out of scope.
