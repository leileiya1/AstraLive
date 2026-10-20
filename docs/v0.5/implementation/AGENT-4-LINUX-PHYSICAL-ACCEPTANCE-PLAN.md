# Next-stage Linux physical acceptance: ownership and permission boundary

**NOT AUTHORIZED TO EXECUTE BY THIS DOCUMENT. OUTPUT_FENCE_UNPROVEN.**
PR11 `0c259cc981c12503485198982e84ad567b529c4e` has a scoped source ACK only
because all cgroup mutations are disabled. It remains BLOCKED for the independent
normal Finish/Renew teardown race documented in the 2026-10-19 re-review. Neither
old9b nor current0c is an approved positive/destructive Linux version. A future
exclusive controller requires a new exact-pin review and explicit environment
authorization; enabling the current denied helper is not an implementation.

Fixed Agent4 code dependency: Registrar `58cbc59042c70f9010a368f963257fdad5154b91`,
fixture/acceptance `08af1049250d2657d7afb5e303d97a02e9761570`, audit integration
`a0a05071d3eae1cc918fc7d7c2c56604fea380da`. Later review-only integration documents
do not alter those bytes. Freeze `c7fd46209d3cbc6f58541dba8b4e1c85609c823e`, digest
`3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1`.
Use the sole official DTO, native ports and co-located Registrar repository seams;
no cloned codec, parallel enrollment/lifecycle RPC or Guardian business SQL.

## Preconditions: explicit operator/environment authorization

- Dedicated test VM/host or independently isolated guest with real cgroup-v2,
  cgroup.kill and delegated controller authority. A fresh **exclusive** delegated
  parent, stable inode/UID and owned-only child process tree are mandatory.
  Never adopt an existing service group. Permission to log into a shared Linux
  host is not permission to change its cgroups or kill its publishers.
- Scoped OS rights: separate non-root Runtime/Guardian identities and distinct
  CONTROL/producer socket groups; only Backend/CONTROL has scoped business SQL.
  Grant only the precise delegation/namespace/credential operations approved by
  the operator. No blanket sudo, shared cgroup/iptables/Docker/service changes.
- Dedicated test process manifest: PID+birth/native owner, process/cgroup inode,
  bound Session/Generation/key/incarnation and resource ownership saved before
  any kill. Unknown members/subgroups, stale handles or unverifiable ownership
  abort with BLOCKED. P1 leaf/subtree constraints must hold through kill; a file
  named cgroup.events on an ordinary filesystem never proves Linux fencing.
- Isolated mount/network namespaces, exclusively owned target ports/endpoints,
  no general Runtime egress or inherited publishing sockets/keys. Runtime gets
  only scoped existing-protocol AF_UNIX proxies to approved test Backend/Worker.
  No changes to SoulX binary wire, PCM/PTS, Generation or Consumption Credit.
- Dedicated PostgreSQL/Redis/data/Room/Product/Provider Binding/key namespaces.
  Real providers/GPU require separate authorization; the initial Linux suite
  uses synthetic CPU media and private receivers. No official livestream target,
  user credentials or shared Worker. Secrets stay in owner-only files/private
  FDs, never frontend/logs/argv/evidence.
- Agree exact cleanup manifest and independent target-side observers in advance.
  Cleanup may affect only those owned identities/resources. No pkill/name-wide
  stop, deletion of denial/latch evidence or sweeping shared namespace rules.

## Agent5 exclusive domain

Own `output_guardian/**` and `infra/guardian/**`; submit shared-entrypoint patches
for Agent4 review, do not edit Agent4 worktree/Backend/Runtime hotspots.

1. Fix unknown-descendant pre-kill checks and demonstrate kernel-enforced scope
   and truthful fail-closed ownership through mutation/kill. Then actual
   cgroup.kill/populated=0 and restart/orphan tests use only freshly owned children.
2. Prove old Publisher/process/socket/peer and retained credentials cannot publish
   or reconnect after retirement, even if old Runtime attempts bypass. Kernel
   process death is distinct from target connection/credential revocation.
3. Independently collect full native installed-binding/Generation/closed barrier,
   known old-output isolation and current exclusive target ownership. Positive
   data must come from supervisory handles and kernel/target observations, not
   Runtime JSON, shared-memory booleans or SQL metadata alone. Current production
   export remains an unconditional refusal until reviewed and accepted.
4. Test continuous Publisher/Decoder/each required Sink with immutable original
   registration/execution/Artifact/Generation/barrier carried from submission.
   Inject Stop/expiry/retire/restart before encode/decode/send/accept and while
   required sinks stall. No current-slot retagging; Unit1 Finish preserves the
   same Session publisher and PCM/PTS/Credit origins for Unit2.
5. Resolve RTMP tail risks with actual target/local decoded terminal ranges and
   registered observer evidence; obtain genuine WebRTC required receive ranges.
   Enqueue/packet/Worker-Credit/model EOF never substitutes. Retain all original
   cold/RTMP failures and timeout/expiry cases; no widened tolerance to pass.

## Agent4 exclusive domain

Own `backend/internal/durableintegration/receiver1`, public Backend/Runtime
entrypoints and `runtime/app/receiver1`, sole Go/Python DTO. Coordinate, never
modify Agent5's core concurrently.

1. Review a trusted Linux Launcher/cross-UID socket/FD/namespace profile. Current
   Darwin same-UID0700/0600 profile is not sufficient; do not simply loosen modes.
2. Assemble the independent native source as **CoordinatedPhysicalSource** with
   a real immutable InstallationGate. Every physical source/Generation/process/
   key/fence change must call RetireInstallation **before** change and wait for
   reader drain, Run-locked mirror retirement, official CAS and durable REVOKED.
   Errors/partial failures stay closed. Gate ownership alone proves no output
   fence; the source must exclusively control all physical mutation paths.
3. Create/revoke trusted Room/Session/Generation/Provider Binding identity from
   authorized owner/context and actual installation, never self-enroll from body.
   Keep single command-dispatched multi-Room installation/facts roots, no
   last-session callback overwrite or legacy/durable dual scheduling.
4. In a separately authorized phase, implement Runtime ReceiverProofs/once-TTS:
   only first valid Consume ACK plus final current proof/short gate permits TTS.
   SQL true may be historical/in flight after CloseAdmission; it alone authorizes
   no output. Lost ACK/UNKNOWN never reconstructs ticket or automatically replays.
5. Join real registered Observer, all required drains and CONTROL completion to
   SQL/Turn cursor. Preserve the single global START, per-unit continuation and
   unique latch, proper Stop/UNKNOWN/expiry behavior and no premature business
   Slot/cursor release. Verify actual Go/Python/SQL/native IPC/CPU sink chain
   before any later GPU/browser/platform acceptance.

## Required acceptance and handoff order

1. Agent5 exact P1 code fix/re-review → isolated default-off merge and post-push
   full regression. Freeze/protection records and prior source ACK must stay intact.
2. Obtain explicit dedicated Linux environment/operator authorization with the
   manifests above. No destructive tests run merely because a merge succeeds.
3. Baseline kernel/UID/ACL/namespace/target census; wrong scope/key/PID/channel,
   old process/socket/credential and unknown descendants refuse before mutation.
4. Separate process-fence, target exclusivity and complete before-change source
   tests. Inject kill/fsync/DB outage/ACK loss/Stop during reader drain and final
   handoff; prove partial failure cannot publish or manufacture a positive source.
5. End-to-end dual-unit continuous real CPU output and independent required-tail
   observations, then multi-Room/tenant isolation. Keep each evidence layer and
   failed/expired/unselected count separate; retain raw logs/resources/full SHA.
6. Agent5 reports kernel/process/target/Sink evidence; Agent4 reports root identity,
   source/SQL/Runtime/Observer assembly. A joint explicit decision is required
   before any release flag can be reconsidered. Missing permission or evidence
   remains BLOCKED/NOT TESTED; no GPU, audience,24-hour SLA or platform claim.
