"""CPU-only browser branch calibration; no GPU or business acceptance."""
import asyncio,json,pathlib,subprocess,threading,time
from fractions import Fraction
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import av,numpy as np,wave
from aiortc import RTCPeerConnection,RTCSessionDescription,MediaStreamTrack
ROOT=pathlib.Path(__file__).parent;OUT=ROOT/'integration/soulx-final-one-hour/cpu-clock';OUT.mkdir(exist_ok=True)
for f in OUT.glob('*.webm'):f.unlink()
loop=asyncio.new_event_loop();threading.Thread(target=loop.run_forever,daemon=True).start();pcs=[];done=threading.Event()
with wave.open(str(OUT.parent/'original-source.wav')) as w:
 original=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')
base=np.resize(original,16000*18);SOURCE=np.interp(np.arange(48000*18)/3,np.arange(len(base)),base).astype('<i2');np.save(OUT/'source.npy',SOURCE)

class Track(MediaStreamTrack):
 def __init__(self,kind):super().__init__();self.kind=kind;self.n=0;self.begin=None
 async def recv(self):
  if self.begin is None:self.begin=time.monotonic()
  step=.02 if self.kind=='audio' else .04
  await asyncio.sleep(max(0,self.begin+self.n*step-time.monotonic()))
  if self.kind=='audio':
   f=av.AudioFrame(format='s16',layout='mono',samples=960);f.planes[0].update(SOURCE[self.n*960:(self.n+1)*960].tobytes().ljust(1920,b'\0'));f.sample_rate=48000;f.pts=self.n*960;f.time_base=Fraction(1,48000)
  else:
   a=np.zeros((192,192,3),np.uint8)
   for b in range(24):a[:16,b*8:(b+1)*8]=[220,40,40] if self.n&(1<<b) else [40,220,40]
   f=av.VideoFrame.from_ndarray(a,format='rgb24');f.pts=self.n*3600;f.time_base=Fraction(1,90000)
  self.n+=1;return f
async def offer(j):
 p=RTCPeerConnection();pcs.append(p);p.addTrack(Track('audio'));p.addTrack(Track('video'));await p.setRemoteDescription(RTCSessionDescription(**j));await p.setLocalDescription(await p.createAnswer());return {'sdp':p.localDescription.sdp,'type':'answer'}
PAGE='''<video id="native" autoplay playsinline></video><video id="split" autoplay muted playsinline></video><canvas id="canvas" width="192" height="192"></canvas><script>
(async()=>{let p=new RTCPeerConnection(),s=new MediaStream(),rows=[],rs=[],writes=Promise.resolve();p.addTransceiver('audio',{direction:'recvonly'});p.addTransceiver('video',{direction:'recvonly'});p.ontrack=e=>s.addTrack(e.track);await p.setLocalDescription(await p.createOffer());await new Promise(r=>{if(p.iceGatheringState==='complete')r();else p.onicegatheringstatechange=()=>{if(p.iceGatheringState==='complete')r()}});await p.setRemoteDescription(await (await fetch('/offer',{method:'POST',body:JSON.stringify(p.localDescription)})).json());while(s.getTracks().length<2)await new Promise(r=>setTimeout(r,50));let v=document.querySelector('#native'),split=document.querySelector('#split'),c=document.querySelector('#canvas'),ctx=c.getContext('2d');v.srcObject=s;v.volume=.001;split.srcObject=new MediaStream(s.getVideoTracks());await v.play();await split.play();function frame(){ctx.drawImage(split,0,0);split.requestVideoFrameCallback(frame)}split.requestVideoFrameCallback(frame);let ac=new AudioContext({sampleRate:48000});await ac.resume();let src=ac.createMediaStreamSource(new MediaStream(s.getAudioTracks())),dest=ac.createMediaStreamDestination();src.connect(dest);let gain=ac.createGain();gain.gain.value=0;src.connect(gain);gain.connect(ac.destination);let streams={A_native:s,A_element:v.captureStream(),B_canvas_native:new MediaStream([...c.captureStream(25).getVideoTracks(),...s.getAudioTracks()]),D_canvas_context:new MediaStream([...c.captureStream(25).getVideoTracks(),...dest.stream.getAudioTracks()])};for(let [name,stream] of Object.entries(streams)){let rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8,opus'});rec.ondataavailable=e=>{writes=writes.then(()=>fetch('/record/'+name,{method:'POST',body:e.data}))};rec.start(1000);rs.push(rec)}let probe=setInterval(async()=>{rows.push({t:performance.now(),context:ac.currentTime,output:ac.getOutputTimestamp(),stats:[...(await p.getStats()).values()].filter(x=>['inbound-rtp','media-playout'].includes(x.type))})},100);await new Promise(r=>setTimeout(r,4500));rows.push({event:'suspend',t:performance.now()});await ac.suspend();await new Promise(r=>setTimeout(r,600));await ac.resume();rows.push({event:'resume',t:performance.now()});await new Promise(r=>setTimeout(r,5500));clearInterval(probe);await Promise.all(rs.map(rec=>new Promise(r=>{rec.onstop=r;rec.stop()})));await writes;await fetch('/report',{method:'POST',body:JSON.stringify(rows)});p.close();await ac.close()})().catch(e=>fetch('/report',{method:'POST',body:JSON.stringify({error:String(e)})}));</script>'''
class Handler(BaseHTTPRequestHandler):
 def reply(self,b,mime='application/json'):self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(b)
 def do_GET(self):self.reply(PAGE.encode(),'text/html')
 def do_POST(self):
  b=self.rfile.read(int(self.headers['Content-Length']))
  if self.path=='/offer':self.reply(json.dumps(asyncio.run_coroutine_threadsafe(offer(json.loads(b)),loop).result()).encode())
  elif self.path=='/report':(OUT/'stats.json').write_bytes(b);self.reply(b'{}');done.set()
  else:
   with (OUT/(self.path.split('/')[-1]+'.webm')).open('ab') as f:f.write(b)
   self.reply(b'{}')
 def log_message(self,*a):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();profile=OUT/'profile';chrome=subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--autoplay-policy=no-user-gesture-required','--no-first-run','--user-data-dir='+str(profile.resolve()),f'http://127.0.0.1:{server.server_port}/'],stdout=subprocess.DEVNULL,stderr=(OUT/'chrome.log').open('w'))
try:
 assert done.wait(35),'CPU browser timeout'
 print((OUT/'stats.json').read_text()[:1500])
finally:
 chrome.terminate();chrome.wait(timeout=10);server.shutdown()
 for p in pcs:asyncio.run_coroutine_threadsafe(p.close(),loop).result()
