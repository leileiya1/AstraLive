# One-hour Golden progress — 2026-10-14

**FAIL / IN PROGRESS. Hour-7 recorded 3600.1805 continuous seconds, but normal
Stop did not reach terminal state.** Distinct failed attempts are retained;
their durations are never added together. A full hour observed is not a full
acceptance PASS.
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

Hour-6 subsequently failed at 1391.268 seconds (23 minutes 11 seconds), with
122 completed narration segments, ten completed answers and nine subsequent
resume transitions. Call ten returned HTTP 200/terminal STOP in 902 ms, one
character whose SHA256 equals `3`. The implicit array index prompt had not
specified zero-based numbering; `3` is outside the three allowed choices.
The parser correctly rejected it. This failure remains valid. Failure Stop
completed ENDED/SEALED/binding release, observed within 101 ms. Chrome final
diagnostic history was not saved after the observer failure; three checkpoints
cannot establish an uninterrupted full hour.

C production `06d886f`/delivery `476f2fb` merged normally as `88a6824`. Only
new staging bridge language lists explicit indices starting at 0 and parses
canonical ASCII indices after trimming ASCII edge whitespace. Invalid values,
provider failures and incomplete terminals remain errors; ordinary/default-off
request and parsing behavior remain unchanged. No frozen API, epoch, profile,
budget or default changed. Full F regression passed at exact `88a6824`.
Twenty-five real model calls on the saved tenth-turn language context all
returned valid choices, maximum 1.856 seconds. This is component evidence,
not another GPU/live hour. [Original failure, full gate and model evidence](evidence/integration-f/bridge-index-real-provider-2/manifest.json).

Hour-7 began afresh at 20:30 local time on `88a6824`. Actual duration was
3600.1805 seconds with one Session/Chrome peer, six ordered checkpoints and no
connection loss before the normal Stop request. The SQL proof records 25
COMPLETED audience turns; independent analysis proves all 25 returned to the
expected next segment/Beat with both required sinks' full receipts. It records
293 completed narration segments, four bridge segments and 25 answers; one
additional narration commit remained UNKNOWN during Stop. All 140 authored
required facts appear once in completed plan metadata; no automatic fact result
is a human naturalness or spoken-content review.

**Overall result remains FAIL:** Stop left Session/run STOPPING and binding
unreleased, including the read-only 20-second teardown guard. Runtime media
stopped, but avatar interruption/cleanup raised StagingFailure. Owner diagnosis
and a bounded ACK/cancellation reproduction are in progress; this is not
silently treated as ENDED, retried speech or a cleanup PASS.

Closed recording components are CONDITIONAL. Chrome has 321 MATCHED speech
prefix/barcode rows, one UNRESOLVED row (ordinal176), and one Stop-censored tail;
RTMP has 322 MATCHED rows and the same censored tail. Absolute speech-prefix to
observation-band offsets P50/P95/max are 13.75/26.75/43.25 ms in Chrome and
0.375/19.625/39.625 ms in RTMP. These are separate recording PTS domains, not
phoneme lip sync, whole-segment drift or physical audience audibility. Both
recordings have zero packet PTS/DTS regressions in this run; no reconnect was
injected.

For all 25 selected SQL turns, conditional selectedAt→Chrome correlated first
audio/video estimates are P50 9.374 s, P95 12.093 s, P99 12.408 s and maximum
12.478 s. They exceed the stated 5/8-second target; same-host UTC/render/device
clock assumptions and selection busy state are not independently calibrated,
so formal busy-comment SLA remains NOT VERIFIABLE. Estimated answer-end gaps
use source duration and are not direct waveform-tail or naturalness proof.

Sampled maxima: Go CPU36.3%/RSS68.75 MiB, Runtime CPU131.6%/RSS827.031 MiB,
RTMP receiver CPU1.8%/RSS21.969 MiB. This excludes Chrome, PostgreSQL, publisher
and whole-host totals. Worker descriptor incremental allocated peak is
966,428,160 bytes (921.658 MiB), below the explicitly selected 1 GiB profile;
sampled device memory maximum is 6,038,749,184 bytes, a separate domain.

Root remains the only GPU/SSH operator. F merged B's closed-run metrics tool
`34d978e` as `f378e96`; 21 rejection/calculation tests pass, and the prior
hour-6 FAIL remains FAIL. [Original hour-7 records, hashes, scripts and separate
component analysis](evidence/integration-f/real-hour-tcp-7/manifest.json).
Large original recordings remain outside Git at
`/private/tmp/astralive-f-real-hour-tcp-7/media/observer/chrome.webm` and
`/private/tmp/astralive-f-real-hour-tcp-7/media/rtmp.flv`. Evidence JSON/log gzip
files preserve original-byte hashes and can be decompressed for inspection.

## Stop repair and subsequent real component tests

C production `43771588c9b988fa1d30ad99e3fab7dafc6db6ba` / delivery
`451405d142b1f61959765d2f3e956e094b613315` merged normally as
`8f04a7567db2710547da2b313e027d1c76eed02e`, without conflicts. It shields the
same admitted, bounded pose ACK transaction from caller cancellation and drains
its exact fingerprint/prefix before Cancel/Release. No Session/Go/Worker/API,
default, profile or deadline changed. A scoped frozen-contract review ACKs no
CCR; B independently reproduces old88 FAIL and fixed PASS over actual loopback
TCP. The original hour's response subtype was not logged, so this proves a
consistent failure mechanism, not exact original packet identity.

F's exact merge gate PASS: Go/race/owned PostgreSQL migration/auth/ownership/
outage/Redis-off/contract, Runtime315 total (303 passed,12 skipped), frontend40
and build. The original5s ACK and2s write bounds remain; this does not guarantee
every delayed cleanup finishes within the Session interrupt budget.

| New actual test | Result | Boundary |
| --- | --- | --- |
| Short1, old Worker epoch407 | FAIL | StageError/STAGING_RETIRED before first media; prior UNKNOWN prevents reuse |
| Short2, fresh Worker epoch080 | Overall FAIL; normal Stop PASS | 60.031s; two of five questions completed; ENDED/SEALED/binding released; committed Stop tail UNKNOWN |
| Short3, same epoch080 | FAIL | Refused by retired Worker after committed cancellation; no media |
| Short4, fresh Worker epoch1faa | PASS for public-flow/normal-Stop component | 60.147s; one explicitly authored question completed, bridge and narration resumed; ENDED/SEALED/binding released; Stop tail remains UNKNOWN |

Short4 uses a separately hashed Stop-component fixture: the same140-statement
product plan and one question. Original five-question fixture, assertion and
failed results are retained. This PASS is not G1/G2, complete fact coverage,
all-question load, complete A/V or human acceptance. The repaired source has
**not** run a fresh full hour; hour7's original FAIL remains unchanged.
Worker committed cancellation deliberately returns UNKNOWN/nonreusable and
retires the epoch. F explicitly restarted the cached owned Worker and opened a
new authorized Session; no old task was recovered or speech replayed. This
operator lifecycle requirement is a release limitation.
Short4's unchanged independent full oracle additionally FAILs on completed
bridge metadata: descriptor `factIds=[]` versus SQL `fact_ids`/segment document
JSON `null`, with equal product versions. All four completed hour7 bridges have
the same mismatch. Public-flow/Stop component PASS does not override this.
Independent normal-Stop, decoded-browser and actual media-byte checks PASS;
recordedAV has six matches plus one Stop-censored tail in each recording.
C/A are fixing only new bridge creation before first save/hash; historical
immutable rows, commands and oracle rules stay unchanged.
[F exact merge, independent controls, all short attempts and hashes](evidence/integration-f/pose-stop-f-postmerge-1/manifest.json).

The new remote branch `exp/v0.5-soulx-staging-golden` was created at `da24925`
with the original hour evidence. The fix and final evidence are subsequently
pushed on that branch only. No main merge/force push or default enablement.

## Final local followup — 2026-10-15

C constructor-only productionee22e1e normally merged as
fb9b75d27f21e176afb4d5fdb32f202fc708ce6a. It initializes new bridge FactIDs
before first persistence/fingerprinting; save/read/DDL/old rows/oracle unchanged.
Owner docs8ffb595 merged separately as7b284a9, with identical production files.
F full exactfb9 gate PASS: Go/race/real owned-PG/auth/fault/Redis-off/contracts,
Runtime316 total304 passed12 skipped, frontend40/build. New actualPG→GoCOMMIT→
production Runtime READY→A admission test runs in both Go and race suites;
explicit CPU fixtures do not substitute for GPU acceptance.
[Final F regression evidence](evidence/integration-f/bridge-empty-facts-f-postmerge-1/result.json).

The user deferred another real one-hour run. None is started. Final-source
GPU/full-hour acceptance remains NOT TESTED; original hour7/full8f failures
remain FAIL, real8f Stop component remains narrowly PASS, and latency remains
above target in conditional estimates. No experimental default is enabled.
