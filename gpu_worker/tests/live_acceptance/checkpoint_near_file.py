"""Preserve sync thresholds/windows; move RTMP audit beside its source, not across VPN."""
import pathlib,subprocess,json,numpy as np,os,shutil
from sync_warped import warped_measure
REMOTE='/home/sapiece/AstraLive/experiments/real-avatar/'+os.environ['SOULX_FINAL_RUN_DIR']
def audit(out,label):
 out=pathlib.Path(out);capture=out/'runtime-capture';capture.mkdir(exist_ok=True)
 # Only small source PCM and numeric timing evidence cross the application tunnel.
 subprocess.run(['rsync','-a',f'school-linux:{REMOTE}/integration/',str(capture)+'/'],check=True,stdout=subprocess.DEVNULL,timeout=45)
 rows=[json.loads(x)for x in (capture/'avatar-events.jsonl').read_text().splitlines()];jobs=[];audio={}
 for x in rows:
  if x['event']=='AudioActuallyConsumed':audio.setdefault(x['job_id'],[]).append(x)
 for x in rows:
  if x['event']=='BeginSpeechJob'and(capture/f"speech-{x['job_id']}.wav").exists():jobs.append({'job_id':x['job_id'],'marker':x['marker'],'generation':x['business_generation_id'],'origin':x['first_sample_index'],'source':str(capture/f"speech-{x['job_id']}.wav"),'audio_events':audio.get(x['job_id'],[])})
 snap=out/('sync-'+label);snap.mkdir(exist_ok=True);target=snap/'browser-native.webm';shutil.copyfile(out/'browser-native.webm',target)
 native=warped_measure(target,jobs,native=True);target.unlink()
 # Measured compute bound, not a relaxed media timeout. Keep all remote windows.
 command=f'cd {REMOTE}; nice -n 10 /home/sapiece/AstraLive/runtime/.venv/bin/python remote_rtmp_audit.py {label}'
 result=subprocess.run(['ssh','-o','BatchMode=yes','school-linux',command],capture_output=True,text=True,check=True,timeout=300)
 rtmp=json.loads(result.stdout);summary={};reasons=[]
 for name,r in [('browser-native.webm',native),('rtmp-received.mkv',rtmp)]:
  p=r['absolute_offset_ms_percentiles'];trusted=[x for x in r['all_windows'] if x.get('correlation',0)>=.7];large=[x for x in r['over_250ms'] if x['correlation']>=.85 and x['correlation']>1.5*(x.get('second_peak_outside_100ms')or 0)]
  summary[name]={'trustedWindows':r['trusted_windows'],'medianP95MaxMs':p,'over250ms':r['over_250ms'],'audioPTSGaps':r['audio_pts_gaps'],'scope':'same-file recording audit; native on Mac, RTMP beside school-linux receiver, unchanged correlation'}
  if len(trusted)<10:reasons.append(name+': insufficient trusted source anchors')
  if p and p[1]>150:reasons.append(name+': recording P95 exceeds 150ms; playback attribution independent')
  if len(large)>=2:reasons.append(name+': multiple unique high-confidence >250ms windows')
  elif r['over_250ms']:summary[name]['requiresIndependentReview']=True
  (snap/(name+'.analysis.json')).write_text(json.dumps(r,indent=2))
 summary.update(passed=not reasons,reasons=reasons,allWindowsRetained=True,requestedCheckpoint=label,sourceJobs=len(jobs));(snap/'summary.json').write_text(json.dumps(summary,indent=2));return summary
