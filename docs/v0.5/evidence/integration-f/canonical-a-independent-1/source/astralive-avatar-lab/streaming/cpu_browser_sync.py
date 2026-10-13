"""CPU-only deterministic WebRTC A/V laboratory. Never connects to the GPU.

Audio is unique seeded noise and video contains matching40ms source indices.
All decoded/recorded windows and fault events are retained. This is not live
SoulX or business acceptance; it tests the browser and source clocks only.
"""
import argparse,asyncio,json,os,pathlib,subprocess,threading,time,urllib.request,wave,signal
from fractions import Fraction
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import av,numpy as np
from aiortc import RTCPeerConnection,RTCSessionDescription,MediaStreamTrack
from browser_audio_policy import prepare_output_policy
ROOT=pathlib.Path(__file__).parent
class Source:
 def __init__(self,out,seconds):
  self.start=None;self.log=(out/'sender-events.jsonl').open('w',buffering=1);rng=np.random.default_rng(1029)
  raw=rng.normal(size=16000*(seconds+60));raw=np.convolve(raw,np.ones(4)/4,mode='same');self.pcm=(raw*.16*32767).clip(-32000,32000).astype('<i2')
  self.audio48=np.repeat(self.pcm,3)
  with wave.open(str(out/'source.wav'),'wb')as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(self.pcm.tobytes())
  self.background=np.zeros((512,512,3),np.uint8);self.background[:]=[90,110,130];self.background[50:450,50:450]=[160,130,110]
 def event(self,**v):self.log.write(json.dumps({'monotonic':time.monotonic(),**v})+'\n')
class Track(MediaStreamTrack):
 def __init__(self,kind,src,origin,epoch):super().__init__();self.kind=kind;self.src=src;self.origin=origin;self.epoch=epoch;self.n=0;self.start=None
 async def recv(self):
  if self.start is None:self.start=time.monotonic()
  step=.02 if self.kind=='audio'else .04;await asyncio.sleep(max(0,self.start+self.n*step-time.monotonic()))
  if self.kind=='audio':
   sample=self.origin*640+self.n*320;a=self.src.audio48[sample*3:sample*3+960];f=av.AudioFrame(format='s16',layout='mono',samples=960);f.planes[0].update(a.tobytes().ljust(1920,b'\0'));f.sample_rate=48000;f.pts=self.n*960;f.time_base=Fraction(1,48000)
  else:
   seq=self.origin+self.n;pixels=self.src.background.copy()
   for row,value,n in [(0,1,16),(8,seq,24),(16,self.epoch,16)]:
    for b in range(n):pixels[row:row+8,b*8:b*8+8]=[220,40,40]if value&(1<<b)else[40,220,40]
   pixels[240:270,140:370]=[150+seq%70,55,55];f=av.VideoFrame.from_ndarray(pixels,format='rgb24');f.pts=self.n*3600;f.time_base=Fraction(1,90000);sample=seq*640
  self.src.event(event='SourceFrame',kind=self.kind,sourceSample=sample,epoch=self.epoch,trackPTS=f.pts);self.n+=1;return f

def run(args):
 out=ROOT/'integration/soulx-cpu-av-repair-20261009'/args.name
 if out.exists() and any(out.iterdir()):raise RuntimeError('Choose a new case name; prior CPU evidence is immutable')
 out.mkdir(parents=True,exist_ok=True);done=threading.Event();permissions_ready=threading.Event();source=Source(out,args.duration);loop=asyncio.new_event_loop();threading.Thread(target=loop.run_forever,daemon=True).start();pcs=[];epoch=0;chrome=None;browser=None
 async def offer(j):
  nonlocal epoch
  epoch+=1;origin=0 if source.start is None else int((time.monotonic()-source.start)*25);source.start=source.start or time.monotonic();pc=RTCPeerConnection();pcs.append(pc);pc.addTrack(Track('audio',source,origin,epoch));pc.addTrack(Track('video',source,origin,epoch));await pc.setRemoteDescription(RTCSessionDescription(**j));await pc.setLocalDescription(await pc.createAnswer());return {'type':pc.localDescription.type,'sdp':pc.localDescription.sdp,'epoch':epoch}
 PAGE=(ROOT/('cpu_product_preview.html' if args.product_hook else 'cpu_browser_sync.html')).read_text().replace('TEST_CONFIG',json.dumps(vars(args)))
 class H(BaseHTTPRequestHandler):
  def send(self,b,mime='application/json'):
   self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(b)
  def do_GET(self):
   if self.path=='/permissions-ready':
    if not permissions_ready.wait(10):raise TimeoutError('permission setup barrier')
    self.send(b'{}');return
   if self.path=='/product_hook.js':self.send((ROOT/'cpu_product_preview.js').read_bytes(),'text/javascript');return
   if self.path=='/audio_health.js':self.send((ROOT/'browser_audio_health.js').read_bytes(),'text/javascript')
   else:self.send(PAGE.encode(),'text/html')
  def do_POST(self):
   b=self.rfile.read(int(self.headers['Content-Length']))
   if self.path=='/offer':self.send(json.dumps(asyncio.run_coroutine_threadsafe(offer(json.loads(b)),loop).result(timeout=20)).encode())
   elif self.path.startswith('/record/'):
    with(out/(self.path.split('/')[-1]+'.webm')).open('ab')as f:f.write(b)
    self.send(b'{}')
   elif self.path=='/report':(out/'browser.json').write_bytes(b);self.send(b'{}');done.set()
   elif self.path=='/fault':
    candidates=[]
    raw=subprocess.run(['ps','-axo','pid=,ppid=,command='],capture_output=True,text=True,check=True).stdout
    for l in raw.splitlines():
     ps=l.strip().split(None,2)
     if len(ps)==3 and '--utility-sub-type=audio.mojom.AudioService'in ps[2]and (int(ps[1])==chrome.pid or str(out/'profile')in ps[2]):candidates.append(int(ps[0]))
    assert len(candidates)==1,{'audioServiceCandidates':candidates}
    pid=candidates[0];stamp=time.monotonic();os.kill(pid,signal.SIGSTOP)
    try:time.sleep(1.6)
    finally:os.kill(pid,signal.SIGCONT)
    fault={'fault':'ownedChromeAudioServiceSIGSTOP','pid':pid,'durationSeconds':time.monotonic()-stamp,'startedMonotonic':stamp,'scope':'this disposable Chrome audio process only; OS default/device untouched'};(out/'fault.json').write_text(json.dumps(fault,indent=2));self.send(json.dumps(fault).encode())
  def log_message(self,*a):pass
 server=ThreadingHTTPServer(('127.0.0.1',0),H);threading.Thread(target=server.serve_forever,daemon=True).start();origin='http://127.0.0.1:'+str(server.server_port);profile=out/'profile';profile.mkdir(exist_ok=True);(profile/'DevToolsActivePort').unlink(missing_ok=True)
 chrome=subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--autoplay-policy=no-user-gesture-required','--remote-debugging-port=0','--no-first-run','--no-default-browser-check','--user-data-dir='+str(profile.absolute()),'about:blank'],stdout=subprocess.DEVNULL,stderr=(out/'chrome.log').open('w'),start_new_session=True);(out/'process-start.json').write_text(json.dumps({'harnessPid':os.getpid(),'chromePid':chrome.pid,'UTC':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'config':vars(args),'noGpuWorkerOrRemoteHost':True},indent=2))
 try:
  for i in range(200):
   if(profile/'DevToolsActivePort').exists():break
   time.sleep(.05)
  browser=prepare_output_policy(profile,origin)
  permissions_ready.set()
  if not done.wait(args.duration+45):raise TimeoutError('CPU experiment timeout')
  result=json.loads((out/'browser.json').read_text());print(json.dumps({'name':args.name,'status':result.get('status'),'error':result.get('error'),'epochs':epoch,'samples':len(result.get('stats',[]))},ensure_ascii=False))
 finally:
  if browser:browser.close()
  chrome.terminate();chrome.wait(timeout=10);server.shutdown()
  for pc in pcs:asyncio.run_coroutine_threadsafe(pc.close(),loop).result(timeout=10)
  async def cleanup_loop():
   pending=[t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
   for t in pending:t.cancel()
   await asyncio.gather(*pending,return_exceptions=True)
  asyncio.run_coroutine_threadsafe(cleanup_loop(),loop).result(timeout=10)
  source.log.close();loop.call_soon_threadsafe(loop.stop)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--name',required=True);p.add_argument('--duration',type=int,default=45);p.add_argument('--pin',action='store_true');p.add_argument('--fault',action='store_true');p.add_argument('--recover',action='store_true');p.add_argument('--product-hook',action='store_true');run(p.parse_args())
