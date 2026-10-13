# Streaming Backpressure v0.4

## Reproduced accumulation

Before edits, regressions showed10000 produced sentence tokens while a consumer paused,1000 native PCM callbacks enqueued without waiting, and a single700-character token sent to TTS. Those tests failed on the baseline and pass with the bounded bridge. Separate Bound media trace regression was also written before adding instrumentation.

## Implementation

`sentence_stream`: asyncio queue8 slots, token slices≤64 characters, async put backpressures the LLM reader. Buffer normally flushes at Chinese sentence marks/clauses or a safe boundary near120 chars. It preserves streamed decimals, latin size labels and numeric units; pathologically indivisible content fails explicitly at240 chars. Timeout no longer flushes arbitrary incomplete phrases. Producer cancellation does not enqueue a sentinel into a full cancelled queue, and is awaited on close. An individual upstream token/SSE line is still initially allocated by httpx; provider maxTokens and trusted response limits remain relevant.

`SherpaOnnxTTSProvider`: eight PCM slots, each≤40ms native-rate mono PCM (≤320ms buffered). A native callback uses run_coroutine_threadsafe(queue.put), waits only in the native thread in50ms cancellation-aware increments, and has at most one pending put. Cancellation sets a threading.Event and cancels a blocked pending put; callback returns0. Error and EOF traverse the same bounded queue. Event loop never blocks on future.result. Native worker is joined through asyncio.shield after cancellation, retaining orderly cleanup. Fake slow consumer/close/error tests validate this interaction.

Sherpa engine's own native generate may allocate internal output and cannot be force-killed safely by Python. Sentence bounds limit routine input; a native computation that never reaches callbacks remains a provider-level cancellation limitation. No claim of a hard total native RSS limit is made.

No SoulX window, Avatar/Media output order, PCM sample timeline, Video PTS, Worker binary TCP protocol, Generation Fence, FORCE or consumption credit algorithm changes. Bound media adds content-free TALKING/generation-filtered trace observation only. Existing nine Bound media tests, fanout, RTMP and WebRTC backpressure/drain regression tests cover the preserved paths. Real GPU/browser/audio quality comparison is NOT TESTED; sentence-boundary tuning requires later Chinese listening acceptance.

## Actual provider follow-up (2026-10-10)

[Real follow-up](AGENT-B-REAL-ACCEPTANCE.md) exercises the existing bounded path with actual DeepSeek/XiaoYa/SoulX and native Chrome/RTMP, plus one real FORCE/cancellation and Worker degradation/recovery. No buffering/media algorithm changed. Twenty normal correlated samples have zero native Chrome video drops and no stalled/evicted peers; measured peak queues remain20 audio/10 video frames. Seven queued old frames are deliberately discarded in the FORCE trial.

Actual XiaoYa skipped Latin size words. `spoken_sizes` converts only explicit size/list/size-stock labels to Chinese letter pronunciation before native generation; facts and units remain unchanged. CPU tests protect units/identifiers; the follow-up uses the patched real TTS. Human pronunciation/lip-sync listening remains NOT TESTED. Native engine memory and pathological non-callback hangs remain the limitations described above.
