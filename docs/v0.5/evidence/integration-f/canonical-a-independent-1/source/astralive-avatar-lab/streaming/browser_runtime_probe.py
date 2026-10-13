"""Actual Chrome display proof through frozen Runtime endpoints (not Go public E2E)."""
import os,json,subprocess,tempfile,threading,urllib.request,urllib.error,pathlib,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=pathlib.Path(__file__).parent;OUT=ROOT/'integration'/os.environ.get('BROWSER_RUN','browser-short');OUT.mkdir(parents=True,exist_ok=True)
TOKEN=(ROOT/'.private/token').read_text().strip();BASE='http://127.0.0.1:18100';SID='soulx-browser-'+str(time.time_ns())
finished=threading.Event();outcome={}
PAGE=r'''<!doctype html><html><body><video id="v" autoplay playsinline muted width="512" height="512"></video><audio id="a" autoplay></audio><canvas id="c" width="512" height="512" hidden></canvas><script>
(async()=>{
let logs=[],pc,rec,chunks=[],stop=false,offset=null,clockRTT=Infinity;const sid='SID';const v=document.querySelector('#v'),a=document.querySelector('#a'),c=document.querySelector('#c'),ctx=c.getContext('2d',{willReadFrequently:true});
a.muted=true;const log=(event,more={})=>logs.push({event,browserMono:performance.now()/1000,...more});
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function api(path,body){let r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});let j=await r.json();if(path==='/diag'){j.events=j.events.filter(x=>x.sessionId===sid);j.sessions=j.sessions.filter(x=>x.sessionId===sid);}if(!r.ok)throw Error(JSON.stringify(j));return j;}
const command=()=>({commandId:crypto.randomUUID(),traceId:crypto.randomUUID()});
async function diag(){let start=performance.now()/1000;let j=await api('/diag');let end=performance.now()/1000,rtt=end-start;if(rtt<clockRTT){clockRTT=rtt;offset=j.schoolMonotonic-(start+end)/2;}return j;}
async function until(fn,limit=45000){let start=performance.now();while(performance.now()-start<limit){if(await fn())return;await wait(100);}throw Error('WAIT_TIMEOUT');}
function display(now,m){if(stop)return;ctx.drawImage(v,0,0,512,512);let marker=0;for(let b=0;b<16;b++){let px=ctx.getImageData(b*8+4,4,1,1).data;if(px[0]>px[1])marker|=1<<b;}log('BrowserFrameDisplayed',{marker,mediaTime:m.mediaTime,presentedFrames:m.presentedFrames});v.requestVideoFrameCallback(display);}
async function speak(uid,text,force=false){log('COMMENT',{uid,force});await api(`/internal/v1/sessions/${sid}/utterances`,{...command(),utteranceId:uid,text,priority:force?100:50,interruptPolicy:force?'FORCE':'NONE',source:'PLATFORM_EVENT',platformContext:{eventType:'COMMENT',user:{externalId:'lab-viewer',nickname:'实验观众'}},voice:{voiceId:'xiao-ya'}});}
async function done(uid){await until(async()=>{let j=await diag();log('Diagnostics',j);let bad=j.events.find(x=>x.utteranceId===uid&&x.eventType==='UTTERANCE_FAILED');if(bad)throw Error(JSON.stringify(bad));return j.events.some(x=>x.utteranceId===uid&&x.eventType==='UTTERANCE_COMPLETED');});}
let result;
try{
 await api('/internal/v1/sessions',{...command(),sessionId:sid,avatar:{avatarId:'soulx-girl',engine:'LIGHTWEIGHT'},voice:{voiceId:'xiao-ya',provider:'SHERPA'},config:{fps:25,preview:{type:'WEBRTC'}},context:{roomId:'isolated-soulx',systemPrompt:'你是实验直播间主持人。只用简短中文回答观众，不谈商品价格和库存。'}});
 await until(async()=>{let j=await diag();return j.events.some(x=>x.eventType==='SESSION_READY');});
 await api(`/internal/v1/sessions/${sid}/start`,command());
 pc=new RTCPeerConnection();pc.addTransceiver('audio',{direction:'recvonly'});pc.addTransceiver('video',{direction:'recvonly'});
 let stream=new MediaStream();pc.ontrack=e=>{stream.addTrack(e.track);if(e.track.kind==='video')v.srcObject=new MediaStream([e.track]);else a.srcObject=new MediaStream([e.track]);};
 await pc.setLocalDescription(await pc.createOffer());await until(()=>pc.iceGatheringState==='complete',12000);
 let answer=await api(`/internal/v1/sessions/${sid}/webrtc/offer`,{type:'offer',sdp:pc.localDescription.sdp});await pc.setRemoteDescription(answer);
 await until(()=>pc.connectionState==='connected'&&stream.getTracks().length===2&&v.readyState>=2,20000);await v.play();await a.play();log('BrowserConnected');v.requestVideoFrameCallback(display);
 a.muted=true;rec=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8,opus'});rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};rec.start(1000);
FLOW let stats=[];for(let x of (await pc.getStats()).values())if(x.type==='inbound-rtp')stats.push({kind:x.kind,packetsReceived:x.packetsReceived,framesDecoded:x.framesDecoded,totalAudioEnergy:x.totalAudioEnergy,jitter:x.jitter});log('FinalRTPStats',{stats});
 result={status:'BROWSER_SHORT_COMPLETED',sid,clockOffsetSchoolMinusBrowser:offset,clockCalibrationRTT:clockRTT,stats};
}catch(e){result={status:'FAILED',sid,error:String(e),clockOffsetSchoolMinusBrowser:offset,clockCalibrationRTT:clockRTT};}
finally{
 try{await api(`/internal/v1/sessions/${sid}/stop`,command());log('NormalStop');}catch(e){log('StopFailed',{error:String(e)});}
 if(rec?.state==='recording'){await new Promise(r=>{rec.onstop=r;rec.stop();});let blob=new Blob(chunks,{type:'video/webm'});await fetch('/record',{method:'POST',body:blob});}
 stop=true;if(pc)pc.close();await fetch('/report',{method:'POST',body:JSON.stringify({result,logs})});
}
})();</script></body></html>'''.replace('SID',SID)
PAGE=PAGE.replace('FLOW', " await wait(3500);await speak('first','请用两句话欢迎观众，并说我们正在验证实时数字人画面。');await done('first');await wait(1800);\n await speak('old','请用六句话解释直播画面的测试流程。');await until(async()=>{let j=await diag();log('Diagnostics',j);return j.sessions[0]?.speaking;});await wait(900);\n await speak('forced','请只说一句：收到，现在开始新的回答。',true);await done('forced');await wait(3000);\n" if os.getenv('BROWSER_FLOW')!='fault' else " await wait(3000);await speak('fault','请用六句话说明数字人如何保持自然动作。');await until(async()=>{let j=await diag();log('Diagnostics',j);return j.sessions[0]?.speaking;});await wait(1800);\n log('FaultTunnelDisconnect');await fetch('/fault',{method:'POST',body:'disconnect'});await done('fault');await wait(1000);await speak('fallback','请只说一句：服务仍在继续，谢谢大家。');await done('fallback');await wait(2500);\n")
if os.getenv('BROWSER_FLOW')=='sync':
 PAGE=PAGE.replace(PAGE[PAGE.index(" await wait(3500);"):PAGE.index(' let stats=[]')]," await wait(3500);await speak('sync','请用两句话欢迎观众，并说我们正在验证实时数字人画面。');await done('sync');await wait(3000);\n")
class Handler(BaseHTTPRequestHandler):
 def proxy(self,body=None):
  path='/experiment/real-avatar-status' if self.path=='/diag' else self.path
  headers={'Content-Type':'application/json'}
  if self.path=='/diag':headers['X-Experiment-Token']=TOKEN
  try:
   with urllib.request.urlopen(urllib.request.Request(BASE+path,body,headers,method='POST' if body is not None else 'GET'),timeout=40) as r:status,raw=r.status,r.read()
  except urllib.error.HTTPError as e:status,raw=e.code,e.read()
  self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if self.path=='/diag':return self.proxy()
  raw=PAGE.encode();self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(raw)
 def do_POST(self):
  body=self.rfile.read(int(self.headers.get('Content-Length','0')))
  if self.path=='/fault':
   p=subprocess.run(['ssh','-S','/tmp/astralive-avatar-gpu-tunnel.sock','-O','exit','-p','20541','root@connect.bjb2.seetacloud.com'],capture_output=True)
   self.send_response(200 if p.returncode==0 else 500);self.end_headers();return
  if self.path=='/record':(OUT/'browser-received.webm').write_bytes(body)
  elif self.path=='/report':
   (OUT/'browser-evidence.json').write_bytes(body);outcome.update(json.loads(body)['result']);finished.set()
  else:return self.proxy(body)
  self.send_response(200);self.end_headers()
 def log_message(self,*_):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory(prefix='soulx-lab-chrome-') as profile:
 chrome=subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--no-first-run','--no-default-browser-check','--autoplay-policy=no-user-gesture-required','--disable-features=WebRtcHideLocalIpsWithMdns','--user-data-dir='+profile,f'http://127.0.0.1:{server.server_port}/'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  if not finished.wait(150):raise RuntimeError('browser evidence timeout')
  print(json.dumps(outcome))
 finally:chrome.terminate();chrome.wait(timeout=10);server.shutdown();server.server_close()
