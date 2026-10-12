"""Software-only staging guards/real CPU decode, NOT GPU or audience evidence."""
import asyncio
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from gpu_worker import staging_contract as c
from gpu_worker.tests.test_staging_contract import begin, commit, message, pose, produced
from app.staging_settings import StagingSettings
from app.staging_observer import barcode_bits, overlay, StagingObserver
from app.soulx_staging import StagingClient, Stage, StagingFailure, correlation
from app.staging_artifact import stage_gpu
from app.providers import AudioChunk, GenerationContext
from app.models import VoiceConfig
from app.narration_segments import SegmentExecutionRequest


class CaptureTests(unittest.TestCase):
    def test_disabled_old_capture_and_enabled_exact_only(self):
        disabled=StagingSettings()
        self.assertEqual(disabled.check_capture({}),disabled.capture())
        enabled=StagingSettings(True,"staging-short-1")
        self.assertEqual(enabled.check_capture(enabled.capture()),enabled.capture())
        for flags in ({},disabled.capture(),enabled.capture()|{"soulxStagingLimitsRevision":"staging-segment-8s-1"}):
            with self.assertRaises(ValueError):enabled.check_capture(flags)
        with patch.dict(os.environ,{"ASTRALIVE_SOULX_STAGING_ENABLED":"true"},clear=True):
            captured=StagingSettings.from_env()
            os.environ["ASTRALIVE_SOULX_STAGING_LIMITS_REVISION"]="staging-segment-8s-1"
            self.assertEqual(captured.check_capture(enabled.capture()),enabled.capture())
        with self.assertRaises(ValueError):StagingSettings(True,"staging-segment-8s-1").check_capture({})

    def test_explicit_new_captured_profiles_use_normative_helper_only(self):
        for name in ("staging-short-gpu1g-1", "staging-segment-8s-gpu1g-1"):
            gate=None if name in c.SHORT_PROFILES else "sha256:"+"a"*64
            settings=StagingSettings(True,name,gate)
            self.assertEqual(settings.check_capture(settings.capture()),settings.capture())
            with patch.dict(os.environ,{"ASTRALIVE_SOULX_STAGING_ENABLED":"true","ASTRALIVE_SOULX_STAGING_LIMITS_REVISION":name,**({"ASTRALIVE_SOULX_STAGING_SHORT_GPU_GATE_SHA256":gate} if gate else {})},clear=True):
                self.assertEqual(StagingSettings.from_env(),settings)
            changed=settings.capture()|{"soulxStagingLimitsRevision":"staging-short-1"}
            with self.assertRaises(ValueError):settings.check_capture(changed)
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(StagingSettings.from_env(),StagingSettings())

    def test_barcode_crc_and_no_pixels_outside_band_changed(self):
        original=bytes((17,18,19))*(512*512)
        output=overlay(original,4095,199)
        self.assertEqual(len(output),len(original))
        for row in range(8):
            self.assertEqual(output[(row*512+192)*3:(row+1)*512*3],original[(row*512+192)*3:(row+1)*512*3])
        self.assertEqual(output[8*512*3:],original[8*512*3:])
        bits=barcode_bits(4095,199)
        code=0
        for bit in bits:code=code*2+bit
        self.assertEqual(code>>12,4095);self.assertEqual((code>>4)&255,199)
        crc=0
        for offset in range(4,24,4):crc^=(code>>offset)&15
        self.assertEqual(crc,code&15)
        with self.assertRaises(ValueError):overlay(original,0,0)

    @unittest.skipUnless(importlib.util.find_spec("av") is not None and importlib.util.find_spec("numpy") is not None,"F observer decoder dependencies unavailable; NOT TESTED")
    def test_f_offline_decoder_matches_exact_runtime_barcode(self):
        import numpy as np
        output=overlay(bytes((17,18,19))*(512*512),4095,199)
        spec=importlib.util.spec_from_file_location("f_observer_audit",Path(__file__).resolve().parents[2]/"integration/v0.5/observer_audit.py")
        audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
        self.assertEqual(audit.barcode(np.frombuffer(output,dtype=np.uint8).reshape(512,512,3)),(4095,199))


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def client(self):return StagingClient({"port":1},"sessionId_1","workerRef_1",StagingSettings(True,"staging-short-1"))

    async def test_pose_exchange_uses_nested_ack_id_and_exact_commit(self):
        client=self.client();client.epoch="workerEpoch_1"
        cm=commit();p=pose();p["pose_proof"]["commit_proof_fingerprint"]=cm["commit_proof_fingerprint"]
        stage=Stage(cm["identity"],begin(),commit=cm,deadline=asyncio.get_running_loop().time()+10)
        sent=[]
        async def exchange(header,response,**kwargs):
            c.validate_message(header);self.assertEqual(correlation({**header,"type":response}),(response,p["pose_proof"]["pose_ack_id"]))
            sent.append(copy.deepcopy(header))
            answer=message("StagePoseConsumedAck")
            answer.update(pose_ack_id=header["pose_proof"]["pose_ack_id"],latest_consumed_sequence=0,
                pose_proof_fingerprint=header["pose_proof_fingerprint"])
            return answer
        client.exchange=exchange
        await client.pose(stage,p["pose_proof"],lambda:None)
        self.assertEqual(stage.pose,sent[0])
        broken=copy.deepcopy(p["pose_proof"]);broken["required_sink_receipts"][0]["audioEndSample"]-=1
        with self.assertRaises(c.ContractError):await client.pose(stage,broken,lambda:None)
        self.assertEqual(len(sent),1)

    async def test_release_exact_retry_unknown_not_reusable(self):
        client=self.client();client.epoch="workerEpoch_1"
        stage=Stage(begin()["identity"],begin(),produced=asyncio.get_running_loop().create_future())
        packets=[];release_attempts=0
        async def exchange(header,response,**kwargs):
            nonlocal release_attempts
            c.validate_message(header);packets.append(copy.deepcopy(header))
            if response=="StageFenced":
                answer=message(response);answer.update(control_id=header["control_id"],latest_consumed_sequence=-1);return answer
            release_attempts+=1
            if release_attempts==1:raise TimeoutError("software lost ACK")
            answer=message(response);answer.update(control_id=header["control_id"],terminal_disposition="UNKNOWN",reusable=False,latest_consumed_sequence=-1);return answer
        client.exchange=exchange;client.active=stage
        with self.assertRaises(TimeoutError):await client.release(stage,reason="STOP")
        answer=await client.release(stage,reason="FORCE")
        self.assertEqual(packets[0],packets[2]);self.assertEqual(packets[1],packets[3])
        self.assertEqual(answer["terminal_disposition"],"UNKNOWN");self.assertFalse(stage.reusable)
        with self.assertRaises(StagingFailure):await client.begin({},b"",0,{},None,None,lambda:None)

    async def test_fresh_sql_barrier_token_and_no_lease_inheritance(self):
        client=self.client();client.sid="s";client.rtt_ms=20
        grants=[{"status":"ACTIVE","sessionId":"s","runEpoch":1,"leaseToken":3,"barrierSeq":2,"remainingMs":10000}]
        class Journal:
            async def request(self,*args):return grants[-1]
        fields=await client.lease_fields({"runEpoch":1,"commandSeq":2},SimpleNamespace(leaseToken=3),Journal(),lambda:None)
        self.assertEqual(fields["a_grant"]["commandSeq"],2)
        self.assertLessEqual(fields["lease_ms"],9780)
        for change in ({"barrierSeq":3},{"leaseToken":4},{"status":"SEALED"},{"remainingMs":100}):
            grants.append(grants[0]|change)
            with self.assertRaises(StagingFailure):await client.lease_fields({"runEpoch":1,"commandSeq":2},SimpleNamespace(leaseToken=3),Journal(),lambda:None)

    async def test_expired_and_failed_stage_never_arm(self):
        client=self.client();stage=Stage({}, {}, deadline=0)
        with self.assertRaises(StagingFailure):await client.arm(stage,{},lambda:None)
        stage.failed=StagingFailure("STAGING_RETIRED")
        with self.assertRaises(StagingFailure):client.check(stage)


@unittest.skipUnless(importlib.util.find_spec("av") is not None and importlib.util.find_spec("numpy") is not None,"software real CPU decode dependencies unavailable; NOT TESTED")
class ArtifactTests(unittest.IsolatedAsyncioTestCase):
    def request(self,max_ms=1920):
        return SegmentExecutionRequest(text="欢迎。",textHash="sha256:"+"a"*64,factIds=[],factVersion="v",productId="p",productSnapshotHash="h",utteranceId="u",attemptId="business-attempt",voice=VoiceConfig(voiceId="v"),requiredSinks=["sink"],expectedNarrationRevision=1,expectedTimelineRevision=0,leaseToken=1,maxDurationMs=max_ms,beatId="beat")

    async def test_full_actual_cpu_h264_decode_padding_and_overlay_hash_domains(self):
        import av
        import numpy as np
        encoder=av.CodecContext.create("libx264","w");encoder.width=encoder.height=512;encoder.pix_fmt="yuv420p"
        from fractions import Fraction
        encoder.time_base=Fraction(1,25);encoder.framerate=Fraction(25,1);encoder.options={"preset":"ultrafast","tune":"zerolatency","bf":"0"};encoder.open()
        raw=bytes((13,55,99))*(512*512)
        frame=av.VideoFrame.from_ndarray(np.frombuffer(raw,dtype=np.uint8).reshape(512,512,3),format="rgb24")
        payload=bytes(encoder.encode(frame)[0])
        class Link:
            worker_ref="worker";epoch="epoch";highest=7;ready={"selected_limits":c.profile("staging-short-1")}
            async def begin(inner,identity,pcm,original,*args):
                inner.identity=identity
                h={"frame_sequence":0,"pts_us":0,"native_rgb_sha256":c.bytes_digest(raw)}
                stage=SimpleNamespace(identity=identity,frames=[(h,payload,"storage")],encoded_bytes=len(payload),descriptor={"descriptor_sha256":"sha256:"+"b"*64,"descriptor":{"frame_count":1,"video_stream_sha256":c.bytes_digest(b"software-staged-H264-stream-hash-domain")}},begin={"original_samples":original,"pad_samples":len(pcm)//2-original})
                return stage
            def check(inner,s):pass
        class TTS:
            async def synthesize_stream(inner,text,voice,context):yield AudioChunk(context.generation_id,0,bytes(1000))
        with tempfile.TemporaryDirectory() as directory:
            link=Link();session=SimpleNamespace(tts_provider=TTS(),avatar_engine=SimpleNamespace(link=link,observer=StagingObserver(directory)),request=SimpleNamespace(config=SimpleNamespace(fps=25)))
            command={"sessionId":"s","runEpoch":1,"timelineEpoch":2,"narrationId":"n","segmentId":"seg","lane":"NARRATION","commandId":"cmd","traceId":"trace"}
            artifact=await stage_gpu(session,self.request(),command,GenerationContext(22,"trace","s","u"),lambda:None,None)
            self.assertEqual(artifact.sample_count,640)
            self.assertEqual(artifact.content_hash,c.bytes_digest(bytes(1280)))
            self.assertEqual(artifact.emitted_video_hash,c.bytes_digest(artifact.video[0].rgb))
            self.assertEqual(artifact.video_hash,c.bytes_digest(b"software-staged-H264-stream-hash-domain"))
            self.assertNotEqual(artifact.video_hash,artifact.emitted_video_hash)
            self.assertEqual(link.identity["generationId"],22);self.assertEqual(link.identity["workerGenerationId"],8)
            self.assertEqual(link.identity["attemptId"],"business-attempt")
            import json
            ref=json.loads(next(Path(directory).glob("attempt-*/reference.json")).read_text())
            self.assertNotEqual(ref["frames"][0]["decodedRGBHash"],ref["frames"][0]["emittedRGBHash"])
            self.assertEqual(ref["frames"][0]["nativeRGBHash"],c.bytes_digest(raw))
            self.assertEqual(ref["frames"][0]["payloadBytes"],len(payload))
            self.assertEqual(ref["frames"][0]["payloadSHA256"],c.bytes_digest(payload))
            self.assertEqual(len(artifact.audio),2)

    async def test_oversized_real_shape_tts_rejects_before_stage_begin(self):
        class TTS:
            async def synthesize_stream(inner,text,voice,context):yield AudioChunk(context.generation_id,0,bytes(32000*2))
        class Link:
            ready={"selected_limits":c.profile("staging-short-1")}
            async def begin(*args):raise AssertionError("must reject before GPU")
        session=SimpleNamespace(tts_provider=TTS(),avatar_engine=SimpleNamespace(link=Link()),request=SimpleNamespace(config=SimpleNamespace(fps=25)))
        with self.assertRaisesRegex(ValueError,"SEGMENT_TOO_LONG"):
            await stage_gpu(session,self.request(),{},GenerationContext(1,"t","s","u"),lambda:None,None)
