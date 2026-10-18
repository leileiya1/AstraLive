# Receiver-1 physical installation handoff, 2026-10-18

**OUTPUT GUARDIAN BLOCKED.** This is an executable CPU evidence collector and
Linux process-fence building block, with an explicit production denial boundary.
It is not a working production `PhysicalSource`. No service was installed, no
Durable LIVE/GPU/shared Worker was enabled, and no external publisher was used.

Agent4 dependency: `0a67a35e5815031d4d0d0a4ca4da89882e31e079`;
integration: `eb00428eeb1f0506e9b71eea47480ba4d982c7db`.
The official frozen DTO/Authority and installation object are unchanged.

## Concrete assembly interfaces

`output_guardian/v2/official.py:receiver_from_deployment` consumes the existing
`Deployment.guardian_ports` directly. It returns a closed `Receiver`; it neither
starts a listener nor registers or authorizes a unit. Supply the real deny
journal, independently controlled output adapter, required sinks and existing
Session sample/PTS/frame/sequence origins. The private FD's initial binding can
contain pre-installation placeholders: it is not the final installed identity.

`producer_pin(provision, installed_binding, wire)` translates only trusted
Registrar `ProducerProvision` metadata into the existing native `ProcessPin`.
It checks the full final installed Runtime principal/incarnation/scope, native
PID/UID/birth and credential verifier. The host supplies this metadata directly;
no HTTP enrollment or body-supplied pin exists. CONTROL must keep its separate
trusted `Deployment.control_pin` and credentials. Never send verifier material
to logs or accept it from the Runtime.

`CPUMedia(..., installed_binding=<official ReceiverBootstrapBinding>)` captures
the entire binding before spawning a real child. The private challenge-bound
READY pipe confirms exact binding hash, native child/parent, dimensions/rate,
Generation and unchanged Session origins after actual FFV1/PCM encoder and
decoder initialization. All resources remain closed. Each original frame's
registration is checked against that immutable child context before encoding;
the queued lineage/barrier/execution/Artifact continues through decoder and
each required sink. No current-slot relabeling is permitted.

Startup/codec readiness precedes Prepare/START/Consume in a real assembly.
Consume checks native readiness before its first Authority call. Waiting for
READY, fsync, codec work, Observer and backpressure occur outside the short
gate. Stop winning immediately after spawn or while waiting for READY must
reap the owned child and keep admission closed. A ready child is not a valid
Permit; a valid Permit is not physical installation proof.

`physical.IndependentPhysicalReader.read_installed(binding, runtime, guardian)`
describes a trusted host-side read capability. Its concrete CPU implementation,
`CPUInstallationReader`, captures the native bound context only while closed,
with no queued media or ACK, and separately checks PID/UID/birth/parent plus
known retired publisher identities. Subsequent reads check current ownership
without interrupting a same-context active unit. `CLOSED_INSTALLED` means
historical closed installation provenance; re-observation must not close a live
Session publisher to manufacture it. This CPU reader uses same-UID process and
shared-memory state and is **not** an independent production Registrar source.
Its `production_installation` always refuses.

Agent4's actual native seam remains:

```go
Observe(context.Context, wire.ReceiverBootstrapBinding, Identity, Identity)
    (wire.ReceiverPhysicalInstallation, error)
```

`physical.RegistrarPhysicalSource.observe` deliberately always returns
`OUTPUT_FENCE_UNPROVEN`. There is no enable flag or evidence dictionary that
converts CPU observations into the frozen positive installation object. The
interface is available for assembly review; the positive native implementation
is still required. Do not RPC a Runtime/Guardian JSON receipt into this seam.

## Required Linux installation profile

The following is a deployment design and required acceptance list, **not Linux
execution evidence**. This workstation is Darwin; the Linux test is skipped.
The existing service/drop-in templates remain disabled and insufficient for
production. Agent4's transport currently enforces a same-UID 0700/0600 profile;
changing file modes alone cannot create a cross-UID profile safely. Agent4 must
review a native host broker/launcher using the existing frozen operations and
strict peer pins. Do not weaken its validator or introduce another protocol.

| Resource | Trusted owner / actual enforcement required |
| --- | --- |
| Runtime | Separate non-root UID; no Guardian/CONTROL/secret groups, capabilities, ptrace access, host PID/mount access, general network interface or inherited publishing fd |
| Guardian and Publisher | Supervisor-owned process tree, immutable installed descriptor and Generation, dedicated per-installation cgroup v2, independent native ownership handles |
| Producer IPC | Existing receiver-1 routes only; Runtime-visible AF_UNIX endpoint, kernel peer identity, per-start capability, bounded messages and original frame lineage |
| CONTROL / Authority IPC | Separate supervisor-owned endpoint and identity; absent from Runtime mounts/groups; current same-UID implementation must be consciously assembled rather than made world/group writable |
| RTMP key / socket | Publisher-only secret mount/private fd, no Runtime env/argv/files, target publish listener reachable only from approved Publisher namespace; target API independently verifies no old publisher connection |
| WebRTC Peer | Guardian-owned peer/transceiver/DTLS transport and outbound network; old peer, SCTP and transport handles closed or physically fenced before new Generation opens |
| Registrar PhysicalSource | Separate trusted supervisor capability; reads kernel/cgroup/native bound context and target-side publisher/peer ownership, never a Runtime boolean |
| Stop/restart | Close local gate first, revoke target credentials/connections and kill owned cgroup; require kernel empty + target disconnection + no usable old credentials/sockets before new admission |
| Required sinks | Each actual transport/decoder/required endpoint revalidates original lineage/Stop; independently observed complete terminal PCM/video ranges, not enqueue/packet/Credit counts |

`linux_fence.OwnedCgroup` implements part of this process fence. It checks the
real Linux cgroup-v2 filesystem, creates a fresh child under an explicitly
delegated UID-owned parent, pins attached direct children, refuses unknown
members, writes `cgroup.kill` and requires actual kernel `populated=0`. It never
adopts an existing live group. It does not revoke keys, prove target exclusivity
or certify namespaces. A strict refusal for unknown descendants is intentional;
a future supervised process-tree launcher must register its own descendants.

`runtime_namespace_census` reads actual `/proc` native identities, distinct
Runtime UID, zero capability sets, `NoNewPrivs`, distinct mount/net namespaces,
loopback-only interfaces, CONTROL group exclusion and Guardian secret directory
modes. It returns only a partial kernel census. It does not prove inherited-fd
closure, effective proxy policy, mount reachability, target exclusivity or
credential revocation. Neither helper can enable `RegistrarPhysicalSource`.

An isolated Linux operator may execute only the owned synthetic-child test:

```sh
AG5_OWNED_CGROUP_PARENT=/path/to/dedicated/delegated/cgroup \
PYTHONPATH=runtime:. .venv-guardian/bin/python -m pytest \
  output_guardian/tests/v2/test_physical.py::test_linux_real_owned_cgroup_kill -v
```

This requires a dedicated delegated cgroup-v2 parent with `cgroup.kill`, not a
shared service group. A passing result proves only this owned-process kill.
UID/group ACL, namespace, inherited socket, target publish, old credential,
Guardian SIGKILL/orphan/restart and per-required-sink tests still need independent
Linux execution. No cross-compilation or ordinary fake filesystem counts.

## Positive installation preconditions still missing

Before Agent4 may return the official positive installation, its native source
must independently associate the exact full bootstrap binding with the managed
Guardian and installed Publisher; observe a real closed gate before Stage;
prove all previous publishers/peers/processes fenced at the destination; prove
old credentials and inherited sockets cannot reconnect; and confirm continuing
exclusive ownership on each eligibility read. A missing/unreadable/expired
observation, backend outage, changed pin/Generation or target ownership loss
must refuse. Persisted metadata is denial/reconciliation knowledge, never an
automatic permission to restart a Publisher.

The host launcher also needs durable, supervisor-owned cgroup/namespace/target
ownership recovery after its own crash. The fresh-cgroup helper alone cannot
adopt an unknown old group. Quarantine that Room and reconcile independently;
do not delete tombstones or issue replacement speech for UNKNOWN consumption.

Normal Unit1 Finish leaves the same Session Publisher/codecs and PCM/PTS/Credit
alive for Unit2. An installation observation is not a terminal drain. The CPU
tests compare actual decoded required ranges; their signed business evidence
envelope is explicitly mocked. Production RTMP/AAC buffering and WebRTC terminal
received ranges remain blocked until real registered sink adapters exist.
