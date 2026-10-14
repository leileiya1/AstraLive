import asyncio,copy,hashlib,json,os,subprocess,sys,time
from pathlib import Path
repo=Path('/Users/sapiece/innovationProject/AstraLive-agent-f')
source=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
files=['runtime/app/narration_segments.py','runtime/app/session_binding.py','runtime/app/providers.py']
for name in files:
 assert (repo/name).read_bytes()==subprocess.check_output(['git','-C',str(repo),'show',source+':'+name])
folder=Path('/private/tmp/astralive-f-bridge-provider-preflight-2');folder.mkdir(exist_ok=False,mode=0o700)
os.environ['ASTRALIVE_STAGING_OBSERVER_DIR']=str(folder/'llm')
sys.path[:0]=[str(repo/'runtime'),str(repo)]
from app.session_binding import BoundDeepSeek
from app.narration_segments import bridge_choice,bridge_language_context
raw=Path('/private/tmp/astralive-f-real-hour-tcp-6/media/sql-proof.json').read_bytes();s=json.loads(raw)
n=s['narrations'][0]['document_json'];p=n['plan'];t=next(x['document_json'] for x in s['turns'] if x['turn_id']==n['turn']['interactionTurnId']);resume=n['resumePoint'];completed=n['cursor']['completedFactIds']
pending=[]
for beat in p['beats']:
 for f in beat['requiredFactIds']:
  if f not in completed and f not in pending:pending.append(f)
context={'goal':p['beats'],'lastCompletedText':resume['cursor']['lastCompletedText'],'question':t['question'],'committedAnswer':t['answerText'],'completedFactIds':completed,'pendingRequiredFactIds':pending,'nextBeatId':resume['nextBeatId'],'style':p['style'],'productId':p['productId'],'factVersion':p['factVersion'],'latestFacts':s['productSnapshots'][0]['productSnapshot']}
original=copy.deepcopy(context);projected=bridge_language_context(context)
choices=['','说到这里，接下来看看下一项讲解内容。','这个问题也正好引出了下一项讲解内容，我们接着往下看。']
cfg=json.loads(Path('/private/tmp/astralive-f-real-hour-tcp-6/media/observer/result.json').read_text())['profiles']['LLM']['config']
key=Path('/Users/sapiece/innovationProject/AstraLive/astralive-avatar-lab/streaming/.private/deepseek-api-key').read_text().strip()
report={'source':source,'scope':'real bound DeepSeek component only; language context reconstructed from original owned hour5 SQL; no fresh tool refresh, Session command, GPU or AV acceptance','originalSQLSHA256':hashlib.sha256(raw).hexdigest(),'originalContextBytes':len(json.dumps(context,ensure_ascii=False).encode()),'projectedContextBytes':len(json.dumps(projected,ensure_ascii=False).encode()),'promptBodiesPersisted':False,'model':cfg['model'],'maxTokens':cfg['maxTokens'],'deadlineSeconds':8,'calls':[],'status':'RUNNING'}
async def main():
 llm=BoundDeepSeek(cfg,key,{'errorCode':''},staging_bridge_enabled=True)
 try:
  for i in range(25):
   began=time.monotonic()
   try:
    async with asyncio.timeout(8):choice=await bridge_choice(llm,context,choices)
    report['calls'].append({'sequence':i+1,'choice':choice,'durationSeconds':time.monotonic()-began,'status':'PASS'})
   except Exception as e:
    report['calls'].append({'sequence':i+1,'errorType':type(e).__name__,'durationSeconds':time.monotonic()-began,'status':'FAIL'});raise
  assert context==original
  report['status']='PASS'
 finally:
  await llm.aclose()
  (folder/'result.json').write_text(json.dumps(report,indent=2)+'\n')
asyncio.run(main());print(json.dumps(report))
