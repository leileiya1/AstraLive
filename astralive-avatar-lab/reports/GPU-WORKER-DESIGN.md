# AstraLive GPU Avatar Worker — proposed experimental interface

Status: DESIGN ONLY. SoulX Lite is selected; production queue sizes and latency budgets still require real incremental-audio/network measurements. No frozen production API, Runtime, WebRTC or RTMP changes are authorized by this document.

Preferred first implementation: SoulX-FlashHead Lite, selected by the user after the actual same-source B-short video review and acceptance of the 60-second clip and 600-second final segment. Its 600-second GPU test passed. Actual network/incremental-audio integration gates remain outstanding. Keep MuseTalk as a measured reference, not a concurrent production dependency.

## Ownership

school-linux owns business sessions, LLM/TTS, generation priority, interruption, audio playback clock, final media fanout and fallback. GPU Worker owns one resident model, cached portrait preprocessing, inference and generation-scoped video production. Worker never starts, stops or controls an AstraLive business session. WebRTC and RTMP remain behind the existing Media Fanout.

## Proposed private protocol (not a frozen-contract addition)

Use an authenticated private TLS stream, preferably bidirectional gRPC with protobuf binary fields. Do not expose an unauthenticated GPU service publicly. One worker handles one assigned room until capacity measurements establish safe multiplexing.

Messages:

- PrepareAvatar: request_id, avatar_id, input_asset_sha256, model_revision, preprocessing_options_hash. Response: cache_id and readiness. Cache identity includes model weights, image/video, face ROI parameters and preprocessing version. A changed key requires a fresh cache.
- BeginGeneration: worker_epoch, generation_id, cache_id, audio_format (PCM signed 16-bit, sample_rate, channels), first_audio_sample_index, timeline_start_pts_us, output_fps, expected_duration_if_known. An epoch identifies each worker process incarnation; IDs cannot be reused within an epoch.
- AudioChunk: generation_id, chunk_sequence, first_sample_index, sample_count, pcm_bytes, final_chunk. Audio sequence is contiguous; timestamps derive from sample index, not network arrival time. This requires a streaming adapter; upstream offline whole-file audio processing alone does not prove support.
- VideoPacket: worker_epoch, generation_id, frame_sequence, pts_us, duration_us, width, height, pixel_format_or_codec, keyframe_flag, payload. school-linux validates epoch and generation again at dequeue and immediately before fanout.
- CancelGeneration: generation_id, reason=FORCE or session-stop. Invalidate publication immediately. Cancel at the next supported inference boundary; return last_completed_sequence. A GPU kernel already running need not be preempted, but its obsolete result must be discarded.
- Credit: generation_id, max_pending_frames, latest_consumed_sequence. Generation-specific credits implement bounded backpressure. Do not increase queues to conceal a slow consumer. A paused playback clock and lost worker consumption require different diagnostics.
- Health: worker_epoch, model_revision, cache_id, ready, last_completed_frame, queue_depth, GPU allocated/reserved bytes, last_error. Separate process liveness from actual generation progress.

This is a proposal requiring contract review before implementation. Field names above do not modify existing AstraLive public schemas.

## Timing, interruption and transport

All timeline PTS originate in Runtime audio sample positions. Wall clocks are for telemetry only. Runtime schedules video against its audio playback clock and records drift; it must avoid letting avatar generation delay existing audio indefinitely. Model lookahead/chunk size and first-frame delay must be measured and declared. Idle video uses the same avatar/timeline; transition continuity and return-to-idle need separate validation.

Use a bounded inbound audio queue and bounded outbound frame queue. Derive capacities from measured chunk burst size and an explicit latency budget; do not copy arbitrary constants into production. On FORCE, atomically invalidate the old generation, clear matching queued audio/video and any decode reorder state, then begin the new generation with an explicit PTS. Backpressure waits use consumption/progress signals, generation changes and cancellation.

Raw RGB bandwidth = width × height × 3 × fps × 8 bits/s, excluding framing. Actual MuseTalk Sun output 576×768×25 is about 265.42 Mbit/s; SoulX 512×512×25 is about 157.29 Mbit/s. Measure the rented network before choosing raw frame transport. Prefer GPU-side low-latency H.264 with short GOP, no B-frames, generation-specific decoder restart/keyframe, or an approved frame-compression format. Encoded output FPS is not neural inference FPS. Account for encoder, network, decoder latency and GPU compute contention explicitly; no bandwidth/bitrate guarantee is claimed.

Measured resident-file generation gives MuseTalk first composited frame 120–160ms and SoulX first 24-frame CPU-available chunk ~300–327ms. These are not TTS-first-chunk or first remotely displayed-frame latencies. SoulX's official streaming encoder processes 24 frames per slice, requiring approximately 0.96s of live audio at 25 FPS before that slice can run. MuseTalk's whole-file Whisper path needs a separately validated incremental-audio adapter. Current lab MP4 encoding uses file-oriented x264 settings with default B-frame buffering; low-latency encoding, hardware NVENC, network and decode must be benchmarked independently.

For SoulX interruption, clear stale audio context immediately and decide explicitly whether to preserve the last published pose latent or reset to the source image; either policy can cause a visual discontinuity and needs acceptance. Do not retain unpublished old-generation pose state accidentally. Chunk cancellation is bounded by an inference boundary, not GPU-kernel preemption. MuseTalk idle/talking file tests reset source indices and do not prove seamless live state transitions.

## Recovery and acceptance

Worker loss causes Runtime to invalidate the epoch and switch locally to Lightweight Avatar while preserving session audio/business flow. A supervisor may restart the same worker with capped retries and jitter; no automatic purchase or instance expansion. Reload model once, verify CUDA/model health, restore cache and advertise readiness before new generation assignment. Do not replay stale generation work after a restart. Resource telemetry and logs exclude credentials, source URLs with signed tokens and production stream keys.

Integration gates after model selection: real chunked PCM; first-frame delay; timestamp drift; 25 FPS paced output under bounded backpressure; FORCE during inference/encoding/network stall; old-frame rejection after cancel and restart; idle/talking continuity; packet loss/worker loss with uninterrupted Lightweight fallback; one-hour real WebRTC/RTMP acceptance with normal Stop and resource cleanup. Lab offline videos and a GPU soak alone do not satisfy these gates.
