"""Stop only zero-session acceptance processes whose environment matches this run."""
import subprocess,sys,json
run=sys.argv[1]
if not run.startswith('soulx-product-3080-') or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in run):raise ValueError('invalid owned run')
code='''import os,pathlib,signal,time,json,urllib.request
root=pathlib.Path.home()/'AstraLive/experiments/real-avatar/RUN'
health=json.load(urllib.request.urlopen('http://127.0.0.1:18100/internal/v1/health',timeout=5))
if health['activeSessions']!=0:raise RuntimeError('active session must receive normal API Stop first')
out=[]
for name in ('runtime-public','backend-public'):
 pid=int((root/'integration'/(name+'.pid')).read_text());proc=pathlib.Path('/proc/'+str(pid))
 if not proc.exists():out.append({'name':name,'pid':pid,'alreadyExited':True});continue
 env=(proc/'environ').read_bytes().split(bytes([0]));expected=('SOULX_EXPERIMENT_DIR='+str(root)).encode()
 if expected not in env:raise RuntimeError('process ownership mismatch')
 os.kill(pid,signal.SIGTERM);deadline=time.monotonic()+10
 while proc.exists() and time.monotonic()<deadline:
  if ') Z ' in (proc/'stat').read_text():break
  time.sleep(.1)
 alive=proc.exists() and ') Z ' not in (proc/'stat').read_text()
 out.append({'name':name,'pid':pid,'alive':alive})
 if alive:raise RuntimeError('owned process did not exit gracefully')
for name in ('rtmp-reader','reader-driver'):
 f=root/(name+'.pid')
 if f.exists():
  pid=int(f.read_text());proc=pathlib.Path('/proc/'+str(pid));alive=proc.exists() and ') Z ' not in (proc/'stat').read_text()
  out.append({'name':name,'pid':pid,'alive':alive})
  if alive:raise RuntimeError('reader did not exit after normal session Stop')
print(json.dumps({'activeSessionsBeforeStop':health['activeSessions'],'processes':out}))
'''.replace('RUN',run)
r=subprocess.run(['ssh','-o','BatchMode=yes','school-linux','python3 -'],input=code,capture_output=True,text=True);print(r.stdout);print(r.stderr);sys.exit(r.returncode)
