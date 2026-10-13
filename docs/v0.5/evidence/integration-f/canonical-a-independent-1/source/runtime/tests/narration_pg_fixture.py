"""Executed by Go PG integration test; synthetic PCM, explicit sink fixture.

Uses production C executor, A HTTP auth+journal and B Timeline, without claiming
browser/RTMP/GPU or actual audience observation. Fixture routes are TEST ONLY.
"""
import asyncio
import json
import sys
import time
import tempfile
import random
from types import SimpleNamespace
import httpx

from app.durability_client import DurabilityClient
from app.narration import NarrationCommands
from test_narration_segments import session


class Language:
    async def stream(self,request):
        yield "1"


async def main():
    base,token=sys.argv[1:3];phase=sys.argv[3] if len(sys.argv)>3 else "";journal=DurabilityClient(base,token)
    from app.durable_events import DurableEventPublisher
    spool_dir=tempfile.TemporaryDirectory();publisher=DurableEventPublisher(journal,spool_dir.name)
    s=await session();s.context=SimpleNamespace(systemPrompt="自然亲切");s.llm=Language();s.tool_client=None
    if phase=="EXPIRED":
        from app.providers import AudioChunk
        class SlowBoundaryTTS:
            async def synthesize_stream(self,text,voice,ctx):
                for sequence in range(100):yield AudioChunk(ctx.generation_id,sequence,bytes(640))
        s.tts_provider=SlowBoundaryTTS()
    manager=SimpleNamespace(sessions={"s":s},get_session=lambda sid:s)
    adapter=NarrationCommands(journal,None,manager)
    adapter.runs["s"]={"epoch":1,"deadline":time.monotonic()+60,"sealed":False,"barrier":0}
    from app.narration_segments import SegmentExecutor
    real=phase in {"MEDIA","MEDIA_SOAK"};soak=phase=="MEDIA_SOAK";mark=close=None
    if real:
        from narration_real_sinks import open_sinks
        sinks,mark,close=await open_sinks(s,journal,lambda:adapter.check("s",1),sys.argv[4])
    else:s.continuity=SegmentExecutor(s,1,journal,lambda:adapter.check("s",1))
    selected=False;installed=0;narration_installed=0;questions=0
    seed=20261011
    positions=[4]+sorted(random.Random(seed).sample(range(25,175),4)) if soak else [4 if real else 1]
    prompts=["多少钱？","库存有多少？","商品价格和库存分别是多少？","现在还有库存吗？","价格多少钱？"]
    async with httpx.AsyncClient(base_url=base,trust_env=False) as client:
        if real:
            response=await client.post("/fixture/start",json=sinks);response.raise_for_status()
        original=journal.request
        async def pause():
            print("KILL_READY:"+phase,flush=True)
            await asyncio.Event().wait()
        async def record(method,path,payload=None):
            nonlocal selected,installed,narration_installed,questions
            if path=="/timeline-record":
                op=payload["operation"]
                if (phase=="ANSWER_PREPARING" and op=="ANSWER_PREPARED") or (phase=="RESUME_PREPARING" and op=="RESUME_PREPARED"):
                    await pause()
            result=await original(method,path,payload)
            if path=="/timeline-record" and payload["operation"]=="COMMIT_INSTALLED":installed+=1
            if path=="/timeline-record" and payload["operation"]=="COMMIT_INSTALLED" and payload["command"]["lane"]=="NARRATION":narration_installed+=1
            if path=="/timeline-record" and payload["operation"]=="COMMIT_INSTALLED" and payload["command"]["lane"]=="NARRATION" and questions<len(positions) and narration_installed==positions[questions]:
                selected=True
                response=await client.post("/fixture/select",params={"question":prompts[questions]});response.raise_for_status();questions+=1
                if real:await mark({"lane":"COMMENT_SELECTED","commandId":response.json()["scheduler"]["current"]["event"]["eventId"],"segmentId":""})
                if phase=="SUSPEND_PENDING":await pause()
            if (path=="/timeline-record" and phase=="SUSPENDED" and
                    payload["operation"] in {"SUSPEND_REQUESTED","SEGMENT_COMPLETED"} and
                    (await client.get("/fixture/snapshot")).json()["state"]=="SUSPENDED"):
                await pause()
            if path=="/timeline-record" and (
                (phase=="ANSWERING" and payload["operation"]=="COMMIT_INSTALLED" and payload["command"]["lane"]=="AUDIENCE_ANSWER")):
                await pause()
            return result
        journal.request=record
        kinds=[]
        for _ in range(150000 if soak else 15000 if real else 600):
            response=await client.get("/fixture/next")
            if response.status_code!=204:
                response.raise_for_status();command=response.json();kinds.append(command["commandType"])
                if real and command["commandType"]=="COMMIT_SEGMENT":await mark(command)
                await adapter.execute(command)
                ack=await client.post("/fixture/ack",json={"commandId":command["commandId"]});ack.raise_for_status()
            snapshot=(await client.get("/fixture/snapshot")).json()
            if snapshot["reason"]=="FINISHED":
                assert snapshot["cursor"]["nextOrdinal"]==(200 if soak else 20 if real else 3)
                assert "SUSPEND_AT_BOUNDARY" in kinds
                if phase=="EXPIRED":
                    assert "START_AUDIENCE_ANSWER" not in kinds and "PREPARE_RESUME_BRIDGE" not in kinds
                else:assert "PREPARE_RESUME_BRIDGE" in kinds
                print(json.dumps({"provenance":"SYNTHETIC_PCM_FIXTURE_SINK_REAL_POSTGRES_HTTP",
                    "commands":kinds,"factIds":snapshot["cursor"]["completedFactIds"],"timelineEpoch":snapshot["timelineEpoch"],
                    "audienceAudible":False,"questions":questions,"randomSeed":seed if soak else None,"injectionOrdinals":positions},ensure_ascii=False));break
            if s.continuity.task and s.continuity.task.done():
                s.continuity.task.result()
            if snapshot["state"]=="RECOVERY_REQUIRED":raise RuntimeError(snapshot)
            await asyncio.sleep(.01)
        else:raise RuntimeError("fixture loop timed out: "+json.dumps(snapshot,ensure_ascii=False))
        if adapter.tasks:await asyncio.gather(*adapter.tasks)
        if real:await close()
    await journal.close()
    await publisher.close();spool_dir.cleanup()


async def run():
    try:await main()
    finally:
        module=sys.modules.get("narration_real_sinks")
        if module:await module.cleanup()

if __name__=="__main__":asyncio.run(run())
