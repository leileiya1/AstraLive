# AGENT 5 — PR11 FINISH/RENEW TEARDOWN FIX READY FOR AGENT 4 REVIEW

**OUTPUT GUARDIAN BLOCKED.** The confirmed v1 normal Finish/Renew race is ready
for independent source review. Two protected postimages still require Agent4
governance, and production physical isolation remains unproved. No merge, Ready
conversion, main/PR8, Durable LIVE, GPU, shared Worker or Linux destructive action.

Dependency: `864cdbf7545ea3fdd52d4f8405bcd83dcb3497b5`.
Implementation: `ecfad8d5b358f0461981d9f2950dd034f8d0fe69`.
Final test source is the same implementation commit. Earlier 2751/393203a/4b1ea9f
are retained development snapshots, superseded by the live-reap correction.
The final documentation/evidence HEAD is published in the existing PR11 comment.
Original worktree/branch reused; normal fetch/merge/push only.

[Lifecycle linearization, diagnostics and exact pre/post hashes](V1-FINISH-RENEW-HANDOFF-20261019.md)
describe the implementation. Product bytes are identical across all final2 runs:
`service.py` postimage
`94eb702cd978b76a21cd29e3642397c976a8b221593a651b55f5375b6a18fa47`;
`process.py` postimage
`56d4093b6cc35c35d668014b083bd52da290f8883f58437ecb98a3e9a605bf19`.
The initial candidate passed the original positive groups but failed the added
crash-at-abort boundary; it is not the final acceptance source.

## Original fault, unchanged tests and final repetitions

All four Agent4 probe files were copied byte-for-byte to a plain temporary source
directory, with hashes retained. Executable copies replace only OUT with a new
dedicated directory. Original assertions, expected results, input, scheduling
events, Permit/Right lifetimes and time windows are unchanged. No extra
worktree/branch or test overlay is used.

Owner independently reproduced the two deterministic groups **before editing
source**: **3 FAIL +3 FAIL**, with actual valid SQL, actual media processes and
full verification before teardown. Their deadline/run/Stop records are retained.
The two original pre-fix20-case histories (18/2 and17/3) are Agent4's supplied
evidence at the dependency pin, not re-executed Owner totals.

Final committed implementation results:

| Check | Result |
| --- | --- |
| Original deterministic normal teardown/Renew |3 PASS |
| Original deterministic with SQL deadlines |3 PASS |
| Original RTMP plus passive exact ledgers |20 PASS /0 FAIL |
| Original RTMP plus lifecycle traces |20 PASS /0 FAIL |
| Extra bounded stress, original phase probe cases0–7 |8 PASS /0 FAIL |
| New deterministic/local/owned-process/real-edge suite |35 PASS |
| Independent current cgroup capability source probes |8 PASS, no mutation |

All48 positive RTMP ledgers are independently checked for exact sample range
`[0,64000]`,100 decoded frames,100 PTS values,64 expected audio packets and100
expected video packets. Full prefix/network suffix verifier PASS precedes
terminal success in every case. The28 phase ledgers retain lifecycle traces.
Valid Renew after terminal ownership returns STATE_CONFLICT and causes no
global Retire; the original Finish expectations remain satisfied.

The source hashes are checked before/after the whole final media run and stayed
unchanged. No failed iteration is discarded or replaced with the last green run.
The initial candidate also passed both deterministic groups and both20 groups,
but then failed a new deterministic real child-death-at-abort test (full proof
already PASS). It was superseded. Final acceptance uses fresh final2 runs after
actual reaper liveness/exit validation and idempotent quarantine cleanup were fixed.

## Negative and concurrency coverage

The final35 comprise28 local/mock/owned-process cases and7 actual loopback
PostgreSQL/MediaMTX/CPU cases. Local events arrange legal in-flight and duplicate
Renew reservations, post-SQL terminal rejection, Stop before/during/after Finish,
old/new Right expiry, stale barrier/Generation, late SQL after Stop/replacement,
SQL outage, cancellation, duplicate Finish/Stop, ordered five-generation rebuild,
registry/Stop fsync fault injection and old-pipe ownership. Actual pipes/processes
exercise EOF/backpressure, shared abort and cancellation of an abort waiter.

The seven real-edge cases remove the last actual audio packet/video packet from
the observed range view before calling the **unchanged** verifier; both refuse
drain. Actual SQL queries completed before a deliberately delayed response test
Stop and terminal ownership separately. A real watchdog expiration while terminal
cleanup is paused refuses completion. Killing only the exact test-owned Publisher
after proof, both before the liveness check and immediately at actual abort entry,
produces UNKNOWN instead of normal completion. Coverage
PENDING/PASS and final FAILED/DRAINED are asserted independently.

The original25 include real authority loss, real WebRTC peer closure, retained
publisher kick, process recovery and missing-tail cases. The v2 regression retains
actual fsync/EBADF, ACK loss, Stop races, immutable delayed lineage, nonzero
sample/PTS origins and single-START/two-unit continuity. CPU/mock receipts do not
become production Sink or audience proof.

## Complete current regression, counts overlap

| Check | Actual result |
| --- | --- |
| Original Guardian v1 |25 PASS |
| Original Guardian v2 |69 PASS |
| Current extended v2 |142 PASS /1 dedicated-Linux SKIP |
| Owner cgroup probes |56 PASS, included in142 |
| Independent cgroup probes |8 PASS |
| Fresh-process CPU cold two-unit |20/20 PASS |
| READY/delay/Stop/expiry repetitions |6 ×5 PASS |
| Official wire /adapter+wire |13 /21 PASS, overlap |
| Durable Journal |11 PASS |
| Frozen contract137 |136 PASS /1 protected-hash FAIL |
| v1 validator |PASS |
| v2 validator |FAIL on protected process.py; both postimages pending |
| Generated official codec check /lint |PASS |
| Current receiver1 Go/Python/PG/native `-race` package |38 top-level PASS /0 FAIL /0 SKIP |
| Full Backend Go test/race outside receiver1 |NOT RERUN; Agent4 independent integration |
| Full PR diff vs latest integration |PASS, no path filtering; final HEAD rechecked |

The broad runner exits1 because of the retained contract/validator failures,
not a green global release result. The inventory remains byte-identical to
integration: exactly two of313 source hashes differ, matching the Owner proposal.
The actual contract test stops at the first mismatch; it does not grant a waiver
for either file. Agent4 must review and register exact approved postimages.

The native38 are freshly executed against the current checkout, not prior267
or38 results. Native process/auth/SQL/CONTROL are real components; physical
installation/output are explicit Agent4 fixtures. No production PhysicalSource,
Host Launcher, RTMP/WebRTC required Sink, Linux UID/ACL/network/cgroup or GPU
acceptance follows.

## Failure history and evidence

Every original before-fix failure and every final exit code is retained. Earlier
unobserved LEASE_LOST/RTMP failures cannot all be retroactively assigned this race.
Historical gzip/JSON evidence is preserved rather than rewritten.

Development tests also retain their failures: first mock Stop scheduling observed
an already-set abort event, and a teardown fault was injected after its callable
had been captured. Test events/injection ordering were corrected. A later mock
rebuild lacked its new observer and correctly failed; its fixture was corrected.
The initial30-frame real negatives never reached ingest/observer readiness and
returned safe UNKNOWN before the intended boundary. Their raw diagnostics show
observerStarted=false and no verifier call. They were replaced with the original
full64000-sample/100-frame test input to reach the actual target boundary, without
changing production deadlines, decoder timeouts or coverage. The new crash-at-abort probe initially exposed a genuine false success;
two intermediate reaper variants then passed that product assertion but had a
fixture-close ERROR because failed/quarantined reaping was not idempotently
closable. Both are retained. Final cleanup distinguishes a disabled restart
capability from repeatable physical closure. The test-runner's
E731 style failure was fixed; no lint suppression was added.

Evidence lives in `evidence/finish-renew-20261019/`:

* `summary.json`, `terminal-range-audit-final.json`: actual results and all48 terminal ranges.
* `final2-media/commands.json`, `probe-provenance.json`, ledgers and gzip logs:
  original cases, exact source copies/hashes, timestamps, CPU/RSS, complete traces.
* `final-lifecycle-35-command.json`, `regression-final2/commands.json`,
  `native-final2/native-commands.json`: current tests, failures and SKIP boundaries.
* `protected-owner-proposal-final.json`, `protected-owner-patch-final.diff.gz`:
  precise two-file Owner authorization request, pre/post and source pins.
* `source-freeze-audit-final.json`:22 frozen files/manifest/digest,7 migrations,
  unchanged313 inventory and approved fixture; no shared-owner source changes.
* `resources-and-cleanup-final.json`, final full-diff/hash audits: dedicated resource
  cleanup and exact complete candidate check.

Raw logs/patches are lossless deterministic gzip, indexed with original SHA256,
source/command/time metadata by [the existing recovery tool](RAW-EVIDENCE.md).
No protected evidence or shared attribute/validator is changed. Private probe
copies and the owned stopped PG root are removed; every test-owned child was
reaped, with no live media/PG/Guardian children in the final read-only census.
No unowned process was signalled, no shared service changed, no platform connected.

No new P0/P1 is observed in the covered final cases. The identified lifecycle
source fix is ready for Agent4 independent review; protected-file governance and
production physical acceptance remain BLOCKED. Do not merge PR11/PR8, enable
LIVE, restore cgroup mutation or interpret this evidence as a production ACK.
