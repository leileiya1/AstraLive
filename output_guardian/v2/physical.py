"""Read-only physical evidence seams for a TRUSTED Registrar supervisor.

No public route, enrollment or replacement Authority protocol. The CPU reader
below proves a native installed CPU context, never RTMP/WebRTC isolation. Its
result cannot be converted into a production ReceiverPhysicalInstallation.
Agent4's Go PhysicalSource needs an independent host-side reader plus verified
Linux/output-target enforcement before it may issue that frozen object.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

import psutil

from runtime.app.receiver1.transport import ProcessIdentity, identity
from runtime.app.receiver1.wire import GuardianWire

from .gate import require


@dataclass(frozen=True)
class PublisherObservation:
    binding_hash: str
    publisher: ProcessIdentity
    guardian: ProcessIdentity
    runtime: ProcessIdentity
    generation: int
    origins: tuple
    installation_nonce: str
    closed_barrier_revision: int
    profile: str = "CPU_PCM_FFV1_ONLY"


class IndependentPhysicalReader(Protocol):
    """Host-supervisor capability, not a Runtime/Guardian response dictionary.

    Its implementation must own the native control handles, observe immutable
    installed descriptor/Generation, old-resource fencing and current exclusive
    ownership independently. A current_slot, JSON receipt, PID alive boolean or
    a database row alone is not this source. No default-success implementation.
    """

    async def read_installed(
        self, binding, runtime: ProcessIdentity, guardian: ProcessIdentity
    ): ...


class CPUInstallationReader:
    """Concrete CPU resource collector. Trusted local supervisor use ONLY.

    A native child ACK is tied to the exact installed official binding, PID and
    startup challenge. Kernel process birth/UID/parent and shared physical gate
    are separately checked. Same-UID Darwin observations cannot certify host
    isolation; all production export attempts refuse. Never trust this object's
    serialized data from Runtime, nor store it as a replayable capability.
    """

    def __init__(self, publisher, runtime, guardian, *, retired_publishers=()):
        require(
            isinstance(runtime, ProcessIdentity)
            and isinstance(guardian, ProcessIdentity)
        )
        self.publisher, self.runtime, self.guardian = publisher, runtime, guardian
        self.retired = tuple(retired_publishers)
        require(all(isinstance(p, ProcessIdentity) for p in self.retired))
        self.record = None
        self.wire = GuardianWire()

    def _native(self):
        require(identity(self.runtime.pid) == self.runtime, "UNAUTHENTICATED")
        require(identity(self.guardian.pid) == self.guardian, "UNAUTHENTICATED")
        child = self.publisher.process
        require(child is not None and child.is_alive(), "OUTPUT_FENCE_UNPROVEN")
        native = identity(child.pid)
        require(
            psutil.Process(native.pid).ppid() == self.guardian.pid
            and native.uid == self.guardian.uid
        )
        for old in self.retired:
            try:
                process = psutil.Process(old.pid)
                same_live_process = (
                    process.status() != psutil.STATUS_ZOMBIE
                    and identity(old.pid) == old
                )
            except psutil.NoSuchProcess:
                same_live_process = False
            require(not same_live_process, "OUTPUT_FENCE_UNPROVEN")
        return native

    def capture_closed(self, binding):
        self.wire.validate("ReceiverBootstrapBinding", binding)
        self.publisher.check_ready()
        native = self._native()
        raw, ack = self.wire.canonical(binding), self.publisher.readiness
        digest = hashlib.sha256(raw).hexdigest()
        require(
            self.publisher.installed_binding == raw and ack["bindingHash"] == digest
        )
        require(ack["pid"] == native.pid and ack["parent"] == self.guardian.pid)
        require(
            ack["generation"] == binding["generationId"] and len(ack["nonce"]) == 64
        )
        gate = self.publisher.gate
        with gate.lock:
            require(
                gate.state in {"FENCED", "STAGED_CLOSED"}
                and gate.active is None
                and not gate.poisoned
            )
            require(not any(gate.edge.tag) and not any(gate.edge.deadlines))
            require(
                binding["runId"] not in gate.stops and not gate.media and not gate.acks
            )
            require(
                tuple(ack["origins"])
                == (gate.audio_end, gate.video_end, gate.video_frames, gate.sequence)
            )
            require(gate.registration is None or gate.registration == raw)
            observation = PublisherObservation(
                digest,
                native,
                self.guardian,
                self.runtime,
                binding["generationId"],
                tuple(ack["origins"]),
                ack["nonce"],
                gate.revision,
            )
            require(self.record is None or self.record == observation, "STATE_CONFLICT")
            self.record = observation
        require(self._native() == native)
        return observation

    async def read_installed(self, binding, runtime, guardian):
        require(
            runtime == self.runtime and guardian == self.guardian, "UNAUTHENTICATED"
        )
        require(self.record is not None and self._native() == self.record.publisher)
        require(self.wire.digest(binding) == self.record.binding_hash)
        require(self.publisher.installed_binding == self.wire.canonical(binding))
        gate = self.publisher.gate
        with gate.lock:
            require(not gate.poisoned and binding["runId"] not in gate.stops)
            if gate.registration is not None:
                require(gate.registration == self.wire.canonical(binding))
            if gate.active is not None:
                require(json.loads(gate.active.identity)["registration"] == binding)
                gate.execution_locked(gate.active)
        # CLOSED_INSTALLED is historical installation provenance. A read must
        # never close an ongoing same-context unit merely to re-observe it.
        return self.record

    def production_installation(self, *_):
        # Same-UID CPU child/fd evidence lacks independent Registrar and Linux
        # publisher/credential/network/required-target isolation. No mock PASS.
        require(False, "OUTPUT_FENCE_UNPROVEN")


class RegistrarPhysicalSource:
    """Safe assembly contract for Agent4's native PhysicalSource adapter.

    This placeholder refuses production observation on every platform. The
    required independent reader / target / Linux controller are identified,
    but no unverifiable evidence flags can turn this into a successful source.
    Agent4 must review a concrete native host assembly, not set a boolean here.
    """

    async def observe(self, binding, runtime, guardian):
        require(False, "OUTPUT_FENCE_UNPROVEN")
