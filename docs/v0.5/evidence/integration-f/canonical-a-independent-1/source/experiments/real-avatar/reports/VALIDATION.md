# Asset validation evidence

Validation host: `school-linux` (`/home/sapiece/AstraLive`), 2026-10-08.
No model inference was invoked.

## Commands executed

```text
ffprobe -v error -show_entries format=duration,size:stream=... -of json FILE
ffmpeg -v error -xerror -i FILE -f null -
runtime/.venv/bin/python -m json.tool experiments/real-avatar/manifest.json
```

## Results

- `ffprobe` returned video FPS/resolution/pixel-format/duration and audio
  sample-rate/channel/duration metadata for every recorded source and derived
  asset in `ASSET-INVENTORY.md`.
- `ffmpeg` decode returned `DECODE_PASS` for four MuseTalk MP4 files and ten
  WAV files (the original/generated Chinese pack plus SoulX conversions and
  official sample audios).  The official SoulX PNG and the contact-sheet JPEG
  were ffprobe-readable; the contact sheet is MJPEG 1224x840/yuvj420p and was
  visually checked as a complete 10-frame sheet.
- `manifest.json` parsed successfully using the Runtime Python 3.12.15.
- Total directory size after generation: 19 MiB (`du -sh`), below the 1 GiB
  preference.  No large weights or training data are present.
