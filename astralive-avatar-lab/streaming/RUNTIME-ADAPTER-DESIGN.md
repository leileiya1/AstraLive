# Independent internal design: PCM prefetch and frame alignment

Stage A and Stage B are GPU/local/private-link evidence. They do not prove commercial Runtime integration. Formal v0.1 files, frozen public schemas and existing WebRTC/RTMP sink clocks remain untouched. First validate this design in an isolated Runtime copy.

## Concrete incompatibility

The current RuntimeSession consumes one TTS chunk, awaits AvatarEngine.push_audio(chunk), pushes audio, then pushes returned video frames. With 20 ms chunks and a 960 ms SoulX horizon, awaiting the first video from the first chunk prevents the remaining 47 chunks from arriving. Returning immediately and playing audio instead creates approximately the model buffering/inference/transport delay of A/V skew. A 960 ms audio batch also cannot simply be pushed before its 24 frames: bounded audio sink delivery can consume a substantial part of that audio while the video loop has not started.

## Proposed optional internal hook

`AvatarEngine.stream_audio(source: AsyncIterator[AudioChunk], generation_id) -> AsyncIterator[AudioChunk]` is an internal experiment hook, never a public contract field.

- The existing fact-safe LLM sentence/TTS source runs in a separate bounded producer. It can obtain the next sentence while the current partial model block waits for more audio. One worker job covers one whole utterance, rather than adding a 960 ms pause at each sentence.
- A persistent, stateful resampler converts actual native TTS audio to 16000 Hz mono s16le. Split into 20 ms media chunks; derive all worker sample metadata from the resulting sample count. Never resample an ever-growing WAV. EOF flushes the resampler and records any explicitly added <=40 ms final silence needed for frame-grid alignment.
- Prefetch forwards PCM to the private Worker and retains at most two seconds in the local audio queue. First audio release waits for first correctly fenced decoded video plus the declared playout buffer. The original sink clocks are not changed.
- The normal Session rendering loop still pushes a 20 ms audio chunk and its corresponding zero/one 25 FPS frames. `push_audio` matches already-prefetched frames, not the source supplier itself. The producer continues independently under bounded audio and video credits.
- A sink wrapper issues remote video Credit only when the existing sink actually consumes the frame; enqueue is not consumption. For a WebRTC MVP use one peer and progress/generation-aware consumption targets. A paused/nonexistent peer must not be diagnosed as GPU inference failure solely because its queue is full.
- At whole-utterance Audio EOF, flush the model's final partial window, publish only valid frames, then wait for fenced completion and the existing sink drain. Short utterances and two sentences must be separate regression tests.
- On FORCE cancel producer/source/resampler/remote job, clear decoded frame queues, invalidate epoch/job mapping, and preserve only acknowledged pose. The business generation remains controlled by Runtime. Internal worker job IDs are monotonically increasing and map to the Runtime generation; multiple utterances may share one business generation.
- GPU loss switches the *remaining* PCM to existing Lightweight Avatar. Session/LLM/TTS/audio sink continue; remote work is not replayed automatically on recovery. Record GPU, cached-idle and repeated-frame sources separately.

## Gates before any long browser run

CPU orchestration tests: no first-chunk deadlock, bounded producer faster than consumer, <960 ms EOF, multi-sentence partial windows, resampler count/continuity, FORCE while waiting on credits/first frame, failure before/after first frame, stale epoch/job rejection and actual sink consumption acknowledgments.

Then isolated real COMMENT -> LLM -> TTS -> private Worker -> existing WebRTC sink -> Browser short checks, measured A/V sync, idle transitions, FORCE, worker loss and cleanup. Only then dual-sink short tests and one continuous one-hour Session. No one-hour test while any preceding gate is failing. All reports must state whether first display is actually a browser requestVideoFrameCallback/recording observation; a paced Python consumer tick is not browser display.
