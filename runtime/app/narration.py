"""Versioned command adapter; ordinary v1 Speak stays on its original path."""
import asyncio
import hashlib
import json
import logging
import time

from .durability_client import DurableCommands, JournalError, fingerprint, MAX_INTEGER
from .narration_segments import SegmentExecutor, bridge_choice
from .providers import LLMRequest


NARRATION_COMMANDS = {"COMMIT_SEGMENT", "SUSPEND_AT_BOUNDARY", "INVALIDATE_AFTER", "BEGIN_EPOCH",
                      "START_AUDIENCE_ANSWER", "PREPARE_RESUME_BRIDGE", "STOP_NARRATION"}


class NarrationCommands(DurableCommands):
    def _admission_failure(self, command, executor, phase, exc, remaining_ms):
        # Fixed classifications only: never stringify exceptions, command
        # payloads, provider text, authentication or lease tokens.
        run=self.runs.get(command["sessionId"],{})
        prior=getattr(executor,"task",None)
        current=getattr(executor.session,"current_task",None)
        allowed={"LEASE_LOST","RUN_SEALED","STALE_TIMELINE_EPOCH","STALE_GENERATION","COMMAND_CONFLICT","DEPENDENCY_UNAVAILABLE"}
        code=getattr(exc,"code",None)
        code=code if code in allowed else "OTHER"
        if phase=="segment_begin" and isinstance(exc,ValueError):
            if prior is not None and not prior.done():code="BOUNDARY_ACTIVE_SEGMENT"
            elif current is not None and not current.done():code="BOUNDARY_ORDINARY_SPEECH"
        row={"phase":phase,"commandId":command["commandId"],"commandType":command["commandType"],
            "code":code,"errorType":type(exc).__name__ if type(exc).__name__ in {"RuntimeFailure","JournalError","ValueError","ValidationError","RuntimeError","TimeoutError"} else "OTHER",
            "previousTaskDone":None if prior is None else prior.done(),"currentTaskIsPrevious":current is not None and current is prior,
            "runSealed":run.get("sealed") is True,"barrierPending":run.get("barrier_pending") is True,
            "deadlineExpired":time.monotonic()>=run.get("deadline",0),
            "startedRemainingMs":remaining_ms if type(remaining_ms) is int else None}
        logging.getLogger("app").warning("narration_admission_failed %s",json.dumps(row))

    async def execute(self, command):
        from .session import RuntimeFailure
        sid, kind, epoch = command["sessionId"], command["commandType"], command["runEpoch"]
        if kind not in NARRATION_COMMANDS:
            result = await super().execute(command)
            if (kind == "BEGIN_RUN" and sid in self.manager.sessions and not command["payload"].get("fenceOnly")
                    and command["payload"].get("featureFlags", {}).get("continuityEnabled") is True):
                session = self.manager.sessions[sid]
                if not getattr(session, "continuity", None):
                    session.continuity = SegmentExecutor(session, epoch, self.journal, lambda: self.check(sid, epoch))
            return result
        if command.get("schemaVersion") != "0.5" or fingerprint(command) != command.get("requestFingerprint"):
            raise RuntimeFailure("COMMAND_CONFLICT", "Immutable narration command mismatch", 409)
        if type(epoch) is not int or not 1 <= epoch <= MAX_INTEGER:
            raise RuntimeFailure("STALE_RUN_EPOCH", "Invalid epoch", 409)
        async with self.locks.setdefault(sid, asyncio.Lock()):
            self.check(sid, epoch)
            acceptance = await self.journal.accept(command)
            if not acceptance["execute"]:
                return acceptance
            session = self.manager.get_session(sid)
            executor = getattr(session, "continuity", None)
            if executor is None:
                raise RuntimeFailure("DEPENDENCY_UNAVAILABLE", "Segment executor unavailable", 503)
            started_at = time.monotonic()
            started = await self.journal.start(command, acceptance["run"]["leaseToken"])
            if not started["execute"]:
                return started
            self.runs[sid]["deadline"] = time.monotonic() + max(0,
                started["run"]["remainingMs"] / 1000 - (time.monotonic() - started_at) - .1)
            try:
                self.check(sid, epoch)
            except Exception as exc:
                self._admission_failure(command,executor,"post_start_guard",exc,started["run"].get("remainingMs"))
                raise
            if kind == "COMMIT_SEGMENT":
                try:
                    await executor.begin(command, started)
                except Exception as exc:
                    self._admission_failure(command,executor,"segment_begin",exc,started["run"].get("remainingMs"))
                    raise
            elif kind == "SUSPEND_AT_BOUNDARY":
                await executor.suspend(command)
            elif kind == "INVALIDATE_AFTER":
                await executor.invalidate(command)
            elif kind == "BEGIN_EPOCH":
                await executor.begin_epoch(command)
            elif kind in {"START_AUDIENCE_ANSWER", "PREPARE_RESUME_BRIDGE"}:
                task = asyncio.create_task(self._prepare(executor, command), name="narration-language-prepare")
                self.tasks.add(task)
                executor.preparations.add(task)
                task.add_done_callback(self.tasks.discard)
                task.add_done_callback(executor.preparations.discard)
                task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
            elif kind == "STOP_NARRATION":
                executor.fence("STOP_NARRATION")
            return started

    async def _prepare(self, executor, command):
        p, session = command["payload"], executor.session
        try:
            executor.guard(command)
            if command["commandType"] == "START_AUDIENCE_ANSWER":
                text = p.get("answerText")
                if not text:
                    request = LLMRequest(p["question"], session.context.systemPrompt +
                        "只回答当前问题，不扩展新主题，最多两句。只能使用本轮最新事实，缺失时说明无法确认。",
                        json.dumps(p["latestFacts"], ensure_ascii=False))
                    text = ""
                    async with asyncio.timeout(8):
                        async for token in session.llm.stream(request):
                            executor.guard(command)
                            text += token
                            if len(text) > 100:
                                raise ValueError("ANSWER_TOO_LONG: no truncation mid-fact")
                    text = text.strip()
                if not text or text[-1] not in "。！？!?；;.":
                    raise ValueError("INCOMPLETE_ANSWER")
                proof = {"text": text, "productSnapshotHash": p["productSnapshotHash"],
                         "factIds": p.get("factIds", [])}
                operation = "ANSWER_PREPARED"
            else:
                context = dict(p["context"])
                # Refresh required dynamic facts immediately before language
                # generation; Go revalidates product hash and authority at CAS.
                if session.tool_client:
                    facts = await session.tool_client.get_product(context["productId"])
                    context["latestFacts"] = facts
                async with asyncio.timeout(8):
                    choice = await bridge_choice(session.llm, context, p["choices"])
                proof, operation = {"choice": choice}, "RESUME_PREPARED"
            executor.guard(command)
            await executor.timeline.journal.record(operation, command, proof)
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                await executor.timeline.journal.record("UNKNOWN", command,
                    {"reason": "PREPARATION_UNKNOWN", "audienceAudible": False})
            finally:
                executor.fence("PREPARATION_UNKNOWN")
            raise
