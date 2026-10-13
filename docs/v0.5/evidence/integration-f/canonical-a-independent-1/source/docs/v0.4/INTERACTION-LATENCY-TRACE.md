# Interaction Latency Trace v0.4

## Observation boundaries

The same normalized trace ID travels selected comment → Go Utterance → Runtime → existing events/SSE. Go records local receipt origin, selected elapsed and accepted elapsed without comment content. Runtime stores up to256 content-free traces using monotonic elapsed time from Runtime admission, exported only through the bound/control-authenticated `/internal/v0.4/sessions/{sessionId}/interaction-traces`. Trace records contain IDs/stages/durations, not credentials or raw text.

| Required stage | Implemented observation | Real Agent B evidence |
| --- | --- | --- |
| comment_received | Go receive origin (trace log emitted on selection) | CPU/Mock |
| scheduler_selected | Go local monotonic delta | CPU/Mock |
| utterance_accepted | Go existing Speak returned | CPU/Mock |
| llm_started / llm_first_token | existing streaming iterator, only when LLM path runs | Fake LLM selected comment |
| first_speakable_segment | first fact or streaming segment before TTS | CPU/Mock |
| tts_started / tts_first_pcm | incremental TTS entry/nonempty PCM | Fake TTS |
| avatar_first_generated_frame | first matching-generation GPU_INFERENCE TALKING packet observed at Runtime | NOT TESTED |
| media_first_audio / media_first_video | output push returned, not downstream playback | Mock sink |
| browser_first_correlated_av | reserved receiver observation, no fabricated timestamp | NOT TESTED |
| rtmp_first_correlated_av | reserved external receiver observation, no fabricated timestamp | NOT TESTED |

CPU/synthetic frames use a distinct `avatar_first_returned_frame`; they cannot satisfy GPU-first-frame. Idle packets and old generations do not satisfy the bound media trace. Worker-host generation time itself is not measured by a Runtime packet receipt.

## Clock and statistics rules

Go uses receipt times carrying Go monotonic data. Runtime uses time.monotonic. Never subtract host wall timestamps or add unrelated host elapsed values as an exact end-to-end result. Source platform timestamp is provenance only. For selected→first text across Go/Runtime, a future observer must anchor command send/ack to a Runtime monotonic exchange and report offset/RTT uncertainty, or measure correlated receive milestones entirely on one observer clock. Chrome/RTMP receivers need their own trace association, preferably the existing opt-in generation/marker instrumentation. No guessed fixed A/V delay is introduced.

Percentiles use empirical nearest rank, with sample count, mean/max and bounded last256 window clearly labeled. Console hides P50/P95 below20 samples. Failure ratios use failed selections/selected attempts; event drop ratios use dropped/input, with filtering/expiry/merge separately reported. Fault/restart injection is a separate phase, not silently removed. Offline stress arrival clocks are explicitly virtual; real-wall replay clocks are measured; both inference consumers are Fake.

[evidence/interaction-latency.json](evidence/interaction-latency.json) records CPU phase selection percentiles and per-selected-trace Runtime-local decomposition: admission→speakable, speakable→PCM, PCM→CPU-returned frame and frame→Mock output admission. GPU/frame→Chrome/full-synchronized-reply durations are null/NOT TESTED. Selection→first speakable across hosts is BLOCKED for exact measurement. RTMP encoder enqueue/pipe send cannot be called platform viewing success; Chrome decoded/rendered A/V also cannot directly prove physical loudspeaker playback.

The provisional P50≤3s/P95≤5s target is BLOCKED for the real path. Fake load already shows waiting for prior speech can exceed it; TTL/fairness do not guarantee every selected reply meets5s. No slow sample is deleted to obtain PASS. Integration Owner must collect genuine SoulX+DeepSeek+XiaoYa+Chrome samples, then report latency decomposition, failure/drop/expiry ratios, queue peaks and operator/auto FORCE counts.

## Real receiver follow-up (2026-10-10)

The previously missing observations are now implemented by opt-in `scripts/interaction-browser-acceptance.ts` and `scripts/interaction-rtmp-observer.py`:20 actual native Chrome/independent RTMP samples with the captured real providers. [Follow-up report](AGENT-B-REAL-ACCEPTANCE.md) contains every sample, decomposition, failed earlier trials and clock uncertainty. Historical CPU table above remains scoped to that original run.

Go `observation` supplies local receipt age/selection/dispatch-ack; Runtime `clockOriginAgeMs` supplies query-time monotonic origin age. `media` is an integer-only, first-observation whitelist of business generation, speech marker, first Video PTS and speech-origin sample; no comments/user credentials are copied. Observer request/response bracketing maps those ages to its own clock, reports half-widths and preserves bounds. Media PTS is identity/timeline correlation, not a wall timestamp. Dispatch acknowledgement remains Speak return, not exact Runtime admission. GPU stage is Runtime receipt of actual GPU output, not Worker-host compute timing.

Chrome2.897s/4.177s and RTMP2.975s/4.229s P50/P95 are onset estimates (n20). The P50 clock-bound upper value3.194s prevents a strict≤3s PASS. Slowest Chrome sample6.669s remains included. Speaker/human lip-sync and actual platform viewers remain NOT TESTED. No receiver control token is exposed to browser code.
