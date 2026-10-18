"""Receiver-1 coordinator over injected sole wire / Authority / Registrar ports.

There is deliberately no v1 bind, SQL fallback, ticket cache or process restore.
Public methods take only already authenticated peers from private IPC. All
external calls are outside the gate; their results cannot reopen a lost barrier.
"""

import asyncio
import base64
import copy
import hashlib
import uuid
from dataclasses import dataclass

from output_guardian.model import Closed

from .gate import Budget, Gate, Lineage, require, sent_now
from .ports import BoundedAuthority


def envelope(**fields):
    return dict(
        contractRevision="durable-live-2",
        receiverRevision="receiver-1",
        requestId="req_" + uuid.uuid4().hex,
        **fields,
    )


@dataclass(frozen=True)
class Media:
    lineage: Lineage
    sequence: int
    kind: str
    payload: bytes
    pts_us: int | None
    audio_start: int
    video_frame: int


@dataclass(frozen=True)
class Tail:
    lineage: Lineage
    first_sequence: int
    last_sequence: int
    audio_start: int
    audio_end: int
    video_pts: tuple
    audio_hash: str
    video_hash: str
    first_video_frame: int
    final_video_frame: int


@dataclass(frozen=True)
class ObservedDrain:
    """Trusted in-process Observer result, never accepted from Runtime JSON."""

    tail: Tail
    sinks: frozenset
    evidence: dict


class Receiver:
    def __init__(
        self,
        wire,
        authority,
        installations,
        outputs,
        journal,
        *,
        guardian_principal,
        guardian_incarnation,
        signing_key,
        key_id,
        scope,
        required_sinks,
        sample_rate=16000,
        width=64,
        height=64,
        session_audio_origin=0,
        session_video_origin=-1,
        session_frame_origin=0,
        session_sequence_origin=-1,
    ):
        require(bool(required_sinks) and len(required_sinks) <= 16, "INVALID_ARGUMENT")
        require(
            sample_rate in {16000, 24000, 48000}
            and 2 <= width <= 1920
            and 2 <= height <= 1080,
            "INVALID_ARGUMENT",
        )
        self.wire, self.authority, self.installations = (
            wire,
            BoundedAuthority(wire, authority),
            installations,
        )
        self.outputs, self.journal = outputs, journal
        self.gate = Gate(journal.stops, journal.denied)
        require(
            all(
                type(n) is int and n >= 0
                for n in (session_audio_origin, session_frame_origin)
            ),
            "INVALID_ARGUMENT",
        )
        require(
            type(session_video_origin) is int
            and session_video_origin >= -1
            and type(session_sequence_origin) is int
            and session_sequence_origin >= -1,
            "INVALID_ARGUMENT",
        )
        self.gate.audio_end, self.gate.video_end = (
            session_audio_origin,
            session_video_origin,
        )
        self.gate.video_frames, self.gate.sequence = (
            session_frame_origin,
            session_sequence_origin,
        )
        self.guardian_principal, self.incarnation = (
            guardian_principal,
            guardian_incarnation,
        )
        self.signing_key, self.key_id = signing_key, key_id
        self.scope, self.required_sinks = tuple(scope), frozenset(required_sinks)
        self.sample_rate, self.width, self.height = sample_rate, width, height
        self.staged, self.record, self.references = None, None, None
        self.audit, self.finished = {}, set()
        self.sealed = False
        self.unit_first, self.unit_audio_start = 0, 0
        self.unit_video_start = 0
        self.audio_hash, self.video_hash, self.video_pts = None, None, []
        self.monitor = None

    def _role(self, peer, role):
        require(peer.role == role and tuple(peer.scope) == self.scope, "FORBIDDEN")

    def _validate(self, name, q):
        # Mandatory injected Agent4 codec; not a second schema/DTO implementation.
        self.wire.validate(name, q)

    def _runtime_locked(self, peer):
        self._role(peer, "REGISTERED_RUNTIME")
        require(self.staged is not None, "BOOTSTRAP_REQUIRED")
        require(
            peer.principal_id == self.staged["runtimePrincipalId"]
            and peer.incarnation == self.staged["runtimeIncarnation"],
            "FORBIDDEN",
        )

    def _consume_locked(self, peer, q, captured=None):
        self._runtime_locked(peer)
        if captured is not None:
            self.gate.compare_locked(captured)
        require(self.staged["runId"] not in self.gate.stops, "RUN_STOPPED")
        require(
            not self.gate.poisoned and self.gate.state == "STAGED_CLOSED",
            "CONSUMPTION_UNKNOWN",
        )
        require(self.gate.active is None, "ACTIVE_UNIT_CONFLICT")
        require(
            q["references"]["bootstrapId"] == self.staged["bootstrapId"],
            "BOOTSTRAP_REQUIRED",
        )
        require(
            q["expectedGenerationId"] == self.staged["generationId"],
            "GENERATION_MISMATCH",
        )
        require(
            q["expectedGuardianIncarnation"] == self.incarnation,
            "GUARDIAN_INCARNATION_MISMATCH",
        )

    def _execution_locked(self, peer, q, captured=None):
        self._runtime_locked(peer)
        if captured is not None:
            self.gate.compare_locked(captured)
        lineage = self.gate.active
        require(
            lineage is not None and q["executionId"] == lineage.execution_id,
            "STALE_EXECUTION",
        )
        require(
            q["artifactId"] == lineage.artifact_id
            and q["artifactHash"] == lineage.artifact_hash,
            "ANSWER_CONFLICT",
        )
        require(self.record["channelBinding"] == peer.channel_binding, "FORBIDDEN")
        self.gate.execution_locked(lineage)
        return lineage

    def _snapshot(self, snap, refs, revision, record=None):
        self._validate("ReceiverAuthoritySnapshot", snap)
        r, b = snap["registration"], self.staged
        require(r["state"] == "ACTIVE" and r["binding"] == b, "REGISTRATION_REVOKED")
        require(
            r["registrationHash"] == self.wire.digest(b) and r["revision"] == revision,
            "STATE_CONFLICT",
        )
        require(refs["bootstrapId"] == b["bootstrapId"], "BOOTSTRAP_REQUIRED")
        a, child, grant, permit, obs = (
            snap[k]
            for k in (
                "artifact",
                "artifactRegistration",
                "grant",
                "permit",
                "observation",
            )
        )
        self.wire.validate_artifact(a)
        require(
            child["bindingHash"] == r["registrationHash"]
            and child["bootstrapId"] == b["bootstrapId"],
            "ANSWER_CONFLICT",
        )
        for key in ("artifactId", "artifactHash"):
            require(
                all(row[key] == refs[key] for row in (a, child, grant, permit, obs)),
                "ANSWER_CONFLICT",
            )
        require(
            grant["grantId"] == refs["grantId"]
            and permit["permitId"] == refs["permitId"],
            "ANSWER_CONFLICT",
        )
        require(permit["factObservationId"] == obs["observationId"], "ANSWER_CONFLICT")
        require(
            self.wire.digest(a["factDependencies"]) == obs["factSetHash"]
            and a["productSnapshotVersion"] == obs["productSnapshotVersion"],
            "FACT_EXPIRED",
        )
        for row in (a, child, grant, permit, obs):
            for key, value in b.items():
                if key in row:
                    require(row[key] == value, "ANSWER_CONFLICT")
        for row in (child, grant, permit, obs):
            for key in ("answerId", "sequence"):
                if key in row:
                    require(row[key] == a[key], "ANSWER_CONFLICT")
        if record is not None:
            require(
                snap["consumption"]
                == dict(state="CONSUMED", receiptId=record["receiptId"])
            )
            require(snap["grantState"] == "CONSUMED")
            for row in (a, grant, permit, obs):
                for key, value in record["binding"].items():
                    if key in row:
                        require(row[key] == value, "ANSWER_CONFLICT")

    async def stage(self, peer, q):
        self._validate("ReceiverStageRequest", q)
        self._role(peer, "CONTROL_REGISTRAR")
        b = copy.deepcopy(q["binding"])
        require(
            tuple(b[k] for k in ("tenantId", "ownerId", "roomId")) == self.scope,
            "FORBIDDEN",
        )
        require(
            b["guardianIncarnation"] == self.incarnation,
            "GUARDIAN_INCARNATION_MISMATCH",
        )
        descriptor = self.wire.canonical(b)
        with self.gate.lock:
            captured = self.gate.capture_locked()
            require(b["runId"] not in self.gate.stops, "RUN_STOPPED")
            require(
                self.gate.state in {"FENCED", "STAGED_CLOSED"}
                and self.gate.active is None,
                "ACTIVE_UNIT_CONFLICT",
            )
        observed = await self.installations.read(
            envelope(
                physicalInstallProofRef=b["physicalInstallProofRef"],
                expectedBindingHash=self.wire.digest(b),
            )
        )
        self._validate("ReadReceiverPhysicalInstallationResponse", observed)
        install = observed["installation"]
        require(
            install["binding"] == b
            and install["guardianPrincipalId"] == self.guardian_principal,
            "OUTPUT_FENCE_UNPROVEN",
        )
        require(bool(install["closedFenceProofRef"]), "OUTPUT_FENCE_UNPROVEN")
        receipt = dict(
            contractRevision="durable-live-2",
            receiverRevision="receiver-1",
            stageReceiptId="stage_" + uuid.uuid4().hex,
            installationRevision=install["installationRevision"],
            challenge=q["challenge"],
            guardianPrincipalId=self.guardian_principal,
            guardianIncarnation=self.incarnation,
            keyId=self.key_id,
            bindingHash=self.wire.digest(b),
            authorityIssuedAt=q["challengeIssuedAt"],
            validUntil=q["challengeExpiresAt"],
            state="CLOSED_STAGED",
        )
        receipt["signature"] = base64.b64encode(
            self.signing_key.sign(self.wire.canonical(receipt))
        ).decode()
        try:
            await asyncio.to_thread(self.journal.append, "run", b["runId"])
        except BaseException:
            with self.gate.lock:
                self.gate.unknown_locked()
            raise Closed() from None
        with self.gate.lock:
            self.gate.compare_locked(captured)
            self.gate.stage_locked(b["runId"], descriptor)
            self.staged = b
            return dict(requestId=q["requestId"], receipt=receipt)

    async def consume(self, peer, q):
        self._validate("ReceiverConsumeRequest", q)
        q = copy.deepcopy(q)
        with self.gate.lock:
            self._consume_locked(peer, q)
            captured = self.gate.capture_locked()
            grant = q["references"]["grantId"]
            require(grant not in self.gate.denied)
            # Reserve locally before any await. A failed/ambiguous attempt is
            # never retried for execution, even when no ACK is available.
            self.gate.denied.add(grant)
            self.audit[grant] = "UNKNOWN"
        try:
            # Existing closed output fixtures have no codec startup phase.
            # Real CPU adapters independently complete their native READY edge
            # before any Authority query; this never extends a Grant/proof.
            check_ready = getattr(self.outputs, "check_ready", None)
            if check_ready is not None:
                check_ready()
            with self.gate.lock:
                self._consume_locked(peer, q, captured)
            snap = await self.authority.query_receiver_authority(
                envelope(references=copy.deepcopy(q["references"]))
            )
            self._snapshot(
                snap["snapshot"], q["references"], q["expectedRegistrationRevision"]
            )
            with self.gate.lock:
                self._consume_locked(peer, q, captured)
            request = envelope(
                consumeTicket=q["consumeTicket"],
                references=copy.deepcopy(q["references"]),
                consumeRequestId=q["consumeRequestId"],
                runtimeIncarnation=peer.incarnation,
                runtimePrincipalId=peer.principal_id,
                channelBinding=peer.channel_binding,
                expectedRegistrationRevision=q["expectedRegistrationRevision"],
            )
            sent = sent_now()
            out = copy.deepcopy(await self.authority.commit_receiver_consume(request))
            self._validate("CommitReceiverConsumeResponse", out)
            # Nothing persists request/ticket, including a generic response cache.
            del request
            with self.gate.lock:
                self._consume_locked(peer, q, captured)
            if not out["consumeAuthorized"]:
                return dict(out, requestId=q["requestId"])
            record = out["consumption"]
            self._validate("ReceiverConsumption", record)
            require(
                record["runtimePrincipalId"] == peer.principal_id
                and record["runtimeIncarnation"] == peer.incarnation
                and record["channelBinding"] == peer.channel_binding,
                "FORBIDDEN",
            )
            require(
                record["guardianPrincipalId"] == self.guardian_principal
                and record["bootstrapId"] == self.staged["bootstrapId"]
            )
            require(
                record["registrationHash"] == self.wire.digest(self.staged)
                and record["registrationRevision"] == q["expectedRegistrationRevision"]
            )
            require(
                record["consumeRequestId"] == q["consumeRequestId"]
                and record["binding"]["grantId"] == grant
            )
            for key, value in self.staged.items():
                if key in record["binding"]:
                    require(record["binding"][key] == value, "ANSWER_CONFLICT")
            for key in ("artifactId", "artifactHash"):
                require(
                    record["binding"][key] == q["references"][key], "ANSWER_CONFLICT"
                )
            initial = Budget.received(out["consumeTiming"], sent, grant=True)
            await asyncio.to_thread(
                self.journal.append,
                "consume",
                self.staged["runId"],
                grant,
                record["receiptId"],
            )
            with self.gate.lock:
                self._consume_locked(peer, q, captured)
            sent = sent_now()
            final = await self.authority.query_receiver_authority(
                envelope(references=copy.deepcopy(q["references"]))
            )
            proof = Budget.received(final["snapshot"]["timing"], sent)
            self._snapshot(
                final["snapshot"],
                q["references"],
                record["registrationRevision"],
                record,
            )
            lineage = Lineage(
                self.staged["runId"],
                record["binding"]["executionId"],
                record["binding"]["artifactId"],
                record["binding"]["artifactHash"],
                self.wire.canonical(dict(registration=self.staged, consumption=record)),
                captured[0],
            )
            with self.gate.lock:
                self._consume_locked(peer, q, captured)
                initial.check()
                proof.check()
                require(len(self.gate.acks) < self.gate.capacity, "OVERLOADED")
                remaining = min(initial.remaining(), proof.remaining())
                ack = dict(
                    out,
                    requestId=q["requestId"],
                    consumeTiming=dict(
                        remainingGrantMs=remaining,
                        remainingProofMs=remaining,
                        safetyMarginMs=100,
                    ),
                )
                self.gate.edge.arm_locked(lineage, proof)
                self.gate.active, self.gate.state = lineage, "ACTIVE_UNIT"
                self.record, self.references = record, copy.deepcopy(q["references"])
                self.unit_first, self.unit_audio_start = (
                    self.gate.sequence + 1,
                    self.gate.audio_end,
                )
                self.unit_video_start = self.gate.video_frames
                self.audio_hash, self.video_hash, self.video_pts = (
                    hashlib.sha256(),
                    hashlib.sha256(),
                    [],
                )
                self.sealed = False
                self.gate.acks.append(
                    (lineage, ack, initial)
                )  # bounded first-ACK acceptance
                self.audit[grant] = "CONSUMED"
                self.gate.accepted.append(
                    ("ACK", self.gate.revision, lineage.execution_id)
                )
                return ack
        except BaseException:
            # Latch may have committed even if its response was lost. Retain
            # denial and close executable state; metadata can only say UNKNOWN.
            with self.gate.lock:
                self.audit[grant] = "UNKNOWN"
                if self.gate.capture_locked() == captured:
                    self.gate.unknown_locked()
            try:
                await asyncio.to_thread(
                    self.journal.append, "consume", self.staged["runId"], grant
                )
            except BaseException:
                pass  # durable staged Run still quarantines a later restart
            raise Closed("CONSUMPTION_UNKNOWN") from None

    async def renew(self, peer, q):
        self._validate("ReceiverRenewRequest", q)
        with self.gate.lock:
            lineage = self._execution_locked(peer, q)
            captured, record = self.gate.capture_locked(), copy.deepcopy(self.record)
            refs = dict(self.references, permitId=q["permitId"])
        sent = sent_now()
        out = await self.authority.query_receiver_authority(envelope(references=refs))
        proof = Budget.received(out["snapshot"]["timing"], sent)
        self._snapshot(out["snapshot"], refs, record["registrationRevision"], record)
        with self.gate.lock:
            self._execution_locked(peer, q, captured)
            self.gate.edge.arm_locked(lineage, proof)
            self.references = refs
            self.gate.accepted.append(
                ("RENEW", self.gate.revision, lineage.execution_id)
            )
            return dict(
                requestId=q["requestId"],
                state="PROOF_UPDATED",
                permit=out["snapshot"]["permit"],
                observation=out["snapshot"]["observation"],
                timing=dict(
                    remainingGrantMs=0,
                    remainingProofMs=proof.remaining(),
                    safetyMarginMs=100,
                ),
            )

    async def media(self, peer, q):
        self._validate("ReceiverMediaRequest", q)
        # Existing proof is the bounded local cache; no blocking SQL/RPC per
        # frame. Renew independently reads fresh same-identity proofs.
        try:
            payload = base64.b64decode(q["payload"], validate=True)
        except (ValueError, TypeError):
            raise Closed("INVALID_ARGUMENT") from None
        require(0 < len(payload) <= 9 * 1024 * 1024, "INVALID_ARGUMENT")
        if q["kind"] == "audio":
            require(
                len(payload) % 2 == 0 and len(payload) <= self.sample_rate * 2,
                "INVALID_ARGUMENT",
            )
        else:
            require(
                len(payload) == self.width * self.height * 3
                and type(q["ptsUs"]) is int,
                "INVALID_ARGUMENT",
            )
        with self.gate.lock:
            lineage = self._execution_locked(peer, q)
            captured = self.gate.capture_locked()
            ordinal = self.gate.sequence
            digest = (
                self.audio_hash if q["kind"] == "audio" else self.video_hash
            ).copy()
        # Potentially large hashing is outside the short gate. A concurrent
        # Stop/Finish/other media invalidates this reservation before handoff.
        digest.update(payload)
        with self.gate.lock:
            self._execution_locked(peer, q, captured)
            require(self.gate.sequence == ordinal, "BOUNDARY_CONFLICT")
            require(not self.sealed, "STALE_EXECUTION")
            require(q["permitId"] == self.references["permitId"], "LEASE_LOST")
            require(q["sequence"] == self.gate.sequence + 1, "BOUNDARY_CONFLICT")
            require(
                q["kind"] != "audio"
                or q["ptsUs"] is None
                or q["ptsUs"] == self.gate.audio_end * 1000000 // self.sample_rate,
                "BOUNDARY_CONFLICT",
            )
            require(len(self.gate.media) < self.gate.capacity, "OVERLOADED")
            require(
                len(self.video_pts) < 2048,
                "OVERLOADED",
            )
            require(
                q["kind"] != "audio"
                or self.gate.audio_end - self.unit_audio_start + len(payload) // 2
                <= self.sample_rate * 60,
                "OVERLOADED",
            )
            require(
                q["kind"] != "video" or q["ptsUs"] > self.gate.video_end,
                "BOUNDARY_CONFLICT",
            )
            item = Media(
                lineage,
                q["sequence"],
                q["kind"],
                payload,
                q["ptsUs"],
                self.gate.audio_end,
                self.gate.video_frames,
            )
            self.gate.media.append(item)
            self.gate.sequence = q["sequence"]
            if q["kind"] == "audio":
                self.gate.audio_end += len(payload) // 2
                self.audio_hash = digest
            else:
                self.gate.video_end = q["ptsUs"]
                self.gate.video_frames += 1
                self.video_pts.append(q["ptsUs"])
                self.video_hash = digest
            self.gate.accepted.append(
                ("MEDIA", self.gate.revision, lineage.execution_id)
            )
            return dict(requestId=q["requestId"], accepted=True)

    async def finish(self, peer, q):
        self._validate("ReceiverFinishUnitRequest", q)
        with self.gate.lock:
            lineage = self._execution_locked(peer, q)
            require(not self.sealed and self.gate.sequence >= self.unit_first)
            self.sealed = True
            captured = self.gate.capture_locked()
            tail = Tail(
                lineage,
                self.unit_first,
                self.gate.sequence,
                self.unit_audio_start,
                self.gate.audio_end,
                tuple(self.video_pts),
                self.audio_hash.hexdigest(),
                self.video_hash.hexdigest(),
                self.unit_video_start,
                self.gate.video_frames - 1,
            )
        try:
            observed = await self.outputs.observe(lineage, tail)
            require(
                isinstance(observed, ObservedDrain)
                and observed.tail == tail
                and observed.sinks == self.required_sinks,
                "EVIDENCE_CONFLICT",
            )
            self._validate("Evidence", observed.evidence)
            require(
                tail.audio_end > tail.audio_start and bool(tail.video_pts),
                "EVIDENCE_CONFLICT",
            )
            require(
                observed.evidence["evidenceType"] == "ALL_REQUIRED_DRAIN"
                and frozenset(observed.evidence["requiredSinks"])
                == self.required_sinks,
                "EVIDENCE_CONFLICT",
            )
            proofs = observed.evidence["sinkProofs"]
            require(
                len(proofs) == len(self.required_sinks)
                and {p["sinkId"] for p in proofs} == self.required_sinks,
                "EVIDENCE_CONFLICT",
            )
            for proof in proofs:
                require(
                    proof["terminal"]
                    and proof["generationId"] == self.staged["generationId"],
                    "EVIDENCE_CONFLICT",
                )
                require(
                    proof["firstAudioSample"] == tail.audio_start
                    and proof["finalAudioSampleExclusive"] == tail.audio_end
                    and proof["audioConsumedThroughExclusive"] >= tail.audio_end,
                    "EVIDENCE_CONFLICT",
                )
                require(
                    proof["finalVideoFrame"] == tail.final_video_frame
                    and proof["videoConsumedThroughFrame"] >= tail.final_video_frame,
                    "EVIDENCE_CONFLICT",
                )
            with self.gate.lock:
                self._execution_locked(peer, q, captured)
                self.gate.finish_locked(lineage)
                self.finished.add(lineage.execution_id)
                self.audit[self.record["binding"]["grantId"]] = "DRAINED"
                return dict(
                    requestId=q["requestId"],
                    state="LOCAL_MEDIA_DRAINED",
                    executionId=lineage.execution_id,
                    artifactId=lineage.artifact_id,
                    artifactHash=lineage.artifact_hash,
                    evidence=observed.evidence,
                )
        except BaseException:
            with self.gate.lock:
                if self.gate.capture_locked() == captured:
                    self.gate.unknown_locked()
            raise Closed("CONSUMPTION_UNKNOWN") from None

    async def query(self, peer, q):
        self._validate("ReceiverQueryConsumptionRequest", q)
        with self.gate.lock:
            self._runtime_locked(peer)
            require(q["bootstrapId"] == self.staged["bootstrapId"], "FORBIDDEN")
        out = copy.deepcopy(
            await self.authority.query_receiver_consumption(
                envelope(bootstrapId=q["bootstrapId"], grantId=q["grantId"])
            )
        )
        self._validate("QueryReceiverConsumptionResponse", out)
        with self.gate.lock:
            if self.audit.get(q["grantId"]) not in {"CONSUMED", "DRAINED"}:
                out["summary"]["state"] = "UNKNOWN"
            return dict(out, requestId=q["requestId"])

    async def stop(self, peer, q):
        self._validate("ReceiverStopRequest", q)
        self._role(peer, "CONTROL_REGISTRAR")
        try:
            with self.gate.lock:
                affected = self.gate.stop_locked(q["runId"])
                revision = self.gate.revision
                if affected:
                    for grant in self.audit:
                        if self.audit[grant] != "DRAINED":
                            self.audit[grant] = "UNKNOWN"
        except Closed:
            # A SIGKILL lock owner can poison this incarnation. Admission is
            # already permanently denied; cleanup must bypass the broken lock.
            try:
                await asyncio.to_thread(self.journal.append, "stop", q["runId"])
            finally:
                await self.outputs.close()
            raise Closed("OUTPUT_FENCE_UNPROVEN") from None
        persisted, proven = True, True
        try:
            await asyncio.to_thread(self.journal.append, "stop", q["runId"])
        except BaseException:
            persisted = False
        # A disk failure never skips independent physical cleanup.
        try:
            proven = await self.outputs.close() if affected or not persisted else True
        except BaseException:
            proven = False
        with self.gate.lock:
            if not persisted:
                self.gate.unknown_locked()
            elif affected and self.gate.revision == revision:
                self.gate.state = "FENCED" if proven else "UNKNOWN"
                self.gate.poisoned |= not proven
        require(persisted and proven, "OUTPUT_FENCE_UNPROVEN")
        return dict(requestId=q["requestId"], state="CLOSED_FENCED", runId=q["runId"])

    async def restart(self):
        # A process restart must construct a NEW Receiver/incarnation. This
        # method only invalidates the current object; it cannot restage it.
        try:
            with self.gate.lock:
                self.gate.unknown_locked()
        except Closed:
            pass  # poisoned shared mutex: independent output kill must still run
        require(await self.outputs.close(), "OUTPUT_FENCE_UNPROVEN")

    async def watchdog(self):
        try:
            while True:
                await asyncio.sleep(0.005)
                expired = False
                with self.gate.lock:
                    expired = self.gate.state == "UNKNOWN"
                    if self.gate.active is not None:
                        try:
                            self.gate.execution_locked(self.gate.active)
                        except Closed:
                            self.gate.unknown_locked()
                            expired = True
                if expired:
                    await self.outputs.close()
        finally:
            await self.restart()
