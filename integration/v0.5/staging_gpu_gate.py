#!/usr/bin/env python3
"""Real Worker staging without sinks; trusted lease DTO fixture, not SQL proof."""
import argparse
import asyncio
import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
import uuid
import wave

import av

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gpu_worker import staging_contract as contract
from gpu_worker.config import secret


async def main_async(args):
    out = args.output.absolute()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    with wave.open(str(args.wav), "rb") as source:
        if (source.getframerate(),source.getnchannels(),source.getsampwidth())!=(16000,1,2):
            raise ValueError("requires actual source16kHz mono s16le WAV")
        original = source.readframes(source.getnframes())
    original_samples = len(original)//2
    pad = (-original_samples)%640
    pcm = original+bytes(pad*2)
    result = {"sourceSHA": args.source, "scope": "real GPU generated staging / prerecorded actual TTS speech / no sinks; direct trusted lease DTO fixture, no Go SQL or business command acceptance",
              "profile": args.profile, "inputWavSHA256": hashlib.sha256(args.wav.read_bytes()).hexdigest(),
              "originalSamples": original_samples, "padSamples": pad, "status": "FAIL", "attempts": []}
    reader = writer = None
    write_lock = asyncio.Lock()
    controls = {}
    attempts = {}
    receiver = None
    limits = contract.profile(args.profile, short_gpu_gate=args.profile!="staging-short-1")
    if len(pcm)//2 > limits["max_source_samples"]:
        raise ValueError("source speech exceeds explicitly chosen profile")

    async def send(header, payload=b""):
        contract.validate_message(header,payload)
        raw = contract.canonical_bytes(header)
        async with write_lock:
            writer.write(struct.pack("!II",len(raw),len(payload))+raw+payload)
            await writer.drain()

    async def read():
        size,payload_size = struct.unpack("!II",await reader.readexactly(8))
        if size>16384 or payload_size>2097152:
            raise ValueError("Worker wire budget failure")
        header=contract.decode_header(await reader.readexactly(size))
        payload=await reader.readexactly(payload_size)
        contract.validate_message(header,payload)
        return header,payload

    async def dispatch():
        try:
            while True:
                h,payload=await read()
                identity=h["identity"];attempt=attempts[identity["stageId"]]
                if identity!=attempt["identity"]:
                    raise ValueError("Worker changed full attempt identity")
                if h["type"]=="StageVideo":
                    seq=h["frame_sequence"]
                    if seq!=len(attempt["video"]):
                        raise ValueError("noncontiguous generated video")
                    packet=av.Packet(payload);packet.pts=packet.dts=seq;packet.time_base=Fraction(1,25)
                    frames=attempt["decoder"].decode(packet)
                    if len(frames)!=1:
                        raise ValueError("decode buffered/gapped frame")
                    rgb=frames[0].to_ndarray(format="rgb24").tobytes()
                    attempt["rgb"].update(rgb)
                    attempt["video_hash"].update(struct.pack("!Q",len(payload))+payload)
                    attempt["video"].append({"sequence":seq,"ptsUs":h["pts_us"],"payloadHash":h["payload_sha256"],"nativeHash":h["native_rgb_sha256"]})
                    attempt["video_bytes"]+=len(payload)
                    if seq in (0,len(pcm)//1280-1):
                        frames[0].to_image().save(out/f"attempt-{attempt['ordinal']}-frame-{seq}.png")
                    # Immutable bytes are kept until validated Produced. This
                    # releases transport slots only, never consumption/pose.
                    with (out/f"attempt-{attempt['ordinal']}.h264").open("ab") as stored:
                        stored.write(payload)
                    ack={"type":"StageReceived",**attempt["common"],"frame_sequence":seq,
                         "payload_sha256":h["payload_sha256"],"native_rgb_sha256":h["native_rgb_sha256"],
                         "storage_receipt_id":identity["stageId"]+":stored:"+str(seq)}
                    await send(ack)
                else:
                    await attempt["queue"].put(h)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            for attempt in attempts.values():
                await attempt["queue"].put(exc)

    async def expect(attempt,name):
        while True:
            h=await asyncio.wait_for(attempt["queue"].get(),15)
            if isinstance(h,Exception):raise h
            if h["type"]=="StageError":raise ValueError("Worker rejected stage: "+h["code"])
            if h["type"]==name:return h
            if h["type"] not in ("StageAudioAccepted","StageReceivedAck","StageRenewAck"):
                raise ValueError("unexpected Worker reply: "+h["type"])

    def grant(identity):
        return {"sessionId":identity["sessionId"],"runEpoch":1,"leaseToken":1,
                "barrierSeq":0,"commandSeq":1,"remainingMs":10000}

    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",args.port),5)
        session="f-real-stage-"+uuid.uuid4().hex
        auth={"type":"Auth","protocol_version":1,"internal_version":"1.2","session_id":session,
              "token":secret(args.token_file),"requested_capabilities":[contract.CAPABILITY],"requested_limits_revision":args.profile}
        begun=time.monotonic()
        await send(auth)
        ready,_=await read()
        contract.validate_negotiation(auth,ready)
        if ready["simulation"]:
            raise ValueError("CPU simulation cannot pass GPU gate")
        result["ready"]=ready
        rtt=max(1,int((time.monotonic()-begun)*1000)+1)
        receiver=asyncio.create_task(dispatch())
        previous_pose=None
        for ordinal in range(2):
            stage=uuid.uuid4().hex
            identity={"sessionId":session,"runEpoch":1,"timelineEpoch":1,"generationId":ordinal+1,
                      "narrationId":"f-no-sink","beatId":"beat","segmentId":"segment-"+stage,
                      "interactionTurnId":None,"utteranceId":"utterance-"+stage,"commandId":"command-"+stage,
                      "traceId":"trace-"+stage,"attemptId":"attempt-"+stage,"stageId":stage,"lane":"NARRATION",
                      "workerRef":args.worker_ref,"workerEpoch":ready["worker_epoch"],
                      "workerGenerationId":ready["highest_generation_id"]+ordinal+1}
            common={"contract_revision":contract.REVISION,"session_id":session,"worker_epoch":ready["worker_epoch"],"identity":identity}
            attempt={"identity":identity,"common":common,"ordinal":ordinal,"queue":asyncio.Queue(),"decoder":av.CodecContext.create("h264","r"),
                     "video":[],"video_hash":hashlib.sha256(),"rgb":hashlib.sha256(),"video_bytes":0}
            attempts[stage]=attempt
            header={"type":"StageBegin",**common,"command_request_fingerprint":contract.digest({"explicitFixture":True,"id":identity["commandId"]}),
                    "a_grant":grant(identity),"a_rtt_ms":0,"grant_age_ms":0,"worker_rtt_ms":rtt,"safety_ms":100,
                    "request_fingerprint":"sha256:"+"0"*64,"cache_id":ready["cache_id"],"pcm_sha256":contract.bytes_digest(pcm),
                    "original_samples":original_samples,"pad_samples":pad,"source_samples":len(pcm)//2,
                    "source_format":copy.deepcopy(contract.SOURCE_FORMAT_DEFAULT) if hasattr(contract,"SOURCE_FORMAT_DEFAULT") else
                    {"sample_rate":16000,"channels":1,"pcm_format":"s16le","fps_num":25,"fps_den":1,"width":512,"height":512,"native_format":"rgb24","codec":"h264"},
                    "lease_ms":10000-rtt-100,"limits_revision":args.profile}
            header["request_fingerprint"]=contract.stage_begin_fingerprint(header)
            await send(header)
            start_reply=await expect(attempt,"StageBegun")
            credit=start_reply["audio_credit_samples"]
            pose=start_reply["pose_history_sha256"]
            if previous_pose is not None and previous_pose!=pose:
                raise ValueError("unplayed first attempt polluted next consumed pose")
            stop_renew=asyncio.Event()

            async def renew():
                sequence=0
                while not stop_renew.is_set():
                    try:await asyncio.wait_for(stop_renew.wait(),1)
                    except asyncio.TimeoutError:
                        sequence+=1
                        request={"type":"StageRenew",**common,"renewal_sequence":sequence,"lease_ms":10000-rtt-100,
                                 "a_grant":grant(identity),"a_rtt_ms":0,"grant_age_ms":0,"worker_rtt_ms":rtt,"safety_ms":100,
                                 "renewal_fingerprint":"sha256:"+"0"*64}
                        request["renewal_fingerprint"]=contract.renewal_fingerprint(request)
                        await send(request)
            renew_task=asyncio.create_task(renew())
            try:
                for seq,offset in enumerate(range(0,len(pcm),30720)):
                    chunk=pcm[offset:offset+30720]
                    while credit<len(chunk)//2:
                        await send({"type":"StageStatus",**common,"nonce":"credit-"+uuid.uuid4().hex})
                        status=await expect(attempt,"StageStatusResult")
                        credit=status["audio_credit_samples"]
                        if credit<len(chunk)//2:
                            await asyncio.sleep(.02)
                    await send({"type":"StageAudio",**common,"chunk_sequence":seq,"first_sample_index":offset//2,
                                "sample_count":len(chunk)//2,"final_chunk":offset+len(chunk)==len(pcm),"chunk_sha256":contract.bytes_digest(chunk)},chunk)
                    audio_ack=await expect(attempt,"StageAudioAccepted")
                    if audio_ack["chunk_sequence"]!=seq or audio_ack["chunk_sha256"]!=contract.bytes_digest(chunk):
                        raise ValueError("Worker changed immutable PCM acknowledgement")
                    credit=audio_ack["audio_credit_samples"]
                produced=await expect(attempt,"StageProduced")
                d=produced["descriptor"]
                if d["frame_count"]!=len(attempt["video"]) or d["pcm_sha256"]!=contract.bytes_digest(pcm) or d["video_stream_sha256"]!="sha256:"+attempt["video_hash"].hexdigest() or d["video_bytes"]!=attempt["video_bytes"]:
                    raise ValueError("produced artifact integrity mismatch")
                control="cancel-"+stage
                await send({"type":"StageCancel",**common,"control_id":control,"reason":"STOP"})
                fenced=await expect(attempt,"StageFenced")
                if fenced["latest_consumed_sequence"]!=-1 or fenced["pose_history_sha256"]!=pose:
                    raise ValueError("no-sink attempt changed consumed pose")
                await send({"type":"StageRelease",**common,"control_id":control,"reason":"CANCELLED",
                            "descriptor_sha256":produced["descriptor_sha256"],"commit_proof_fingerprint":None,
                            "pose_proof_fingerprint":None,"latest_consumed_sequence":-1})
                released=await expect(attempt,"StageReleased")
                if not released["reusable"] or released["terminal_disposition"]!="PROVEN_CANCELLED" or released["pose_history_sha256"]!=pose:
                    raise ValueError("unplayed artifact not safely released")
                previous_pose=pose
                result["attempts"].append({"identity":identity,"produced":produced,"released":released,
                    "decodedRGB_SHA256":"sha256:"+attempt["rgb"].hexdigest(),"video":attempt["video"]})
            finally:
                stop_renew.set();await renew_task
        result["status"]="PASS_REAL_GPU_STAGING_NO_SINKS"
    except Exception as exc:
        result["errorType"]=type(exc).__name__
        raise
    finally:
        if receiver:receiver.cancel();await asyncio.gather(receiver,return_exceptions=True)
        if writer:writer.close();await writer.wait_closed()
        (out/"result.json").write_text(json.dumps(result,indent=2)+"\n")
        print(json.dumps({"status":result["status"],"attempts":len(result["attempts"])}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port",type=int,required=True);p.add_argument("--token-file",required=True)
    p.add_argument("--worker-ref",default="soulx-lite-01");p.add_argument("--source",required=True)
    p.add_argument("--wav",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--profile",choices=("staging-short-1","staging-segment-8s-1"),default="staging-short-1")
    asyncio.run(main_async(p.parse_args()))


if __name__=="__main__":main()
