# PR11 v1 Finish/Renew terminal ownership

**OUTPUT GUARDIAN BLOCKED.** This is an Owner patch for
`PR11-V1-FINISH-RENEW-TEARDOWN`, not a production physical-isolation approval.
Latest dependency is `864cdbf7545ea3fdd52d4f8405bcd83dcb3497b5`;
normal merge is `c0334148136bf7b2dfb7b7473c79f91a7f4e43ce`.
Implementation: `ecfad8d5b358f0461981d9f2950dd034f8d0fe69`.
PR11 remains Draft targeting integration. No main/PR8 merge or LIVE/GPU action.

## Lifecycle and linearization

Every v1 bind has a distinct in-memory lifecycle with its original Attempt and
barrier. This is local synchronization, not an installation/authority protocol
or independent physical ownership proof. The actual Publisher, pipe, socket,
native process and dedicated ingest controls remain the output resources.

`ACTIVE → DRAINING → QUIESCING → TERMINATING → DRAINED` is normal completion;
Stop/expiry/transport/permission uncertainty instead invalidates to `REVOKED`.

1. Finish claims `DRAINING` under the existing operations mutex, then releases
   it before encoder/observer/SQL/thread/process work. New media is sealed;
   legitimate Renew remains permitted during the full original range proof.
2. A Renew returning from SQL checks both original Right deadlines, its new
   proof, original lifecycle and barrier. Immediately before Publisher.call it
   reserves the current lifecycle's renew cohort, without an intervening await.
   The reservation is released in finally, including error/cancellation paths.
3. Only after complete `verify_combined` PASS and current Right/Stop/barrier
   checks does Finish close new Renew admission (`QUIESCING`). It awaits the
   already-reserved cohort using an event, holding no lifecycle lock. Accepted
   renewals can finish their valid update; SQL replies that have not reserved
   cannot enter the Publisher afterward. Valid losers get existing STATE_CONFLICT
   without Retire, not a new output authorization. Real expiry/invalid SQL/Stop
   still follows revocation, even when normal teardown is pending.
4. After the cohort drains, Finish rechecks current authority and actual live
   Publisher/pipe, then claims `TERMINATING`. No new Renew calls Publisher in
   this phase. Shared cleanup closes/reaps the actual resources without a long
   lifecycle/cleanup mutex. HTTP publish/read authentication also denies new
   connections in quiescing/terminal phases.
5. **Success vs Stop linearizes at the final current-life/Right/barrier/Stop
   check and synchronous drained invalidation, with no intervening await.**
   Stop before that check defeats success; Stop afterward revokes a historically
   completed unit. Neither creates future output permission. Late Renew after
   DRAINED returns STATE_CONFLICT and never recreates the child or Right.

There is no generic exception-to-success rule. Proven media followed by a real
child crash, authority expiry, failed cleanup, missing sink or Stop stays UNKNOWN.
An expired original Right cannot be rescued by the incoming Permit. No deadline,
100ms margin, Grant, PTS, Credit, original verifier or media-range threshold changes.

## Cleanup, cancellation and stale results

`close_resources` coalesces one shielded owned-resource cleanup task. It detaches
socket/peer references synchronously, attempts all independent closures even
when one fails, and quarantines failed cleanup. Stop invalidates before awaiting
that task. No SQL, pipe, native wait, socket close or fsync holds a new lifecycle
mutex. The Publisher's existing per-RPC pipe lock only serializes framed calls;
Stop/abort does not acquire it.

`Publisher.abort` coalesces an independent shielded reaper for the exact owned
Popen/pipe. Concurrent abort callers join it; cancellation does not discard the
resource owner. Start cannot allocate a replacement until old reaping/pipe close/
registry unlink finishes. Normal terminal cleanup pins the expected Popen and
requires a live original pipe/process and the expected owned kill exit status.
An already-dead child or broken pipe is a failure even after full media proof.
An abnormal reaper quarantines restart permanently in that Publisher object,
while subsequent nonterminal abort/close remains idempotent. Expected-process checks reject old writers, and old
cleanup cannot unlink a future registry. Native recovery creation-time/marker
verification and actual owned-Popen signalling are preserved; no Runtime PID/name
claim or adopted old process is used.

Renew/Finish and delayed poll failures retire only their captured lifecycle and
barrier. A delayed SQL reply cannot tear down a replacement installation.
Stop tombstone fsync failure now still performs fatal resource revocation; it
cannot skip cleanup or acknowledge a successful durable Stop. Public completion
remains DRAIN_UNKNOWN on any failed terminal path, with explicit final diagnostics.

## Diagnostic separation

`last_drain_result` records coverage PENDING/PASS independently from terminal
DRAINED/FAILED, failure stage/cause, revocation code and bounded `pollFaults`.
Every polling fault is marked `terminal:false`. `last_drain_poll_fault` retains
the last nonterminal observation; `last_drain_fault` describes the final failure
and is cleared when original coverage succeeds. Thus an old audio-tail polling
miss cannot be presented as the terminal teardown failure after full proof PASS.
Only fixed phase/error codes, safe counters and range evidence are recorded;
no exception text, RTMP URL, password or ticket is added to diagnostics.

## Exact protected-file proposal

Agent5 owns this source patch; **Agent4 exclusively owns protection registration**.
The313 inventory and validators are unchanged. The exact pre/post bytes and
patch are recorded in
`evidence/finish-renew-20261019/protected-owner-proposal-final.json` and
`protected-owner-patch-final.diff.gz`; source is fixed at the implementation above.

| File | Preimage SHA256 | Proposed postimage SHA256 |
| --- | --- | --- |
| `output_guardian/service.py` |`12b5225dffcfad095bf4f07140d30c907325a8ccf244aa124b80d3153fc76e52`|`94eb702cd978b76a21cd29e3642397c976a8b221593a651b55f5375b6a18fa47`|
| `output_guardian/process.py` |`5d95a661471d1f13415efae4b6ce35fb0fed23d961d45bceab35de9526f5b4d3`|`56d4093b6cc35c35d668014b083bd52da290f8883f58437ecb98a3e9a605bf19`|

Approved legacy fixture remains
`101add95bf76d9a6d0fe317572e20d69b72248547fb8eea9d3cfc150ad377525`.
No frozen22 file, original manifest/digest, migration, official wire, Backend,
shared Runtime, GPU protocol or v2 source changes. Contract/validator protection
failures pending these two postimages are recorded as FAIL, never waived PASS.

## Acceptance evidence

See the accompanying [acceptance report](V1-FINISH-RENEW-ACCEPTANCE-20261019.md)
and `evidence/finish-renew-20261019/` for exact probe copies/hashes, unchanged
assertions, before/after commands, all failures, actual ranges and lifecycle
ledgers. Executable copies change only OUT to new dedicated evidence directories.
Raw logs/patches use the established deterministic lossless gzip representation;
[restore and verify](RAW-EVIDENCE.md) preserves their original bytes and hashes.

The new35 tests distinguish explicit mock local/owned-process scheduling from seven actual
loopback PostgreSQL/MediaMTX/CPU negative cases. Original Agent4 probes retain
their assertions and 64000-sample/100-frame input. This v1 terminal ownership
does not become v2 per-unit Finish: v2 Session Publisher, single START,
Continuation, nonzero PCM/PTS and Credit are unchanged and independently rerun.

Agent4 must review the exact protected patch, complete the two-file governance
if approved, and independently rerun the final candidate. Production PhysicalSource
and cgroup mutation remain denied; no Linux destructive or platform test is
authorized by this source correction.
