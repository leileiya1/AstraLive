# Model preparation boundary

## MuseTalk 1.5 — primary

Official repository: https://github.com/TMElyralab/MuseTalk at
`0a89dec45a0192b824e3cf4daf96c239440c5ed8` (MIT repository license).
The README identifies 1.5 as the recommended release and documents normal
and realtime entry points: `sh inference.sh v1.5 normal` and
`sh inference.sh v1.5 realtime`.  Its realtime configuration uses
`preparation: True`, a video path, and `audio_clips`; preparation can be set
false only for subsequent clips of an already-prepared avatar.  The upstream
README recommends a 25 FPS input, which is why the prepared copy is 25 FPS.

Prepared handoff:

- Baseline pair: `musetalk/original/original_video.mp4` plus
  `musetalk/original/official_yongen.wav`.
- Scheduler/latency inputs: `musetalk/normalized/test_10s.mp4` and the
  explicitly looped `musetalk/normalized/test_30s.mp4`.
- Chinese audio: `audio/musetalk/short_10s_source.wav` (and the remaining
  original-rate files under `audio/`).
- Input mapping: `configs/musetalk-v15-realtime-inputs.yaml`.

Not done by design: no Python/CUDA environment, no MuseTalk checkpoint,
VAE/Whisper/DWPose/SYNCNet components, and no inference execution.  K2200
with 4 GiB is explicitly excluded from this workload.

## SoulX-FlashHead Lite — comparison

Official repository: https://github.com/Soul-AILab/SoulX-FlashHead at
`9bc03de06bb0de82cd6bc477804512ae06144bf2` (Apache-2.0 repository license).
The Lite launcher passes a condition image and audio to `generate_video.py`:
`--model_type lite --cond_image ... --audio_path ... --audio_encode_mode
stream`.  The minimal input is therefore one source image, not a source
video, plus an audio file.  The upstream code loads audio as mono at the
configured sample rate; the official sample is 16 kHz mono, and separately
converted 16 kHz mono Chinese files are supplied for comparison.

Prepared handoff:

- Exact upstream baseline: `soulx/normalized/official_girl.png` plus
  `soulx/original/official_podcast_sichuan_16k.wav`.
- Chinese comparison input: the same image plus
  `audio/soulx/{short_10s,medium_30s,long_60s,silence_10s}_16k_mono.wav`.
- Exact Lite command template: `configs/soulx-flashhead-lite-command.txt`.

Not done by design: `SoulX-FlashHead-1_3B` and `wav2vec2-base-960h` weights
were not downloaded, no Gradio server was launched, and no image/video was
obtained outside the official repository.

## Ditto — recorded only

Official material: https://github.com/antgroup/ditto-talkinghead
(Apache-2.0); its checkpoint reference is
https://huggingface.co/digital-avatar/ditto-talkinghead.  It remains deferred:
no clone, environment, checkpoints, sample assets, or tests were performed.

## Integration shape

Do not replace AstraLive's Go Backend, Runtime, TTS, WebRTC, RTMP, frozen
contracts, or systemd services.  The future Avatar Worker owns model loading,
avatar preparation/cache, inference, and per-generation cancellation.  It
accepts already-produced PCM/TTS and returns timestamped video frames to the
existing Runtime media-output boundary.  This preparation folder is only a
research input pack.
