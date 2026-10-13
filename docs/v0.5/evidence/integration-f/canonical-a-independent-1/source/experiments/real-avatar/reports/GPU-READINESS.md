# GPU readiness decision

## Decision: READY TO RENT GPU

The primary MuseTalk gate is satisfied by a real official input pair from the
pinned upstream repository: the H.264/yuv420p 25 FPS `yongen` video and its
PCM `yongen` audio both exist in this isolated pack and were ffprobe-checked.
The required 10-second and explicitly disclosed looped 30-second video tests,
Chinese PCM test pack, 25 FPS normalization, source/commit/license notes,
hashes, and MuseTalk contact sheet are present.

SoulX Lite has its actual official input shape prepared as well: the official
condition image, official 16 kHz audio baseline, and separate 16 kHz Chinese
conversions.  Weights are intentionally absent and are a GPU-stage download,
not a preparation defect.

Constraints retained for the GPU stage:

- Per-asset demo-media/publicity rights are not separately stated by either
  repository.  Keep every supplied portrait/video/audio `RESEARCH_ONLY`; do
  not publish, distribute, or represent it as AstraLive talent.
- Existing Chinese VITS skipped Latin tokens in the logged synthesis pass.
  Quality scoring may use the pack for plumbing, but an abbreviation-pronunciation
  test needs a suitable voice before it can pass.
- `test_30s.mp4` is a 30-second loop of 10.720 seconds of official footage;
  it supports scheduling/stability checks only, not unique long-motion claims.
- All quality, latency, VRAM and stability metrics remain NOT BENCHMARKED.

No model weights, training data, training jobs, GPU rental, production Runtime
edits, frozen-contract edits, systemd edits, or RTMP configuration changes
were made during this preparation.
