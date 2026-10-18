# Agent4 PR11 independent integration review

**AGENT 4 BLOCKED — PR11. ASTRALIVE V0.5 BLOCKED.**

Reviewed Guardian HEAD `9b969d099b7a3b6b85f3595d26c36fb953d47263` against integration
`a0a05071d3eae1cc918fc7d7c2c56604fea380da`. PR11 stays Draft/unmerged; there is no
merge commit or post-merge production acceptance. Existing worktree/branch reused.
No main, frozen contract, production entrypoint, flag, GPU or platform changes.

## Agent2 FINAL ACK received: source-fix layer A only

[Agent2 FINAL ACK](https://github.com/leileiya1/AstraLive/pull/8#issuecomment-6250617590)
is [formally received in PR8](https://github.com/leileiya1/AstraLive/pull/8#issuecomment-6250746332).
R1-INSTALLATION-REVISION-DRIFT's **source implementation** blocker is cleared only
for `58cbc59042c70f9010a368f963257fdad5154b91`, acceptance
`08af1049250d2657d7afb5e303d97a02e9761570`, under the trusted before-change
CoordinatedPhysicalSource lifecycle and database permission assumptions. Those
production bytes remain unchanged. Agent2's12 additional adversarial cases and
other overlapping groups are owner evidence, not newly executed Agent4 totals.

A Backend true whose SQL and final observation already completed can reach the
network Writer after CloseAdmission. Its Reader still prevents Retire completing;
the physical tuple cannot legally change yet. An in-flight historical reply is
not fresh output authority and cannot directly start TTS. Receiver final proof,
short gate and actual physical sink revalidation remain independently necessary.
The old shorthand comment about no positive emission must not be treated as an
absolute network-delivery ordering guarantee. Layer B remains BLOCKED.

## Merge compatibility and ownership

Merge base is `eb00428eeb1f0506e9b71eea47480ba4d982c7db`. Read-only
`git merge-tree --write-tree` produces conflict-free tree
`d80f50431fb2a75e351b267a08664f837da59b11`. Its255 additions relative to integration
are entirely under Agent5's `output_guardian/v2`, `output_guardian/tests/v2` and
`infra/guardian/v2`. No shared-file difference remains in that tree.

The already approved fixture is identical on both sides, SHA256
`101add95bf76d9a6d0fe317572e20d69b72248547fb8eea9d3cfc150ad377525`.
The current313-entry protection inventory remains exactly
`f97ea1ea0ed9ea9b048daef86c2502defc708f6370387d2000534bfb1d7559ea`.
No second registration, old inventory restoration or new fixture variant occurs.
All22 normative files/original manifest are byte-identical to frozen `c7fd462`;
full digest remains `3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`.
Authority/Streaming/DTO/7 migrations/shared production entrypoints/GPU Wire/PTS/Credit
are unchanged. The candidate is a plain archive, not a new worktree or branch.

## P1: PR11-CGROUP-UNKNOWN-DESCENDANT-KILL

[Formal BLOCKED/minimal owner request](https://github.com/leileiya1/AstraLive/pull/11#issuecomment-6250767759).
`linux_fence.py:83–90` enumerates only current-group `cgroup.procs`, then writes
`cgroup.kill=1`. It neither checks subgroups nor establishes/verifies kernel
no-descendant constraints. The same method says unknown members/descendants must
be reconciled without killing untracked PIDs. In an ordinary domain cgroup,
current-group procs omits descendant members, whereas kill affects the complete
tree: [Linux kernel primary documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html#core-interface-files).
The missing check can issue a destructive operation outside the tracked PID set.
A later populated check or timeout cannot undo that write.

Independent non-destructive probes use ordinary0700 temporary directories and
inert text PID999999. Only the filesystem-magic check is stubbed; actual method
control flow, inode/UID/mode checks and file writes remain. No real cgroup or PID
signal is used. Parent procs is empty, events populated1; an unknown child either
exists before the call or is injected immediately after reading parent procs.
In both cases `cgroup.kill` is written1 before the eventual Closed/timeout.
Three independent repeats each produce **2 FAIL /2 PASS**: unknown preexisting
and late subgroup fail the required no-write assertion; unknown direct member
and empty owned leaf controls pass. This is a code-control-flow failure supported
by kernel semantics, not a claim of an actual Linux process being killed.

Minimal Agent5 fix: enforce the advertised directly-owned/leaf scope at kernel
creation and verify it before every destructive operation, refusing unknown
subgroups/descendants before kill. Preserve a trustworthy exclusive mutation
boundary through the destructive write; merely taking another racy PID snapshot
is insufficient. A complete proven subtree-ownership scheme is an alternative,
not permission to widen the current kill scope. Add preexisting/late subgroup,
unknown direct PID and valid owned-leaf regressions. Keep kernel-fs/inode/UID
checks and production denial. Agent4 has not edited Agent5's core.

## Other source findings and applicable acceptance

The rest of the reviewed receiver/CPU boundary retains short-lock rechecks,
irreversible local Stop, one consumed grant/first ACK reservation, denial journal
quarantine and no generic true-response cache. Consume preserves its original
Commit clock through fsync/final proof; Renew cannot revive an expired edge.
READY precedes Authority admission and does not enlarge Grant/proof/100ms margin.
Original immutable registration/consumption/barrier travels through Media,
encoder/decoder and each decoded CPU sink. Normal Finish keeps Session process,
PCM/PTS/frame/sequence origins for Unit2 and requires exact decoded terminal
ranges. Missing registered Evidence builder yields UNKNOWN. Standalone exit78
and the always-denying production source remain. These observations do not waive
the P1 or establish real RTMP/WebRTC output fencing.

| Independently executed candidate check | Result and layer |
| --- | --- |
| Native real Go/Python/PG/AF_UNIX against current9b Guardian |22 PASS; physical source/outputs are fixtures |
| Original source revision cases x3 /Agent2 owner probes |6 /15 PASS; overlapping native groups |
| Streaming real PostgreSQL |18 PASS |
| Full Go test /race |Each267 top-level PASS,0 FAIL,13 SKIP; full reasons retained |
| Go vet |PASS |
| Contracts /Journal /official wire /adapter |137 /11 /13 /8 PASS |
| Validators /generator check |PASS |
| Exact Guardian v1 |25 PASS, local private PG/RTMP/WebRTC fixtures |
| Original69 cases on current PR11 code |69 PASS, official Wire; Authority/installation/Evidence mocked |
| Current extended Guardian v2 |82 PASS,1 Linux SKIP; includes preceding69 |
| READY and cold two-unit child |5 PASS;20 independent fresh-process runs PASS |
| Protected negative mutations |2 rejected;313 restored checks PASS |
| New cgroup scope probes |Each repeat2 FAIL /2 PASS; ordinary-file model only |
| Candidate full git diff --check |FAIL: preserved raw-log whitespace |
| Candidate code/test/handoff-only whitespace |PASS |
| Actual pushed merged Guardian regression |NOT TESTED: PR11 not merged |

A broad recursive Guardian run reports107 PASS/1 SKIP (same25+82 cases); these
counts are NOT added. Full runner's first native group used the old fixed d8
core by design; a separate owned-PG native run explicitly points the Guardian
source at this current merge candidate and passes22/6/15. The shim changes only
test-runner source selection, never production code or assertions. Both raw runs
are retained. Every native run owns fresh PostgreSQL17.11/four DBs with fsync,
synchronous_commit/full_page_writes enabled, and drops/stops its services.

The full candidate's raw pytest/psql/initdb evidence causes git whitespace
failure. It is not labeled PASS or ignored. Agent5 should preserve exact original
failure bytes with a verifiable lossless representation/index rather than strip
or delete history; Agent4 has not changed attributes or bypassed any validator.

Original cold LEASE_LOST lacks sufficient timing to establish a unique cause.
Original intermittent RTMP tail mismatch remains unresolved despite subsequent
passes. Current20 cold passes establish only this CPU profile/run, not universal
stability, production drains or SLA. No deadline/tolerance/assertion was widened.

## Disposition and next stage

PR11 remains Draft and BLOCKED; no merge/ready/force action is attempted.
Agent5 fixes its cgroup scope helper and raw-evidence check in its existing domain,
then supplies a new complete HEAD for re-review. There is no approved Linux
execution pin for the blocked helper. After a safe isolated merge, the roles and
permission prerequisites in [the Linux task boundary](AGENT-4-LINUX-PHYSICAL-ACCEPTANCE-PLAN.md)
apply under separate explicit environment authorization. Current production
PhysicalSource, Linux isolation, old credentials/publishers, true ReceiverProofs/
once-TTS/Observer/sinks/GPU/audience remain BLOCKED or NOT TESTED.

[Machine summary/each SKIP/commands/raw failures/resources](../evidence/agent-4/pr11-review-2026-10-18/summary.json)
and [exact merge/freeze/ownership/source audit](../evidence/agent-4/pr11-review-2026-10-18/source-audit.json)
are retained. No shared Linux/cgroup/iptables/service or real platform was touched.
