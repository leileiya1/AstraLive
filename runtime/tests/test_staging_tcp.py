"""Actual loopback TCP1.2 + real CPU H264 decode + real Timeline arithmetic.

Worker wire, PCM, sinks and SQL authority are explicit SOFTWARE TEST DOUBLES.
The emulated GPU provenance verifies strict wire comparisons; no GPU inference
or browser/RTMP/audience acceptance is established by these cases.
"""
import asyncio
import copy
from fractions import Fraction
import hashlib
import os
import struct
import tempfile
from types import SimpleNamespace
from pathlib import Path
import unittest

import av
import numpy as np
from gpu_worker import staging_contract as c
from gpu_worker.tests.test_staging_contract import message
from app.soulx_staging import StagingAvatarEngine
from app.staging_settings import StagingSettings
from app.providers import AudioChunk
from app.narration_segments import SegmentExecutor, SegmentExecutionRequest
from app.models import VoiceConfig
from app.durability_client import fingerprint


class SoftwareWorkerWire:
    def __init__(self, reject_commit=False, simulation=False, production_delay=0):
        self.reject_commit=reject_commit;self.simulation=simulation;self.production_delay=production_delay;self.background=None
        self.events=[];self.error=None;self.task=None;self.socket=None
        self.begin=None;self.full=None;self.pose=None;self.armed=False;self.sequence=-1;self.storage=set()
        self.pcm=b"";self.wire_frames=[];self.eof=None

    async def packet(self,reader):
        n,p=struct.unpack("!II",await reader.readexactly(8))
        h=c.decode_header(await reader.readexactly(n));payload=await reader.readexactly(p)
        c.validate_message(h,payload);return h,payload

    async def send(self,writer,header,payload=b""):
        c.validate_message(header,payload);raw=c.canonical_bytes(header)
        writer.write(struct.pack("!II",len(raw),len(payload))+raw+payload);await writer.drain()

    def answer(self,name,**kwargs):
        h=message(name);h.update(contract_revision=c.REVISION,session_id="s",worker_epoch="software-epoch")
        if "identity" in h:h["identity"]=self.begin["identity"]
        h.update(kwargs);return h

    async def handler(self,reader,writer):
        self.task=asyncio.current_task();self.socket=writer
        try:
            auth,_=await self.packet(reader)
            ready=message("GPU_WORKER_READY");ready.update(session_id="s",worker_epoch="software-epoch",cache_id="software-cache",input_asset_sha256="sha256:"+"a"*64,
                simulation=self.simulation,highest_generation_id=7,model_revision="software-model",selected_limits=c.profile("staging-short-1"))
            self.ready=ready;await self.send(writer,ready)
            while True:
                h,payload=await self.packet(reader);kind=h["type"];self.events.append(kind)
                if kind=="StageHealth":
                    await self.send(writer,self.answer("StageHealthAck",nonce=h["nonce"],audio_credit_samples=32000,native_queue_frames=0,network_inflight_frames=0))
                elif kind=="StageBegin":
                    self.begin=h
                    await self.send(writer,self.answer("StageBegun",request_fingerprint=h["request_fingerprint"],limits=ready["selected_limits"],audio_credit_samples=32000))
                elif kind=="StageAudio":
                    self.pcm+=payload
                    await self.send(writer,self.answer("StageAudioAccepted",chunk_sequence=h["chunk_sequence"],chunk_sha256=h["chunk_sha256"],audio_credit_samples=32000))
                    if h["final_chunk"]:self.background=asyncio.create_task(self.video(writer))
                elif kind=="StageReceived":
                    self.storage.add(h["frame_sequence"])
                    await self.send(writer,{**h,"type":"StageReceivedAck"})
                    if len(self.storage)==len(self.wire_frames):await self.send(writer,self.eof)
                elif kind=="StageRenew":
                    await self.send(writer,self.answer("StageRenewAck",renewal_sequence=h["renewal_sequence"],renewal_fingerprint=h["renewal_fingerprint"],lease_remaining_ms=h["lease_ms"]))
                elif kind=="StageCommit":
                    if self.reject_commit:
                        await self.send(writer,self.answer("StageError",code="STAGING_COMMIT_UNPROVEN",operation_id=None,publication_fenced=True,state="FENCED"));continue
                    self.armed=True;self.full=h
                    await self.send(writer,self.answer("StageCommitAck",descriptor_sha256=h["commit_proof"]["descriptor_sha256"],commit_proof_fingerprint=h["commit_proof_fingerprint"]))
                    self.events.append("COMMIT_ACK_WRITTEN")
                elif kind=="StagePoseConsumed":
                    if not self.armed:raise AssertionError("pose before arm")
                    c.validate_pose_consumed(h,self.full)
                    if h["pose_proof"]["latest_consumed_sequence"]<=self.sequence:raise AssertionError("same-prefix new pose ID")
                    self.pose=h;self.sequence=h["pose_proof"]["latest_consumed_sequence"]
                    await self.send(writer,self.answer("StagePoseConsumedAck",pose_ack_id=h["pose_proof"]["pose_ack_id"],pose_proof_fingerprint=h["pose_proof_fingerprint"],latest_consumed_sequence=self.sequence))
                elif kind=="StageCancel":
                    await self.send(writer,self.answer("StageFenced",control_id=h["control_id"],latest_consumed_sequence=self.sequence))
                elif kind=="StageRelease":
                    complete=h["reason"]=="COMPLETE" and self.sequence==len(self.wire_frames)-1
                    await self.send(writer,self.answer("StageReleased",control_id=h["control_id"],latest_consumed_sequence=self.sequence,
                        terminal_disposition="PROVEN_COMPLETE" if complete else "UNKNOWN" if self.armed else "PROVEN_CANCELLED",reusable=complete or not self.armed))
                else:raise AssertionError("unexpected wire effect "+kind)
        except (asyncio.IncompleteReadError,ConnectionError,asyncio.CancelledError):pass
        except Exception as exc:self.error=exc
        finally:
            if self.background:self.background.cancel();await asyncio.gather(self.background,return_exceptions=True)
            writer.close();await writer.wait_closed()

    async def video(self,writer):
        await asyncio.sleep(self.production_delay)
        ctx=av.CodecContext.create("libx264","w");ctx.width=ctx.height=512;ctx.pix_fmt="yuv420p"
        ctx.time_base=Fraction(1,25);ctx.framerate=Fraction(25,1);ctx.options={"preset":"ultrafast","tune":"zerolatency","bf":"0"};ctx.open()
        native=hashlib.sha256();stream=hashlib.sha256();video_bytes=0
        provenance={"workerRef":"software-worker","workerEpoch":"software-epoch","model_source_revision":"software-model","weights_manifest_sha256":self.ready["weights_manifest_sha256"],
            "avatar_sha256":"sha256:"+"a"*64,"input_asset_sha256":self.ready["input_asset_sha256"],"cache_id":"software-cache","preprocessing_version":"software-preprocess","capability":c.CAPABILITY,"source":"GPU_INFERENCE"}
        for seq in range(self.begin["source_samples"]//640):
            raw=np.full((512,512,3),seq%255,dtype=np.uint8);frame=av.VideoFrame.from_ndarray(raw,format="rgb24");frame.pts=seq
            encoded=ctx.encode(frame)[0];payload=bytes(encoded);native.update(raw.tobytes());stream.update(struct.pack("!Q",len(payload)));stream.update(payload);video_bytes+=len(payload)
            h=self.answer("StageVideo",frame_sequence=seq,pts_us=seq*40000,sample_start=seq*640,sample_end=(seq+1)*640,keyframe=encoded.is_keyframe,
                payload_sha256=c.bytes_digest(payload),native_rgb_sha256=c.bytes_digest(raw.tobytes()),provenance=provenance)
            self.wire_frames.append(h);await self.send(writer,h,payload)
        d=message("StageProduced")["descriptor"]
        for key in ("source_format","original_samples","pad_samples","source_samples","pcm_sha256","request_fingerprint"):d[key]=copy.deepcopy(self.begin[key])
        d.update(identity=self.begin["identity"],frame_count=len(self.wire_frames),last_sequence=len(self.wire_frames)-1,last_pts_us=(len(self.wire_frames)-1)*40000,video_bytes=video_bytes,
            video_stream_sha256="sha256:"+stream.hexdigest(),native_rgb_stream_sha256="sha256:"+native.hexdigest(),limits=self.ready["selected_limits"],provenance=provenance)
        for key in d["resources"]:d["resources"][key]=0
        self.eof=self.answer("StageProduced",descriptor=d,descriptor_sha256=c.descriptor_hash(d))


class JournalDouble:
    incarnation="software-runtime"
    def __init__(self,events):self.events=events;self.timeline_spool=self;self.operations=[]
    async def request(self,method,path,payload):
        if path=="/media-start":return {"generationId":22}
        if path=="/grant":return {"status":"ACTIVE","sessionId":"s","runEpoch":1,"leaseToken":1,"barrierSeq":0,"remainingMs":10000}
        raise AssertionError("unexpected authority route")
    async def record_timeline(self,record):
        self.operations.append(record);self.events.append(record["operation"])
        return {"durable":True,"testDouble":True,"state":"committed","revision":1,"receiptSeq":len(self.operations),
            "observationHash":c.digest(record),"producerIncarnation":self.incarnation}


class SinkDouble:
    def __init__(self,wire):self.timeline=None;self.wire=wire;self.audio=[];self.video=[]
    def bind_timeline(self,t):self.timeline=t
    async def interrupt(self,generation):pass
    async def push_video(self,frame):
        assert self.wire.armed and "COMMIT_ACK_WRITTEN" in self.wire.events
        self.video.append(frame)
        commit=self.timeline.commits[frame.identity.segmentId]
        for sink in ("preview","rtmp"):
            self.timeline.observe_sink_progress(frame.identity,sink,"video",frame.sourceSample,min(commit.end,frame.sourceSample+1920))
    async def push_audio(self,chunk):
        assert self.wire.armed and "COMMIT_ACK_WRITTEN" in self.wire.events
        self.audio.append(chunk)
        for sink in ("preview","rtmp"):
            self.timeline.observe_sink_progress(chunk.identity,sink,"audio",chunk.startSample,chunk.endSample)
    async def drain(self,generation):pass


class LocalTCPTests(unittest.IsolatedAsyncioTestCase):
    async def run_segment(self,wire):
        server=await asyncio.start_server(wire.handler,"127.0.0.1",0)
        self.addAsyncCleanup(server.wait_closed);self.addCleanup(server.close)
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        token=os.path.join(directory.name,"token");Path(token).write_text("software-only-role-token"*2);os.chmod(token,0o600)
        avatar=StagingAvatarEngine({"port":server.sockets[0].getsockname()[1],"assetSHA256":"a"*64,"tokenFile":token},"s","software-worker",StagingSettings(True,"staging-short-1"))
        self.addAsyncCleanup(avatar.link.close)
        await avatar.prepare(None)
        class TTS:
            async def synthesize_stream(self,text,voice,ctx):yield AudioChunk(ctx.generation_id,0,bytes(3840))
        sink=SinkDouble(wire);session=SimpleNamespace(session_id="s",state="LIVE",generation_id=1,current_task=None,avatar_engine=avatar,media_output=sink,tts_provider=TTS(),request=SimpleNamespace(config=SimpleNamespace(fps=25)))
        journal=JournalDouble(wire.events);ex=SegmentExecutor(session,1,journal,lambda:None)
        req=SegmentExecutionRequest(text="欢迎。",textHash=c.bytes_digest("欢迎。".encode()),factIds=[],factVersion="v",productId="p",productSnapshotHash="hash",utteranceId="u",attemptId="business-attempt",voice=VoiceConfig(voiceId="v"),requiredSinks=["preview","rtmp"],expectedNarrationRevision=2,expectedTimelineRevision=0,leaseToken=1,maxDurationMs=1920,beatId="beat")
        command={"schemaVersion":"0.5","sessionId":"s","runEpoch":1,"timelineEpoch":1,"segmentId":"seg","narrationId":"n","commandId":"cmd","traceId":"trace","commandSeq":3,"commandType":"COMMIT_SEGMENT","lane":"NARRATION","payload":req.model_dump()}
        command["requestFingerprint"]=fingerprint(command)
        await ex.begin(command,{"attemptId":"inbox-different-attempt"})
        return ex,wire,sink,journal

    async def test_complete_actual_tcp_and_b_sidecar_order(self):
        ex,wire,sink,journal=await self.run_segment(SoftwareWorkerWire())
        await asyncio.wait_for(ex.task,5)
        self.assertIsNone(wire.error)
        self.assertEqual(wire.events[0],"StageHealth")
        self.assertLess(wire.events.index("SEGMENT_READY"),wire.events.index("COMMIT_INSTALLED"))
        self.assertLess(wire.events.index("COMMIT_INSTALLED"),wire.events.index("StageCommit"))
        self.assertLess(wire.events.index("StageRelease"),wire.events.index("SEGMENT_COMPLETED"))
        self.assertNotIn("Credit",wire.events)
        self.assertEqual(ex.session.avatar_engine.link.active.released["terminal_disposition"],"PROVEN_COMPLETE")
        self.assertEqual(wire.begin["identity"]["attemptId"],"business-attempt")
        self.assertEqual(wire.begin["identity"]["generationId"],22);self.assertEqual(wire.begin["identity"]["workerGenerationId"],8)
        self.assertEqual(wire.sequence,2)
        self.assertGreaterEqual(wire.events.count("StagePoseConsumed"),2)
        self.assertGreater(len(sink.audio),0)
        self.assertFalse(journal.operations[-1]["proof"]["audienceAudible"])
        ready=journal.operations[0]["proof"]["descriptor"]
        self.assertEqual(ready["videoHash"],wire.eof["descriptor"]["video_stream_sha256"])
        self.assertEqual(ready["contentHash"],wire.eof["descriptor"]["pcm_sha256"])
        self.assertEqual(ready["stagingEmittedVideoHash"],c.bytes_digest(b"".join(frame.rgb for frame in sink.video)))
        self.assertNotEqual(ready["videoHash"],ready["stagingEmittedVideoHash"])
        self.assertEqual(journal.operations[1]["proof"]["commit"]["descriptor"],ready)
        self.assertEqual(journal.operations[2]["proof"]["commit"]["descriptor"],ready)

    async def test_commit_rejection_never_hands_to_sink_and_unknown(self):
        ex,wire,sink,journal=await self.run_segment(SoftwareWorkerWire(reject_commit=True))
        with self.assertRaises(Exception):await asyncio.wait_for(ex.task,5)
        self.assertFalse(sink.audio);self.assertFalse(sink.video)
        self.assertEqual(journal.operations[-1]["operation"],"UNKNOWN")
        self.assertTrue(ex.timeline.sealed)
        self.assertTrue(ex.session.avatar_engine.degraded)

    async def test_async_fresh_renewal_during_slow_production(self):
        ex,wire,sink,journal=await self.run_segment(SoftwareWorkerWire(production_delay=1.2))
        await asyncio.wait_for(ex.task,5)
        self.assertIn("StageRenew",wire.events)
        self.assertLess(wire.events.index("StageRenew"),wire.events.index("SEGMENT_READY"))
        self.assertIsNone(wire.error)

    async def test_force_fence_after_arm_before_first_sink(self):
        ex,wire,sink,journal=await self.run_segment(SoftwareWorkerWire())
        def guard():
            if "COMMIT_ACK_WRITTEN" in wire.events:raise ValueError("software FORCE barrier")
        ex.run_guard=guard
        with self.assertRaisesRegex(ValueError,"FORCE barrier"):await asyncio.wait_for(ex.task,5)
        self.assertFalse(sink.audio);self.assertFalse(sink.video)
        self.assertIn("StageCancel",wire.events)
        self.assertIn("StageRelease",wire.events)
        self.assertEqual(journal.operations[-1]["operation"],"UNKNOWN")
        self.assertFalse(ex.session.avatar_engine.link.active.reusable)

    async def test_simulation_negotiation_rejected_before_any_begin(self):
        wire=SoftwareWorkerWire(simulation=True)
        with self.assertRaisesRegex(Exception,"STAGING_IDENTITY_MISMATCH"):await self.run_segment(wire)
        self.assertFalse(wire.events)
