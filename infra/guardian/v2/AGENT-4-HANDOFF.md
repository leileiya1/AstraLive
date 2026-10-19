# Agent4 integration handoff — receiver-1 domain increment

Current correction: [PR11 P1 fix](PR11-P1-FIX-20261019.md). The cgroup helper is
unavailable for mutation until a trusted exclusive controller is independently
proved. No kill or positive installation is authorized. Raw historical logs are
losslessly archived: [restore/verify](RAW-EVIDENCE.md).

## 2026-10-18 dependency update

Consume the fixed receiver-1 official ports and native identity transport using
the [current owner review](OWNER-REVIEW-20261018.md) and
[physical source handoff](PHYSICAL-SOURCE-HANDOFF.md). The original baseline
handoff below is retained as history. Production installation remains blocked.

**OUTPUT GUARDIAN BLOCKED** for production. Base is
`e98d8cf53d1aa5518f9c908785b7a5feae5117f8` on existing
`feat/v05-output-guardian`; new incremental PR targets
`integration/v05-durable-live`. Do not merge main or enable Durable LIVE.

Dependencies are intentionally unresolved at that pin: Agent4's sole
`astralive_contracts/durable_live_v2` DTO/strict decode/auth contexts and trusted
Registrar/Session installation adapter; Agent2's three-operation authenticated
Authority transport/repository. **No dependency delivery SHA is available at
this baseline.** The test suite injects frozen contract mocks only from tests.
Production modules never import the contract examples or test codecs.

Stable internal integration ports (not another wire DTO):

1. `ports.Wire`: `decode(schema, raw)`, `validate(schema, document)`,
   `canonical(document)`, `digest(document)`, `validate_artifact(document)`.
   Supply an adapter to the sole generated package; never a permissive decoder.
2. `ports.Authority`: async `query_receiver_authority`,
   `commit_receiver_consume`, `query_receiver_consumption`, all with the exact
   frozen request/response documents. `BoundedAuthority` validates both ways,
   response requestId and a 200ms timeout (hard maximum250ms), without retries,
   generic true ACK caches, SQL access or a new HTTP/auth protocol.
3. `TrustedInstallation.read` consumes the frozen
   `ReadReceiverPhysicalInstallation` request/response. Provisioned transport,
   per-process Guardian principal, pinned Ed25519 key/keyId and scope are
   constructor dependencies; Stage cannot introduce keys/Generation/processes.
4. `Receiver(wire, authority, installations, outputs, journal, ...)` implements
   seven Guardian operations. `PrivateIPC` exposes exactly their frozen POST
   routes, including `/guardian/durable-live-2/bootstrap/stage`. The other six
   private operations remain Backend/Registrar owned. `ProcessPin` is trusted
   host provisioning input, never a Runtime JSON enrollment API. Separate
   CONTROL and producer sockets plus kernel UID/PID/create-time, independent
   credentials and server-generated channel binding authenticate every request.
5. `Supervisor.start/close` starts the output adapter closed, its independent
   watchdog and IPC, and closes output before waiting on listener cleanup. The
   standalone v2 entry exits78; Agent4 owns the eventual approved assembly.

Run Stop has its own irreversible tombstone, independent of Backend delivery.
Stage, final positive Consume ACK enqueue/activation, Renew, bounded Media
sequence commit, Finish and Restart share one short local gate. Every external
RPC, hash of media bytes, fsync, Observer, encoding/decoding and backpressure
wait is outside it. Results are checked again against original captured
registration/Run/barrier/execution/process/channel and both local deadlines.
An owned child also takes this shared revocable gate around **nonblocking**
socket acceptance, checking original full lineage at encoder/decoder/sink
edges. A SIGKILL lock owner permanently poisons the incarnation after a bounded
25ms acquisition attempt; independent kill/join remains available. This is a
fail-closed bound, not a performance guarantee.

The deny journal contains metadata only, never tickets/true ACKs/text/media or
restorable execution. Files use temp+file fsync+rename+directory fsync. Backend
ACK loss, disk failure, local Stop or Guardian/client restart only produces
UNKNOWN. On startup any previously seen Run is quarantined, including a Run
whose Stop fsync might have failed; corrupt/pending records refuse startup.
This intentionally stricter recovery policy has no automatic same-Run resume.
Do not delete denial records or manufacture a new business identity to retry an
UNKNOWN COMMENT. CONTROL reconciliation/business recovery remains Agent2/4-owned.
The CPU adapter kills only UID+PID+creation-time-matched owned children on
recovery. Unknown ownership or stale unproven IPC filesystem objects blocks
startup; Registrar/supervisor must independently reconcile them.

`Receiver.media` uses the current locally cached proof; Renew reads fresh
authority independently. It does not block on PostgreSQL per frame. An expired
proof cannot be revived by a late renewal. Both monotonic and suspend-inclusive
clocks apply, anchored before RPC, with fixed100ms margin. A consumed Grant's
initial deadline is irrelevant to ongoing renewed output. First ACK retains
its original Grant deadline through disk/proof work and transport writes.

Configure the **existing trusted Session origins** at construction:
`session_audio_origin`, `session_video_origin`, `session_frame_origin`,
`session_sequence_origin`; do not replace them with zero on each unit. Runtime
must capture sidecar lineage **at submission** of PCM/GPU work using the existing
job/sequence association. Do not obtain identities from a later current slot.
`Lineage` includes canonical complete parent registration and consumption plus
barrier revision. `Media` carries that immutable owner through every queue and
child. No Worker binary, generation namespace, PTS or Credit behavior changes.

Normal Finish seals the unit, captures its true audio span, ordered video
PTS/frame range, payload hashes and final outer ordinal, then waits outside the
gate for the trusted Observer. It accepts only exact `ObservedDrain.tail`, every
required sink and complete terminal `Evidence.sinkProofs` for that Generation
and those ranges. Final closure advances only the barrier/slot to STAGED_CLOSED;
the publisher, libav contexts and Session clocks stay alive. Backend must still
confirm trusted business drain before authorizing Unit2's new Artifact/Grant.
Neither enqueue, packet counts nor Worker Credit is treated as drain.

The executable CPU adapter is FFV1+PCM, with persistent real libav codec and
decoder contexts and bounded per-required-sink decoded fanout. Its trusted
Evidence builder is absent by default (Finish then UNKNOWN). Tests use a
synthetic registered Evidence envelope **after real decoded range checks**.
This does not supply production RTMP/AAC delay/tail handling or WebRTC received
range proofs. Agent4 must keep those required sinks blocked until genuine
registered production adapters/receipts are independently reviewed. Do not
route v2 through PR10 attempt-only bind, end/flush the Session publisher at every
unit, pad audio, reset PTS or relabel delayed frames to manufacture a drain.

Resource limits: one active unit, media/first-ACK deques8 each, IPC connections16,
HTTP headers8KiB, control256KiB, media9MiB transport envelope, audio chunk≤1second,
video≤1920×1080 RGB24, per-unit≤2048video frames/60seconds PCM, per-sink queue8,
at most32 retained unit manifests per CPU Session. Media queue references are
shared across fanout, not copied per sink. Large RGB/16-connection deployment
still needs memory-budget acceptance; none of these bounds is a latency SLA.
Timeout/backpressure/unknown lineage fails closed rather than dropping required
media and advancing a cursor. Journal/audit retention has no destructive GC.

Rollback: keep v2 admissions disabled; revoke/kill its owned output and reconcile
UNKNOWN first. Retain journal/tombstones and Backend consumptions. V1 continues
only for independently owned legacy Rooms; never adopt v2 grants into v1.
No shared Runtime patch is needed in this PR: the above ports are the proposed
Agent4-owned assembly boundary and require its review before public integration.
