# Captured staging bridge language policy

Candidate production source: `8971085bb7d117c4a96ce571184ef27b4f0fa92b` (includes diagnostic source `ff4041e9fbac974b45ffc8315f8021d677c441cd`). F approved this private request scope; A independently reviewed this exact source and reported no blocking contract issue. No frozen contract, public DTO, command, receipt, cursor, feature default, Provider profile/version, model, maxTokens=256, or 8-second bridge timeout changes.

## Actual failure

F's continuous real hour5 failed after 33 narration completions and one real price answer. The bridge Provider returned HTTP 200 after 3549 ms with finishReason `length`, completionTokens=reasoningTokens=256, contentDeltaCount=0, responseChars=0, and promptTokens=45763. This is a confirmed Provider non-stop failure, not an 8-second timeout, and the original parser correctly refused it. Original failed evidence remains under `/private/tmp/astralive-f-real-hour-tcp-5`; it is not converted into a success by this change. No new real Provider, GPU, Chrome, RTMP or hour acceptance was run by C.

## Private request scope

Only the actual captured `staging.enabled` factory constructs `BoundDeepSeek(staging_bridge_enabled=True)`. `stream_bridge_choice` uses the private `thinking: {type: disabled}` addition. Ordinary `stream`, including a forged bridge-looking system prompt, and flags-off bridge requests preserve their old body. No environment is re-read for this decision. The current official [DeepSeek request reference](https://api-docs.deepseek.com/api/create-chat-completion/) and [thinking mode guide](https://api-docs.deepseek.com/guides/thinking_mode/) document this request setting; F verified these primary sources before approving the scope.

The private language projection selects exactly the captured `nextBeatId` from `context.goal`, retaining its title, requiredFactIds, beatId, productId and factVersion. Missing/duplicate/mismatched targets are refused before Provider calls. The projection drops other Beat metadata and segment IDs, retains all other context fields and all pending/completed fact IDs, and leaves the original command and request fingerprint untouched. It grants no cursor or fact-completion authority to the LLM. An empty nextBeatId creates no invented next Beat.

Safe reconstruction of hour5 metadata measured 97,742 original context bytes versus 3,068 projected bytes, excluding fresh Tool Facts. It preserves 33 completed and 107 pending fact IDs. This is a reconstruction measurement, not a claimed new real HTTP request. Test-only observer evidence hashes the actual projected request and adds its private request policy revision, bytes and thinking setting, never prompt/key/reasoning contents.

Only the staging parser now refuses oversized, invalid or out-of-range bridge choices instead of selecting empty bridge by default. HTTP/provider length/missing-terminal errors remain errors. Legacy parser behavior remains unchanged. Preparation failure diagnostics record static allowlisted class/code, initial guard/tool refresh/bridge LLM/final guard/journal record stages and timings; no private payload or raw exception text is logged. UNKNOWN and publication fencing remain authoritative.

## Verification and rollback

46 focused CPU tests passed on candidate source (3.459 seconds), including paired captured/flags-off/ordinary bodies, immutable fingerprint, projection validation, HTTP400, finish-length, missing-terminal, invalid choices, safe failure stages and production bound factory capture. Synthetic HTTP streams and test doubles are labelled CPU tests and do not prove real Provider acceptance. The exact immutable source full gate also passed: owned Go/PostgreSQL/race/authentication/outage suite exit0 (133.864 seconds), Runtime 306 tests with 12 skips exit0 (35.186 seconds), frontend 40 tests and build exit0. The archive gate resolves and pins the source before testing. Commands/results/log hashes are in [evidence](../../evidence/agent-c/bridge-language-policy/manifest.json). The initial preparation-only focused invocation failed because it omitted `runtime/tests` from PYTHONPATH; that failure is preserved, and the corrected invocation passed. No production behavior was altered to compensate for that test import failure.

Rollback uses the existing staging switch for a newly authorized Session. Already captured Sessions cannot switch profiles in place, and existing UNKNOWN commands are never rewritten or blindly replayed. No Stop-proof cache or GPU transport changes are included.
