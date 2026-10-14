"""Go-owned PG passes a real immutable command to CPU Runtime SegmentExecutor.

Synthetic PCM/lightweight avatar/fixture sink/journal are explicit test doubles.
Only the actual Runtime READY proof is returned; this is not native acceptance.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[2])]
from app.narration_segments import SegmentExecutor
from app.durable_events import DurableEventPublisher
from test_narration_segments import session,Journal

async def main():
    data=json.load(sys.stdin);command=data['command'];generation=data['generation']
    sess=await session();journal=Journal()
    original_request=journal.request
    async def request(method,path,payload):
        if path=='/media-start':return {'generationId':generation}
        return await original_request(method,path,payload)
    journal.request=request
    with tempfile.TemporaryDirectory(prefix="bridge-facts-spool-") as spool:
        publisher=DurableEventPublisher(journal,spool)
        try:
            executor=SegmentExecutor(sess,command["runEpoch"],journal,lambda:None)
            executor.timeline.epoch=command["timelineEpoch"]
            await executor.begin(command,{});await executor.task
        finally:await publisher.close()
    ready=next(record['proof'] for record in journal.operations if record['operation']=='SEGMENT_READY')
    assert ready['descriptor']['factIds']==[]
    assert ready['descriptor']['factVersion']==command['payload']['factVersion']
    json.dump({'scope':'CPU_RUNTIME_READY_PROOF_NOT_NATIVE','proof':ready},sys.stdout)

if __name__=='__main__':asyncio.run(main())
