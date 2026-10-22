"""Runtime-side answer stream coordinator (option 1: the Runtime owns the flow).

Port of the Agent3 Go coordinator state machine
(backend/internal/turnmanager/answerstream/coordinator.go) onto the Runtime's
real transports: JournalClient (RUNTIME_JOURNAL) and ReceiverRuntime
(REGISTERED_RUNTIME at Guardian). Rules kept verbatim:

* at most two undrained units (one active + one lookahead); no new Prepare
  while the newest unit is still PREPARED/STARTING;
* only Prepare may be retried after an uncertain receipt, with the SAME
  immutable Artifact and idempotency key;
* START (unit 1) / continuation (later units) only after the predecessor is
  DRAINED; START + consume + once-TTS failures are terminal UNKNOWN;
* drain requires the Guardian's registered evidence AND Backend confirmation;
* seal only at a genuine source EOF; business completion stays with CONTROL;
* Stop is irreversible and never resumed from memory.

Importing this module opens no socket and grants nothing.
"""

import asyncio
import hashlib
import secrets

from astralive_contracts import durable_live_v2 as dto

from .journal_client import JournalRefused, JournalUnknown

PREPARED, STARTING, PLAYING, DRAINING, DRAINED = (
    "PREPARED",
    "STARTING",
    "PLAYING",
    "DRAINING",
    "DRAINED",
)


class CoordinatorError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PrepareUncertain(CoordinatorError):
    def __init__(self):
        super().__init__("PREPARE_RECEIPT_UNCERTAIN")


def request_id():
    return "req_" + secrets.token_hex(16)


class JournalExecutor:
    """Executor seam implemented with the Runtime's own credentials.

    ``command`` holds the trusted command/Attempt context and the registered
    bootstrap. ``synthesize(text)`` is the single TTS invocation and must
    return media items ``(kind, payload, pts_us)`` already produced for that
    text; they are submitted under the unit's lineage captured at consume.
    """

    def __init__(self, journal, receiver, command, synthesize, *, renew_every=8):
        self.journal, self.receiver, self.command = journal, receiver, dict(command)
        self.synthesize, self.renew_every = synthesize, renew_every
        self.inbox_revision = command["expectedInboxRevision"]
        self.answer_revision = command["expectedAnswerRevision"]
        self._lock = asyncio.Lock()  # one writer: no self-inflicted CAS races
        self.permits, self.executions, self.receipts = {}, {}, {}
        self.answer_id = None

    async def _refresh(self):
        """Read current revisions; other actors (Guardian's consume commit)
        legitimately advance them. Read-only, grants nothing."""
        if self.answer_id is None:
            return
        out, _ = await self.journal.call(
            "JournalQueryAnswer", self._base(answerId=self.answer_id)
        )
        self.inbox_revision = out["answer"]["inboxRevision"]
        self.answer_revision = out["answer"]["answerRevision"]

    async def _idempotent(self, operation, build):
        """Revision-guarded write with a stable idempotency key: one refresh
        and one identical retry on STATE_CONFLICT. Never used for START."""
        await self._refresh()
        try:
            return (await self.journal.call(operation, build()))[0]
        except JournalRefused as exc:
            if exc.code != "STATE_CONFLICT":
                raise
        await self._refresh()
        return (await self.journal.call(operation, build()))[0]

    def _base(self, **extra):
        c = self.command
        return dict(
            schemaVersion="0.5",
            contractRevision="durable-live-2",
            requestId=request_id(),
            tenantId=c["tenantId"],
            ownerId=c["ownerId"],
            runId=c["runId"],
            commandId=c["commandId"],
            attemptId=c["attemptId"],
            sessionId=c["sessionId"],
            runEpoch=c["runEpoch"],
            producerIncarnation=c["producerIncarnation"],
            requestHash=c["requestHash"],
            **extra,
        )

    async def check(self, artifact):
        self.receiver.wire.validate_artifact(artifact)
        c = self.command
        for key in (
            "tenantId",
            "ownerId",
            "runId",
            "commandId",
            "attemptId",
            "sessionId",
        ):
            if artifact[key] != c[key]:
                raise CoordinatorError("ANSWER_CONFLICT")

    async def prepare(self, artifact):
        async with self._lock:

            def build():
                return self._base(
                    artifact=artifact,
                    idempotencyKey="unit:" + artifact["artifactId"],
                    expectedInboxRevision=self.inbox_revision,
                    expectedAnswerRevision=self.answer_revision,
                )

            try:
                out = await self._idempotent("JournalPrepareAnswer", build)
            except JournalUnknown:
                raise PrepareUncertain() from None
            self.answer_id = artifact["answerId"]
            if out["artifactHash"] != artifact["artifactHash"] or not out["prepared"]:
                raise CoordinatorError("ANSWER_CONFLICT")
            self.inbox_revision, self.answer_revision = (
                out["inboxRevision"],
                out["answerRevision"],
            )
            self.receipts[artifact["artifactId"]] = out["receiptId"]

    async def start(self, artifact, first):
        async with self._lock:
            await self._refresh()  # read-only; the START itself is never retried
            c = self.command
            permit, _ = await self.journal.call(
                "AcquireOutputPermit",
                {
                    "schemaVersion": "0.5",
                    "contractRevision": "durable-live-2",
                    "requestId": request_id(),
                    "tenantId": c["tenantId"],
                    "ownerId": c["ownerId"],
                    "runId": c["runId"],
                    "sessionId": c["sessionId"],
                    "runEpoch": c["runEpoch"],
                    "producerIncarnation": c["producerIncarnation"],
                    "guardianId": c["guardianId"],
                    "answerArtifactId": artifact["artifactId"],
                },
            )
            if first:
                out, sent = await self.journal.call(
                    "JournalStart",
                    self._base(
                        permitId=permit["permitId"],
                        expectedInboxRevision=self.inbox_revision,
                        answerArtifactId=artifact["artifactId"],
                        answerArtifactHash=artifact["artifactHash"],
                        expectedAnswerRevision=self.answer_revision,
                    ),
                )
                grant = out["answerGrant"]
                self.inbox_revision = out["revision"]
            else:
                out, sent = await self.journal.call(
                    "JournalStartAnswerSegment",
                    self._base(
                        answerId=artifact["answerId"],
                        artifactId=artifact["artifactId"],
                        artifactHash=artifact["artifactHash"],
                        expectedAnswerRevision=self.answer_revision,
                        permitId=permit["permitId"],
                    ),
                )
                grant = out["grant"]
                self.answer_revision = out["answerRevision"]
            self.receiver.remember_start(grant, out, sent)
            self.permits[artifact["artifactId"]] = (grant, permit)

    async def consume_once(self, artifact):
        grant, permit = self.permits[artifact["artifactId"]]
        refs = {
            "bootstrapId": self.command["bootstrapId"],
            "artifactId": artifact["artifactId"],
            "artifactHash": artifact["artifactHash"],
            "grantId": grant["grantId"],
            "permitId": permit["permitId"],
        }
        execution = await self.receiver.consume(
            self.command["registration"], refs, artifact
        )
        lineage = self.receiver.submit(execution)  # owner fixed at submission
        self.executions[artifact["artifactId"]] = (execution, lineage)
        media = await self.receiver.speak_once(execution, artifact, self.synthesize)
        for n, (kind, payload, pts) in enumerate(media):
            if n and n % self.renew_every == 0:
                await self.receiver.renew(lineage, permit["permitId"])
            await self.receiver.media(lineage, permit["permitId"], kind, payload, pts)

    async def confirm_drain(self, artifact):
        _, lineage = self.executions[artifact["artifactId"]]
        evidence = await self.receiver.finish(lineage)  # registered Observer proof
        async with self._lock:
            out = await self._idempotent(
                "JournalConfirmAnswerSegment",
                lambda: self._base(
                    answerId=artifact["answerId"],
                    artifactId=artifact["artifactId"],
                    artifactHash=artifact["artifactHash"],
                    expectedAnswerRevision=self.answer_revision,
                    idempotencyKey="drain:" + artifact["artifactId"],
                    evidence=evidence,
                ),
            )
            if out["artifactHash"] != artifact["artifactHash"]:
                raise CoordinatorError("EVIDENCE_CONFLICT")
            self.answer_revision = out["answerRevision"]

    async def seal(self, artifacts):
        manifest = [
            {k: a[k] for k in ("artifactId", "sequence", "artifactHash")}
            for a in artifacts
        ]
        text = "".join(a["answerText"] for a in artifacts)
        async with self._lock:
            out = await self._idempotent(
                "JournalSealAnswer",
                lambda: self._base(
                    answerId=artifacts[0]["answerId"],
                    expectedAnswerRevision=self.answer_revision,
                    idempotencyKey="seal:" + artifacts[0]["answerId"],
                    sequenceCount=len(artifacts),
                    finalAnswerTextHash=hashlib.sha256(
                        text.encode("utf-8")
                    ).hexdigest(),
                    manifestHash=dto.digest(manifest),
                ),
            )
            self.answer_revision = out["answerRevision"]
            return out


class AnswerCoordinator:
    """One already admitted COMMENT answer; units come from ``source``.

    ``source`` is an async iterator of complete, hash-verified AnswerArtifact
    documents (segmentation/LLM lives outside this class). No worker task is
    spawned; the caller drives prepare_next / start_next / drain.
    """

    def __init__(self, source, executor):
        self.source, self.executor = source, executor
        self.entries = []  # [artifact, phase]
        self.retry = None
        self.preparing = self.sealed = False
        self.terminal = None
        self.uncertain = False
        self.seal_receipt = None

    def _live(self):
        if self.terminal is not None:
            raise CoordinatorError(self.terminal)

    def _abort(self, exc):
        if self.terminal is None:
            self.terminal = "ANSWER_UNKNOWN"
        self.uncertain = True
        raise CoordinatorError(self.terminal) from exc

    def stop(self):
        """Irreversible local Stop; Backend/Guardian Stop are orchestrated by
        the caller's existing Stop path. No resume from memory."""
        if any(phase in (STARTING, PLAYING, DRAINING) for _, phase in self.entries):
            self.uncertain = True
        self.terminal = "RUN_STOPPED"

    async def prepare_next(self):
        """Return True when a unit was prepared, False at sealed EOF."""
        self._live()
        if self.sealed:
            return False
        if self.preparing:
            raise CoordinatorError("ANSWER_OPERATION_IN_FLIGHT")
        undrained = sum(phase != DRAINED for _, phase in self.entries)
        if self.retry is None and (
            undrained >= 2
            or (self.entries and self.entries[-1][1] in (PREPARED, STARTING))
        ):
            raise CoordinatorError("ANSWER_WINDOW_FULL")
        self.preparing = True
        try:
            artifact = self.retry
            if artifact is None:
                try:
                    artifact = await self.source.__anext__()
                except StopAsyncIteration:
                    artifacts = [a for a, _ in self.entries]
                    if not artifacts:
                        self._abort(CoordinatorError("ANSWER_EMPTY"))
                    self._live()
                    try:
                        self.seal_receipt = await self.executor.seal(artifacts)
                    except Exception as exc:  # noqa: BLE001 - any doubt is UNKNOWN
                        self._abort(exc)
                    self._live()
                    self.sealed = True
                    return False
                self.retry = artifact
            self._live()
            try:
                await self.executor.check(artifact)
            except Exception as exc:  # noqa: BLE001 - any doubt is UNKNOWN
                self._abort(exc)
            self._live()
            try:
                await self.executor.prepare(artifact)
            except PrepareUncertain:
                self._live()
                raise
            except Exception as exc:  # noqa: BLE001 - any doubt is UNKNOWN
                self._abort(exc)
            self._live()
            self.entries.append([artifact, PREPARED])
            self.retry = None
            return True
        finally:
            self.preparing = False

    async def start_next(self):
        self._live()
        index = next(
            (n for n, (_, phase) in enumerate(self.entries) if phase == PREPARED), -1
        )
        if index < 0 or (index > 0 and self.entries[index - 1][1] != DRAINED):
            raise CoordinatorError("ANSWER_PREDECESSOR_NOT_DRAINED")
        artifact = self.entries[index][0]
        self.entries[index][1] = STARTING
        try:
            await self.executor.check(artifact)
            self._live()
            await self.executor.start(artifact, first=index == 0)
            self._live()
            await self.executor.consume_once(artifact)
        except CoordinatorError as exc:
            if exc.code == "RUN_STOPPED":
                raise
            self._abort(exc)
        except Exception as exc:  # noqa: BLE001 - any doubt is UNKNOWN
            self._abort(exc)
        self._live()
        self.entries[index][1] = PLAYING

    async def drain(self):
        self._live()
        index = next(
            (n for n, (_, phase) in enumerate(self.entries) if phase == PLAYING), -1
        )
        if index < 0:
            raise CoordinatorError("ANSWER_PREDECESSOR_NOT_DRAINED")
        artifact = self.entries[index][0]
        self.entries[index][1] = DRAINING
        try:
            await self.executor.confirm_drain(artifact)
        except Exception as exc:  # noqa: BLE001 - any doubt is UNKNOWN
            self._abort(exc)
        self._live()
        self.entries[index][1] = DRAINED

    def view(self):
        return {
            "prepared": len(self.entries),
            "drained": sum(phase == DRAINED for _, phase in self.entries),
            "sealed": self.sealed,
            "stopped": self.terminal == "RUN_STOPPED",
            "unknown": self.uncertain or self.terminal == "ANSWER_UNKNOWN",
            "preparing": self.preparing,
        }
