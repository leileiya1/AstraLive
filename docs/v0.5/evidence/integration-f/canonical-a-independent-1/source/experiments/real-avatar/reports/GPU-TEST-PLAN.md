# RTX 4090 24 GiB GPU test plan

All metrics in this document are **NOT BENCHMARKED** until the named run
produces saved logs and decoded output.  The current K2200 is not a fallback
for this plan.

## Preflight

1. Use a fresh isolated Avatar Worker environment; retain AstraLive Runtime,
   frozen contracts, WebRTC and RTMP configuration unchanged.
2. Record GPU model, driver, CUDA, PyTorch, free/total VRAM, upstream commit,
   checkpoint hashes, source asset hashes and exact command line.
3. Before inference, run `ffmpeg -v error -i INPUT -f null -` for every
   selected video/audio input and record PASS/FAIL.  Do not promote ffprobe
   metadata alone to decode PASS.
4. Start with one worker and one avatar.  Do a warm-up that is excluded from
   reported performance metrics.

## Ordered runs

1. **MuseTalk 1.5 official offline baseline.** Use original `yongen` video +
   audio.  Save output and source/output probes.
2. **MuseTalk 30-second Chinese quality run.** Use the explicitly looped
   30-second test video and Chinese audio.  State the source-loop limitation
   in review material; it cannot prove long unique-motion quality.
3. **MuseTalk realtime run.** Measure cold and warm first frame; then measure
   worker inference FPS and emitted/output FPS under a 25 FPS audio clock.
4. **SoulX Lite matched run.** Use the official condition image and the same
   converted Chinese source audio.  Run the exact Lite script before making
   cross-model claims.
5. **Blind quality review.** Randomize/crop labels for at least two reviewers;
   score naturalness, mouth-audio match, face flicker/drift and identity
   consistency.  Preserve per-rater data and do not infer a winner from a
   single operator.
6. **Ten-minute stability run.** One continuous worker/session, normal Stop,
   generation interruption during speech, silence/idle transitions, and final
   process/FD/GPU-memory cleanup evidence.  Do not add elapsed time from a
   failed retry.

## Required run record

| Metric | Required value now |
| --- | --- |
| GPU VRAM peak / free | NOT BENCHMARKED |
| Worker inference FPS | NOT BENCHMARKED |
| Actual output FPS | NOT BENCHMARKED |
| Cold/warm first-frame latency | NOT BENCHMARKED |
| Audio-to-video latency | NOT BENCHMARKED |
| Face flicker / drift | NOT BENCHMARKED |
| Lip accuracy | NOT BENCHMARKED |
| Identity consistency | NOT BENCHMARKED |
| Idle/speaking transition stability | NOT BENCHMARKED |
| 10-minute continuous stability | NOT BENCHMARKED |

Success is not just a high model FPS: audio/video timestamps must progress,
no canceled-generation frame may reach the peer/fanout, normal Stop must
complete, and the Avatar Worker must release GPU allocations and child
processes.
