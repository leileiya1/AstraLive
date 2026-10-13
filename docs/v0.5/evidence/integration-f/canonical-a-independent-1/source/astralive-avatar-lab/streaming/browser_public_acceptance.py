"""Isolated public Go COMMENT -> resident GPU -> real fenced Chrome canvas."""
import json,os,pathlib,subprocess,tempfile,threading,time,urllib.request,urllib.error
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=pathlib.Path(__file__).parent;DURATION=int(os.getenv('SOULX_ACCEPTANCE_SECONDS','90'));OUT=ROOT/'integration'/os.environ.get('SOULX_ACCEPTANCE_RUN',f'public-{DURATION}s-{time.time_ns()}');OUT.mkdir(parents=True,exist_ok=False)
TOKEN=(ROOT/'.private/token').read_text().strip();PAGE=(ROOT/'browser_public_acceptance.html').read_text().replace('DURATION_SECONDS',str(DURATION)).replace('FAULT_PROBE_ENABLED','true' if os.getenv('SOULX_FAULT_PROBE')=='1' else 'false');finished=threading.Event();outcome={};lock=threading.Lock()
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
  if self.path=='/':self.send(200,PAGE.encode(),'text/html')
  else:self.proxy()
 def do_POST(self):
  body=self.rfile.read(int(self.headers.get('Content-Length','0')))
  if self.path=='/fault':
   p=subprocess.run(['ssh','-S','/tmp/astralive-soulx-45713-gpu.sock','-O','exit','-p','45713','root@connect.bjb2.seetacloud.com'],capture_output=True)
   self.send(200 if p.returncode==0 else 500,json.dumps({'disconnected':p.returncode==0}).encode())
  elif self.path=='/events':
   with lock:
    with (OUT/'browser-events.jsonl').open('ab') as f:f.write(body)
   self.send(200,b'{}')
  elif self.path.startswith('/record-chunk?'):
   seq=int(self.path.split('segment=')[1]);(OUT/f'record-{seq:06d}.part').write_bytes(body);self.send(200,b'{}')
  elif self.path=='/report':
   outcome.update(json.loads(body));(OUT/'summary.json').write_bytes(body);self.send(200,b'{}');finished.set()
  else:self.proxy(body)
 def log_message(self,*_):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory(prefix='soulx-public-chrome-') as profile:
 chrome=subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--no-first-run','--no-default-browser-check','--autoplay-policy=no-user-gesture-required','--disable-features=WebRtcHideLocalIpsWithMdns','--user-data-dir='+profile,f'http://127.0.0.1:{server.server_port}/'],stdout=subprocess.DEVNULL,stderr=(OUT/'chrome.log').open('wb'))
 try:
  deadline=time.monotonic()+DURATION+300
  while not finished.wait(30):
   if time.monotonic()>deadline:raise RuntimeError('browser acceptance timed out')
   print(json.dumps(dict(run=str(OUT),pending=True,wall_time_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))),flush=True)
  time.sleep(.5)
  parts=sorted(OUT.glob('record-*.part'))
  with (OUT/'browser-received.webm').open('wb') as f:
   for p in parts:f.write(p.read_bytes())
  print(json.dumps(outcome),flush=True)
 finally:
  chrome.terminate();chrome.wait(timeout=10);server.shutdown();server.server_close()
