import asyncio,hashlib,json,time
from pathlib import Path
import httpx
ROOT=Path('/private/tmp/astralive-f-real-golden-pilot-tcp-7/media')
x=json.loads((ROOT/'sql-proof.json').read_text());d=x['narrations'][0]['document_json'];fixture=json.loads((ROOT.parent/'authored-fixture.json').read_text());product=fixture['product']
context={'goal':d['plan']['beats'],'lastCompletedText':d['resumePoint']['cursor']['lastCompletedText'],'question':d['turn']['question'],'committedAnswer':d['turn']['answerText'],'completedFactIds':d['cursor']['completedFactIds'],'pendingRequiredFactIds':[f for b in d['plan']['beats'] for f in b['requiredFactIds'] if f not in d['cursor']['completedFactIds']],'nextBeatId':d['resumePoint']['nextBeatId'],'style':d['plan']['style'],'productId':d['plan']['productId'],'factVersion':d['plan']['factVersion'],'latestFacts':{'ok':True,'data':{'productId':d['plan']['productId'],**product}}}
choices=['','说到这里，接下来看看下一项讲解内容。','这个问题也正好引出了下一项讲解内容，我们接着往下看。']
messages=[{'role':'system','content':'你只选择口语过渡，不决定哪些事实已经完成。不重复已讲卖点；必要时选空过渡。'},{'role':'system','content':'只回复简洁自然的口语。商品库存、价格等动态事实只能依据已提供的 Tool Facts；缺失或不可用时直接说明暂时查不到，不得猜测。'},{'role':'system','content':'Tool Facts:\n商品事实只用于理解上下文，禁止自行添加。'},{'role':'user','content':'选择自然的过渡语，只返回选项序号。上下文：'+json.dumps(context,ensure_ascii=False)+'；选项：'+json.dumps(choices,ensure_ascii=False)}]
async def main():
 key=Path('/Users/sapiece/innovationProject/AstraLive/astralive-avatar-lab/streaming/.private/deepseek-api-key').read_text().strip()
 out=Path(__file__).parent;result={'scope':'REAL_LLM_SSE_METADATA_ONLY_RECONSTRUCTED_DEMO_BRIDGE_NO_GPU_SINK_LIVE','primaryDocs':'https://api-docs.deepseek.com/guides/thinking_mode/','reasoningContentStored':False,'cases':[]}
 async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=20) as client:
  for name,budget,disabled in [('original-default-256',256,False),('default-1024',1024,False),('explicit-disabled-256',256,True)]:
   payload={'model':'deepseek-flash','stream':True,'max_tokens':budget,'messages':messages}
   if disabled:payload['thinking']={'type':'disabled'}
   row={'name':name,'maxTokens':budget,'thinking':'explicit_disabled' if disabled else 'provider_default','requestSHA256':hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest(),'reasoningChars':0,'contentChars':0,'finishReasons':[],'done':False};start=time.monotonic()
   try:
    async with client.stream('POST','https://api.deepseek.com/chat/completions',headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=payload) as response:
     row['httpStatus']=response.status_code
     if response.status_code==200:
      async for line in response.aiter_lines():
       if not line.startswith('data:'):continue
       raw=line[5:].strip()
       if raw=='[DONE]':row['done']=True;break
       if not raw:continue
       packet=json.loads(raw)
       for choice in packet.get('choices',[]):
        delta=choice.get('delta',{});row['contentChars']+=len(delta.get('content') or '');row['reasoningChars']+=len(delta.get('reasoning_content') or '')
        reason=choice.get('finish_reason')
        if reason is not None:row['finishReasons'].append(reason if reason in ['stop','length','content_filter','tool_calls'] else 'OTHER')
       usage=packet.get('usage')
       if usage:row['usage']={k:usage[k] for k in ['prompt_tokens','completion_tokens','total_tokens'] if type(usage.get(k)) is int}
    row['outcome']='COMPLETE_CONTENT' if row.get('httpStatus')==200 and row['done'] and row['finishReasons']==['stop'] and row['contentChars'] else 'FAILED_OR_INCOMPLETE'
   except Exception as error:row['outcome']='FAILED';row['errorType']=type(error).__name__
   row['durationMs']=round((time.monotonic()-start)*1000);result['cases'].append(row);(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(row),flush=True)
asyncio.run(main())
