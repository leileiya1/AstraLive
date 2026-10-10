"""Run the unchanged recording-correlation algorithm beside the RTMP receiver."""
import pathlib,json,shutil,sys
from sync_warped import warped_measure
root=pathlib.Path(__file__).parent;label=sys.argv[1]
if any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in label):raise ValueError('invalid snapshot label')
p=root/('rtmp-sync-'+label);p.mkdir(exist_ok=False)
# Preserve fixed receiver bytes; the live FFmpeg append must not move this snapshot.
shutil.copyfile(root/'rtmp-received.mkv',p/'rtmp-received.mkv')
rows=[json.loads(x) for x in (root/'integration/avatar-events.jsonl').read_text().splitlines()];jobs=[];audio={}
for x in rows:
 if x['event']=='AudioActuallyConsumed':audio.setdefault(x['job_id'],[]).append(x)
for x in rows:
 if x['event']=='BeginSpeechJob':
  f=root/'integration'/f"speech-{x['job_id']}.wav"
  if f.exists():
   target=p/f.name;shutil.copyfile(f,target);jobs.append({'job_id':x['job_id'],'marker':x['marker'],'generation':x['business_generation_id'],'origin':x['first_sample_index'],'source':str(target),'audio_events':audio.get(x['job_id'],[])})
r=warped_measure(p/'rtmp-received.mkv',jobs,native=False);(p/'analysis.json').write_text(json.dumps(r,indent=2));(p/'rtmp-received.mkv').unlink();print(json.dumps(r))
