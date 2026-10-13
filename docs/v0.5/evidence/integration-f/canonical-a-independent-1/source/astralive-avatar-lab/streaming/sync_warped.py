"""Account for actual media underflow without deleting source windows.

A source PCM window need not be contiguous in playback. Native reference timing
uses same-host audio-consumption observations, independent of recorded audio.
RTMP reference timing uses the paired clock's video presentation cadence; that
clock emits exactly 640 source samples per new source frame. Neither path uses
an observed audio offset to construct the reference. All incomplete/unvoiced or
ambiguous measurements remain in the evidence.
"""
import pathlib,json,wave,collections
import numpy as np
from sync_measure import audio,frames,correlate

def cadence_reference(source,start,quantum,positions):
 indices=[round((t-positions[0])*16000/quantum)*quantum for t in positions];duplicates=0
 for i in range(1,len(indices)):
  if indices[i]<indices[i-1]+quantum:indices[i]=indices[i-1]+quantum;duplicates+=1
 ref=np.zeros(indices[-1]+quantum,np.float32)
 for idx,pos in zip(indices,range(start,start+quantum*len(positions),quantum)):
  part=source[pos:pos+quantum];ref[idx:idx+len(part)]=part
 return ref,indices,duplicates

def warped_measure(path,jobs,native=True):
 heard,gaps=audio(path);fs=frames(path);rows=[]
 for job in jobs:
  with wave.open(str(job['source'])) as w:source=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32)/32768
  jf=[x for x in fs if x['marker']==job['marker'] and x['generation']==job['generation']];first={}
  for f in jf:first.setdefault(f['sequence'],f['t'])
  schedule={x['first_sample_index']-job['origin']:x['consumed_monotonic_s'] for x in job.get('audio_events',[])}
  quantum=320 if native else 640
  for start in range(0,max(0,len(source)-7680),7680):
   base={'job_id':job['job_id'],'source_sample':start,'window_samples':7680}
   if start//640 not in first:rows.append({**base,'status':'no_video_anchor'});continue
   anchor=first[start//640];parts=[];positions=[];missing=[]
   for pos in range(start,start+7680,quantum):
    stamp=schedule.get(pos) if native else first.get(pos//640)
    if stamp is None:missing.append(pos)
    else:positions.append(stamp);parts.append(source[pos:pos+quantum])
   if missing:rows.append({**base,'status':'missing_timing_schedule','missing_samples':missing});continue
   ref,indices,duplicates=cadence_reference(source,start,quantum,positions)
   rms=float(np.sqrt(np.mean(source[start:start+7680]**2)))
   if rms<.015:rows.append({**base,'status':'unvoiced','rms':rms});continue
   match=correlate(ref,heard,anchor,tail_seconds=max(1.5,len(ref)/16000+1.5))
   if not match:rows.append({**base,'status':'insufficient_recording_range','reference_playback_seconds':len(ref)/16000});continue
   if match:rows.append({**base,'status':'measured','video_recording_s':anchor,'rms':rms,'reference_playback_seconds':len(ref)/16000,'timing_collision_count':duplicates,**match})
 trusted=[x for x in rows if x.get('correlation',0)>=.7];offsets=[x['video_minus_audio_ms'] for x in trusted]
 return {'path':str(path),'method':'frame-aligned 480ms exact PCM references expanded by independently observed underflow cadence; no audio-derived timing correction','cadence_source':'school same-host audio consumption (20ms quantized)' if native else 'source-paired RTMP video cadence (40ms quantum)','all_windows':rows,'window_status_counts':dict(collections.Counter(x['status'] for x in rows)),'trusted_windows':len(trusted),'absolute_offset_ms_percentiles':np.percentile(np.abs(offsets),[50,95,100]).tolist() if offsets else None,'audio_pts_gaps':gaps,'over_250ms':[x for x in trusted if abs(x['video_minus_audio_ms'])>250]}
if __name__=='__main__':
 import sys
 p=pathlib.Path(sys.argv[1]);capture=p/'runtime-capture' if (p/'runtime-capture').exists() else p;rows=[json.loads(x) for x in (capture/'avatar-events.jsonl').read_text().splitlines()];jobs=[]
 for x in rows:
  if x['event']=='BeginSpeechJob' and (capture/f"speech-{x['job_id']}.wav").exists():jobs.append({'job_id':x['job_id'],'marker':x['marker'],'generation':x['business_generation_id'],'origin':x['first_sample_index'],'source':str(capture/f"speech-{x['job_id']}.wav"),'audio_events':[a for a in rows if a['event']=='AudioActuallyConsumed' and a['job_id']==x['job_id']]})
 out={}
 for f in ['browser-native.webm','browser-canvas.webm','rtmp-received.mkv']:
  out[f]=warped_measure(p/f,jobs,native=f!='rtmp-received.mkv');print(f,out[f]['trusted_windows'],out[f]['absolute_offset_ms_percentiles'],len(out[f]['over_250ms']),flush=True)
 (p/'cadence-aware-sync.json').write_text(json.dumps(out,indent=2))
