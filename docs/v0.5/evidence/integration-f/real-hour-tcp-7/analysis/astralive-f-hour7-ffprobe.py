import hashlib,json,subprocess
from pathlib import Path
root=Path('/private/tmp/astralive-f-real-hour-tcp-7/media')
reports=[]
for label,path in [('chrome',root/'observer/chrome.webm'),('rtmp',root/'rtmp.flv')]:
 result=subprocess.run(['ffprobe','-v','error','-show_packets','-show_streams','-show_entries','packet=stream_index,pts_time,dts_time,duration_time:stream=index,codec_name,codec_type,time_base','-of','json',str(path)],capture_output=True,check=True)
 data=json.loads(result.stdout);streams=[]
 for stream in data['streams']:
  packets=[r for r in data['packets'] if r['stream_index']==stream['index']]; stats=dict(stream,packetCount=len(packets))
  for field in ['pts_time','dts_time']:
   values=[float(r[field]) for r in packets if field in r];stats[field]={'count':len(values),'first':values[0] if values else None,'last':values[-1] if values else None,'regressions':sum(b<a for a,b in zip(values,values[1:])),'duplicates':sum(b==a for a,b in zip(values,values[1:]))}
  streams.append(stats)
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 reports.append({'recording':label,'path':str(path),'bytes':path.stat().st_size,'sha256':h.hexdigest(),'streams':streams})
print(json.dumps({'scope':'closed-recording packet timestamps only; no AV drift, lip-sync, continuous audibility or acceptance upgrade','originalGateStatus':'FAIL','recordings':reports},indent=2))
