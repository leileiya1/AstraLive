"""Opt-in segment execution. Go/PG owns cursor, turn and fact completion.

READY is complete bounded PCM AND video, not a streaming provider promise.
The old SoulX credit/pose API cannot stage this safely; it fails closed here.
"""
import asyncio
import copy
import hashlib
import json
import os
import logging
from dataclasses import asdict, dataclass, is_dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .durability_client import fingerprint, PostgresTimelineJournal
from .media_timeline import MediaTimeline, MediaIdentity, TimedAudioChunk, TimedVideoFrame
from .models import VoiceConfig
from .providers import GenerationContext, LLMRequest
from .voice_stream import StreamingVoiceAdapter


def enabled():
    if "ASTRALIVE_NARRATION_CONTINUITY_ENABLED" in os.environ:
        raise ValueError("use frozen ASTRALIVE_CONTINUITY_ENABLED; old continuity flag is unsupported")
    value = os.getenv("ASTRALIVE_CONTINUITY_ENABLED", "false").lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError("invalid continuity flag")
    return value in {"true", "1"}


def json_value(value):
    if is_dataclass(value):
        result = json_value(asdict(value))
        if hasattr(value, "ptsUs"):
            result["ptsUs"] = value.ptsUs
        return result
    if isinstance(value, dict):
        return {("/".join(key) if isinstance(key, tuple) else key): json_value(val)
                for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(val) for val in value]
    return value


class SegmentExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=240)
    textHash: str
    factIds: list[str]
    factVersion: str
    productId: str
    productSnapshotHash: str
    utteranceId: str
    attemptId: str
    voice: VoiceConfig
    requiredSinks: list[str] = Field(min_length=1)
    expectedNarrationRevision: StrictInt
    expectedTimelineRevision: StrictInt
    leaseToken: StrictInt
    maxDurationMs: StrictInt = Field(default=8000, ge=1, le=8000)
    beatId: str | None = None
    interactionTurnId: str | None = None


@dataclass(frozen=True)
class ReadyArtifact:
    audio: tuple
    video: tuple
    sample_count: int
    content_hash: str
    video_hash: str
    provenance: str
    stage: object = None
    emitted_video_hash: str | None = None


class TimelineJournal:
    """Calls A's authenticated SQL endpoint; never a memory durability fallback."""
    def __init__(self, client):
        self.client = client
        self.backend = PostgresTimelineJournal(client)

    async def record(self, operation, command, proof):
        return await self.backend.record(operation, command, json_value(proof))


async def stage_segment(session, request, context, guard, max_bytes=160 * 1024 * 1024):
    """One bounded attempt. No sink handoff or semantic completion while staging.

    The stateless per-attempt Lightweight renderer has no shared pose history.
    Native/GPU renderers need an explicitly reviewed immutable staging API.
    """
    from .lightweight_avatar import LightweightAvatarEngine
    from .providers import MockAvatarEngine
    avatar = session.avatar_engine
    if type(avatar) not in (LightweightAvatarEngine, MockAvatarEngine):
        raise RuntimeError("DEPENDENCY_UNAVAILABLE: renderer lacks safe immutable READY staging")
    staged_avatar = copy.copy(avatar)
    staged_avatar.generation_id = context.generation_id
    if isinstance(avatar, LightweightAvatarEngine):
        staged_avatar.audio_us = staged_avatar.next_frame_us = 0
    adapter = StreamingVoiceAdapter(session.tts_provider, request.voice.voiceId)
    audio, video, count, size = [], [], 0, 0
    pcm_hash, video_hash = hashlib.sha256(), hashlib.sha256()
    source = adapter.synthesize_stream(request.text, request.voice, context)
    try:
        async for chunk in source:
            guard()
            count += len(chunk.pcm) // 2
            if count * 1000 > request.maxDurationMs * 16000:
                raise ValueError("SEGMENT_TOO_LONG: replan before commit")
            if chunk.generation_id != context.generation_id:
                raise ValueError("STALE_RUN_EPOCH")
            frames = await staged_avatar.push_audio(chunk)
            guard()
            audio.append(chunk)
            pcm_hash.update(chunk.pcm)
            for frame in frames:
                if frame.generation_id != context.generation_id:
                    raise ValueError("STALE_RUN_EPOCH")
                if video and frame.pts_us <= video[-1].pts_us:
                    raise ValueError("VIDEO_SEQUENCE_GAP")
                video.append(frame)
                video_hash.update(frame.rgb)
                size += len(frame.rgb)
            size += len(chunk.pcm)
            if size > max_bytes:
                raise ValueError("READY_ARTIFACT_BUDGET_EXCEEDED")
    finally:
        await source.aclose()
    if not count or not video or video[0].pts_us != 0:
        raise ValueError("INCOMPLETE_READY_ARTIFACT")
    return ReadyArtifact(tuple(audio), tuple(video), count, "sha256:" + pcm_hash.hexdigest(),
                         "sha256:" + video_hash.hexdigest(),
                         "SIMULATION" if type(avatar) is MockAvatarEngine else "LIGHTWEIGHT_2D")


class SegmentExecutor:
    """Separate control admission and one cancellable media task per Session.

    DurableCommands supplies validated envelopes/STARTED attempts and lease guard.
    Cancellation is accompanied by a publication fence, never used as its proof.
    """
    def __init__(self, session, run_epoch, journal, run_guard, sample_rate=48000):
        self.session, self.journal, self.run_guard = session, journal, run_guard
        self.timeline = MediaTimeline(session.session_id, run_epoch, sample_rate, TimelineJournal(journal))
        self.task = None
        self.command = None
        self.closed = False
        self.current_identity = None
        self.preparations = set()
        self.stale_epoch_frames_dropped = 0
        self.pose_task = None
        output = getattr(session.media_output, "output", session.media_output)
        if not hasattr(output, "bind_timeline"):
            raise RuntimeError("DEPENDENCY_UNAVAILABLE: named Timeline sinks required")
        output.bind_timeline(self.timeline)
        from .soulx_staging import StagingAvatarEngine
        if isinstance(session.avatar_engine, StagingAvatarEngine):
            session.avatar_engine.publication_fence = self.timeline.fence_now

    def fence(self, reason="STOP"):
        self.closed = True
        self.timeline.fence_now(reason)
        if self.task:
            self.task.cancel()
        for task in self.preparations:
            if task is not asyncio.current_task():
                task.cancel()

    def guard(self, command=None, generation=None):
        self.run_guard()
        if self.closed or self.session.state != "LIVE":
            raise ValueError("RUN_SEALED")
        if command and (command["runEpoch"] != self.timeline.run_epoch or
                        command["timelineEpoch"] != self.timeline.epoch):
            raise ValueError("STALE_TIMELINE_EPOCH")
        if generation is not None and generation != self.session.generation_id:
            raise ValueError("STALE_GENERATION")

    async def begin(self, command, attempt):
        self.guard(command)
        if self.task and not self.task.done():
            raise ValueError("BOUNDARY_CONFLICT: one active segment")
        if self.session.current_task is not None and not self.session.current_task.done():
            raise ValueError("BOUNDARY_CONFLICT: ordinary speech active")
        if fingerprint(command) != command["requestFingerprint"]:
            raise ValueError("COMMAND_CONFLICT")
        self.command = copy.deepcopy(command)
        self.task = asyncio.create_task(self._execute_guarded(command, attempt), name="narration-segment")
        self.session.current_task = self.task
        self.task.add_done_callback(self._done)

    def _done(self, task):
        if self.session.current_task is task:
            self.session.current_task = None
        if not task.cancelled() and task.exception() is not None:
            self.timeline.fence_now("SEGMENT_EXECUTION_UNKNOWN")
            # The SQL STARTED marker remains non-replayable; reconcile evidence.

    async def _execute_guarded(self, command, attempt):
        try:
            await self._execute(command, attempt)
        except asyncio.CancelledError:
            self.timeline.fence_now("SEGMENT_CANCELLED_UNKNOWN")
            await self._cancel_staging("FORCE")
            raise
        except Exception:
            self.timeline.fence_now("SEGMENT_EXECUTION_UNKNOWN")
            await self._cancel_staging("FAILED")
            try:
                await self.timeline.journal.record("UNKNOWN", command,
                    {"reason": "SEGMENT_EXECUTION_UNKNOWN", "audienceAudible": False})
            finally:
                self.closed = True
            raise
        finally:
            if self.pose_task:
                self.pose_task.cancel()
                await asyncio.gather(self.pose_task, return_exceptions=True)
                self.pose_task = None

    async def _execute(self, command, attempt):
        request = SegmentExecutionRequest.model_validate(command["payload"])
        if request.textHash != "sha256:" + hashlib.sha256(request.text.encode()).hexdigest():
            raise ValueError("SEGMENT_CONFLICT")
        grant = await self.journal.request("POST", "/media-start", {
            "sessionId": command["sessionId"], "commandId": command["commandId"],
            "producerIncarnation": self.journal.incarnation, "generationFloor": self.session.generation_id})
        generation = grant["generationId"]
        self.session.generation_id = generation
        await self.session.avatar_engine.interrupt(generation)
        await self.session.media_output.interrupt(generation)
        context = GenerationContext(generation, command["traceId"], command["sessionId"], request.utteranceId)
        guard = lambda: self.guard(command, generation)
        from .soulx_staging import StagingAvatarEngine
        staged = isinstance(self.session.avatar_engine, StagingAvatarEngine)
        if staged:
            from .staging_artifact import stage_gpu
            artifact = await stage_gpu(self.session, request, command, context, guard, self.journal)
        else:
            artifact = await stage_segment(self.session, request, context, guard)
        guard()
        start = self.timeline.position(self.timeline.committed_end)
        sample_count = artifact.sample_count * start.sampleRate // 16000
        descriptor = {"sampleCount": sample_count, "sourceSampleCount": artifact.sample_count,
            "sourceSampleRate": 16000, "contentHash": artifact.content_hash,
            "videoHash": artifact.video_hash, "videoFrameCount": len(artifact.video),
            "videoTiming": {"fps": self.session.request.config.fps}, "providerProvenance": artifact.provenance,
            "utteranceId": request.utteranceId, "finalMarker": True, "requiredSinks": request.requiredSinks,
            "factVersion": request.factVersion, "textHash": request.textHash, "factIds": request.factIds}
        if staged:
            descriptor.update(workerEpoch=artifact.stage.identity["workerEpoch"],
                workerGenerationId=artifact.stage.identity["workerGenerationId"],
                stagingDescriptorHash=artifact.stage.descriptor["descriptor_sha256"],
                stagingEmittedVideoHash=artifact.emitted_video_hash,
                stagingDescriptor=artifact.stage.descriptor["descriptor"],
                originalSampleCount=artifact.stage.begin["original_samples"], padSamples=artifact.stage.begin["pad_samples"])
        await self.timeline.journal.record("SEGMENT_READY", command, {
            "attemptId": request.attemptId, "generationId": generation, "descriptor": descriptor})
        guard()
        result = await self.timeline.CommitSegment(command, request.attemptId, generation,
            descriptor, start, self.timeline.revision)
        identity = result["identity"]
        self.current_identity = identity
        guard()
        pose_task = None
        if staged:
            link = self.session.avatar_engine.link
            proof = self._staging_commit_proof(artifact, identity, start, sample_count)
            await link.arm(artifact.stage, proof, guard)
            # Fresh SQL fence after physical arm, immediately before first sink.
            await link.lease_fields(command, request, self.journal, guard)
            guard();link.check(artifact.stage)
            pose_task = asyncio.create_task(self._staging_pose_loop(artifact, identity, proof, guard), name="all-required-staging-pose")
            self.pose_task = pose_task
        def handoff_guard():
            guard()
            if staged:link.check(artifact.stage)
        video_index, source_count = 0, 0
        release_origin = asyncio.get_running_loop().time()
        for chunk in artifact.audio:
            handoff_guard()
            # A READY artifact is not an unbounded publication burst. Release
            # on the source sample clock with at most two PCM chunks of lead;
            # each required sink retains its own bounded B queue and clock.
            due = release_origin + max(0, source_count / 16000 - .04)
            delay = due - asyncio.get_running_loop().time()
            if delay > 0:
                await asyncio.sleep(delay)
            handoff_guard()
            end = source_count + len(chunk.pcm) // 2
            while video_index < len(artifact.video) and artifact.video[video_index].pts_us * 16000 // 1000000 < end:
                handoff_guard()
                frame = artifact.video[video_index]
                await self.session.media_output.push_video(TimedVideoFrame(frame.generation_id, frame.pts_us,
                    frame.width, frame.height, frame.rgb, identity,
                    start.sampleIndex + frame.pts_us * start.sampleRate // 1000000, start.sampleRate))
                video_index += 1
            # Install the matching video window before advancing the audio
            # clock. Staged readiness is not permission to send unbounded media.
            await self.session.media_output.push_audio(TimedAudioChunk(chunk.generation_id, chunk.sequence,
                chunk.pcm, chunk.sample_rate, chunk.channels, identity,
                start.sampleIndex + source_count * start.sampleRate // 16000,
                start.sampleIndex + end * start.sampleRate // 16000, start.sampleRate))
            source_count = end
        try:
            await self.session.media_output.drain(generation)
            if pose_task:
                await asyncio.wait_for(pose_task, 10)
                await link.release(artifact.stage, complete=True)
        finally:
            if pose_task and not pose_task.done():
                pose_task.cancel()
                await asyncio.gather(pose_task, return_exceptions=True)
        handoff_guard()
        commit = self.timeline.commits[identity.segmentId]
        final = self.timeline.position(commit.end)
        sinks = []
        for sink in request.requiredSinks:
            if any(commit.consumed.get((sink, media)) != commit.end for media in ("audio", "video")):
                logging.getLogger("app").warning("narration_checkpoint_unproven %s", json.dumps({
                    "sessionId": command["sessionId"], "segmentId": identity.segmentId,
                    "runEpoch": identity.runEpoch, "timelineEpoch": identity.timelineEpoch,
                    "requiredEnd": commit.end, "sinkWatermarks": json_value(commit.consumed),
                    "audienceAudible": False}))
                raise ValueError("RECOVERY_UNKNOWN: required sink tail unproven")
            for media in ("audio", "video"):
                sinks.append({"sinkId": sink, "identity": json_value(identity), "media": media,
                    "startSample": commit.start, "endSample": commit.end, "finalMarker": True,
                    "evidenceType": "sink_consumed", "evidenceRef": command["commandId"] + ":" + sink + ":" + media})
        await self.timeline.SegmentCompleted(identity, final, sinks)

    async def _cancel_staging(self, reason):
        from .soulx_staging import StagingAvatarEngine
        avatar = self.session.avatar_engine
        if isinstance(avatar, StagingAvatarEngine) and avatar.link.active and not avatar.link.active.released:
            try:
                await asyncio.shield(avatar.link.release(avatar.link.active, reason=reason))
            except Exception:
                # Retain UNKNOWN and binding; Session.stop retries only cleanup.
                self.timeline.fence_now("STAGING_CLEANUP_UNKNOWN")

    def _staging_commit_proof(self, artifact, identity, start, sample_count):
        import math
        from gpu_worker import staging_contract as c
        actual = self.timeline.installation_ack(identity)
        installed = c.installed_reference(artifact.stage.identity, actual["a_ack"])
        divisor = math.gcd(start.sampleRate, 16000)
        return {"descriptor_sha256": artifact.stage.descriptor["descriptor_sha256"],
            "a_installed_ref": installed, "b_installed_ref": actual["b_installed_ref"],
            "output": {"sampleRate": start.sampleRate, "startSample": start.sampleIndex,
                "endSample": start.sampleIndex+sample_count, "sourceRate": 16000,
                "sourceSamples": artifact.sample_count, "ratioNumerator": start.sampleRate//divisor,
                "ratioDenominator": 16000//divisor},
            "required_sinks": [{"sinkId": sink, "incarnation": installed["producerIncarnation"]}
                for sink in sorted(self.timeline.commits[identity.segmentId].descriptor["requiredSinks"])],
            "optional_sinks": []}

    async def _staging_pose_loop(self, artifact, identity, proof, guard):
        link = self.session.avatar_engine.link
        stage = artifact.stage
        confirmed = -1
        try:
            while True:
                guard();link.check(stage)
                # No receipt is invented before each actual required sink runs.
                if all(self.timeline.sink_revisions.get((identity.segmentId, entry["sinkId"]), 0)>0
                       for entry in proof["required_sinks"]):
                    pose = self.timeline.consumed_pose_proof(identity, stage.descriptor, proof)
                    if pose["latest_consumed_sequence"] > confirmed:
                        await link.pose(stage, pose, guard)
                        confirmed = pose["latest_consumed_sequence"]
                        if confirmed == stage.descriptor["descriptor"]["last_sequence"]:
                            return
                await asyncio.sleep(.02)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stage.failed = exc
            self.timeline.fence_now("STAGING_POSE_UNKNOWN")
            raise

    async def suspend(self, command):
        self.guard(command)
        p = command["payload"]
        return await self.timeline.SuspendAtBoundary(command, p["boundarySegmentId"], self.timeline.revision)

    async def invalidate(self, command):
        self.guard(command)
        p = command["payload"]
        return await self.timeline.InvalidateAfter(command, self.timeline.position(p["cutSample"]),
                                                    p["reason"], self.timeline.revision)

    async def begin_epoch(self, command):
        self.run_guard()
        p = command["payload"]
        return await self.timeline.BeginEpoch(command, p["expectedPreviousEpoch"], p["newEpoch"],
            self.timeline.position(p["originPosition"]["sampleIndex"]), p["reason"])


def bridge_language_context(context):
    """Private language projection; immutable command/cursor remain Go owned."""
    goal=context.get("goal");next_beat=context.get("nextBeatId")
    if not isinstance(goal,list) or not isinstance(next_beat,str):raise ValueError("BRIDGE_CONTEXT_INVALID")
    matches=[beat for beat in goal if isinstance(beat,dict) and beat.get("beatId")==next_beat] if next_beat else []
    if next_beat and len(matches)!=1:raise ValueError("BRIDGE_CONTEXT_INVALID")
    selected=[]
    if matches:
        beat=matches[0]
        if (type(beat.get("title")) is not str or not isinstance(beat.get("requiredFactIds"),list)
                or any(type(fact) is not str for fact in beat["requiredFactIds"])
                or beat.get("productId")!=context.get("productId") or beat.get("factVersion")!=context.get("factVersion")):
            raise ValueError("BRIDGE_CONTEXT_INVALID")
        selected=[copy.deepcopy({key:beat[key] for key in ("beatId","title","requiredFactIds","productId","factVersion")})]
    projected=copy.deepcopy(context);projected["goal"]=selected
    return projected


async def bridge_choice(llm, context, choices):
    """LLM chooses approved language; cannot invent facts or mutate the cursor."""
    staged=getattr(llm,"staging_bridge_enabled",False) is True
    if staged:context=bridge_language_context(context)
    if staged:
        indexed=[{"index":index,"text":choice} for index,choice in enumerate(choices)]
        permitted=", ".join(str(index) for index in range(len(choices)))
        prompt=LLMRequest(
            "选择自然的过渡语。选项索引从0开始，0表示空过渡。只返回一个允许的ASCII索引：" + permitted +
            "。不要文字、符号、空白或JSON。上下文：" + json.dumps(context,ensure_ascii=False) +
            "；明确索引选项：" + json.dumps(indexed,ensure_ascii=False),
            "你只选择口语过渡，不决定哪些事实已经完成。不重复已讲卖点；必要时选索引0的空过渡。", "商品事实只用于理解上下文，禁止自行添加。")
    else:
        prompt = LLMRequest(
            "选择自然的过渡语，只返回选项序号。上下文：" + json.dumps(context, ensure_ascii=False) +
            "；选项：" + json.dumps(choices, ensure_ascii=False),
            "你只选择口语过渡，不决定哪些事实已经完成。不重复已讲卖点；必要时选空过渡。", "商品事实只用于理解上下文，禁止自行添加。")
    text = ""
    stream=getattr(llm,"stream_bridge_choice",llm.stream)
    async for token in stream(prompt):
        text += token
        if len(text) > 16:
            if staged:raise ValueError("BRIDGE_CHOICE_INVALID")
            return 0
    if staged:
        if text not in {str(index) for index in range(len(choices))}:raise ValueError("BRIDGE_CHOICE_INVALID")
        return int(text)
    try:
        result = int(text.strip())
        if 0 <= result < len(choices):return result
        if staged:raise ValueError("BRIDGE_CHOICE_INVALID")
        return 0
    except ValueError:
        if staged:raise ValueError("BRIDGE_CHOICE_INVALID") from None
        return 0
