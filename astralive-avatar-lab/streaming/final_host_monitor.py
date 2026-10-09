"""Read-only host snapshot. Run on school-linux; never print environment/argv."""
import json,pathlib,subprocess,time,urllib.request,os
ROOT=pathlib.Path.home()/'AstraLive/experiments/real-avatar/soulx-final-one-hour-pinned-20261009';out={'wall_time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'bootId':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'load':os.getloadavg(),'memory':{}}
for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
 if line.startswith(('MemTotal:','MemAvailable:','SwapTotal:','SwapFree:')):k,v=line.split(':');out['memory'][k]=v.strip()
out['processes']={}
for name in ['runtime-public','backend-public','rtmp-reader']:
 p=(ROOT if name=='rtmp-reader' else ROOT/'integration')/(name+'.pid')
 if p.exists():
  pid=int(p.read_text());r=subprocess.run(['ps','-p',str(pid),'-o','pid=,ppid=,lstart=,etimes=,%cpu=,rss=,stat='],capture_output=True,text=True);out['processes'][name]={'pid':pid,'alive':r.returncode==0,'ps':r.stdout.strip()}
try:
 with urllib.request.urlopen('http://127.0.0.1:19997/v3/paths/list',timeout=3) as r:out['rtmp']=json.load(r)
except Exception as e:out['rtmpError']=type(e).__name__
try:
 with urllib.request.urlopen('http://127.0.0.1:18100/internal/v1/health',timeout=3) as r:out['runtimeHealth']=json.load(r)
except Exception as e:out['runtimeHealthError']=type(e).__name__
p=ROOT/'integration/runtime-public.log'
if p.exists():
 with p.open('rb') as f:f.seek(max(0,p.stat().st_size-100000));lines=f.read().decode(errors='replace').splitlines()
 for line in reversed(lines):
  try:
   j=json.loads(line);msg=j.get('message','')
   if msg.startswith('runtime_media_metrics '):out['runtimeMedia']=json.loads(msg.split(' ',1)[1]);break
  except (ValueError,KeyError):pass
out['rtmpPublisherReady']=any(x.get('ready',False) for x in out.get('rtmp',{}).get('items',[]));print(json.dumps(out))
