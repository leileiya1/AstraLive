"""CPU FFmpeg serialization check, deliberately paired underflow; no acceptance Session."""
import asyncio,pathlib,os,tempfile,json,wave,numpy as np
from app.config import RTMPSettings
from app.providers import AudioChunk,VideoFrame
from app.soulx_rtmp_clock import PairedRTMPMediaOutput
import av
async def main():
 p=pathlib.Path(os.environ['SOULX_EXPERIMENT_DIR']);file=p/'paired-ffmpeg-test.flv'
 class Sink(PairedRTMPMediaOutput):
  def _command(self,v,a):return super()._command(v,a)[:-1]+[str(file)]
 s=Sink(RTMPSettings(enabled=True,url='rtmp://127.0.0.1:19355/live',stream_key='cpu-test',width=512,height=512,fps=25));await s.start()
 rng=np.random.default_rng(77);source=(rng.normal(0,.15,640*30)*32767).astype('<i2')
 for i in range(30):
  if i in [5,15]:await asyncio.sleep(.2)
  for part in [0,1]:await s.push_audio(AudioChunk(1,i*2+part,source[i*640+part*320:i*640+(part+1)*320].tobytes()))
  img=np.zeros((512,512,3),np.uint8);img[:]=[20,90,130]
  for b in range(8):img[:8,b*8:b*8+8]=[220,40,40] if i&(1<<b) else [40,220,40]
  await s.push_video(VideoFrame(1,i*40000,512,512,img.tobytes()))
 await asyncio.wait_for(s.drain(1),10);await asyncio.sleep(.08);await s.stop()
 heard=[];res=av.AudioResampler(format='s16',layout='mono',rate=16000)
 for f in av.open(str(file)).decode(audio=0):
  for a in res.resample(f):heard.append((int(round(float(a.pts*a.time_base)*16000)),a.to_ndarray().reshape(-1).astype(np.float32)/32768))
 a=np.zeros(max(t+len(x) for t,x in heard)+1)
 for t,x in heard:
  if t>=0:a[t:t+len(x)]=x
 frames={}
 for f in av.open(str(file)).decode(video=0):
  im=f.to_ndarray(format='rgb24');seq=sum(1<<b for b in range(8) if im[4,b*8+4,0]>im[4,b*8+4,1]);frames.setdefault(seq,float(f.pts*f.time_base))
 from sync_measure import correlate
 offsets=[]
 for i in range(1,30):
  r=correlate(source[i*640:(i+1)*640].astype(np.float32)/32768,a,frames[i]);offsets.append(r['video_minus_audio_ms'])
 result={'scope':'offline CPU serialization, intentional underflow, no GPU/full-stack claim','frames':len(frames),'offsetsMs':offsets,'maxAbsoluteMs':max(abs(x) for x in offsets),'pairCounters':s.diagnostics()};(p/'paired-ffmpeg-regression.json').write_text(json.dumps(result,indent=2));print(json.dumps({'frames':len(frames),'maxAbsoluteMs':result['maxAbsoluteMs']}));assert result['maxAbsoluteMs']<70
asyncio.run(main())
