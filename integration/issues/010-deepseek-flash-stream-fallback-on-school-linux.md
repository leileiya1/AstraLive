# ISSUE-010: DeepSeek Flash stream falls back during School-Linux full-stack smoke

Status: **CLOSED**. Discovered and resolved on 2026-10-07; final one-hour revalidation completed on 2026-10-07 UTC / 2026-10-07–08 Asia/Taipei.

The isolated real-provider integration completed with the configured OpenAI-compatible DeepSeek endpoint and `deepseek-flash`. In the full deployed stack, however, each ordinary LLM-routed utterance emitted `RUNTIME_WARNING` with `code=LLM_FAILED`, `fallback=input_text`, and `errorType=RuntimeError`. Deterministic Product Tool answers were still routed independently and the WebRTC media failure in ISSUE-009 remains the immediate acceptance blocker.

The secret was supplied only through process environment and is absent from evidence. The exact provider response/stream terminator mismatch was not investigated further because the acceptance rules require stopping after the media gate failure. No model switch or Runtime production change was made.

Evidence: [Redis event snapshot](../evidence/school-linux/school-linux-failed-smoke-snapshot.log) and [Runtime log](../evidence/school-linux/school-linux-runtime-failed-smoke.log).

## Resolution

The OpenAI-compatible stream parser now requires a terminal `finish_reason=stop`, accepting either a following `[DONE]` marker or clean EOF. EOF without terminal stop, `length`, `content_filter`, error packets, non-2xx responses, malformed JSON, and connection resets remain failures. SSE comments, keepalive and event lines are ignored, and only `delta.content` is emitted; `reasoning_content` never reaches TTS. The deployed DeepSeek token limit was raised to 1024 because hidden reasoning tokens could legitimately exhaust the former 128/256 limits; strict `finish_reason=length` handling was retained.

All eight streaming semantic regressions passed, as did the real DeepSeek integration and full Real LLM → sentence stream → CPU TTS → Lightweight Avatar → aiortc chain. During the final hour, two isolated `ConnectTimeout` warnings were recorded as external upstream network failures at 13:14:35.955Z and 13:30:26.172Z. There were zero unexpected protocol failures, zero `UTTERANCE_FAILED`, and the stream continued normally. See [final audit](../evidence/school-linux-final/audit.json) and [Runtime events](../evidence/school-linux-final/runtime-events.json).
