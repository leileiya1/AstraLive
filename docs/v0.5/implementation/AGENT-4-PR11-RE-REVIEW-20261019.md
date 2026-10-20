# PR11 independent re-review, 2026-10-19

**AGENT 4 BLOCKED — PR11 RE-REVIEW. No merge. ASTRALIVE V0.5 BLOCKED.**

Historical0c review. [The later47eedbb Finish/Renew review](AGENT-4-PR11-FINISH-RENEW-REVIEW-20261019.md)
confirms the original3+3+48 positives, but withholds protected registration/merge
for a newly reproduced old-Media/new-Generation retirement defect and a separate
combined test fixture SQL race. Historical raw failures below remain preserved.

Reviewed full HEAD `0c259cc981c12503485198982e84ad567b529c4e`, core fix
`dabe495fcc8102febe2ee1512f295a37662f34ae`, against original integration
`0cc1a141e443ee1069dc997a91182e4b48257be5`. Fetch verified both pins and Draft/open
PR11 targeting integration. Read the owner's exact handoff, source, tests and
archive tooling. Reused original Agent4 worktree/branch; no other Agent/worktree/
branch, production-source edit, force push, Linux destructive operation or GPU.

## A. P1 SOURCE FIX ACK — DESTRUCTIVE CAPABILITY DISABLED

The original unknown-descendant recursive-kill source blocker is closed **only
by removing the unproved capability**, not by proving exclusive Linux control.
`OwnedCgroup` has no mkdir, procs write, kill write, rmdir or positive fence receipt.
Constructor refuses before allocation, attach/fence/close refuse before mutation;
exceptions, repeated calls, concurrent lifecycle and resetting a local retired
flag cannot reach a removed mutation. Snapshot/permissions/local locks are never
exclusive-controller evidence. Actual filesystem-magic and native ownership
checks remain, but their model tests do not constitute kernel acceptance.
Repository call-site audit finds no production positive caller of this helper;
current CPU Publisher and official ports do not require an enabled cgroup helper.
Production PhysicalSource exports and the standalone entrypoint still refuse.

Unchanged original four probes were run three times: each **3 PASS /1 FAIL**.
The remaining old positive empty-leaf test demands a kill write without exclusive
control. This premise is now explicitly unsupported, so its rejection is the
correct capability boundary, not a product regression to be fixed by enabling kill.
The original assertions/logs are retained, not edited/skipped/marked all green.
Current independent tests explicitly assert that even the same empty valid leaf
refuses mutation: **8 PASS**. Owner's modeled scope adversaries: **56 PASS**.
These include late subtree creation, PID birth/ownership changes and repeated
local calls. Ordinary-file models stub filesystem recognition only where stated;
no actual Linux kill, attach or cgroup removal was performed. This ACK cannot be
reused for a future positive controller, which requires new exact-pin review.

## B. Code integration BLOCKED: PR11-V1-FINISH-RENEW-TEARDOWN

The cgroup fix and evidence migration pass. A separate normal-completion race
remains in the existing v1 Guardian, whose production bytes are **unchanged**
from integration. This is not attributed to the cgroup patch. The user's required
full Guardian quality gate is nevertheless unsatisfied.

Independent real CPU/loopback PostgreSQL/MediaMTX observations:

- Exact original v1 suite25 PASS; recursive suite167 PASS/1 Linux SKIP includes
  the same25 plus142 v2 cases. These are not additive independent totals.
- Original RTMP success case with passive exact ledgers,20 fresh rigs:18 PASS /
  **2 FAIL**. A separate20 with in-memory lifecycle traces:17 PASS /**3 FAIL**.
- All5 failures had already passed the original complete coded-packet/range
  verifier before terminal teardown failed. No observer tolerance was changed.
- Deterministically schedule a valid real SQL Renew after the Publisher's actual
  terminal abort, while Finish has not finished its terminal work: **3 FAIL**.
  A second3 with current DB deadlines measured: **3 FAIL**. Run remains LIVE,
  desired LIVE, no Stop requested. Old Right had761.7/772.7/776.3ms left; fresh
  SQL Permits had898.4/898.7/898.8ms left. This is not an expired-permit test.

Minimal interleaving in `output_guardian/service.py` and `process.py`:

1. Original synthetic input is64000 PCM samples and100 frames. Encoder flush
   returns64 audio hashes/100 video hashes, with the unchanged expected ranges.
2. Recorded prefix commonly has62 audio packets/99 frames; live receiver supplies
   the exact suffix. Initial polling may say tail26/28/29 not matched; a later
   unchanged `verify_combined` succeeds with complete terminal coverage.
3. `finish:461` calls actual `publisher.abort`; `process:143` clears process/pipe
   before waiting for owned child exit. A valid control Renew can interleave.
4. `renew:309` calls the now-closed Publisher. `Publisher.call:110` rejects;
   `renew:320` retires, invalidates barrier/right and concurrently closes resources.
5. Finish is still between its last proof/barrier check and terminal cleanup.
   It then encounters retired/cleared resources and returns DRAIN_UNKNOWN.
   Passive traces show abort -> Renew -> Retire/invalidate -> LEASE_LOST -> failed
   Finish. No missing-tail evidence is converted to success and no replay occurs.

The public `DRAIN_DIAGNOSTIC` prints the last polling coverage error, not the
terminal exception. One failing trace had a prior audio-tail diagnostic and a
later coverage PASS, then teardown failed; another had no tail diagnostic at all.
Thus a stale tail message is insufficient to diagnose actual final audio loss.
This round has a reproducible lifecycle failure rather than proof of a final
encoder flush loss. The earlier owner's failures have no equivalent ledger,
so they cannot all be retroactively assigned this cause. Original LEASE_LOST and
RTMP failures remain retained and causally unclosed where evidence is absent.

Independent diagnostic wrappers only observe original methods and add bounded
scheduling points; no production implementation/timeout/Permit/PTS/Credit change.
Both20-case runs include real decoding and own each loopback target. Their failure
rates are not SLA estimates. The first budget probe had a collection syntax error;
that development log is retained separately, followed by corrected diagnostic
source and actual3 failing product cases. It is not counted as a product failure.

### Minimal owner correction and re-review gate

Agent5 supplies a narrow v1 normal-terminal lifecycle patch and deterministic
regression, distinguishing intentional drained teardown from live transport/lease
failure. Coordinate normal Finish with in-flight/new Renew and owned resources
without a long I/O lock. Preserve actual Stop/expiry/barrier precedence and exact
required-range evidence; do not simply swallow LEASE_LOST, cancel required proof
renewal early, return completion on missing bytes, or relax audio coverage.
Correct diagnostics must distinguish prior retryable coverage faults from final
teardown faults without exposing URLs/credentials. Re-run missing-tail, real
Stop/expiry, backpressure, EOF, concurrent Renew/Finish/Stop and repeated positive
RTMP controls. Preserve all current failures.

`output_guardian/service.py` and associated v1 files are protected. Agent5 should
provide an exact reviewable patch/tests in its own domain, with pre/post/source
pins; Agent4 governs any specifically authorized protected-file registration.
Do not refresh the313 inventory, weaken validators, or edit frozen normative
files. No protected production correction was attempted in this review.

## Original evidence independently recovered

All199 current archives restored into a new empty directory using the submitted
restore tool. Every gzip hash/raw SHA/byte count checked. All136 selected raw
files match blocked9b Git blobs byte-for-byte. All85 old evidence JSON blobs
remain byte-identical; all198 entries of the historical Owner hash manifest also
verify using the restored originals. Historical cold/RTMP failures are preserved.
No protected file or existing hash/command manifest was rewritten.

Executed the complete, unfiltered
`git diff --check 0cc1a141e443ee1069dc997a91182e4b48257be5 0c259cc981c12503485198982e84ad567b529c4e`:
**exit0**, on final full HEAD rather than the older0164 audit. No attributes or
validator exception was added. Whitespace/archive blocker is therefore cleared.

## Actual independent candidate regression

A plain archive of conflict-free merge tree `d6273534ed08d3428becb756870692baa89116eb`
was used. No worktree/branch or production overlay. The test-runner shim changes
only which Guardian source the native acceptance harness loads (current candidate
rather than historical d8); full Go packages, production sources and assertions
remain unchanged. Original shim/source/commands retained for reproducibility.

| Check | Actual result and evidence layer |
| --- | --- |
| Real Go/Python/PG/AF_UNIX Receiver1 |22 PASS; native auth/SQL real; physical installation/output fixture |
| Original R1 revision probes x3 / owner probes |6 /15 PASS; overlapping groups |
| Streaming PostgreSQL |18 PASS |
| Complete Go test /race |Each267 top-level PASS,0 FAIL,13 SKIP; all reasons retained |
| Go vet |PASS |
| Contracts /Journal /official wire /official adapter |137 /11 /13 /8 PASS |
| Both validators /generator --check |PASS |
| Exact Guardian v1 /current original v2 |25 /69 PASS |
| Current extended v2 |142 PASS,1 dedicated-Linux SKIP; contains69/56/4 archive tests |
| READY/expiry/Stop/two-unit suite |5 PASS, included in142 |
| Unchanged historical4 scope probes x3 |Each3 PASS/1 unsupported old-positive FAIL |
| Current independent scope /owner scope |8 /56 PASS; ordinary-file models |
| Passive20 /phase20 original RTMP repetition |18 PASS/2 FAIL;17 PASS/3 FAIL |
| Deterministic normal Finish/Renew /deadline-observed repeat |Each3 FAIL |
| Protection |313 PASS;2 deliberate mutations rejected, restored PASS |
| Restore/archive/full-final-HEAD diff |PASS,199 /136 /198 verified as above |
| Merged/post-push Guardian acceptance |NOT TESTED: PR11 not merged |

Do not add overlapping groups. Full generic runner exit0 does not make the
additional targeted failed regressions pass. Its recursive Guardian result167
is exactly25+142; its historical d8 suite is also separately labeled. All owned
PostgreSQL databases were dropped and the server stopped; loopback test fixtures
cleaned their own resources. No shared service was touched. Full runner command
records include CPU/RSS; targeted runs retain timings/phase ledgers but separate
per-process CPU/RSS was not collected.

All22 frozen normative files and manifest retain original bytes. Approved digest:
`3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`.
The task's shortened digest is not used to change the approved pin. All313
protected expectations and approved fixture remain byte-identical. Seven
migrations, official DTO, Authority/Streaming, shared Backend/Runtime and GPU Wire/
PTS/Credit remain unchanged. Actual merge diff only adds Agent5-owned paths.

## C. OUTPUT_FENCE_UNPROVEN / BLOCKED

No working exclusive Linux cgroup controller, kernel populated proof, independent
physical source, Host Launcher/UID/ACL/network isolation, retired Publisher/
credentials/socket exclusion, production Receiver once-TTS/Observer or genuine
required RTMP/WebRTC Sink has passed. CPU/native auth/SQL/model results do not
waive these gates. No GPU/browser/platform/audience/SLA claim.

Agent5 first supplies the narrow lifecycle correction above based on reviewed
HEAD0c259cc and Agent4's unchanged source dependencies58cbc59/08af104. A future
Linux positive controller is a separate task after re-review, not an enable flag.
Agent4 exclusively owns Host Launcher, CoordinatedPhysicalSource and mandatory
RetireInstallation-before-change, Session/Generation/Binding, Receiver/Observer
assembly and protected-file governance. The existing
[Linux environment/ownership plan](AGENT-4-LINUX-PHYSICAL-ACCEPTANCE-PLAN.md) continues
to require explicit dedicated host/VM, exclusive cgroup delegation, separate UID/
ACL/namespaces, owned network/test targets/data/credentials and cleanup scope.
No authorization for shared Linux kill/cgroup/network/service changes exists.

[Machine summary, SKIPs, commands, failed tests, ledgers, synthetic recordings and
probe source](../evidence/agent-4/pr11-rereview-2026-10-19/summary.json) are committed
as review evidence only. PR11 remains Draft/unmerged, PR8 Draft, main unchanged,
LIVE closed and GPU unused. Code-integration ACK is withheld; no merge SHA exists.
