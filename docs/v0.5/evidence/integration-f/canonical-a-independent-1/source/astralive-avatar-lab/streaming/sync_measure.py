"""Source-sample marker correlation with intact recording PTS. Keep every window."""
import json,pathlib,wave
import av,numpy as np

def audio(path):
 c=av.open(str(path));rs=av.AudioResampler(format='s16',layout='mono',rate=16000);pieces=[];gaps=[];last=None
 for frame in c.decode(audio=0):
  t=float(frame.pts*frame.time_base)
  if last is not None and abs(t-last)>.004:gaps.append({'time_s':t,'gap_s':t-last})
  last=t+frame.samples/frame.sample_rate
  for f in rs.resample(frame):pieces.append((round(float(f.pts*f.time_base)*16000),f.to_ndarray().reshape(-1).astype(np.float32)/32768))
 for f in rs.resample(None):pieces.append((round(float(f.pts*f.time_base)*16000),f.to_ndarray().reshape(-1).astype(np.float32)/32768))
 out=np.zeros(max(i+len(a) for i,a in pieces)+1,np.float32)
 for i,a in pieces:
  if i<0:a=a[-i:];i=0
  out[i:i+len(a)]=a
 return out,gaps

def frames(path,synthetic=False):
 out=[]
 for f in av.open(str(path)).decode(video=0):
  h,w=f.height,f.width
  plane=f.planes[2];chroma=np.frombuffer(plane,dtype=np.uint8).reshape(plane.height,plane.line_size)
  def bits(row,n):
   base=192 if synthetic else 512
   return sum(1<<b for b in range(n) if chroma[((4 if synthetic else row+4)*h//base)//2,((b*8+4)*w//base)//2]>128)
  out.append({'t':float(f.pts*f.time_base),'marker':1 if synthetic else bits(0,16),'sequence':bits(0 if synthetic else 8,24),'generation':1 if synthetic else bits(16,16)})
 return out

def correlate(ref,heard,estimate,tail_seconds=1.5):
 lo=max(0,int((estimate-1)*16000));hi=min(len(heard),int((estimate+tail_seconds)*16000));clip=heard[lo:hi].astype(np.float64);ref=ref.astype(np.float64)
 if len(clip)<len(ref):return None
 size=1<<(len(clip)+len(ref)-2).bit_length();corr=np.fft.irfft(np.fft.rfft(clip,size)*np.conj(np.fft.rfft(ref,size)),size)[:len(clip)-len(ref)+1];cs=np.r_[0,np.cumsum(clip**2)];energy=cs[len(ref):]-cs[:-len(ref)];re=float(np.sum(ref**2));valid=energy>max(1e-8,re*1e-4);score=np.full_like(corr,-1.);score[valid]=corr[valid]/np.sqrt(energy[valid]*re);idx=int(np.argmax(score));mask=np.abs(np.arange(len(score))-idx)>1600;second=float(np.max(score[mask])) if mask.any() else None
 return {'audio_recording_s':(lo+idx)/16000,'correlation':float(score[idx]),'second_peak_outside_100ms':second,'video_minus_audio_ms':(estimate-(lo+idx)/16000)*1000}

def measure(path,jobs,synthetic=False,window_samples=8000,stride_samples=8000):
 heard,gaps=audio(path);fs=frames(path,synthetic);rows=[];missing=[]
 for job in jobs:
  if not pathlib.Path(job['source']).exists():missing.append(job);continue
  if str(job['source']).endswith('.npy'):source=np.load(job['source'])[::3].astype(np.float32)/32768
  else:
   with wave.open(str(job['source'])) as w:
    assert w.getframerate()==16000
    source=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
  jf=[x for x in fs if x['marker']==job['marker'] and x['generation']==job['generation']]
  for start in range(0,max(0,len(source)-window_samples),stride_samples):
   ref=source[start:start+window_samples];rms=float(np.sqrt(np.mean(ref**2)))
   if rms<.015:rows.append({'job_id':job['job_id'],'source_sample':start,'status':'unvoiced','rms':rms});continue
   candidates=[x for x in jf if abs(x['sequence']*640-start)<=640]
   if not candidates:rows.append({'job_id':job['job_id'],'source_sample':start,'status':'no_video_anchor','rms':rms});continue
   f=min(candidates,key=lambda x:abs(x['sequence']*640-start));estimate=f['t']-(f['sequence']*640-start)/16000;result=correlate(ref,heard,estimate)
   if result:rows.append({'job_id':job['job_id'],'source_sample':start,'video_recording_s':estimate,'rms':rms,**result,'status':'measured'})
 trusted=[x['video_minus_audio_ms'] for x in rows if x.get('correlation',0)>=.7];return {'path':str(path),'method':f'same-file PTS preserved, exact source PCM {window_samples/16000}s windows, stride {stride_samples/16000}s, video sequence markers; every window retained','windows':rows,'audio_pts_gaps':gaps,'missing_sources':missing,'trusted_windows':len(trusted),'absolute_offset_ms_percentiles':np.percentile(np.abs(trusted),[50,95,100]).tolist() if trusted else None}
if __name__=='__main__':
 p=pathlib.Path(__file__).parent/'integration/soulx-final-one-hour/cpu-clock';out={}
 for f in p.glob('*.webm'):
  r=measure(f,[{'job_id':1,'marker':1,'generation':1,'source':str(p/'source.npy')}],True);out[f.stem]=r;print(f.stem,r['absolute_offset_ms_percentiles'],r['audio_pts_gaps'])
 (p/'analysis.json').write_text(json.dumps(out,indent=2))
