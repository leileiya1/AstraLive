import json,pathlib,wave,numpy as np,av
ROOT=pathlib.Path(__file__).parent;P=ROOT/'integration';r=[json.loads(x) for x in (P/'avatar-events.jsonl').read_text().splitlines()];job=next(x for x in r if x['event']=='BeginSpeechJob')
def wav(p):
 with wave.open(str(p)) as w:assert w.getframerate()==16000;return np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
source=wav(P/f"speech-{job['job_id']}.wav");heard=wav(P/'browser-sync/audio.wav');size=1<<(len(heard)+len(source)-2).bit_length();corr=np.fft.irfft(np.fft.rfft(heard,size)*np.conj(np.fft.rfft(source,size)),size)[:len(heard)-len(source)+1];index=int(np.argmax(corr));audio_start=index/16000
cos=float(corr[index]/(np.linalg.norm(source)*np.linalg.norm(heard[index:index+len(source)])))
container=av.open(str(P/'browser-sync/browser-received.webm'));first=None;last=None;frames=0;times=[]
for f in container.decode(video=0):
 frames+=1;image=f.to_ndarray(format='rgb24');h,w=image.shape[:2];marker=0
 # MediaRecorder started with a 256x256 black frame, so it scales later frames.
 for bit in range(16):
  x=int((bit*8+4)*w/512);y=int(4*h/512);pix=image[y,x]
  if int(pix[0])>int(pix[1]):marker|=1<<bit
 t=float(f.pts*f.time_base)
 if marker==job['marker']:
  if first is None:first=t
  last=t;times.append(t)
summary=dict(job_id=job['job_id'],marker=job['marker'],source_samples=len(source),recording_audio_samples=len(heard),audio_source_start_recording_s=audio_start,reference_audio_correlation=cos,first_talking_video_recording_s=first,last_talking_video_recording_s=last,video_minus_audio_start_ms=(first-audio_start)*1000 if first is not None else None,decoded_frames=frames,scope='recorded browser media after WebRTC; correlation against exact admitted 16k speech PCM',median_talking_frame_delta_ms=float(np.median(np.diff(times))*1000) if len(times)>1 else None)
(P/'browser-sync/av-sync-analysis.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
