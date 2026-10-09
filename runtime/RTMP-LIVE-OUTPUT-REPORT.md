# AstraLive v0.1 RTMP Live Output Report

Date: 2026-10-08  
Primary host: `school-linux`  
Acceptance verdict: **READY FOR REAL PLATFORM RTMP**

## Executive result

The RTMP output implementation is complete and its individual gates passed: headless FFmpeg publishing, H.264/AAC conformance, continuous clocks, bounded fanout, five-minute idle, twenty FORCE interrupts, WebRTC/RTMP concurrent operation, RTMP outage isolation, reconnect, and more than ten minutes of A/V synchronization evidence.

The final gate passed on 2026-10-08: Session `session_6e7640d1e7fbe3b7ea61cf60b8c0b8e3` completed 911.9 seconds of dual output, with 918 seconds of browser monitoring, followed by normal Session Stop and verified cleanup. The timer started only after LIVE, browser connection/media, and RTMP publisher confirmation. Runtime PID 2826165 and FFmpeg PID 2826929 remained unchanged, as did the host boot ID.

The prior 804.5-second disappearance is classified as **SSH/HARNESS TERMINATION strongly supported; exact prior exit status unavailable**. The old harness tied remote processes to foreground SSH children and an EXIT/INT/TERM cleanup trap; the agent tool session subsequently returned `Unknown process id 76542`. No application traceback, FFmpeg error, OOM, or boot change was found. These facts support external termination but do not establish the exact terminating signal or prove a precise 900-second outer timeout.

Final services ran as independent `systemd --user` transient units with linger; the browser driver and SSH tunnel ran under macOS launchd, outside the agent command lifetime. There was no 900-second outer command timeout. RTMP core clocks, fanout, reconnect, and backpressure were retained. Acceptance-only periodic diagnostics exposed a deque slicing bug, which was fixed with a JSON serialization regression test; the first run was archived and a new complete run supplied all periodic metrics.

Validation: initial baseline 61 tests, 0 failures, 11 optional skips; after the diagnostics regression test, 62 tests, 0 failures, 11 skips. Remote aiortc integration 4/4, Real LLM 1/1, and Full Real Chain 1/1 passed. The first Full Real Chain invocation omitted the configured TTS model directory; its setup error and successful configured rerun are both retained.

## Architecture and fanout

```text
Session
  -> FanoutMediaOutput
       -> independent bounded queue/workers -> WebRTCMediaOutput
       -> independent bounded queue/workers -> FFmpegRTMPMediaOutput
```

`FanoutMediaOutput` gives each sink separate audio and video queues, backpressure counters, warning state, generation invalidation, drain, and cleanup. A slow or failed sink may drop its own stale media without blocking the other sink. WebRTC answer handling remains owned by `WebRTCMediaOutput`; RTMP lifecycle and encoding remain owned by `FFmpegRTMPMediaOutput`.

The outputs may run together, or RTMP may run alone with `WEBRTC_ENABLED=false`. The frozen public contract was not changed.

## RTMP configuration

Configuration is centralized in `RTMPSettings` and is loaded from deployment environment variables:

- `RTMP_ENABLED`, `RTMP_URL`, `RTMP_STREAM_KEY`
- `RTMP_WIDTH`, `RTMP_HEIGHT`, `RTMP_FPS`
- `RTMP_VIDEO_BITRATE`, `RTMP_AUDIO_BITRATE`, `RTMP_AUDIO_SAMPLE_RATE`
- `RTMP_PRESET`, `RTMP_VIDEO_BUFFER_MS`, `RTMP_AUDIO_BUFFER_MS`
- bounded reconnect, recovery-window, and stop-timeout settings

The tested default was 720x1280 at 25 FPS, H.264 `libx264`/`yuv420p`, and AAC 48 kHz stereo. Odd dimensions are rejected because `yuv420p` requires even dimensions.

## FFmpeg command and secret handling

The effective command shape is:

```text
ffmpeg -nostdin \
  -f s16le -ar 48000 -ac 1 -i pipe:<audio-fd> \
  -f rawvideo -pix_fmt rgb24 -video_size 720x1280 -framerate 25 -i pipe:<video-fd> \
  -map 1:v:0 -map 0:a:0 \
  -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -r 25 \
  -c:a aac -b:a 128k -ar 48000 -ac 2 -af aresample=async=1:first_pts=0 \
  -f flv rtmp://host/app/***
```

Start logs, warnings, captured stderr, evidence, and this report use a redacted target. The test used a fake local stream name and no real platform stream key. LLM credentials were loaded from a chmod-600 temporary file and deleted after acceptance; scanning process listings, the Runtime user journal, and evidence found zero credential matches. FFmpeg receives its output URL as an argument, so real stream-key invisibility in `ps` has not been established by this local-target acceptance and must be addressed before deploying a secret-bearing target.

## Headless media, video and audio encoding

Audio and video enter FFmpeg through two anonymous Linux pipes. No OBS, browser relay, physical sound card, FIFO directory, or large raw temporary file is used.

Avatar RGB frames are scaled while preserving aspect ratio and centered on a black canvas at the configured RTMP dimensions. They are not stretched. FFmpeg encodes video with CPU `libx264`; the Quadro K2200 is not required. Mono PCM TTS is resampled to 48 kHz when necessary and encoded as stereo AAC.

## Continuous clocks and A/V sync

The RTMP video task owns a fixed `RTMP_FPS` clock. It repeats the latest valid frame and starts with a black frame. The audio task owns a fixed 20 ms, 48 kHz clock and emits silence whenever no TTS audio is available. Producer speed therefore does not control output speed.

A captured stream exceeding ten minutes ended video at 612.915 seconds and audio at 612.885 seconds, a 0.030-second difference. This existing bounded A/V drift evidence is retained. FFprobe during the final accepted Session independently confirmed H.264/yuv420p, 720x1280, 25/1 FPS and AAC/48 kHz stereo.

## Backpressure and interrupt

Queue capacities are calculated from the configured time windows rather than large fixed frame counts. The tested 400 ms defaults produce ten video slots at 25 FPS and twenty audio slots at 20 ms per chunk. Each fanout sink owns its queues and drop counters.

FORCE advances the generation and invalidates queued old-generation media in both fanout and RTMP queues. Twenty consecutive FORCE interrupts retained FFmpeg PID 1395372; the connection was not restarted and new generations completed.

## WebRTC independence and reconnect

A 115-second real browser preflight ran WebRTC and RTMP concurrently. Browser audio packets and decoded frames increased, browser dropped frames remained zero, FORCE retained one FFmpeg PID, and normal Stop passed.

In the RTMP outage test, MediaMTX was stopped deliberately. The independent preview sink advanced from audio/video counters 1/1 to 23/23 while RTMP was unavailable. FFmpeg was relaunched with bounded backoff, publisher recovery succeeded, and the Runtime remained alive. Conversely, WebRTC peer lifecycle is isolated from the RTMP sink by separate fanout lifecycle state.

## Fifteen-minute soak and resource usage

The final mandatory run passed 911.9 seconds with one Session, Runtime, and FFmpeg publisher. Ten business cycles covered Speak, COMMENT, ordinary LLM, Product, Price, Stock, XL, FORCE, LOWER_PRIORITY, NONE and idle. FORCE interrupts totaled 30, LOWER_PRIORITY 10, and NONE FIFO checks 10. The existing independent 300.2-second idle PASS is retained without repeating a separate five-minute run.

Independent remote samples every 60 seconds recorded process state, RSS, CPU ticks, threads, FDs, host available memory, queue sizes, produced/consumed totals, drops, reconnects and write failures. RTMP and fanout queues stayed within audio/video bounds of 20/10. Counters advanced; process starts remained 1, reconnects 0, write failures 0, and failed pushes 0. Browser counters increased in all 30 periodic samples, with zero browser frame drops and 3 accumulated packet losses. There were 809 schema-valid events and no SESSION_FAILED, UTTERANCE_FAILED or MEDIA_FAILED.

Driver Runtime RSS was 243,412 KiB initially, 973,300 KiB near 5 minutes, 1,317,448 KiB near 10 minutes, 1,335,012 KiB near 15 minutes, and 1,262,544 KiB after Stop. Intermediate decreases and a roughly 1.2–1.3 GiB late-run range were observed; host available RAM remained around 42.6–43.9 GiB. FFmpeg RSS ranged from 136,624 to 139,248 KiB. This run does not show obvious unbounded memory growth; it does not prove absence of a long-duration leak.

## Cleanup

The final Session stopped through the formal API with SESSION_STOPPING followed by SESSION_ENDED; Backend status was ENDED. Runtime activeSessions returned to 0, media diagnostics contained no sessions, FFmpeg exited with no zombie, and Runtime FDs returned to 8 with no pipe FDs. Session workers/queues were removed. Only after these checks were the test infrastructure services stopped, ports released, and temporary secret file removed. MediaMTX's Compose wrapper returned 130 during deliberate infrastructure Stop; the container exited 0 and was no longer running.

## Scope and limitations

- The required local MediaMTX dual-output gate is complete; existing isolation/reconnect and idle evidence is retained.
- The historical incident's exact signal/exit code remains unavailable; no Runtime application crash is claimed.
- This phase does not connect to any real platform and includes no platform adapter, RAG, or MuseTalk work.

## Evidence

- [Final summary](../integration/evidence/rtmp-final/final-summary.json)
- [Harness investigation](../integration/evidence/rtmp-final/harness-investigation.json)
- [Final browser statistics](../integration/evidence/rtmp-final/browser-stats.json)
- [Final RTMP statistics](../integration/evidence/rtmp-final/rtmp-stats.json)
- [Final resource samples](../integration/evidence/rtmp-final/resource-stats.json)
- [Final FFprobe](../integration/evidence/rtmp-final/ffprobe.json)
- [Normal Stop](../integration/evidence/rtmp-final/normal-stop.json)
- [Processes after Stop](../integration/evidence/rtmp-final/processes-after-stop.json)
- [Infrastructure cleanup](../integration/evidence/rtmp-final/infrastructure-cleanup.json)
- [Final redacted FFmpeg log](../integration/evidence/rtmp-final/ffmpeg-redacted.log)
- First final-run evidence is preserved under `integration/evidence/rtmp-final/attempt-1/`; historical incomplete evidence remains under `integration/evidence/rtmp/`.

- [Summary](../integration/evidence/rtmp/rtmp-summary.json)
- [FFprobe and A/V sync](../integration/evidence/rtmp/ffprobe.json)
- [Runtime event summary](../integration/evidence/rtmp/runtime-events.json)
- [Resource samples](../integration/evidence/rtmp/resource-stats.json)
- [Redacted FFmpeg log](../integration/evidence/rtmp/ffmpeg-redacted.log)
- [Interrupt test](../integration/evidence/rtmp/interrupt-test.json)
- [Idle test](../integration/evidence/rtmp/idle-test.json)
- [Reconnect test](../integration/evidence/rtmp/reconnect-test.json)
- [Dual-output preflight driver](../integration/evidence/rtmp/browser-connected-runtime-rtmp-preflight-fixed-retry-1.json)
- [Dual-output browser preflight](../integration/evidence/rtmp/browser-connected-soak-rtmp-preflight-fixed-retry-1.json)
- [Incomplete 900-second driver](../integration/evidence/rtmp/browser-connected-runtime-rtmp-final-15m.json)

## Verdict

**READY FOR REAL PLATFORM RTMP** — the requested local acceptance gates passed. No real platform connection was made.
