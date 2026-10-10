"""Private management status plus GPU/process telemetry, no credentials in output."""
import json,pathlib,urllib.request,time,subprocess,sys
p=pathlib.Path(sys.argv[1]);c=json.loads((p/'config/worker.json').read_text());token=pathlib.Path(c['management_token_file']).read_text().strip()
r=urllib.request.Request(f"http://127.0.0.1:{c['management_port']}/v1/status",headers={'Authorization':'Bearer '+token})
try:
    with urllib.request.urlopen(r,timeout=5) as f:h=json.load(f)
except Exception as e:h={'monitorError':type(e).__name__}
s=json.loads((p/'state/supervisor.json').read_text());pid=s.get('childPid') or s.get('workerPid');alive=bool(pid and pathlib.Path('/proc/'+str(pid)).exists())
out={'wall_time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'alive':alive,'supervisor':s,'health':h}
r=subprocess.run(['nvidia-smi','--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5);out['nvidia_smi']=r.stdout.strip()
if alive:
    out['processMemory']=[x.strip() for x in pathlib.Path('/proc/'+str(pid)+'/status').read_text().splitlines() if x.startswith(('VmRSS:','VmHWM:','Threads:'))]
print(json.dumps(out))
