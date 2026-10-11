"""Business Session consumption credits for WebRTC and headless RTMP.

Retains the validated queues, media clocks, generation fence and Worker protocol.
RTMP pipe consumption is not a claim that a live platform accepted the stream.
"""
import asyncio
from fractions import Fraction
from gpu_worker.validated.runtime_avatar import ConsumptionMediaOutput
from gpu_worker.validated.prefetch import WorkerUnavailable
from .providers import MediaDeliveryError
from .media_timeline import enabled as timeline_enabled, TimedAudioChunk, TimedVideoFrame


class BoundConsumptionMediaOutput(ConsumptionMediaOutput):
    def __init__(self, output, avatar):
        super().__init__(output, avatar)
        self.timeline_v2 = timeline_enabled()

    def bind_attempt(self, identity, startPosition):
        """C-owned orchestration seam; attach identity without changing Worker wire.

        Invoke after CommitSegment, before submitting that attempt. The source
        Worker origin and the run output origin are distinct sample domains.
        """
        if not self.timeline_v2:
            raise ValueError("MediaTimeline V2 disabled")
        if (identity.sessionId, identity.runEpoch, identity.timelineEpoch) != (
                startPosition.sessionId, startPosition.runEpoch, startPosition.timelineEpoch):
            raise ValueError("attempt position identity mismatch")
        bindings = self.__dict__.setdefault("timeline_bindings", {})
        existing = bindings.get(identity.generationId)
        if existing and existing[:2] != (identity, startPosition):
            raise ValueError("SEGMENT_CONFLICT")
        if not existing:
            if len(bindings) >= 8:
                raise ValueError("retire fenced attempt bindings before admission")
            bindings[identity.generationId] = (identity, startPosition,
                getattr(self.avatar, "timeline_samples", 0), Fraction(0))

    async def push_audio(self, chunk):
        binding = self.__dict__.get("timeline_bindings", {}).get(chunk.generation_id)
        if binding:
            identity, position, origin, count = binding
            next_count = count + Fraction(len(chunk.pcm) // 2 * position.sampleRate, chunk.sample_rate)
            chunk = TimedAudioChunk(chunk.generation_id, chunk.sequence, chunk.pcm, chunk.sample_rate,
                chunk.channels, identity, position.sampleIndex + int(count), position.sampleIndex + int(next_count), position.sampleRate)
            self.timeline_bindings[chunk.generation_id] = (identity, position, origin, next_count)
        await super().push_audio(chunk)

    def set_interaction_trace(self, trace, generation):
        self.interaction_trace = (trace, generation)

    def _trace_frame(self, packet, frame, stage):
        observation = self.__dict__.get('interaction_trace')
        if (observation and frame.generation_id == observation[1] == self.avatar.generation_id
                and packet and packet.get('activity') == 'TALKING'):
            if stage != 'avatar_first_generated_frame' or packet.get('source') == 'GPU_INFERENCE':
                pipeline = self.avatar.pipeline
                observation[0].annotate_media(generationId=frame.generation_id,
                    speechMarker=packet.get('marker'), firstVideoPTSUS=frame.pts_us,
                    speechOriginSample=getattr(pipeline, 'origin', None))
                observation[0].mark(stage, 'Runtime observes TALKING packet ' + packet.get('source','UNKNOWN') + '; not Worker-host generation timestamp or viewer playback')

    def _rtmp(self):
        if hasattr(self.output, "video_delivery_position"):
            return self.output
        return next((c.output for c in getattr(self.output, "channels", [])
                     if c.name == "rtmp"), None)

    def has_peer(self):
        sink = self._rtmp()
        return super().has_peer() or bool(sink and sink.video_delivery_position() is not None)

    async def drain(self, generation):
        web, rtmp = self._webrtc(), self._rtmp()
        # An enabled preview with no subscriber is optional for headless RTMP.
        # Drain the publishing sink alone, so an absent preview cannot produce
        # a failure warning or count as success when every real sink failed.
        if rtmp and not (web and web.peers):
            for c in getattr(self.output, "channels", []):
                if c.name == "rtmp":
                    await asyncio.wait_for(asyncio.gather(c.audio.join(), c.video.join()), 20)
            await rtmp.drain(generation)
            if generation == self.avatar.generation_id and rtmp.video_delivery_position() is None:
                raise MediaDeliveryError("RTMP encoder unavailable during playback")
            self.__dict__.get("timeline_bindings", {}).pop(generation, None)
            return
        await super().drain(generation)
        self.__dict__.get("timeline_bindings", {}).pop(generation, None)

    async def push_video(self, frame):
        packet = self.metadata.pop(id(frame), None)
        binding = self.__dict__.get("timeline_bindings", {}).get(frame.generation_id)
        if binding:
            identity, position, origin, _ = binding
            sample = position.sampleIndex + (frame.pts_us * 16000 // 1000000 - origin) * position.sampleRate // 16000
            frame = TimedVideoFrame(frame.generation_id, frame.pts_us, frame.width, frame.height,
                                   frame.rgb, identity, sample, position.sampleRate)
        web, rtmp = self._webrtc(), self._rtmp()
        self._trace_frame(packet, frame, "avatar_first_generated_frame")
        await self.output.push_video(frame)
        self._trace_frame(packet, frame, "media_first_video")
        # Join means admission to a sink, never acknowledgement of consumption.
        if packet:
            for c in getattr(self.output, "channels", []):
                if c.name in {"webrtc", "rtmp"}:
                    await asyncio.wait_for(c.video.join(), 2)
        if packet is None:
            return
        self.avatar.last_frame = packet
        self.avatar.log("FrameEnqueued", source=packet["source"],
                        activity=packet.get("activity"), marker=packet.get("marker"), pts_us=frame.pts_us)
        if packet["source"] not in {"GPU_INFERENCE", "CPU_SIMULATION"}:
            return
        targets = [(p, p.video.enqueued) for p in web.peers
                   if p.connection.connectionState == "connected"] if web else []
        position = rtmp.video_delivery_position() if rtmp else None
        target = rtmp.video_enqueued if position else None
        if not targets and target is None:
            raise WorkerUnavailable("no playback consumer for GPU credit")
        # Hold the original connection: recovery must never credit a retired job
        # through the replacement Worker epoch.
        link = self.avatar.link
        generation = frame.generation_id
        v2 = self.timeline_v2

        async def ack():
            while self.avatar.running and generation == self.avatar.generation_id:
                web_consumed = any(p in web.peers and p.video.generation_id == generation
                                   and p.video.consumed >= t for p, t in targets)
                current = rtmp.video_delivery_position() if target is not None else None
                rtmp_consumed = bool(current and current[0] == generation and current[1] >= target)
                retired = False
                if v2:
                    # Aggregate counters cannot identify a frame when late video
                    # is dropped. Releasing flow credit for an active retired
                    # packet never creates a sink-consumed/completion receipt.
                    web_state = getattr(web, "video_disposition", lambda f: None)(frame) if web else None
                    rtmp_state = getattr(rtmp, "video_disposition", lambda f: None)(frame) if rtmp else None
                    web_consumed, rtmp_consumed = web_state == "consumed", rtmp_state == "consumed"
                    fanout_state = getattr(self.output, "video_disposition", lambda f: None)(frame)
                    retired = web_state == "dropped" or rtmp_state == "dropped" or fanout_state == "dropped"
                    identity = getattr(frame, "identity", None)
                    timeline = getattr(self.output, "timeline", None) or getattr(
                        getattr(rtmp, "timeline_clock", None), "timeline", None)
                    if timeline and identity and not timeline.eligible(identity, frame.sourceSample, frame.sourceSample):
                        return
                if web_consumed or rtmp_consumed or retired:
                    try:
                        await link.consumed(packet)
                    except WorkerUnavailable:
                        self.avatar.log("CreditLinkUnavailable")
                        self.avatar.degraded = True
                        if self.avatar.pipeline:
                            await self.avatar.pipeline.degrade()
                        return
                    cached = self.avatar.cached_idle
                    if (web_consumed or rtmp_consumed) and packet.get("activity") == "IDLE" and (cached is None or
                            (packet["generation_id"], packet["frame_sequence"]) >
                            (cached["generation_id"], cached["frame_sequence"])):
                        self.avatar.cached_idle = packet
                    self.avatar.log("FrameRetiredForCredit" if retired and not (web_consumed or rtmp_consumed)
                                    else "FrameActuallyConsumed", pts_us=frame.pts_us,
                                    source=packet["source"], job_id=packet["generation_id"],
                                    frame_sequence=packet["frame_sequence"],
                                    sink="webrtc" if web_consumed else "rtmp" if rtmp_consumed else "discard",
                                    **({"evidenceType": "discarded" if retired and not (web_consumed or rtmp_consumed)
                                        else "sink_consumed"} if v2 else {}))
                    return
                if not current and not any(p in web.peers and
                        p.connection.connectionState not in {"failed", "closed", "disconnected"}
                        for p, _ in targets):
                    return
                await asyncio.sleep(.005)

        task = asyncio.create_task(ack())
        self.acks.add(task)
        task.add_done_callback(self.acks.discard)

    async def invalidate(self, generation):
        self.__dict__.get("timeline_bindings", {}).clear()
        await super().invalidate(generation)
