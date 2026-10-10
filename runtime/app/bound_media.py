"""Business Session consumption credits for WebRTC and headless RTMP.

Retains the validated queues, media clocks, generation fence and Worker protocol.
RTMP pipe consumption is not a claim that a live platform accepted the stream.
"""
import asyncio
from gpu_worker.validated.runtime_avatar import ConsumptionMediaOutput
from gpu_worker.validated.prefetch import WorkerUnavailable
from .providers import MediaDeliveryError


class BoundConsumptionMediaOutput(ConsumptionMediaOutput):
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
            return
        await super().drain(generation)

    async def push_video(self, frame):
        packet = self.metadata.pop(id(frame), None)
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

        async def ack():
            while self.avatar.running and generation == self.avatar.generation_id:
                web_consumed = any(p in web.peers and p.video.generation_id == generation
                                   and p.video.consumed >= t for p, t in targets)
                current = rtmp.video_delivery_position() if target is not None else None
                rtmp_consumed = bool(current and current[0] == generation and current[1] >= target)
                if web_consumed or rtmp_consumed:
                    try:
                        await link.consumed(packet)
                    except WorkerUnavailable:
                        self.avatar.log("CreditLinkUnavailable")
                        self.avatar.degraded = True
                        if self.avatar.pipeline:
                            await self.avatar.pipeline.degrade()
                        return
                    cached = self.avatar.cached_idle
                    if packet.get("activity") == "IDLE" and (cached is None or
                            (packet["generation_id"], packet["frame_sequence"]) >
                            (cached["generation_id"], cached["frame_sequence"])):
                        self.avatar.cached_idle = packet
                    self.avatar.log("FrameActuallyConsumed", pts_us=frame.pts_us,
                                    source=packet["source"], job_id=packet["generation_id"],
                                    frame_sequence=packet["frame_sequence"],
                                    sink="webrtc" if web_consumed else "rtmp")
                    return
                if not current and not any(p in web.peers and
                        p.connection.connectionState not in {"failed", "closed", "disconnected"}
                        for p, _ in targets):
                    return
                await asyncio.sleep(.005)

        task = asyncio.create_task(ack())
        self.acks.add(task)
        task.add_done_callback(self.acks.discard)
