"""Kill only this pinned install's current validated supervisor child, once."""
import json,pathlib,os,signal,time
p=pathlib.Path('/root/autodl-tmp/astralive-services/soulx-lite-01');s=json.loads((p/'state/supervisor.json').read_text());pid=s['childPid'];supervisor=s['supervisorPid']
if s['status']!='READY':raise RuntimeError('worker not ready')
proc=pathlib.Path('/proc/'+str(pid));cmd=(proc/'cmdline').read_bytes().split(bytes([0]));stat=(proc/'stat').read_text().split(') ',1)[1].split()
if b'gpu_worker.service' not in cmd or int(stat[1])!=supervisor:raise RuntimeError('ownership mismatch')
f=p/'state/acceptance-crash-20261010.json'
if f.exists():raise RuntimeError('fault injection already performed')
f.write_text(json.dumps({'pid':pid,'epoch':s['workerEpoch'],'monotonic':time.monotonic()}));os.kill(pid,signal.SIGKILL);print(json.dumps({'ownedPid':pid,'oldEpoch':s['workerEpoch'],'injected':True}))
