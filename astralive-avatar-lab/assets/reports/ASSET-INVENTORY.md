# Realistic Avatar PoC asset inventory

Status date: 2026-10-08.  Every media record below was obtained from the named
official repository at the pinned commit, is kept `RESEARCH_ONLY`, and is
excluded from public Git by `experiments/real-avatar/.gitignore`.

## Verification method

Each media file was inspected with `ffprobe`; video dimensions, frame rate,
pixel format and container duration are from that output.  A separate
`ffmpeg -v error -xerror -i INPUT -f null -` decode pass was also executed
for every prepared MP4/WAV and returned zero errors.  SHA-256 values are for
the local prepared copy.

## MuseTalk 1.5 inputs

Upstream: https://github.com/TMElyralab/MuseTalk/tree/0a89dec45a0192b824e3cf4daf96c239440c5ed8
(commit `0a89dec45a0192b824e3cf4daf96c239440c5ed8`, 2025-09-26).  The upstream
`configs/inference/test.yaml` and `realtime.yaml` explicitly reference
`data/video/yongen.mp4` and `data/audio/yongen.wav`.

| File | Source URL | Format and verified media properties | Size / SHA-256 | License / status |
| --- | --- | --- | --- | --- |
| `musetalk/original/original_video.mp4` | https://github.com/TMElyralab/MuseTalk/blob/0a89dec45a0192b824e3cf4daf96c239440c5ed8/data/video/yongen.mp4 | H.264, 704x1216, 25 FPS, yuv420p, 10.720 s; no audio stream | 1,870,923 B; `1effa976d410571cd185554779d6d43a6ba636e0e3401385db1d607daa46441f` | Repository MIT; demo-media rights are not separately stated. RESEARCH_ONLY, present and decodable. |
| `musetalk/original/official_yongen.wav` | https://github.com/TMElyralab/MuseTalk/blob/0a89dec45a0192b824e3cf4daf96c239440c5ed8/data/audio/yongen.wav | PCM s16le, 48,000 Hz, stereo, 8.000 s | 1,536,078 B; `2b775c363c968428d1d6df4456495e4c11f00e3204d3082e51caff415ec0e2ba` | Repository MIT; demo-media rights are not separately stated. RESEARCH_ONLY, present and decodable. |
| `musetalk/normalized/original_video_25fps.mp4` | Derived only from the official video above | H.264, 704x1216, 25 FPS, yuv420p, 10.720 s | 1,074,955 B; `9cd29e81ee046d23d426ba21e9a2ee5c0b7839d3444851f3e480d002a10ed8fe` | Derived RESEARCH_ONLY; PASS. |
| `musetalk/normalized/test_10s.mp4` | First segment of normalized official video | H.264, 704x1216, 25 FPS, yuv420p, 10.080 s | 1,033,303 B; `794e19020409342cc27060505c3b9c5753b9dd6ab2271063d134ffeae265d4e6` | Derived RESEARCH_ONLY; PASS. |
| `musetalk/normalized/test_30s.mp4` | Loop of normalized official video | H.264, 704x1216, 25 FPS, yuv420p, 30.000 s | 2,652,840 B; `2443c94379d4fe2b073f0ffd11a90c4dd876186ce710cfedd76507a91f7fd447` | Derived RESEARCH_ONLY; PASS, but repeats the 10.720-second source 2.8 times. It is not 30 seconds of unique footage. |

Preview: `previews/musetalk_original_25fps_contact_sheet.jpg` (SHA-256
`74c97d1f0a0ce459c6095271f93cc373dfc9e87432d56ffcbda2206e013ab95e`), a
visually inspected 10-frame contact sheet from the normalized MuseTalk video.

## SoulX-FlashHead Lite inputs

Upstream: https://github.com/Soul-AILab/SoulX-FlashHead/tree/9bc03de06bb0de82cd6bc477804512ae06144bf2
(commit `9bc03de06bb0de82cd6bc477804512ae06144bf2`, 2026-05-28).  The current
`inference_script_single_gpu_lite.sh` calls `generate_video.py` with
`--model_type lite --cond_image examples/girl.png --audio_path
examples/podcast_sichuan_16k.wav --audio_encode_mode stream`; these are input
assets, not generated-result showcases.

| File | Source URL | Format and verified properties | Size / SHA-256 | License / status |
| --- | --- | --- | --- | --- |
| `soulx/original/official_girl.png` | https://github.com/Soul-AILab/SoulX-FlashHead/blob/9bc03de06bb0de82cd6bc477804512ae06144bf2/examples/girl.png | PNG, 512x512, rgb24 | 357,474 B; `384abd202f7dae45fdbbab3b6a7777cd7c8a64625fb19217a45d056f2162c624` | Repository Apache-2.0; individual portrait/publicity rights are not separately stated. RESEARCH_ONLY, present. |
| `soulx/original/official_podcast_sichuan_16k.wav` | https://github.com/Soul-AILab/SoulX-FlashHead/blob/9bc03de06bb0de82cd6bc477804512ae06144bf2/examples/podcast_sichuan_16k.wav | PCM s16le, 16,000 Hz, mono, 65.920 s | 2,109,484 B; `2eab639d2104b84292945a0ca902b12794163480b7f1bbefc56bc5400f6172f9` | Repository Apache-2.0; individual media rights are not separately stated. RESEARCH_ONLY, present and decodable. |
| `soulx/normalized/official_girl.png` | Byte-copy of official condition image | PNG, 512x512, rgb24 | Same content as above | RESEARCH_ONLY; Lite-compatible baseline input. |

No SoulX 1.3B or wav2vec2 weights were downloaded.  No third-party portrait
was downloaded.

## AstraLive Chinese audio pack

Generated with the existing CPU-only `SherpaOnnxTTSProvider` and existing
`runtime/.local/vits-piper-zh_CN-xiao_ya-medium` model; the isolated script is
`scripts/generate_chinese_audio.py`.  It starts no service and writes only to
this experiment directory.  Originals are PCM s16le / 22,050 Hz / mono;
`audio/soulx/*_16k_mono.wav` are separate PCM s16le / 16,000 Hz / mono
conversions for the SoulX interface and do not overwrite originals.

| File | Actual duration | SHA-256 | Transcript/status |
| --- | ---: | --- | --- |
| `audio/short_10s.wav` | 6.836 s | `734a9a59307ff8e90fafe2ebe7235da63dea0d6dde8bbb058750ebe02f1a44b8` | “大家好，欢迎来到 AstraLive 直播间。今天我们一起测试真人数字人的实时互动效果。” |
| `audio/medium_30s.wav` | 11.526 s | `af9646198f7a4466d70cbdbd6142d89a1265840e5d4047e4166c917c8326c71b` | “刚才有朋友问，这款卫衣有没有 XL 尺码。这里需要说明，商品支持 XL 尺码，不代表 XL 一定还有库存，具体库存仍然需要实时查询。” |
| `audio/long_60s.wav` | 72.052 s | `920ac60d981d403043c3e10bb4d03b8aca8f1b1886eb52570ac85186b3305db9` | Natural livestream explanation; full transcript in `audio/transcripts.json`. |
| `audio/silence_10s.wav` | 10.000 s | `f24029e05d10c95e43a210695d1539d21b2c07e7df6269ba099ac7f400559874` | 10 seconds of digital silence. |

The filenames preserve requested test labels; actual durations above are the
measured truth.  This Chinese VITS lexicon logged OOV warnings for Latin
tokens such as `AstraLive`, `XL`, `SKU`, `AI`, `FAQ`, `RTX`, and `WebRTC`; it
therefore is suitable for the Chinese-media plumbing test but **not** a pass
for natural English-abbreviation pronunciation.  GPU quality review must
listen for that omission and use a voice that supports the required terms if
pronunciation is in scope.

Total prepared material is approximately 17 MiB, below the 1 GiB preference.

### Audio conversion map

| File | Actual duration / format | SHA-256 | Transcript |
| --- | --- | --- | --- |
| `audio/musetalk/short_10s_source.wav` | 6.836 s; PCM s16le, 22,050 Hz, mono | `734a9a59307ff8e90fafe2ebe7235da63dea0d6dde8bbb058750ebe02f1a44b8` | Same as `short_10s.wav`; byte-copy for MuseTalk input mapping. |
| `audio/soulx/short_10s_16k_mono.wav` | 6.836 s; PCM s16le, 16,000 Hz, mono | `a6e327e14f46d094191916c34e169dffda4ff3d33b5f1f12126a152dd26a2d2d` | Same as `short_10s.wav`; separate SoulX conversion. |
| `audio/soulx/medium_30s_16k_mono.wav` | 11.526 s; PCM s16le, 16,000 Hz, mono | `c03fbb727ed9bbe2da7100c28e49438adcc83ae91bdb20f74cec7238ca757cad` | Same as `medium_30s.wav`; separate SoulX conversion. |
| `audio/soulx/long_60s_16k_mono.wav` | 72.052 s; PCM s16le, 16,000 Hz, mono | `3f364aae9cc9682e4393daf7ec5b0202e57a7e013a3a6d12283ef845c2c7d571` | Same full transcript in `audio/transcripts.json`; separate SoulX conversion. |
| `audio/soulx/silence_10s_16k_mono.wav` | 10.000 s; PCM s16le, 16,000 Hz, mono | `309a60b2b5f4b1abe835c871079657c09f7325bd10b005a9403ad2949bfa7157` | Same digital-silence transcript; separate SoulX conversion. |

The official MuseTalk and SoulX sample audios retain no supplied transcript
in their repositories; this inventory does not invent one.
