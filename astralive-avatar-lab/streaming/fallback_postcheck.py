"""Detached single-session final driver; append-only evidence and recoverable state."""
import json,pathlib,subprocess,threading,time,urllib.request,urllib.error,os,numpy as np
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=pathlib.Path(__file__).parent;OUT=ROOT/'integration/soulx-final-one-hour-paired-20261009/fallback-postcheck';TOKEN=(ROOT/'.private/token').read_text().strip();PAGE=(ROOT/'fallback_postcheck.html').read_bytes();finished=threading.Event();lock=threading.Lock();state={};monitor={};monitor_lock=threading.Lock()
def dump(name,value):
 p=OUT/name;tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(p)
def append(name,obj):
 with (OUT/name).open('a') as f:f.write(json.dumps(obj)+'\n')
def sample():
 global monitor
 while not finished.is_set():
  start=time.monotonic()
  try:
   r=subprocess.run(['ssh','-o','ControlPath=/tmp/astralive-soulx-repair-school.sock','-o','BatchMode=yes','-o','ConnectTimeout=10','school-linux','python3 ~/AstraLive/experiments/real-avatar/soulx-final-one-hour-fallback-postcheck-20261009/final_host_monitor.py'],capture_output=True,text=True,timeout=20);school=json.loads(r.stdout)
  except Exception as e:school={'monitorError':str(e)}
  try:
   code="import json,pathlib,subprocess,time; p=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab/streaming/evidence/soulx-final-one-hour-repaired-20261009'); pid=int((p/'worker.pid').read_text()); r=subprocess.run(['nvidia-smi','--query-gpu=name,memory.used,utilization.gpu,temperature.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True); print(json.dumps({'pid':pid,'alive':pathlib.Path('/proc/'+str(pid)).exists(),'gpu':r.stdout.strip(),'ready':json.loads((p/'worker-ready.json').read_text()),'wall_time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}))"
   r=subprocess.run(['ssh','-o','ControlPath=/tmp/astralive-soulx-repair-school.sock','-o','BatchMode=yes','-o','ConnectTimeout=10','-p','45713','root@connect.bjb2.seetacloud.com','/root/autodl-tmp/astralive-avatar-lab/environments/astralive-soulx/bin/python -c '+__import__('shlex').quote(code)],capture_output=True,text=True,timeout=20);gpu=json.loads(r.stdout)
  except Exception as e:gpu={'monitorError':str(e)}
  with monitor_lock:monitor={'school':school,'gpu':gpu,'rtmpPublisherReady':school.get('rtmpPublisherReady',False),'workerAlive':gpu.get('alive',False),'sampleMonotonic':time.monotonic()};snap=dict(monitor)
  append('gpu-stats.jsonl',gpu);append('rtmp-stats.jsonl',school.get('rtmp',{'error':school.get('rtmpError')}));append('runtime-events.jsonl',school);dump('monitor-latest.json',snap)
  finished.wait(max(0,30-(time.monotonic()-start)))
class Handler(BaseHTTPRequestHandler):
 def send(self,status,raw,mime='application/json'):
  self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def proxy(self,body=None):
  headers={'Content-Type':'application/json'};base='http://127.0.0.1:18180';path=self.path
  if path=='/diag':base='http://127.0.0.1:18100';path='/experiment/real-avatar-status';headers['X-Experiment-Token']=TOKEN
  if body is not None:headers['Idempotency-Key']=self.headers.get('Idempotency-Key',str(time.time_ns()))
  try:
   with urllib.request.urlopen(urllib.request.Request(base+path,body,headers,method='POST' if body is not None else 'GET'),timeout=60) as r:status,raw=r.status,r.read()
  except urllib.error.HTTPError as e:status,raw=e.code,e.read()
  except Exception as e:status,raw=502,json.dumps({'error':type(e).__name__}).encode()
  self.send(status,raw)
 def do_GET(self):
  if self.path=='/':self.send(200,PAGE,'text/html')
  elif self.path=='/player_gate.js':self.send(200,(ROOT/'final_player_gate.js').read_bytes(),'text/javascript')
  elif self.path=='/monitor':
   with monitor_lock:j=dict(monitor)
   j['ageSeconds']=time.monotonic()-j.get('sampleMonotonic',0)
   self.send(200,json.dumps(j).encode())
  else:self.proxy()
 def do_POST(self):
  b=self.rfile.read(int(self.headers.get('Content-Length','0')))
  if self.path=='/events':
   with lock:
    with (OUT/'browser-events.jsonl').open('ab') as f:f.write(b)
    for line in b.decode().splitlines():
     j=json.loads(line)
     if j['event']=='WebRTCStats':append('browser-stats.jsonl',j)
     if j['event'] in ['SessionCreated','EntryGatesCompleted','Cycle','Failure']:state.update(j);dump('progress.json',state)
   self.send(200,b'{}')
  elif self.path.startswith('/record/'):
   name=self.path.split('/')[-1];assert name in ['native','canvas']
   with lock:
    with (OUT/('browser-'+name+'.webm')).open('ab') as f:f.write(b)
   self.send(200,b'{}')
  elif self.path=='/ready':dump('formal-ready.json',json.loads(b));self.send(200,b'{}')
  elif self.path=='/gate':
   j=json.loads(b);samples=j.pop('nativeSamples');j['nativeEstimatedSync']={'samples':len(samples),'absolute_ms_p50_p95_max':np.percentile(np.abs(samples),[50,95,100]).tolist() if samples else None,'scope':'receiver estimated playout in sender NTP; not speaker-loopback measurement'}
   with monitor_lock:j['monitor']=dict(monitor)
   reasons=[]
   if len(samples)<20:reasons.append('native playout timestamps unavailable/insufficient')
   elif np.percentile(np.abs(samples),95)>150:reasons.append('native estimated sync P95 exceeds 150ms')
   if j['stats']['connection']!='connected':reasons.append('WebRTC not connected')
   if not j['monitor'].get('workerAlive'):reasons.append('worker not alive')
   if not j['monitor'].get('rtmpPublisherReady'):reasons.append('RTMP publisher not ready')
   j.update(passed=not reasons,reason='; '.join(reasons) or 'initial continuous gate passed; recording correlation independently audited');labels={90:'90s',300:'5m',900:'15m',1800:'30m',2700:'45m',3600:'60m'};dump('checkpoint-'+labels[j['requestedSeconds']]+'.json',j);self.send(200,json.dumps(j).encode())
  elif self.path=='/report':j=json.loads(b);dump('browser-summary.json',j);dump('normal-stop.json',j.get('normalStop',{'error':j.get('stopError'),'completed':False}));self.send(200,b'{}');finished.set()
  else:self.proxy(b)
 def log_message(self,*a):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();threading.Thread(target=sample,daemon=True).start();profile=OUT/'chrome-profile';chrome=subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--no-first-run','--no-default-browser-check','--autoplay-policy=no-user-gesture-required','--disable-features=WebRtcHideLocalIpsWithMdns','--user-data-dir='+str(profile.resolve()),f'http://127.0.0.1:{server.server_port}/'],stdout=subprocess.DEVNULL,stderr=(OUT/'chrome.log').open('w'),start_new_session=True);dump('driver-process.json',{'driverPid':os.getpid(),'chromePid':chrome.pid,'serverPort':server.server_port,'startupUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'independentProcessGroup':True})
try:
 while not finished.wait(30):
  if chrome.poll() is not None:dump('driver-failure.json',{'error':'Chrome exited','exitCode':chrome.returncode});break
finally:
 finished.set();chrome.terminate();chrome.wait(timeout=10);server.shutdown()
