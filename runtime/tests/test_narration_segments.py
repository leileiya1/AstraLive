"""C execution/fault tests. Synthetic PCM and SQL journal double, not GPU evidence."""
import asyncio
import hashlib
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.narration_segments import (SegmentExecutor, SegmentExecutionRequest, enabled,
                                    stage_segment, bridge_choice, json_value)
from app.providers import MockTTSProvider, GenerationContext, AudioChunk
from app.lightweight_avatar import LightweightAvatarEngine
from app.models import VoiceConfig
from app.durability_client import fingerprint
from app.durable_events import DurableEventPublisher
import tempfile


def request(text="这是完整讲解。"):
    return SegmentExecutionRequest(text=text,textHash="sha256:"+hashlib.sha256(text.encode()).hexdigest(),
        factIds=["fact"],factVersion="v1",productId="p",productSnapshotHash="h",
        utteranceId="u",attemptId="a",voice=VoiceConfig(voiceId="v"),requiredSinks=["fixture"],
        expectedNarrationRevision=2,expectedTimelineRevision=0,leaseToken=1)


class Journal:
    incarnation="fixture-runtime"
    def __init__(self): self.operations=[];self.fail=None
    async def request(self,method,path,payload):
        if path=="/media-start":return {"generationId":2}
        self.operations.append(payload)
        if payload["operation"]==self.fail:raise ConnectionError("fixture journal outage")
        return {"durable":True,"fixture":True}


class FixtureSink:
    """Explicit sink double: advances contiguous watermarks only on handed media."""
    def __init__(self):self.audio=[];self.video=[];self.timeline=None;self.generation=1
    def bind_timeline(self,t):self.timeline=t
    async def interrupt(self,g):self.generation=g
    async def push_audio(self,c):
        if self.timeline.eligible(c.identity,c.startSample,c.endSample):
            self.audio.append(c)
            self.timeline.observe_sink_progress(c.identity,"fixture","audio",c.startSample,c.endSample)
    async def push_video(self,f):
        if self.timeline.eligible(f.identity,f.sourceSample,f.sourceSample):self.video.append(f)
    async def drain(self,g):
        for i,f in enumerate(self.video):
            commit=self.timeline.commits[f.identity.segmentId]
            end=self.video[i+1].sourceSample if i+1<len(self.video) else commit.end
            self.timeline.observe_sink_progress(f.identity,"fixture","video",f.sourceSample,end)


async def session():
    avatar=LightweightAvatarEngine(size=32);await avatar.prepare(None);await avatar.start()
    return SimpleNamespace(avatar_engine=avatar,tts_provider=MockTTSProvider(),media_output=FixtureSink(),
        session_id="s",state="LIVE",generation_id=1,current_task=None,request=SimpleNamespace(config=SimpleNamespace(fps=25)))


class ConfigTests(unittest.TestCase):
    def test_frozen_flag_no_alias(self):
        for value,want in [(None,False),("false",False),("true",True),("0",False),("1",True)]:
            with patch.dict(os.environ,{} if value is None else {"ASTRALIVE_CONTINUITY_ENABLED":value},clear=True):self.assertEqual(enabled(),want)
        for env in [{"ASTRALIVE_CONTINUITY_ENABLED":""},{"ASTRALIVE_CONTINUITY_ENABLED":"invalid"},
                    {"ASTRALIVE_NARRATION_CONTINUITY_ENABLED":"false"},
                    {"ASTRALIVE_NARRATION_CONTINUITY_ENABLED":"true","ASTRALIVE_CONTINUITY_ENABLED":"true"}]:
            with patch.dict(os.environ,env,clear=True),self.assertRaises(ValueError):enabled()


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    def publisher(self,journal):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        publisher=DurableEventPublisher(journal,directory.name);self.addAsyncCleanup(publisher.close)
        return publisher
    async def test_ready_commit_actual_fixture_consumption(self):
        s=await session();j=Journal();self.publisher(j);ex=SegmentExecutor(s,1,j,lambda:None)
        p=request().model_dump();c={"schemaVersion":"0.5","sessionId":"s","runEpoch":1,
            "timelineEpoch":1,"segmentId":"seg","narrationId":"n","commandId":"c","traceId":"trace",
            "commandType":"COMMIT_SEGMENT","lane":"NARRATION","payload":p}
        c["requestFingerprint"]=fingerprint(c)
        await ex.begin(c,{"attemptId":"different-inbox-attempt"});await ex.task
        self.assertEqual([x["operation"] for x in j.operations],
            ["SEGMENT_READY","COMMIT_INTENT","COMMIT_INSTALLED","SEGMENT_COMPLETED"])
        self.assertEqual(j.operations[0]["proof"]["attemptId"],"a")
        self.assertFalse(j.operations[-1]["proof"]["audienceAudible"])
        self.assertEqual(len(j.operations[-1]["proof"]["sinkReceipts"]),2)
        # Full old tuple remains the same (including generation); changing the
        # answer epoch must reject late audio/video independently of cancellation.
        old_audio, old_video = s.media_output.audio[0], s.media_output.video[0]
        old = ex.current_identity
        cut = ex.timeline.committed_end
        invalid = {**c,"commandId":"invalidate","commandType":"INVALIDATE_AFTER",
                   "payload":{"cutSample":cut,"reason":"AUDIENCE_ANSWER"}}
        await ex.invalidate(invalid)
        epoch = {**c,"commandId":"epoch","commandType":"BEGIN_EPOCH","timelineEpoch":2,
                 "payload":{"expectedPreviousEpoch":1,"newEpoch":2,
                            "originPosition":{"sampleIndex":cut},"reason":"AUDIENCE_ANSWER"}}
        await ex.begin_epoch(epoch)
        counts = (len(s.media_output.audio),len(s.media_output.video))
        await s.media_output.push_audio(old_audio);await s.media_output.push_video(old_video)
        self.assertEqual(counts,(len(s.media_output.audio),len(s.media_output.video)))
        self.assertFalse(ex.timeline.eligible(old,old_audio.startSample,old_audio.endSample))
        old=ex.current_identity;ex.fence("FORCE");self.assertFalse(ex.timeline.eligible(old,0,1))

    async def test_ready_failure_no_commit_no_output_and_unknown(self):
        s=await session();j=Journal();self.publisher(j);j.fail="SEGMENT_READY";ex=SegmentExecutor(s,1,j,lambda:None)
        c={"schemaVersion":"0.5","sessionId":"s","runEpoch":1,"timelineEpoch":1,
           "segmentId":"seg","narrationId":"n","commandId":"c","traceId":"trace",
           "commandType":"COMMIT_SEGMENT","lane":"NARRATION","payload":request().model_dump()}
        c["requestFingerprint"]=fingerprint(c);await ex.begin(c,{})
        with self.assertRaises(ConnectionError):await ex.task
        self.assertFalse(s.media_output.audio);self.assertFalse(s.media_output.video)
        self.assertTrue(ex.timeline.sealed);self.assertEqual(j.operations[-1]["operation"],"UNKNOWN")

    async def test_native_renderer_fail_closed_before_tts(self):
        s=await session();s.avatar_engine=SimpleNamespace()
        with self.assertRaisesRegex(RuntimeError,"immutable READY"):
            await stage_segment(s,request(),GenerationContext(1,"t","s","u"),lambda:None)

    async def test_tts_duration_cap_no_truncation(self):
        s=await session()
        class LongTTS:
            async def synthesize_stream(self,text,voice,ctx):
                for n in range(500):yield AudioChunk(ctx.generation_id,n,bytes(640))
        s.tts_provider=LongTTS()
        with self.assertRaisesRegex(ValueError,"SEGMENT_TOO_LONG"):
            await stage_segment(s,request(),GenerationContext(1,"t","s","u"),lambda:None)
        self.assertFalse(s.media_output.audio)

    async def test_bridge_cannot_invent_fact_or_cursor(self):
        class LLM:
            async def stream(self,r):yield "价格只要1元"
        self.assertEqual(await bridge_choice(LLM(),{},["","接着看看容量。"]),0)

    async def test_position_serialization_has_exact_pts(self):
        s=await session();ex=SegmentExecutor(s,1,Journal(),lambda:None)
        self.assertEqual(json_value(ex.timeline.position(48000))["ptsUs"],1000000)

    async def test_bound_runtime_rejects_untimed_before_first_after_finish_force(self):
        from app.config import Settings
        from app.events import MemoryEventPublisher
        from app.models import CreateSession
        from app.providers import MockLLMProvider,MockAvatarEngine,MockMediaOutput
        from app.session import SessionManager,RuntimeFailure
        from test_runtime import CREATE,utterance
        manager=SessionManager(Settings(),MemoryEventPublisher(),MockLLMProvider,MockTTSProvider,MockAvatarEngine,MockMediaOutput)
        self.addAsyncCleanup(manager.close);await manager.create_session(CreateSession(**CREATE));await asyncio.sleep(.01)
        await manager.start_session("session_1","trace");s=manager.get_session("session_1")
        class Bound:
            command=None
            def __init__(self):self.fences=[]
            def fence(self,reason):self.fences.append(reason)
        bound=Bound();s.continuity=bound
        for assigned in [None,{"lane":"NARRATION"},{"lane":"AUDIENCE_ANSWER"}]:
            bound.command=assigned
            with self.assertRaises(RuntimeFailure):await s.speak(utterance("plain",policy="NONE"))
            with self.assertRaisesRegex(RuntimeFailure,"new Session"):
                await s.speak(utterance("forced",policy="FORCE"))
        self.assertEqual(bound.fences,["OPERATOR_FORCE"]*3);self.assertFalse(s.speech_queue)
        await s.stop("trace");self.assertIn("SESSION_STOP",bound.fences)
        # A fresh separately captured compatibility Session uses an unbound sink.
        new={**CREATE,"sessionId":"ordinary"};await manager.create_session(CreateSession(**new));await asyncio.sleep(.01)
        await manager.start_session("ordinary","trace");ordinary=manager.get_session("ordinary")
        self.assertIsNone(ordinary.continuity);await ordinary.speak(utterance("legacy"));await asyncio.sleep(.05)
        self.assertTrue(any(e["eventType"]=="UTTERANCE_COMPLETED" and e.get("utteranceId")=="legacy" for e in manager.publisher.events))
