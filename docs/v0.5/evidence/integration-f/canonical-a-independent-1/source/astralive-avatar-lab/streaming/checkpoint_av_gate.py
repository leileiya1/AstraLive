"""Same-session offline sync audits; all source windows and outliers retained."""
import pathlib,subprocess,json,numpy as np,time,os,shutil
from sync_warped import warped_measure
REMOTE='/home/sapiece/AstraLive/experiments/real-avatar/'+os.environ.get('SOULX_FINAL_RUN_DIR','soulx-final-one-hour-pinned-20261009')
def audit(out,label):
 out=pathlib.Path(out);capture=out/'runtime-capture';capture.mkdir(exist_ok=True)
 subprocess.run(['rsync','-a',f'school-linux:{REMOTE}/integration/',str(capture)+'/'],check=True,stdout=subprocess.DEVNULL,timeout=45)
 subprocess.run(['rsync','-a',f'school-linux:{REMOTE}/rtmp-received.mkv',str(out/'rtmp-received.mkv')],check=True,stdout=subprocess.DEVNULL,timeout=45)
 rows=[json.loads(x)for x in (capture/'avatar-events.jsonl').read_text().splitlines()];jobs=[];audio_by_job={}
 for x in rows:
  if x['event']=='AudioActuallyConsumed':audio_by_job.setdefault(x['job_id'],[]).append(x)
 for x in rows:
  if x['event']=='BeginSpeechJob'and(capture/f"speech-{x['job_id']}.wav").exists():jobs.append({'job_id':x['job_id'],'marker':x['marker'],'generation':x['business_generation_id'],'origin':x['first_sample_index'],'source':str(capture/f"speech-{x['job_id']}.wav"),'audio_events':audio_by_job.get(x['job_id'],[])})
 result={};summary={};reasons=[];snap=out/('sync-'+label);snap.mkdir(exist_ok=True)
 for name,native in [('browser-native.webm',True),('rtmp-received.mkv',False)]:
  # Freeze current recorder bytes, so appends cannot move the end during analysis.
  target=snap/name;shutil.copyfile(out/name,target);r=warped_measure(target,jobs,native=native);result[name]=r
  p=r['absolute_offset_ms_percentiles'];trusted=[x for x in r['all_windows']if x.get('correlation',0)>=.7];large=[x for x in r['over_250ms']if x['correlation']>=.85 and x['correlation']>1.5*(x.get('second_peak_outside_100ms')or 0)];summary[name]={'trustedWindows':r['trusted_windows'],'medianP95MaxMs':p,'over250ms':r['over_250ms'],'audioPTSGaps':r['audio_pts_gaps'],'scope':'same-file recording audit, separately from native playback estimate'}
  if len(trusted)<10:reasons.append(name+': insufficient trusted source anchors')
  if p and p[1]>150:reasons.append(name+': recording P95 exceeds 150ms; preserve samples, playback attribution independent')
  if len(large)>=2:reasons.append(name+': multiple unique high-confidence >250ms windows')
  elif r['over_250ms']:summary[name]['requiresIndependentReview']=True
  (snap/(name+'.analysis.json')).write_text(json.dumps(r,indent=2));target.unlink() # full original recording remains, avoid six redundant copies
 summary.update(passed=not reasons,reasons=reasons,allWindowsRetained=True,requestedCheckpoint=label,sourceJobs=len(jobs));(snap/'summary.json').write_text(json.dumps(summary,indent=2));return summary
if __name__=='__main__':
 import sys
 print(json.dumps(audit(sys.argv[1],sys.argv[2])))
