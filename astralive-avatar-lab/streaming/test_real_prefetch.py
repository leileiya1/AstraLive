"""Real COMMENT content -> existing LLM/TTS -> Worker -> paced school consumer.
This is NOT a browser or commercial Session acceptance.
"""
import asyncio,json,os,pathlib,sys,time,wave
ROOT=pathlib.Path(__file__).parent;sys.path.insert(0,'/home/sapiece/AstraLive/runtime')
from app.providers import OpenAICompatibleLLMProvider,LLMRequest,GenerationContext
from app.models import VoiceConfig
from app.real_tts import SherpaOnnxTTSProvider
from app.session import sentence_stream
from async_link import WorkerLink
from prefetch import PrefetchPipeline,PCM
from resample import resampled
RUN=ROOT/'network'/os.environ.get('REAL_PREFETCH_RUN','real-prefetch');RUN.mkdir(parents=True,exist_ok=True)
logfile=(RUN/'events.jsonl').open('w',buffering=1)
rows=[]
def log(event,**kw):
    r=dict(event=event,monotonic_s=time.monotonic(),**kw);rows.append(r);logfile.write(json.dumps(r,ensure_ascii=False)+'\n')
async def main():
    summary=dict(status='RUNNING',scope='real LLM/TTS/Worker paced file consumer; no browser/Session/WebRTC/RTMP')
    (RUN/'summary.json').write_text(json.dumps(summary,indent=2))
    llm=OpenAICompatibleLLMProvider('https://api.deepseek.com',os.environ['LLM_API_KEY'],'deepseek-flash',max_tokens=1024)
    log('TTSModelLoadStart');tts=SherpaOnnxTTSProvider('/home/sapiece/AstraLive/runtime/.local/vits-piper-zh_CN-xiao_ya-medium',num_threads=2);log('TTSModelLoaded')
    link=WorkerLink(ROOT/'.private/token',log);await link.connect()
    pipeline=PrefetchPipeline(link,int(os.environ.get('REAL_PREFETCH_GENERATION','100001')),1)
    context=GenerationContext(1,'soulx-real-prefetch','soulx-real-prefetch','comment-real-prefetch')
    source=LLMRequest('请用两句话欢迎观众，然后说现在正在验证数字人实时画面。','你是实验直播间讲解员，只说自然简短中文。','没有商品资料，不谈价格库存。')
    first_token=None;native_samples=0;sentences=[]
    async def tokens():
        nonlocal first_token
        log('COMMENT_Received',source='COMMENT',text=source.text)
        async for delta in llm.stream(source):
            if first_token is None:first_token=time.monotonic();log('LLMFirstToken')
            yield delta
    async def native():
        nonlocal native_samples
        for_count=0
        with wave.open(str(RUN/'native-tts.wav'),'wb') as capture:
            capture.setnchannels(1);capture.setsampwidth(2);capture.setframerate(tts.sample_rate)
            async for sentence in sentence_stream(tokens()):
                sentences.append(sentence);log('TTSBeginSentence',sentence_sequence=len(sentences)-1,text=sentence)
                async for chunk in tts.synthesize_stream(sentence,VoiceConfig(voiceId='xiao-ya'),context):
                    if native_samples==0:log('FirstNativePCM',sample_rate=chunk.sample_rate)
                    native_samples+=len(chunk.pcm)//2;capture.writeframesraw(chunk.pcm)
                    for_count+=1;yield PCM(1,chunk.pcm,chunk.sample_rate,chunk.channels)
            log('NativeAudioEOF',native_samples=native_samples,source_chunks=for_count)
    encoder=await asyncio.create_subprocess_exec('/usr/bin/ffmpeg','-nostdin','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','512x512','-r','25','-i','pipe:0','-c:v','libx264','-preset','ultrafast','-tune','zerolatency','-bf','0','-g','25','-pix_fmt','yuv420p',str(RUN/'video.mp4'),stdin=asyncio.subprocess.PIPE)
    count=frames=0;clock=None;maximum_lag=0;errors=[]
    try:
        with wave.open(str(RUN/'playout-pcm.wav'),'wb') as capture:
            capture.setnchannels(1);capture.setsampwidth(2);capture.setframerate(16000)
            async for chunk in pipeline.stream(resampled(native(),1)):
                if clock is None:clock=time.monotonic();log('FirstPacedPCMRelease')
                due=clock+count/16000;await asyncio.sleep(max(0,due-time.monotonic()))
                out=await pipeline.render(chunk)
                maximum_lag=max(maximum_lag,max(0,time.monotonic()-due))
                capture.writeframesraw(chunk.pcm);count+=len(chunk.pcm)//2
                for packet in out:
                    if frames==0:log('FirstPacedVideoConsumer')
                    encoder.stdin.write(packet['rgb']);await encoder.stdin.drain()
                    frames+=1;await link.consumed(packet)
                    log('Consumed',frame_sequence=packet['frame_sequence'],pts_us=packet['pts_us'])
        encoder.stdin.close();await encoder.wait()
        if encoder.returncode:raise RuntimeError('review encoder failure')
        merge=await asyncio.create_subprocess_exec('/usr/bin/ffmpeg','-nostdin','-y','-v','error','-i',str(RUN/'video.mp4'),'-i',str(RUN/'playout-pcm.wav'),'-c:v','copy','-c:a','aac','-shortest',str(RUN/'real-comment-tts-worker.mp4'))
        if await merge.wait():raise RuntimeError('mux failure')
        verify=await asyncio.create_subprocess_exec('/usr/bin/ffmpeg','-nostdin','-v','error','-i',str(RUN/'real-comment-tts-worker.mp4'),'-f','null','-')
        if await verify.wait():raise RuntimeError('decode failure')
        summary['status']='REAL_PREFETCH_MECHANICAL_PASS' if maximum_lag<.040 else 'LATENCY_NOT_PASS'
    except Exception as e:
        summary['status']='FAILED';errors.append(repr(e));print(repr(e),flush=True)
        if encoder.returncode is None:encoder.kill();await encoder.wait()
    finally:
        await pipeline.cancel();await link.close()
        native_first=next((e['monotonic_s'] for e in rows if e['event']=='FirstNativePCM'),None)
        summary.update(worker_epoch=link.epoch,source='COMMENT',llm_model='deepseek-flash',tts='sherpa-onnx/xiao-ya',native_sample_rate=tts.sample_rate,native_samples=native_samples,playout_samples=count,gpu_decoded_consumed_frames=frames,eof_padding_samples=pipeline.eof_pad_samples,audio_queue_peak_ms=pipeline.audio.peak/16,maximum_pacing_lag_ms=maximum_lag*1000,errors=errors,sentences=sentences,first_native_pcm_to_stage_s={key:next((e['monotonic_s']-native_first for e in rows if e['event']==key),None) if native_first else None for key in ['WorkerFrameDecoded','FirstPacedPCMRelease','FirstPacedVideoConsumer']})
        (RUN/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False),flush=True);logfile.close()

asyncio.run(main())
