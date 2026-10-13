import asyncio,json,pathlib,hashlib,time,sys
from app.real_tts import SherpaOnnxTTSProvider
from app.voice_stream import StreamingVoiceAdapter
from app.models import VoiceConfig
from app.providers import GenerationContext
BASE=pathlib.Path('/Users/sapiece/innovationProject/AstraLive-agent-f/integration/v0.5/fixtures')
OUT=pathlib.Path(__file__).resolve().with_name('repeat-measurement.json')
async def main():
 catalog=json.loads((BASE/'real_golden_catalog.json').read_text());short=json.loads((BASE/'real_golden_smoke.json').read_text())
 provider=SherpaOnnxTTSProvider('/Users/sapiece/innovationProject/AstraLive/runtime/.local/vits-piper-zh_CN-xiao_ya-medium',0,2)
 voice=VoiceConfig(voiceId='xiao_ya',provider='xiaoya');adapter=StreamingVoiceAdapter(provider,'xiao_ya')
 rows=[]
 for index,(fid,text) in enumerate(catalog['facts'].items(),1):
  samples=0;digest=hashlib.sha256();t=time.monotonic()
  async for chunk in adapter.synthesize_stream(text,voice,GenerationContext(index,'catalog-tts','catalog-only',fid)):
   assert chunk.sample_rate==16000 and chunk.channels==1
   samples+=len(chunk.pcm)//2;digest.update(chunk.pcm)
  pad=(-samples)%640
  rows.append({'factId':fid,'text':text,'sourceSamples16k':samples,'padSamples':pad,'paddedSamples':samples+pad,'durationSeconds':(samples+pad)/16000,'pcmSHA256':digest.hexdigest(),'synthesisWallSeconds':time.monotonic()-t})
  if index%10==0:print(index,'measured',flush=True)
 answers=['这款目前价格是 99 CNY。','目前商品整体库存还有 20 件，各规格单独库存暂不可用。','这款商品叫桌面整理指南。']
 answerrows=[]
 for i,text in enumerate(answers,1):
  samples=0
  async for chunk in adapter.synthesize_stream(text,voice,GenerationContext(200+i,'catalog-answer-tts','catalog-only','answer'+str(i))):samples+=len(chunk.pcm)//2
  padded=samples+(-samples)%640;answerrows.append({'text':text,'sourceSamples16k':samples,'paddedSamples':padded,'durationSeconds':padded/16000})
 shortids=set(short['facts']);shortrows=[r for r in rows if r['factId'] in shortids]
 result={'scope':'REAL_LOCAL_CPU_SHERPA_TTS_ONLY_NOT_GOLDEN','runtimeRoot':'/Users/sapiece/innovationProject/AstraLive-agent-f/runtime','nativeSampleRate':provider.sample_rate,'resampleRate':16000,'provider':'sherpa-onnx xiao_ya medium','speakerId':0,'speed':1.0,'numThreads':2,'fixtureSHA256':{n:hashlib.sha256((BASE/n).read_bytes()).hexdigest() for n in ('real_golden_catalog.json','real_golden_smoke.json')},'rows':rows,'longNarrationSeconds':sum(r['durationSeconds'] for r in rows),'shortNarrationSeconds':sum(r['durationSeconds'] for r in shortrows),'shortMeasurement':'reuse exact shared sentence measurements from long catalog; no separate TTS replay','overEightSeconds':[r for r in rows if r['paddedSamples']>128000],'answerRows':answerrows}
 OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('longNarrationSeconds','shortNarrationSeconds','overEightSeconds','answerRows')},ensure_ascii=False),flush=True)
asyncio.run(main())
