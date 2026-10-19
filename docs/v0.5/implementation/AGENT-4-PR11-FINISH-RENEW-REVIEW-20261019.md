# PR11 Finish/Renew independent review, 2026-10-19

**AGENT 4 BLOCKED — PR11 FINISH/RENEW RE-REVIEW. No merge.**

Reviewed complete HEAD `47eedbb0f4d990c18cbe8bdf462b65486d385523`, implementation
`ecfad8d5b358f0461981d9f2950dd034f8d0fe69`, against integration
`864cdbf7545ea3fdd52d4f8405bcd83dcb3497b5`. Fetch verified Draft PR11 targeting
integration, a clean original Agent4 worktree/branch and unchanged main. A plain
archive of conflict-free merge tree `8863b948ef6b00ee3078ce4ce8760d23a071d036`
was reviewed/tested; no new Agent/worktree/branch or production overlay.

## Confirmed improvements and unchanged original probes

The new cohort closes fresh Renew Publisher admission synchronously at QUIESCING,
then waits for reserved members without a long lifecycle lock. DRAINING permits
necessary proof renewals; post-SQL terminal losers get STATE_CONFLICT, while
invalid/expired proofs revoke. Final checked current-life/Right/barrier/Stop and
synchronous drained invalidation define the completion boundary. Actual output
cleanup is separate from local phase metadata. Shielded reaping pins owned Popen/
pipe, prevents allocation during reaping and rejects known dead/broken original
handles during terminal cleanup. Normal Finish is not v2 per-unit Finish.

The35 Owner lifecycle tests were independently executed: **35 PASS**, including
seven real private PostgreSQL/MediaMTX/CPU edge cases. Those cover actual child
death before teardown/at abort entry, real watchdog expiry, delayed real SQL,
Stop and missing final audio/video coverage. Packet loss in those negatives is
injected into the observed range view before the unchanged verifier; this is not
an actual production-network loss/fencing proof. The other28 are explicit local/
owned-process scheduling fixtures. Pipe, cancellation, duplicate cleanup and
fsync-failure cases pass within their documented model/native layers. Source
review checks the live original handle and expected exit status correction;
the earlier development crash-at-abort false-success is not accepted evidence.

Restored original Agent4 probe bytes from the integration evidence; executable
copies change **OUT directory only**, preserving assertions, original scheduling,
SQL deadlines and input. Independent actual results:

- Original deterministic3 and deadline-observed3: **3 PASS +3 PASS**.
- Original passive20, lifecycle-phase20 and selected original phase cases0–7:
  **20 PASS +20 PASS +8 PASS**, no failed case discarded.
- All48 ledgers have the checked original `[0,64000]` audio sample range,
  100 video frames/100 PTS values,64 expected audio and100 expected video packets,
  and original exact prefix/suffix verification PASS. Original tests assert the
  returned LOCAL_MEDIA_DRAINED. This new implementation returns only after its
  synchronous DRAINED transition, and the test subsequently Stops the Run.
  The unchanged probes do not independently snapshot the live phase at that
  return; this source-backed inference is labeled in `range-audit48.json`, not
  presented as an additional physical Observer measurement.

These successes resolve the original positive scheduling reproduction in the
covered profile. They do not establish safe handling of every old-life callback.

## New P1: PR11-STALE-MEDIA-RETIRES-NEW-LIFECYCLE

Required review boundary11 remains violated in modified protected `service.py`.
Renew/Finish/poll failures capture a lifecycle, but **Media** still uses global
retirement after an await:

```python
await self.publisher.call(message)       # line500
self.check(attempt)                     # correctly rejects the old Attempt
...
except BaseException:                   # line507
    await self.retire()                  # line508: retires CURRENT life/resources
```

A late callback can therefore revoke and kill an unrelated newer authorized
Generation. This Media path existed before the repair; it is an uncovered required
boundary in the proposed full protected postimage, not attributed to the new
cohort or a new wire defect.

### Independent reproduction and actual observations

Local explicit mock reproduction:1 FAIL. Followed by a real private loopback
PostgreSQL/MediaMTX/native-process reproduction **3/3 FAIL**:

1. Activate valid Generation1. Submit one original320-sample audio packet. Let
   its actual owned Publisher RPC finish, then delay only delivery of that ACK
   to `Guardian.media`; no fake success or error is substituted.
2. Establish the next Attempt/Outbox/STARTED Inbox/unique active Slot in the same
   dedicated seven-migration SQL fixture, keeping scope/Run/Session valid.
   This is explicit test control-state provisioning, not production Session
   registration/Provider Binding acceptance. Actual PostgresAuthority queries
   validate the new Attempt and fresh Permit, without an Authority mock.
3. `Guardian.bind` legitimately authorizes Generation2 and starts a real new
   Publisher. Record it alive, new barrier3, valid Right remaining
   **698.45 /697.96 /699.57ms**, no Stop.
4. Release the old successful Media ACK. The old request correctly fails current
   Attempt validation, then its global exception cleanup retires the NEW life.
5. Each case: barrier **3→4**, new phase **REVOKED**, Right removed, new owned
   Publisher killed/detached. No expiry, invalid new permit or Stop caused this.

`test_real_stale_media_scoped.py.txt` is the minimal actual probe. An initial
version omitted the new SQL Attempt fixture and safely failed LEASE_LOST before
new authorization; those3 setup failures are retained and are **not** product
proof. The corrected scoped3 cases reach the intended boundary. Native PID data
and Rights are per-case JSON, no credentials/URL/ticket in evidence.

### Minimal Agent5 correction

Capture and validate the original life/Attempt/barrier at Media admission. Every
post-await failure, cancellation and delayed sink callback must retire/alter only
that still-current captured life, using the existing scoped retirement primitive
or equivalent identity check. Reject the stale request without retiring, relabeling
or mutating a replacement Generation. Audit associated post-await global state
and diagnostics as part of this same narrow stale-callback boundary. Preserve
actual Stop/expiry precedence, old-output isolation and UNKNOWN/no replay; do not
swallow a real current-life transport failure. No new authorization RPC/protocol,
PTS/Credit change or architecture expansion is needed.

Re-run this native3 case, old negative ACK/cancellation cases, old/new Session/
Generation/channel boundaries, original3+3+48, actual crash/pipe/Stop/expiry/
missing-tail and complete regressions. Supply a **new service.py postimage**,
exact Owner patch and source pin for Agent4 review; current94eb postimage is not
approved merely because its original positive cases pass.

## Additional combined-regression failure: test SQL connection race

Combined Guardian regression: **201 PASS /1 FAIL /1 Linux SKIP**. The failure is
`lifecycle/test_real_edges.py::test_real_proven_ranges_never_override_lifecycle[stop]`.
It fails **before the intended Stop boundary**, while setting up `target=await
rig.permit()`: background `renew_forever()` also calls `rig.permit()` on the
same fixture `Rig.db` asyncpg connection. The driver correctly raises
`InterfaceError: cannot perform operation: another operation is in progress`.

A separate real private PostgreSQL test launches two fixture permit writes:
**3/3 FAIL**, each observing that exact InterfaceError. This is a deterministic
fixture concurrency issue, not production PostgresAuthority, which has its own
query lock. The separate35 passing run does not waive the combined failure.
Agent5 should fix the **new lifecycle test's setup** using a separate dedicated
connection or proper shared-fixture-write serialization; leave the already
approved protected v1 conftest postimage unchanged. Do not skip the Stop case,
retry until green, alter deadlines or misreport the failure as a Stop security PASS.
The independent fixture probe's initial collection SyntaxError is also retained;
corrected source then reaches the3 actual fixture failures.

## Exact protected-file governance: verified, NOT APPROVED/NOT REGISTERED

Independent bytes/hash calculations agree with the exact Owner proposal and
uncompressed Owner patch (byte-identical to the actual two-file Git diff).
Original preimages, proposed postimages, proposal, raw patch and audit are retained.

| Path | Preimage SHA256 | Proposed postimage SHA256 |
| --- | --- | --- |
| `output_guardian/service.py` |`12b5225dffcfad095bf4f07140d30c907325a8ccf244aa124b80d3153fc76e52`|`94eb702cd978b76a21cd29e3642397c976a8b221593a651b55f5375b6a18fa47`|
| `output_guardian/process.py` |`5d95a661471d1f13415efae4b6ce35fb0fed23d961d45bceab35de9526f5b4d3`|`56d4093b6cc35c35d668014b083bd52da290f8883f58437ecb98a3e9a605bf19`|

The user authorizes exact registration **after** source review passes. That
condition is unmet. Neither postimage is formally registered in this review;
no inventory field/hash/validator was changed. Existing313 entries/count and
prior authorizations remain exact. Candidate311 files match; exactly these two
proposed source files differ. Original fixture remains SHA256
`101add95bf76d9a6d0fe317572e20d69b72248547fb8eea9d3cfc150ad377525`.

Untouched candidate contract suite: **136 PASS /1 FAIL**; v2 validator: **FAIL**
on protected process.py. They are not labeled PASS. The existing compliant
integration baseline313 checks pass; two negative mutations on that **baseline
archive only** are rejected at their precise paths and restored. Prospective
post-registration candidate negatives/full regression are **NOT TESTED**, since
approval is withheld. Baseline negative PASS is not a candidate-governance PASS.
There is no temporary approved inventory/overlay disguising these failures.

## Complete independent results and limits

| Check | Actual result |
| --- | --- |
| Real Receiver1 Go/Python/PG/AF_UNIX |22 PASS; physical source/output are explicit fixtures |
| Original R1 x3 /owner probes |6 /15 PASS, overlapping groups |
| Streaming PG |18 PASS |
| Whole Go test/race |Each267 top-level PASS,0 FAIL,13 explicit SKIP |
| Go vet |PASS |
| Original deterministic /budget /RTMP |3 /3 /48 PASS |
| Owner lifecycle standalone |35 PASS, including7 real negative boundary cases |
| Original Guardian v1 exact |25 PASS |
| Original v2 /current extended v2 |69 /142 PASS; extended1 Linux SKIP |
| Combined Guardian |201 PASS/1 fixture FAIL/1 Linux SKIP; same groups, not added |
| Cgroup current independent+owner |8+56 PASS; non-destructive models only |
| READY/Stop/expiry/two-unit |5 PASS, included in142 |
| New stale Media callback native scope |3 FAIL; local mock1 FAIL |
| Independent fixture-concurrency probe |3 FAIL after development collection fix |
| Contracts137 /v1 validator /v2 validator |136 PASS/1 protected FAIL; PASS; protected FAIL |
| Journal /official wire /official Adapter |11 /13 /8 PASS |
| Generator --check |PASS |
| Unfiltered complete PR diff-check |PASS on full47eedbb HEAD |
| Final registered candidate /post-merge tests |NOT TESTED: neither approved nor merged |

The broad unregistered runner exits1 for contract/protection and combined Guardian
failures. Its historical d8 core group is labeled separately; native harness
source selection explicitly loads current47 candidate. No Go/production assertion
or source overlay. All SKIPs, initial failures, retries and source provenance are
retained. Group totals overlap and are not summed. Resources/timings are in the
full and original-media runner command records; other standalone commands have
raw logs/timings but no separate CPU/RSS measurement.

All22 normative files and original manifest retain frozen c7fd462 bytes and digest
`3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`.
Seven migrations, official DTO/Authority/Streaming, GPU protocol/PTS/Credit,
validators/default guards and approved fixture are unchanged. Production changes
are only proposed in PR11; the integration branch receives review evidence only.
Owned PG databases were dropped, PG stopped; all private targets/children cleaned
by their fixtures, no shared service or unauthorized Linux resource touched.

## Next handoff

Agent5 first fixes scoped old Media cleanup and its new test SQL setup in the
existing branch/domain, keeping cgroup mutation denied. Agent4 alone reviews
fresh exact protected proposals, registers only safe authorized postimages and
performs later controlled integration. No ready/merge or production ACK now.

After a safe isolated merge, a separately authorized dedicated Linux VM/host,
exclusive delegated cgroup, distinct UID/ACL/namespaces, isolated network/targets/
DB/data/credentials and an exact cleanup manifest are required. Agent5 owns
exclusive controller/native old-Publisher/socket/credential and required Sink
proof. Agent4 owns trusted Host Launcher, CoordinatedPhysicalSource and mandatory
RetireInstallation-before-change, Session/Generation/Binding and later Receiver
once-TTS/Observer assembly. Current CPU local decoding and native SQL/auth do not
prove any of those production boundaries.

Production PhysicalSource, genuine target/Sink/old-output isolation remain
**OUTPUT_FENCE_UNPROVEN / BLOCKED**. PR11 and PR8 remain Draft; main untouched,
LIVE closed, no GPU/platform/shared-Linux destructive tests. No merge SHA exists.

[Raw results, source copies, pre/post/patch, exact probes,48 ranges, SKIPs and
resource/cleanup records](../evidence/agent-4/pr11-finish-review-2026-10-19/summary.json)
are review evidence, not a passing registered/merged production implementation.
