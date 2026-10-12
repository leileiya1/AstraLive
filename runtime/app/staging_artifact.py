"""Bounded real source TTS + immutable full GPU H264 decode before READY."""
import asyncio
import hashlib
from uuid import uuid4

from gpu_worker import staging_contract as contract
from .providers import AudioChunk, VideoFrame
from .voice_stream import StreamingVoiceAdapter


async def stage_gpu(session, request, command, context, guard, journal):
    from .narration_segments import ReadyArtifact
    link = session.avatar_engine.link
    if session.request.config.fps != 25:
        raise ValueError("STAGING_UNSUPPORTED: captured fps must be 25")
    parts = []
    count = 0
    limits = link.ready["selected_limits"]
    source = StreamingVoiceAdapter(session.tts_provider, request.voice.voiceId).synthesize_stream(request.text, request.voice, context)
    try:
        async for chunk in source:
            guard()
            if chunk.generation_id != context.generation_id or chunk.sample_rate != 16000 or chunk.channels != 1:
                raise ValueError("STAGING_IDENTITY_MISMATCH")
            count += len(chunk.pcm) // 2
            if count * 1000 > request.maxDurationMs * 16000 or count > limits["max_source_samples"]:
                # Never truncate an immutable authored command or silently retry.
                raise ValueError("SEGMENT_TOO_LONG: authored statement requires explicit new plan")
            parts.append(chunk.pcm)
    finally:
        await source.aclose()
    if not count:
        raise ValueError("INCOMPLETE_READY_ARTIFACT")
    pcm = b"".join(parts) + b"\0\0" * (-count % 640)
    parts.clear()
    if len(pcm) // 2 > limits["max_source_samples"] or len(pcm) * 500 > request.maxDurationMs * 16000:
        raise ValueError("SEGMENT_TOO_LONG: frame padding exceeds authored cap")
    identity = {key: command[key] for key in ("sessionId", "runEpoch", "timelineEpoch", "narrationId", "segmentId", "lane", "commandId", "traceId")}
    identity.update(generationId=context.generation_id, beatId=request.beatId,
        interactionTurnId=request.interactionTurnId, utteranceId=request.utteranceId,
        attemptId=request.attemptId, stageId="stage-" + uuid4().hex,
        workerRef=link.worker_ref, workerEpoch=link.epoch, workerGenerationId=link.highest + 1)
    contract.validate_identity(identity)
    stage = await link.begin(identity, pcm, count, command, request, journal, guard)
    guard();link.check(stage)
    observer = session.avatar_engine.observer
    observation = observer.begin(stage, pcm)
    video = []
    decoded_hash = hashlib.sha256()
    # CPU decoding does not mutate the original Worker RGB/pose history.
    import av
    decoder = av.CodecContext.create("h264", "r")
    decoder.thread_count = 1
    decoder.open()
    size = len(pcm) + stage.encoded_bytes
    try:
        for header, payload, _ in stage.frames:
            guard();link.check(stage)
            frames = decoder.decode(av.Packet(payload))
            if len(frames) != 1 or frames[0].width != 512 or frames[0].height != 512:
                raise ValueError("INCOMPLETE_READY_ARTIFACT: H264 decode sequence")
            rgb = frames[0].to_ndarray(format="rgb24").tobytes()
            emitted = observer.frame(observation, header, rgb)
            del rgb
            video.append(VideoFrame(context.generation_id, header["pts_us"], 512, 512, emitted))
            decoded_hash.update(emitted)
            size += len(emitted)
            if size > limits["runtime_artifact_bytes"]:
                raise ValueError("READY_ARTIFACT_BUDGET_EXCEEDED")
            # Let Stop, grant renewal and socket storage/control run between frames.
            await asyncio.sleep(0)
        if decoder.decode(None):
            raise ValueError("INCOMPLETE_READY_ARTIFACT: delayed H264 tail")
    finally:
        del decoder
    if len(video) != stage.descriptor["descriptor"]["frame_count"]:
        raise ValueError("INCOMPLETE_READY_ARTIFACT")
    audio = tuple(AudioChunk(context.generation_id, seq, pcm[offset:offset+640])
        for seq, offset in enumerate(range(0, len(pcm), 640)))
    observer.finish(observation, readyContentHash=contract.bytes_digest(pcm),
        readyEmittedVideoHash="sha256:" + decoded_hash.hexdigest(),
        originalSamples=count, padSamples=len(pcm)//2-count)
    return ReadyArtifact(audio, tuple(video), len(pcm)//2, contract.bytes_digest(pcm),
        "sha256:" + decoded_hash.hexdigest(), "GPU_INFERENCE", stage)
