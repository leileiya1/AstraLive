# AstraLive v0.1 School-Linux Acceptance Report

Date: 2026-10-07. Contract: frozen v1.1.0. Verdict: **FAIL**.

## Host

The target was `school-linux` (`sapiece-ThinkStation-P368-C3G108`): Ubuntu 26.04.1 LTS, Intel Core i9-13900, 61 GiB RAM, and Quadro K2200 4 GiB. The GPU was treated only as a display device. The boot ID remained `2c39c26e-0e68-4c2d-947f-3a211f5af075` throughout the work.

## Environment

System Python 3.14.4 was left untouched. An isolated CPython 3.12.15 venv was created. Go 1.24.13, Bun 1.3.14, and Node 24.21.0 were installed under the user account. Docker 29.5.1, Compose v5.1.3, and system FFmpeg 8.0.1 were already present. See [environment report](SCHOOL-LINUX-ENVIRONMENT.md).

## Migration

The source was copied to `/home/sapiece/AstraLive` with rsync. The transfer contained 321 entries / about 14.3 MB. `runtime/.venv`, `runtime/.local`, `frontend/node_modules`, `__pycache__`, `.pytest_cache`, and `.DS_Store` were excluded and rebuilt as applicable on Linux. Historical reports and evidence were preserved.

## Dependencies

Runtime base, real TTS, real Lightweight Avatar, real media, and test dependencies installed successfully; `pip check` passed. The sherpa-onnx model was downloaded with the repository checksum script. MuseTalk, large local LLMs, CUDA PyTorch, and legacy CUDA packages were not installed. Existing PostgreSQL and Redis were reused directly on localhost; MinIO was not required.

## Contract

**PASS.** `PYTHONPATH=. runtime/.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v` ran 5 tests with 0 failures, including the Bad LLM / XL fact-safety guard.

## Backend

**PASS.** The first `go test ./...` encountered transient EOFs while downloading modules from `proxy.golang.org`; an unchanged retry completed with 0 failures. No business code was changed to bypass tests.

## Runtime

**PASS for test gates.** Default discovery ran 36 tests, 25 passed and 11 provider opt-ins skipped, with 0 failures. All nine ISSUE-008 deterministic regressions executed: healthy consumer, stalled audio, stalled video, healthy plus stalled Peer, interrupt during drain, Stop after media failure, 300 short utterances, bounded Peer close, and old-generation enqueue race. A separate real-aiortc run passed 4/4 tests.

## Frontend

**PASS after completing the required toolchain.** Without a real Node executable, Bun's Node shim caused six Vitest suites to fail during collection at `z.object`. Installing Node 24.21.0, matching the known Mac baseline, made the required command pass: 6 files / 24 tests. The STUN production build also passed. `getWebRTCConfiguration()` remained in the production hook path and the built browser peer exposed the configured STUN server.

## TTS

**PASS.** Real sherpa-onnx CPU TTS produced non-zero in-memory PCM for all required cases. Model load was 504.9 ms. First-chunk / total generation measurements were:

| Case | First chunk | Total | Audio |
| --- | ---: | ---: | ---: |
| Ordinary Chinese | 167.1 ms | 302.3 ms | 5.512 s |
| Price | 131.7 ms | 141.3 ms | 4.150 s |
| Aggregate stock | 113.7 ms | 123.3 ms | 3.502 s |
| XL wording | 59.3 ms | 242.7 ms | 6.522 s |
| COMMENT-style reply | 69.0 ms | 175.3 ms | 4.629 s |

RSS warmed from 155.3 MiB before the first case to 275.4 MiB after all five. Process CPU-over-wall samples were about 200% after first-use initialization; the first case included library warm-up and reported 1524%. sherpa-onnx printed `Ignore OOV 'XL'`; this is recorded as a **KNOWN UX ISSUE** and did not prevent PCM generation.

## Avatar

**PASS.** The actual CPU Lightweight Avatar rendered 250 frames at 512×512. Configured audio-clock output was 25 FPS. Render capacity was 6,978 FPS, with 0.143 ms average, 0.139 ms p50, and 0.149 ms p95 per frame; process CPU-over-wall was 100%, and RSS was 189.7→190.0 MiB. GPU acceleration: **NOT REQUIRED FOR LIGHTWEIGHT V0.1**.

## Headless Audio

**PASS for the exercised path.** Physical sound card: **NOT REQUIRED**. TTS audio was generated as mono PCM16 in memory. Mac Chrome received browser audio over WebRTC and reported positive `totalAudioEnergy` before the later Peer eviction. No ALSA/PulseAudio output or dummy sink was used.

## WebRTC

**FAIL.** The formal frontend `useLivePreview()` peer initially reached `ICE=connected` and `connectionState=connected`. Chrome received 1,045 audio packets / 110,156 bytes with positive energy and decoded 523 video frames. Runtime then evicted the only still-connected Peer as `video_sender_stalled`; the 30-second browser sample was `disconnected/disconnected`. See [ISSUE-009](../issues/009-school-linux-webrtc-video-queue-peer-eviction.md).

## Product Tool

**PARTIAL PASS, not an acceptance gate completion.** Before the media failure, two Runtime→Go product requests returned HTTP 200. The five-minute business loop and one-hour Tool count were not run.

## Fact Safety

**PASS for automated guards; hour-long proof not available.** Contract acceptance captured the safe TTS-boundary XL wording and passed the hostile Bad LLM test. The School-Linux evidence contains no `XL有27件` or equivalent forbidden claim. The run stopped before a five-minute or one-hour transcript could be established.

## Interrupt

**PARTIAL.** FORCE and lower-priority flows began and Redis recorded intended interruption/completion events before the media failure. The runner failed before completing and acknowledging its first full business cycle, so the preflight interrupt gate is not accepted.

## WebRTC Drain

**LOCAL REGRESSION PASS; DEPLOYED REVALIDATION NOT COMPLETED.** No literal `WebRTC playback drain timed out` occurred. Instead, the production browser path exposed premature `video_sender_stalled` eviction when the 125-frame queue filled although the Peer was connected and had consumed video less than 300 ms earlier. ISSUE-008 therefore remains **FIXED — WAITING FOR ONE-HOUR REVALIDATION** and was not closed.

## Resource Usage

Before the browser run, Runtime RSS was 119,284 KiB and Backend RSS 22,232 KiB; available RAM was about 44.7 GiB. PostgreSQL and Redis used about 74.7 MiB and 49.4 MiB at the failure snapshot. K2200 usage remained the display baseline at 304 MiB, 40 °C, 0% utilization. The run was too short for a memory-leak or temperature trend conclusion.

## Queue Trend

**FAIL.** At eviction, audio was 455 enqueued / 150 consumed with queue 305/500; video was 200 enqueued / 75 consumed with queue 125/125. The consumer was active, but producer-to-playback backlog reached the fixed video capacity and triggered eviction. No long-run queue trend is claimed.

## One-hour Soak

**NOT RUN.** The 90-second readiness smoke failed before the formal five-minute preflight. Per the acceptance rules, neither the formal preflight nor the 3,600-second soak was started.

## Stop / Cleanup

**PASS after the failed smoke.** The browser runner issued normal Stop; Redis recorded `SESSION_STOPPING → SESSION_ENDED`, Runtime health reported `activeSessions=0`, and all test-owned Runtime, Backend, proxy, frontend, tunnel, and browser processes were removed. Ports 18000/18080/18081/18082/18083 were no longer listening. The host boot ID was unchanged.

## Errors

- Two `UTTERANCE_FAILED` and two `MEDIA_FAILED` events followed the healthy-Peer eviction. This alone fails Core MVP acceptance.
- Ordinary real-LLM utterances emitted `LLM_FAILED` and used input-text fallback in the deployed stack; recorded separately as [ISSUE-010](../issues/010-deepseek-flash-stream-fallback-on-school-linux.md).
- The initial pre-smoke stack attempt pointed Runtime at the old Mac tunnel Redis port; it was corrected to direct `127.0.0.1:6379/14` before the browser-connected smoke. Its failed evidence was retained rather than hidden.

## Evidence

- [Raw environment](../evidence/school-linux/school-linux-environment-raw.log)
- [Contract](../evidence/school-linux/school-linux-contract-tests.log), [Runtime](../evidence/school-linux/school-linux-runtime-tests.log), [real aiortc](../evidence/school-linux/school-linux-webrtc-integration-tests.log)
- [Backend final retry](../evidence/school-linux/school-linux-backend-tests-retry.log), [Frontend final tests](../evidence/school-linux/school-linux-frontend-tests-node.log), [Frontend build](../evidence/school-linux/school-linux-frontend-build-final.log)
- [Provider benchmarks](../evidence/school-linux/school-linux-provider-benchmarks.json), [real TTS tests](../evidence/school-linux/school-linux-real-tts-tests.log), [real LLM/TTS/Avatar](../evidence/school-linux/school-linux-real-llm-tts-avatar-test.log)
- [Browser failure](../evidence/school-linux/browser-connected-soak-school-linux-smoke-2.json), [Runtime failure log](../evidence/school-linux/school-linux-runtime-failed-smoke.log), [Redis snapshot](../evidence/school-linux/school-linux-failed-smoke-snapshot.log), [cleanup](../evidence/school-linux/school-linux-cleanup.log)

## Verdict

**FAIL.** Contract, component tests, real TTS, CPU Lightweight Avatar, headless PCM, initial cross-host ICE, Session Stop, and cleanup passed. The deployed WebRTC media path produced two `UTTERANCE_FAILED` events after evicting an actively consuming connected Peer, so the five-minute and one-hour gates were correctly not run.

`ASTRALIVE V0.1 CORE MVP FAILED`
