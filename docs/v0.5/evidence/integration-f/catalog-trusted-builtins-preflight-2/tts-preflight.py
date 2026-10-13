import asyncio,json,pathlib,hashlib,subprocess
from app.real_tts import SherpaOnnxTTSProvider
from app.voice_stream import StreamingVoiceAdapter
from app.models import VoiceConfig
from app.providers import GenerationContext
root=pathlib.Path('/Users/sapiece/innovationProject/AstraLive-agent-f');out=root/'docs/v0.5/evidence/integration-f/catalog-trusted-builtins-preflight-2'
async def main():
 catalog=json.loads((root/'integration/v0.5/fixtures/real_golden_catalog.json').read_text());values=catalog['trustedBuiltinPreview'];cases=[]
 for k in ('name','price','stock','sizes'):
  text=catalog['facts'][k]
  assert '{{'+k+'}}' in text
  rendered=text.replace('{{'+k+'}}',values[k]);assert '{{' not in rendered
  cases.append({'kind':'actual_trusted_statement','factId':k,'template':text,'text':rendered})
 cases += [{'kind':'current_go_answer','factId':'price','text':'这款目前价格是 99.00 CNY。'}, {'kind':'current_go_answer','factId':'stock','text':'目前商品整体库存还有 20 件，各规格单独库存暂不可用。'}, {'kind':'current_go_answer','factId':'name','text':'这款是桌面整理指南。'}, {'kind':'current_go_bridge_choice','factId':None,'text':'说到这里，接下来看看下一项讲解内容。'}, {'kind':'current_go_bridge_choice','factId':None,'text':'这个问题也正好引出了下一项讲解内容，我们接着往下看。'}]
 provider=SherpaOnnxTTSProvider('/Users/sapiece/innovationProject/AstraLive/runtime/.local/vits-piper-zh_CN-xiao_ya-medium',0,2);adapter=StreamingVoiceAdapter(provider,'xiao_ya');rows=[]
 for index,case in enumerate(cases,1):
  samples=0;digest=hashlib.sha256()
  async for chunk in adapter.synthesize_stream(case['text'],VoiceConfig(voiceId='xiao_ya',provider='xiaoya'),GenerationContext(index,'trusted-builtin-check','not-live','case'+str(index))):
   assert chunk.sample_rate==16000 and chunk.channels==1;samples+=len(chunk.pcm)//2;digest.update(chunk.pcm)
  pad=(-samples)%640;rows.append({**case,'sourceSamples16k':samples,'padSamples':pad,'paddedSamples':samples+pad,'durationSeconds':(samples+pad)/16000,'prePadPCMSHA256':digest.hexdigest()});print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
 result={'scope':'PARTIAL_REAL_CPU_TTS_TRUSTED_BUILTINS_ANSWERS_BRIDGES_NOT_FULL_CATALOG_NOT_PUBLIC_START_NOT_GOLDEN','currentSource':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'nativeRate':provider.sample_rate,'sourceRate':16000,'provider':'SherpaOnnx xiao_ya medium CPU speaker0 speed1 threads2','fixtureSHA256':{n:hashlib.sha256((root/'integration/v0.5/fixtures'/n).read_bytes()).hexdigest() for n in ('real_golden_catalog.json','real_golden_smoke.json')},'rows':rows,'overEightSeconds':[r for r in rows if r['paddedSamples']>128000],'newFullNarrationSeconds':None,'unchanged136Rows':'Historical original TTS measurements only, not a new full synthesis pass','sqlTrustedPlaceholderPublicStart':'NOT_TESTED'}
 (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
asyncio.run(main())
