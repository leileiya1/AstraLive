# ISSUE-009: Healthy School-Linux WebRTC peer evicted when video queue fills

Status: **CLOSED — REVALIDATED ON SCHOOL-LINUX**. Discovered on 2026-10-07 during the 90-second browser-connected smoke and closed after the final continuous School-Linux run.

Mac Chrome used the production frontend `useLivePreview()` configuration with `stun:stun.l.google.com:19302`. ICE and `connectionState` reached `connected`; the browser received audio and decoded video. During the first mixed business cycle, Runtime evicted the only Peer with reason `video_sender_stalled`, after which two utterances terminated as `UTTERANCE_FAILED` / `MEDIA_OUTPUT_FAILED` and Chrome became `disconnected/disconnected` at the 30-second sample.

The eviction diagnostic does not describe a dead consumer:

```text
peerId: peer_9f046a18e4a8464da81b5fe1061fbe61
connectionState: connected
iceConnectionState: completed
audio queue: 305 / 500
video queue: 125 / 125
audio enqueued / consumed: 455 / 150
video enqueued / consumed: 200 / 75
last audio recv: 2026-10-07T06:44:42.703500Z
last video recv: 2026-10-07T06:44:42.682874Z
eviction event: 2026-10-07T06:44:42.979Z
```

Both tracks had consumed frames less than 300 ms before eviction. The current `_VideoTrack.push()` is synchronous: when its 125-frame queue is full, it raises `MediaDeliveryError`; `WebRTCMediaOutput.push_video()` immediately evicts the Peer as `video_sender_stalled`. Real TTS and Avatar can produce media substantially faster than the 25 FPS playback clock, so queue fullness alone can evict an actively consuming healthy Peer.

This is distinct from the old ISSUE-008 drain timeout: the literal `WebRTC playback drain timed out` did not occur in this run. ISSUE-008 nevertheless remains `FIXED — WAITING FOR ONE-HOUR REVALIDATION` because the required revalidation could not start.

Evidence:

- [Browser result](../evidence/school-linux/browser-connected-soak-school-linux-smoke-2.json)
- [Runtime log](../evidence/school-linux/school-linux-runtime-failed-smoke.log)
- [Redis event snapshot](../evidence/school-linux/school-linux-failed-smoke-snapshot.log)
- [Tool/signaling proxy](../evidence/school-linux/school-linux-runtime-tool.jsonl)

Required next step belongs to the Runtime media owner: distinguish healthy playback backpressure from a non-consuming sender, retain bounded stalled-Peer eviction, add a regression with production-rate audio/video burst generation and an actively consuming 25 FPS Peer, then repeat the School-Linux five-minute preflight before any one-hour run. No production Runtime fix was attempted in this acceptance session.

## Resolution

Runtime now treats `TARGET_FPS` as the media playback clock (configurable 20/25/30, default 25), derives bounded queue capacities from time-based buffer settings, and asynchronously waits on healthy consumers. Queue fullness alone never triggers eviction: consumption progress and recent `recv()` activity are checked throughout bounded waits. A Peer is evicted only when the queue is full, consumption has stopped, and its receive timestamp is stale. Pushes are concurrent per Peer, generation-aware, interruptible, and Stop-bounded.

The final 3,671-second run held video to 10 frames / 400 ms and audio to 20 frames / 400 ms. It recorded 103,552 backpressure events and 2,749,816.9 ms cumulative wait, while video enqueued and consumed totals both reached 43,251. Peer stall events and evictions were both zero. Chrome remained connected through T+60 minutes and decoded 90,031 frames with zero dropped frames. See [final audit](../evidence/school-linux-final/audit.json).
