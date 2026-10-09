# SoulX incremental PCM experiment

This directory is isolated from AstraLive v0.1. Upstream SoulX code/weights, base Torch, public contracts, Runtime and production services are untouched.

`adapter.py` accepts only received PCM; it has no WAV/audio-file API. `run_poc.py` reads a test WAV a chunk at a time and releases each chunk only after that chunk's capture-duration deadline. This is a controlled live source simulation, not real TTS integration. Inference occurs before source EOF. FFmpeg uses the source WAV separately to mux the review recording; that file is not accessible to the adapter.

Supported input: 16000 Hz, mono, s16le, contiguous sample-index/sequence metadata, monotonic generation IDs, partial or empty EOF, cancellation. Other formats are explicitly rejected; resampling belongs in a separately validated producer. PTS = first_sample_index / sample_rate + frame_sequence / 25, never arrival time.

Fixed model parameters: eight-second past-audio window, 33 generated frames / nine motion-history frames / 24 new frames, 15360 newly received samples (960 ms). Recompute only the bounded rolling feature window, retaining official normalization and attention semantics. No ever-growing WAV recomputation, feature-window reduction or model retraining. Exact append-only wav2vec2 embeddings are not claimed.

Media buffers: <=32000 queued PCM samples (2 s), <15360 partial samples, one bounded eight-second feature window, <=24 output frames (960 ms), nine committed pose frames. `events.jsonl` is finite experiment telemetry, not a production telemetry implementation. Backpressure waits are awakened by cancel/close; a worker failure is surfaced to the consumer. Source producer is blocked by credit rather than discarded silently.

`GPU_WORKER_READY` is emitted only after model/avatar preparation, three inference/feature warmup blocks AND the published-pose restoration path. The first experimental revision missed that alternate encode compilation path and incurred 15.18 s on generation 2; retain that failed evidence. A later revision declares a 120 ms consumer playout buffer to absorb 100 ms input quantization plus scheduling jitter. First-arrival and inference timestamps are unchanged.

On FORCE: invalidate publication under the consumer lock, clear queues, finish already submitted CUDA safely, reject its stale output; reset audio history and reconstruct pose from last nine consumed frames, not the cancelled output. Model and portrait latent cache remain resident. A remote worker must use `consume(commit=False)` and update committed pose only from acknowledged remote consumption.

GPU commands (existing validated environment only):

```sh
/root/autodl-tmp/astralive-avatar-lab/environments/astralive-soulx/bin/python /root/autodl-tmp/astralive-avatar-lab/streaming/test_adapter.py
POC_RUN=new-run /root/autodl-tmp/astralive-avatar-lab/environments/astralive-soulx/bin/python /root/autodl-tmp/astralive-avatar-lab/streaming/run_poc.py
```

`POC_RECHECK=1` runs the 100 ms 30/60 s regressions plus variable input, late audio, slow consumer, FORCE and idle/talking. Every re-run gets a separate directory; do not overwrite raw failed evidence. FFmpeg encoder input time is explicitly not first encoded-packet time. A local decoded MP4 does not prove remote first frame, browser playback, real-time A/V synchronization, worker-loss fallback or any live acceptance.
