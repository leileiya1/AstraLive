import argparse,asyncio,json
from pathlib import Path
import httpx
from fastapi import FastAPI
from runtime.app.durable_live_journal import ExecutionInbox,OutputGate,router

parser=argparse.ArgumentParser()
parser.add_argument('snapshot',type=Path)
args=parser.parse_args()

class NoJournalEffect:
    producer='review-producer'
    async def query(self,*args):raise AssertionError('unsupported version reached journal')
    async def call(self,*args):raise AssertionError('unsupported version mutated journal')

async def main():
    async def forbidden(*args):raise AssertionError('unsupported version caused media/readiness effect')
    inbox=ExecutionInbox(NoJournalEffect(),OutputGate(forbidden),forbidden,guardian_id='review',readiness=forbidden)
    app=FastAPI();app.include_router(router(inbox,'x'*32))
    rows=json.loads((args.snapshot/'contracts/v0.5/durable-live-2/examples/protocol.json').read_text())
    command=next(x['request'] for x in rows if x['operationId']=='RuntimeExecute')
    results=[]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://runtime') as client:
        for prefix in ['durable-live','durable-live-2']:
            path='/internal/v0.5/'+prefix+'/sessions/'+command['sessionId']+'/commands'
            response=await client.post(path,json=command,headers={'Authorization':'Bearer '+'x'*32})
            results.append({'path':path,'status':response.status_code,'body':response.json()})
    assert [r['status'] for r in results]==[422,404]
    print(json.dumps({'layer':'real current v1 Runtime ASGI handler, CPU, no journal/media callbacks allowed','results':results},indent=2))
asyncio.run(main())
