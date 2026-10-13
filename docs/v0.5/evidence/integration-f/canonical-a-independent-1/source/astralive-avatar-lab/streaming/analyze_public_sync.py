"""Browser-recorded audio is aligned with exact sample IDs in displayed frames.
Windowed correlation preserves inserted TTS gaps; WAV must honor recording PTS.
"""
import argparse,json,pathlib,wave,numpy as np,av
ap=argparse.ArgumentParser();ap.add_argument('run');ap.add_argument('--events',required=True);ap.add_argument('--video-file',default='browser-received.webm');ap.add_argument('--clock-summary',default='summary.json');args=ap.parse_args();run=pathlib.Path(args.run);rows=[json.loads(x) for x in pathlib.Path(args.events).read_text().splitlines()];jobs=[x for x in rows if x['event']=='BeginSpeechJob']
summary=json.loads((run/args.clock_summary).read_text());browser=[json.loads(x) for x in (run/'browser-events.jsonl').read_text().splitlines()];offset=summary['clockOffsetSchoolMinusBrowser'];start=min(x['browserMonotonic'] for x in browser if x['event']=='BrowserFrameDisplayed')+offset;end=max(x['browserMonotonic'] for x in browser)+offset;jobs=[x for x in jobs if start<=x['monotonic_s']<=end]
with wave.open(str(run/'browser-audio.wav')) as w:
 assert w.getframerate()==16000;heard=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
frames=[];container=av.open(str(run/args.video_file))
for f in container.decode(video=0):
 image=f.to_ndarray(format='rgb24');h,w=image.shape[:2]
 def bits(y,n):
  return sum((1<<b) for b in range(n) if int(image[(y+4)*h//512,(b*8+4)*w//512,0])>int(image[(y+4)*h//512,(b*8+4)*w//512,1]))
 frames.append(dict(t=float(f.pts*f.time_base),marker=bits(0,16),sequence=bits(8,24),generation=bits(16,16)))
result=[]
for job in jobs:
 p=pathlib.Path(args.events).parent/f"speech-{job['job_id']}.wav"
 if not p.exists():continue
 with wave.open(str(p)) as w:source=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
 jf=[x for x in frames if x['marker']==job['marker'] and x['generation']==job['business_generation_id']]
 for start in range(0,max(0,len(source)-8000),8000):
  ref=source[start:start+8000]
  if np.sqrt(np.mean(ref**2))<.015:continue
  matches=[x for x in jf if abs(x['sequence']*640-start)<=640]
  if not matches:continue
  target=min(matches,key=lambda x:abs(x['sequence']*640-start));estimate=target['t']-(target['sequence']*640-start)/16000
  lo=max(0,int((estimate-1)*16000));hi=min(len(heard),int((estimate+1.5)*16000));clip=heard[lo:hi].astype(np.float64);ref=ref.astype(np.float64)
  if len(clip)<len(ref):continue
  size=1<<(len(clip)+len(ref)-2).bit_length();corr=np.fft.irfft(np.fft.rfft(clip,size)*np.conj(np.fft.rfft(ref,size)),size)[:len(clip)-len(ref)+1]
  cumulative=np.concatenate(([0.0],np.cumsum(clip.astype(np.float64)**2)));energy=cumulative[len(ref):]-cumulative[:-len(ref)];reference_energy=float(np.sum(ref**2));valid=energy>max(1e-8,reference_energy*1e-4);normalized=np.full_like(corr,-1.0);normalized[valid]=corr[valid]/np.sqrt(energy[valid]*reference_energy);idx=int(np.argmax(normalized));score=float(normalized[idx]);audio=(lo+idx)/16000
  result.append(dict(job_id=job['job_id'],marker=job['marker'],source_sample=start,audio_recording_s=audio,video_recording_s=estimate,correlation=score,video_minus_audio_ms=(estimate-audio)*1000))
trusted=[x['video_minus_audio_ms'] for x in result if x['correlation']>=.7];out=dict(method='0.5s voiced reference windows, within +/-1s of sample-tagged received frame; recording audio PTS honored',video_input=args.video_file,windows=result,trusted_windows=len(trusted),threshold_correlation=.7,absolute_offset_ms_percentiles=np.percentile(np.abs(trusted),[50,95,100]).tolist() if trusted else None)
(run/'sync-analysis.json').write_text(json.dumps(out,indent=2));print(json.dumps({k:v for k,v in out.items() if k!='windows'}))
