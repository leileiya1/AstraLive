# Browser first-report prerequisite and failed-run cleanup

Current tested source: `25f58511cb6b46e4783a25b018487ebda0237e30`.
Cloud was subsequently switched off by the user. Work after that instruction
was local only; do not interpret a prior READY snapshot as current availability.

## Actual real pilot11 — FAIL before narration

[Retained source-pinned real run](evidence/integration-f/real-golden-pilot-tcp-11/result.json)
used F `ed692369ed72dd1793056d4afad0f4f8fbaef25d`, TCP, owned PostgreSQL,
actual DeepSeek/XiaoYa/SoulX, native Chrome and local RTMP. The managed GPU was
started from its existing cached release; assets/environment/source doctor
checks passed and model READY was observed with Worker epoch
`8aab7fb221af4be1ab74c6acfd6d6874`. Existing approved1GiB profile/gate was
retained. No reinstall/model download, public inference port or main change.

All four real provider profile preflights passed. Before `StartNarration`, the
browser clock check rejected the run. [Actual browser evidence](evidence/integration-f/real-golden-pilot-tcp-11/media/observer/result.json)
records AudioContext running, context delta1.52s over performance delta1.5177s,
74 received RTP packets/70080 received and jitter-buffer-emitted samples,
totalSamplesDuration1.5s and zero discarded packets. Initial inbound report was
null, so decodedAudioDeltaSeconds stayed null and ready=false. This is a missing
baseline defect in the observer, not evidence of an actual stalled clock.

SQL has zero narrations/segments/attempts/turns/commits. Canonical price repair,
answer/resume and GPU business generation were **NOT EXERCISED**. The initial
recording chunk1341bytes passed storage hash/sequence checks but is not speech or
complete A/V proof. Browser final diagnostics were pending after failure.
Session/run STOPPING and bindingReleased=false were captured immediately after
the failure Stop request. This is an early teardown snapshot, not a proven
production Stop refusal, completed cleanup or crash-recovery PASS.

## Local acceptance-only repair

C independently confirmed the const-null-baseline cause before implementation
handoff. F implemented the acceptance fixture fix; C production/worktree was
not modified. `goldenAudioReady()` establishes the first real valid inbound
report within the **same1500ms budget**, then requires both finite AudioContext
and RTP-duration progress≥0.1s. Missing data is never substituted with zero.
Comparison binds the same actual report ID; replacement, nonfinite readings,
insufficient remaining budget, suspended/ended/disabled tracks and non-growing
clocks still reject. No synthetic audio, fixed A/V delay, budget increase or
weakened real-speech/recording guard was introduced.

F's Go Golden test additionally observes failure cleanup while dispatchers and
Runtime are still alive, before dumping SQL. It polls read-only for at most20s,
using the existing normal Stop observation budget as the failure-teardown bound:
exactly one owned fixture Session must be ENDED, its runs exist and are SEALED
with timestamps, and its bindings exist and are released. Missing rows cannot
pass. No extra Stop/FORCE, speech retry, SQL state change or invented receipt is
issued. The original observer error remains FAIL even if cleanup completes;
pending/query-error cleanup is separately recorded in `failureCleanupObservation`.
The guard is not a change to production command timeout or recovery policy.

## Validation and preserved failures

[Full final module gate](evidence/integration-f/browser-preflight-cleanup-final-1/result.json)
PASS: Go/race, owned PostgreSQL migrations/auth/ownership/fault/Redis-off,
Runtime280 total/12skip, frontend40/build and v1.1 contracts. New teardown
predicate tests actually pass in both Go suites. Their rows are explicitly
controlled DB fixtures, not Runtime/native Stop proof.

[Chrome/raw recording/policy evidence](evidence/integration-f/browser-first-report-local-1/manifest.json):
12 controlled JS policy scenarios PASS, plus64 existing independent oracle tests
PASS. Chrome155.0.8059.40 with unchanged B aiortc timeline tracks and CPU silence
reproduces the first-report race by withholding only the initial audio stats.
Old HTML FAILs; fixed HTML obtains baseline after15.2ms and records0.106667s
AudioContext/0.1s actual RTP-duration progress, ready=true within123.1ms.
Actual1741-byte VP8/Opus recording is ffprobe-valid, and silence still rejects
the real speech gate. This is readiness/recording evidence, not GPU, audible
content, lip-sync or a live user latency result.

Initial local source6012868 and7756e6d full gates FAILed because the **new test
fixture** attempted parent-row deletion before dependent provider-binding and
recovery-lease rows. Database FKs correctly rejected it. Both complete failure
artifacts remain [first](evidence/integration-f/browser-preflight-fixture-failure-1/result.json)
and [second](evidence/integration-f/browser-preflight-fixture-failure-2/result.json).
The fixture now respects FK order; no constraint/old regression was removed.
The browser policy test is retained as a separate explicit acceptance gate so
ordinary Runtime unit discovery gains no mandatory Chrome installation.

Reproduce the explicit policy gate with
`<media-python> runtime/tests/golden_audio_preflight_policy.py -v`.
For native first-report reproduction, set `PYTHONPATH=runtime:runtime/tests` and
run `runtime/tests/golden_browser_cpu_diagnostic.py --fixture-html <before.html
or after.html> --empty-first-audio-report --output <new-nonexistent-directory>`.
Use the retained exact HTMLs and script hashes; never overwrite prior evidence.
An absent browser/dependency is NOT TESTED, not a readiness PASS.

## Ownership, rollback and remaining work

F owns modified Golden Go test, new `golden_cleanup_test.go`, browser HTML,
policy/CPU diagnostic scripts and this evidence. Shared test-file changes are
for stricter observation and read-only teardown, dependent on actual A/C state
and unchanged B media tracks; F is final merge owner. A scoped-ACKed the cleanup
observation approach; C confirmed the browser cause. No production, migration,
frozen DTO/hash/schema, GPU Worker or flag default changed. Frozen1 SHA256 stays
`969d2e82d41f20084196d68a77bb3d1a6158a596a9ca63d47de9f6c1a78e8360`.

Rollback these acceptance-only increments separately if needed, retaining
failure artifacts and explicitly restoring the known old baseline defect in the
report. Do not change durable records or replay uncertain speech. Source reverts
are ordinary reviewed reverts, never force resets/main pushes.

Next requires a newly available cloud GPU: one fresh complete short real
business fixture at the final fixed source, then independent SQL/staged bytes/
Chrome/RTMP audit. G1/G2, full crash/Redis-kill recovery, human naturalness and
complete A/V metrics remain FAIL/NOT TESTED. Earlier price replay and recorder
failures are not upgraded by this local readiness repair. All experimental
defaults remain off; new remote-branch push follows the real-testing checkpoint.
