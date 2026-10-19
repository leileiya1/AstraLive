# AGENT 5 — RECEIVER1 OWNER REVIEW / PHYSICAL FENCE HANDOFF

**OUTPUT GUARDIAN BLOCKED.** Owner approval below is scoped to the precise v1
fixture repair, official port compatibility and local CPU boundary. It is not
production installation, Linux isolation, LIVE or audible exactly-once approval.
PR11 stays Draft, targeting `integration/v05-durable-live`; Agent4 reviews and
governs integration. No main/shared Runtime/Worker/GPU entrypoint was changed.

Original worktree/branch were reused. After fetch and clean-state/pin checks,
integration was merged normally, without force/reset or replacing work:

| Dependency / increment | Full commit |
| --- | --- |
| Agent4 receiver-1 foundation | `0a67a35e5815031d4d0d0a4ca4da89882e31e079` |
| Fixed integration | `eb00428eeb1f0506e9b71eea47480ba4d982c7db` |
| Previous PR11 | `d8eb05e79661b859547242575e0ac6d1d7303aa1` |
| Normal dependency merge | `acb0a3eaef4ceda50d4d9b5127045dd3cb8d78f6` |
| Exact fixture owner repair | `b77f5385bbdea45d4f1f9b3ee583c0304268950e` |
| READY / official ports / physical building blocks | `3b8435e796f993606f2340cc0aaabc9c992f0c2e` |
| Fixed implementation used by final regression | `be0d81f2dd3079b8fb990826970cd5341f61f98e` |

The final documentation/evidence HEAD is published in the PR review comment;
test source is identified separately to avoid a self-referential commit hash.

## Exact legacy fixture owner decision: APPROVED

The legacy fixture's Run uses the `durable-live-1` database default. Its Outbox,
Attempt, Permit and media identity are the old v1 path; no AnswerArtifact, v2
bootstrap registration, per-unit grant or receiver consume latch is created.
Migration000007 correctly compares explicit Outbox `contractRevision` to the
Run revision and rejects the omitted field. Adding the actual v1 revision is
the correct narrow fixture repair; it does not turn this partial fixture into a
valid v2 business command or relax any production validation.

Only `output_guardian/tests/conftest.py`'s existing `jsonb_build_object` changes:

```diff
-jsonb_build_object('tenantId','t',
+jsonb_build_object('contractRevision','durable-live-1','tenantId','t',
```

The complete one-line [exact diff](evidence/owner-review-20261018/fixture-exact.diff)
and [owner decision](evidence/owner-review-20261018/owner-fixture-decision.json)
are retained. Preimage SHA256 is
`7c2643a5b33452ca37dfd000d5cce0ffb80bbe3776224dae98dd09e737e0bea5`;
postimage is
`101add95bf76d9a6d0fe317572e20d69b72248547fb8eea9d3cfc150ad377525`.
Both match Agent4's exact proposed patch. A disposable git archive, not another
worktree/branch, first reproduced **4 PASS /21 setup ERROR**, then passed **25/25**
after only that patch; its unchanged v2 suite passed **69/69**.

**BLOCKED pending Agent4 protection governance.** This is one of313 protected
files. Agent5 has not changed `protected-files.json`, its expectations or the
validator. Final137 suite therefore reports **136 PASS /1 FAIL**, and v2
validator exits1 at precisely this file. These are failures, not waived PASS.
Agent4 must synchronize the approved exact pre/post change during controlled
integration. The22 normative files, original manifest/digest, protection
inventory and validators retain their fixed-integration bytes. See the
[freeze/ownership audit](evidence/owner-review-20261018/freeze-and-ownership-audit.json).

## Cold-start and continuous CPU media: scoped APPROVED, causal limit retained

Agent4's original68 PASS/1 `LEASE_LOST` is preserved
[verbatim](evidence/owner-review-20261018/agent4-original-cold-failure.txt).
It rejects the first parent Media call after Consume at the local deadline
check. It has no original timing trace, so a unique scheduler/import/CPU cause
cannot be established retrospectively. Twelve independent pre-fix runs all
passed; this does not erase the first failure.

Inspection found a concrete readiness gap: `CPUMedia.start` returned after spawn
and ownership fsync, before the child imported/opened codecs and decoders.
The fix waits for a private nonce/native-process/binding-bound READY response
after actual codec/decoder open, without holding the gate. Startup timeout is
only a closed-resource startup bound, never a Grant/Permit extension. Consume
before READY makes zero Authority calls. The assembly must finish this startup
before issuing speech grants. Stop winning startup cleans up the owned child;
an additional real spawn/Stop regression verifies no surviving PID.

Final committed-source20 fresh Python processes all passed the original
two-unit CPU test. Actual READY initialization took100.09–125.41ms;
ACK→first Media10.71–14.09ms, leaving684.69–688.17ms on the first monotonic
proof budget (suspend-inclusive budget also checked). Six independent repeats
of all five readiness tests passed: **30/30 cases**, including a real900ms child
startup delay before any Grant, a startup timeout, Consume before READY,
Stop immediately after spawn, and an800ms post-ACK event-loop stall.

The injected800ms stall correctly rejects `LEASE_LOST`; no media is enqueued or
sequence advanced. The negative pre-fix failure and all measurements are
retained. Frozen Grant duration,100ms margin, PTS, Consumption Credit and
expiry assertions are unchanged. This fixes initialization ordering; it does
not promise output under arbitrarily stalled scheduling or establish a cold SLA.

Unit1 Finish keeps the same actual process/codec/decoder, installed Generation,
Session sample/PTS/frame origins and media ordinals for Unit2. Real lossless CPU
decode and every required CPU sink's full terminal ranges are checked. Authority,
installation and business Evidence envelope in these CPU tests are explicit
mocks; no RTMP/WebRTC production drain claim follows.

## Official ports and real Authority compatibility: scoped APPROVED

All original69 Guardian tests now use Agent4's sole `GuardianWire`, replacing
the test-only duplicated codec adapter. Opaque immutable `SecretString` survives
the existing consume deepcopy; explicit mock Backend serialization uses the
official canonical wire boundary. No DTO/schema/auth protocol is added.

New `official.py` consumes `Deployment.guardian_ports`, `AuthorityTransport`,
separate `InstallationReader` and trusted `ProcessPin` metadata. The initial FD
binding is not substituted for the final Registrar-installed principal/binding.
CONTROL Stage keeps its separate native pin, capability and signed receipt.
Review covers complete registration/execution/Artifact/Generation identity,
native PID/UID/birth, channel binding, exact scope and wrong-role refusal.

The unchanged Agent4 native suite was run against the final Guardian source:
**14 top-level PASS /0 FAIL /0 SKIP**, Go `-race`, real owned PostgreSQL7 migrations,
real Go/Python processes, inherited FD, native Unix Authority/Installation/CONTROL
and producer channels. Cases include one real consumption latch, successful
Backend Commit with reply lost, Stop before final true ACK, actual150ms output
expiry during220ms RPC wait, renewal after the original Grant expired, old
epoch/Generation/key/binding/scope rejection and managed-process SIGKILL.
The positive installation/output source is Agent4's explicitly named fixture;
this is real transport/SQL evidence with mocked physical ownership.

The Authority transport starts monotonic and suspend-inclusive timing before
worker queue admission, subtracts elapsed socket/worker time and never retries
or caches true. Guardian additionally retains its original Commit anchor through
fsync, final fresh Query and the last short gate; a fresh Query cannot replace
the first Grant deadline. Renew uses its own original Query anchor. Final gate,
ACK socket and original media lineage checks remain in place. The live expiry
case proves refusal across a real RPC delay; official adapter tests separately
cover queued/cancelled worker bounds and deadline accounting. No per-frame SQL
query is introduced.

## Final test evidence and all known failures

Raw commands, exit codes, timings and child CPU/RSS are under
[committed-final](evidence/owner-review-20261018/committed-final/commands.json).
The repeatable runner is `review/run_review.py --output <new directory>`; it
refuses existing output directories and preserves failing checks.

| Final committed-source check | Result |
| --- | --- |
| Guardian v1, actual local RTMP decode / WebRTC peer / cleanup |25 PASS |
| Original Guardian v2 cases, now official Wire |69 PASS |
| Full v2 including new readiness/installation/adapter cases |82 PASS /1 Linux SKIP |
| Fresh-process cold two-unit decode |20/20 PASS |
| Readiness delay/expiry/Stop repeats |6 ×5 PASS |
| Native Go/Python/SQL race suite |14 top-level PASS /0 SKIP |
| Official Python wire + adapter/resource suites |21 PASS |
| Durable Journal |11 PASS |
| Frozen contract suite |136 PASS /1 protected-hash FAIL |
| v1 validator / generated codec check / lint / source+doc diff |PASS |
| v2 validator |FAIL: exact protected fixture hash, pending Agent4 |
| Linux UID/ACL/namespace/cgroup execution; GPU; production sinks |NOT TESTED /BLOCKED |

The complete runner exits **1**, correctly retaining both governance failures.
Its diff check also caught two trailing blank lines while documentation was
being added; the final documentation diff audit passes after correction, with
the original diff-check failure retained. The final complete raw-evidence
diff check reports original pytest/psql/initdb whitespace warnings. Those bytes
are intentionally preserved; that full raw-log check is not labeled PASS.
See [final diff audit](evidence/owner-review-20261018/final-diff-audit.json).
Machine-readable [result summary](evidence/owner-review-20261018/result-summary.json),
[source hashes](evidence/owner-review-20261018/implementation-source-manifest.json)
and [cold timing measurements](evidence/owner-review-20261018/cold-final-measurements.json)
are included.

Failure history is not discarded:

* Prepatch v1 setup21 errors, Agent4's original cold `LEASE_LOST`, and the
  deliberately expired post-ACK probe remain in root evidence.
* The first native attempt was correctly refused because the new dedicated
  database/marker did not match Agent4's required safety name. The test driver
  was corrected; no Backend/test safety check was weakened. Second and final
  isolated native runs pass. All own databases were dropped and clusters stopped.
* Development `final/v1-25.txt` records **24 PASS /1 FAIL**, with actual RTMP
  audio-tail mismatch (`head62_tail29_expected64`, `tailmatchFalse`). The
  independent observer correctly refused drain. Candidate and final full runs
  both pass25; this intermittent real-media tail failure is unresolved and
  excludes a flake-free production drain/SLA claim. No v1 drain assertion,
  tolerance or timeout was changed to hide it.
* While adding startup cleanup, Agent5 briefly placed a gate comparison before
  its capture and edited source during a development runner. Five development
  cold probes record `UnboundLocalError`; the placement was corrected, a real
  spawn/Stop test added, and the entire acceptance runner repeated against the
  fixed committed source. `final/` is development history; only
  `committed-final/` identifies the final code. All failed logs remain available.

## Physical source handoff: BLOCKED for production

[Physical source handoff](PHYSICAL-SOURCE-HANDOFF.md) documents the executable
CPU installed-binding reader, always-denying production `RegistrarPhysicalSource`,
actual Linux cgroup-v2 process-fence implementation and read-only namespace
census, exact Agent4 assembly interfaces, credential/socket ownership and
missing target-side isolation proof. No mock can produce a positive production
installation through these helpers. Same-UID Darwin CPU observations cannot
certify Linux UID/network/secret isolation.

Agent4 must supply and review an independent native supervisory source, native
cross-UID IPC profile, actual old-process/key/socket/peer revocation and target
publisher exclusivity, then production decoder/required-sink terminal evidence.
Before all of those are proved, keep `OUTPUT_FENCE_UNPROVEN`. The standalone
entry remains exit78 and service templates remain uninstalled/disabled.

All work used synthetic CPU media and private local services. Real fsync,
AF_UNIX, process death/recovery, libav and decoded CPU sinks are distinct from
mock business Evidence. GPU, shared Worker and external livestream were not
used. [Cleanup record](evidence/owner-review-20261018/resources-and-cleanup.json)
confirms no remaining owned candidate processes or local PG/FFmpeg/MediaMTX,
and removal of only the dedicated source archive and stopped cluster roots.
