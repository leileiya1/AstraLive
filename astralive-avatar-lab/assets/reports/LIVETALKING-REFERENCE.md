# LiveTalking reference notes — read-only analysis

Reference: https://github.com/lipku/LiveTalking at
`b3e7490a20e7a6330492f8a6ea8200a5d50279d1` (Apache-2.0).  No LiveTalking
service, dependency environment, model, or avatar-preparation job was run.

## Observed patterns

- `avatars/musetalk/genavatar.py` builds an avatar cache from a video or
  images: extracted full frames, face/bounding-box metadata, masks, and latent
  tensors.  `musetalk_avatar.py` loads that cache, warms the Whisper ASR
  feature extractor, applies a cyclic/mirrored frame index, infers a batch,
  and blends the predicted mouth region back into the original frame.
- `base_avatar.py` treats all-silence audio batches as an idle fast path: it
  returns original frames rather than running the neural inference path.
  It also supports custom image/audio cycles for action/idle state.
- The `/human` route calls `flush_talk()` before enqueuing new text when an
  interrupt flag is set.  `flush_talk()` flushes both TTS and ASR queues and
  resets custom audio state.  `/interrupt_talk` uses the same operation.
- The render loop runs TTS, feature extraction/inference, and output frame
  processing as separate workers, throttling when the output buffer grows.
  Its README distinguishes `inferfps` (GPU inference) and `finalfps` (final
  push/output) and states both must meet the real-time target.

## Suitable for AstraLive Avatar Worker

1. Precompute/cache avatar-dependent data once per avatar version.  Treat
   preparation result as immutable and key it by source hash + model version
   + crop/bbox settings; do not redo face work per utterance.
2. Maintain an audio-clocked frame scheduler at the Runtime's 25 FPS target.
   Report separately: Avatar Worker inference FPS, output FPS, queue depth,
   and end-to-end first-frame latency.
3. On silence, emit a stable idle frame/cycle without GPU mouth inference.
   A speaking-to-idle and idle-to-speaking transition should preserve PTS and
   have explicit visual stability checks.
4. Carry AstraLive's generation ID through input PCM, feature queues,
   inference output, and media output.  On interrupt, cancel/drain only the
   superseded generation and reject late frames before the existing WebRTC / 
   RTMP fanout.  Bounded generation-aware cleanup is required; never clear a
   shared queue blindly.
5. Warm models explicitly before measurement, then capture cold and warm
   first-frame latency separately.  Track `infer_fps` and `output_fps` as
   different counters, matching the useful distinction in LiveTalking.

## Not adopted

LiveTalking owns its own HTTP routes, WebRTC/RTMP outputs, TTS/ASR queues, and
session lifecycle.  AstraLive already owns these concerns, including dynamic
backpressure, interruption semantics and RTMP fanout.  Do not run it as a
second streaming service or replace AstraLive's transport/control plane.
