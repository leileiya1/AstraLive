# One-hour Golden progress — 2026-10-14

**FAIL / IN PROGRESS. No continuous one-hour run has completed.** Distinct
failed attempts are retained; their durations are never added together.
This increment is on `exp/v0.5-soulx-staging-golden`; no main merge or default
enablement is authorized by this evidence.

## Harness and material

F acceptance commits `7535f46`, `1d8ca95`, `aac8cfd` add an explicit 3600-second
soak, one Session/Chrome peer, checkpoints at 90/300/900/1800/2700/3600 seconds,
25 seeded, spaced comment replays, and fresh CPU duration validation. Original
30-minute behavior remains. The hour-3 fixture preserves 140 required facts and
adds 800 fact-free scripted exercises in 174 beats. It is demonstration/stress
material, not 940 unique facts or a claim of marketing naturalness.

The final fresh native XiaoYa preflight passed all 940 statements, totaling
5823.52 padded seconds, maximum 7.56 seconds. Earlier two preflights failed the
unchanged 8-second cap and remain in evidence. Shortening fixture wording did
not change voice speed, staging budgets or frozen contracts. The full local
module gate passed at `1d8ca95`; `aac8cfd` changes fixture data only.

## Actual runs

| Run | Source | Result | Actual boundary |
| --- | --- | --- | --- |
| TCP hour-1 | `aac8cfdd92e92472d8426e32c03dd9363e2b2527` | FAIL | DeepSeek profile probe 502; no Session |
| TCP hour-2 | same | FAIL | Worker unavailable after SSH forward exited; no Session |
| TCP hour-3 | same | FAIL | Narration recovery projection after eight completed segments; ninth command STARTED with no media generation; no comment reached |
| TCP hour-4 | `c12533eb8bbc74ea300e23fc4e2bbdc441857b8d` | FAIL | One completed segment; next synchronous begin failed with ValueError/OTHER; original projection already STOPPING/SESSION_STOP; no comment reached |

Hour-3 test duration was 128.59 seconds including preflight/cleanup. The actual
Session lasted about 92 seconds. Eight completed source intervals cover 38.84
seconds of speech. These numbers do not constitute continuous speaking for
128 seconds. Worker remained Ready in the same process/epoch; generatedFrames
was 1104. The original narration failure projection was not preserved before
Stop changed it; root cause is not yet confirmed. F `4fb94ca` preserves this
projection for the next attempt without weakening failure or cleanup rules.

Stop released the provider binding, but Session/run remained STOPPING and the
20-second read-only cleanup guard did not observe full terminal state. The
ninth attempt's CANCELLED projection coincides with Stop sealing and does not
alone establish the preceding failure cause. UNKNOWN media is not replayed.

Actual RTX 3080 10 GiB / cached SoulX Lite, macOS Go test-process production
HTTP components, separate production Python Runtime, PostgreSQL 17, native
Chrome 155, real DeepSeek/XiaoYa, and local FFmpeg RTMP were used. Go→Runtime
used TCP; Runtime→Worker used authenticated SSH-forwarded TCP. Redis URL was
unreachable in PostgreSQL-only mode. This is not production server restart,
Redis kill/recovery, remote audience, Windows, UDS or QUIC acceptance.

Chrome VP8/Opus packets span about 83.65 seconds; RTMP H264/AAC spans 91.10
seconds. Neither recording had packet PTS/DTS regressions. This is a container
clock check, not correlated A/V drift, audience audibility, naturalness or SLA
proof. The Chrome recorder retained chunks but final browser diagnostics were
unavailable after the failure; keep this limitation.

[Bounded evidence manifest](evidence/integration-f/hour-preflight-and-failures-1/manifest.json)
contains original gate/projection/log/preflight/monitor results and hashes.
[Actual Chrome frame](evidence/integration-f/hour-preflight-and-failures-1/run-3/preview.png).
Large original recordings remain at `/private/tmp/astralive-f-real-hour-tcp-3/media/observer/chrome.webm`
and `/private/tmp/astralive-f-real-hour-tcp-3/media/rtmp.flv` on the test host.

Next: owner-scoped safe admission diagnostics, confirm the first failure,
repair only the reproduced cause, rerun regression gates, then start a fresh
single-session hour. Full continuity, busy-comment latency, complete fact
coverage and naturalness remain **FAIL / NOT TESTED**, not upgraded by local
unit success or these short clips.

Hour-4 diagnostic source `0d1c045` was normally merged as `c12533e`; full
postmerge software gates passed. Actual hour-4 test took 50.38 seconds,
narration observation 10.025 seconds. The prior task was done; run was not
sealed, barrier was not pending, deadline had not expired, grant remaining was
9594 ms at the admission diagnostic. This excludes an active prior task and
expired grant at that observation, but does not identify the underlying
ValueError or Worker link failure. No UNKNOWN receipt is inferred from it.
[Hour-4 original evidence and postmerge gate](evidence/integration-f/hour-admission-diagnostic-failure-1/manifest.json).

An independent B local TCP protocol reproduction shows cancellation can orphan
an in-flight renewal ACK. Production Worker FIFO ordering was not captured in
hour-4, so this software proof is not labeled its confirmed physical root
cause. C is repairing the demonstrated renewal/release race and expanding
safe diagnostics; Stop aftermath proof remains a separate issue.

## Subsequent source and actual first bridge failure

F merged C renewal drain `8b335e8` as `b816ac0`; independent B protocol review
and full F postmerge software gates passed. Actual hour-5 reached 90/300-second
checkpoints, 33 completed narration segments and one completed price answer,
then failed at 342.077 seconds with `PREPARATION_UNKNOWN`. It remains FAIL.
The real bridge call returned HTTP 200 in 3549 ms, `finishReason=length`, all
256 completion tokens used for reasoning, zero content, and 45,763 prompt
tokens. This was not an 8-second timeout. Cleanup still lacked terminal proof.

C private bridge policy `8971085` normally merged as `a1583df` limits only
captured-staging bridge requests to a next-Beat language projection and
`thinking.type=disabled`. The command/payload/fingerprint, semantic cursor,
provider binding/profile, ordinary/default-off stream, 256-token and 8-second
limits remain unchanged. A fixed-source contract review ACK confirms this
private implementation needs no frozen-interface revision. Provider failures
and invalid/overlong staging choices remain errors rather than empty bridges.
The parameter is supported by the [official DeepSeek API reference](https://api-docs.deepseek.com/api/create-chat-completion/).

Full F software gates at exact `a1583df` passed. Three actual DeepSeek bridge
component calls returned approved indices with terminal STOP, in
0.566/0.681/0.908 seconds. Their context was reconstructed from original owned
hour-5 SQL, reduced from 98,028 to 3,354 UTF-8 bytes including saved facts.
They are not a live coordinator, fresh tool refresh, GPU, naturalness or busy
SLA result. [Original failure, regression, component evidence and hashes](evidence/integration-f/bridge-policy-real-provider-1/manifest.json).

After the user's cloud reboot, Worker was restarted from verified cached
installation without downloading models. New Worker epoch
`407e0b9b24a94f75b3f63aeeba2576d1`, PID 1162, Ready/UP. Hour-6 began afresh on
`a1583df`, with no old Session or elapsed duration reused. Its final result is
pending; original five failures are not overwritten.
