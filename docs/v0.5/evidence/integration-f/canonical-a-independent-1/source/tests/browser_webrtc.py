"""Headless Chrome real-browser WebRTC smoke via the public Go SDP endpoint."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def verify(base, sid):
    result = {}
    finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            page = '''<!doctype html><html><body><video id="v" autoplay muted playsinline></video><audio id="a" autoplay></audio><pre id="result">PENDING</pre><script>
(async()=>{
 const result=document.getElementById('result');
 const stun=STUN_URL;
 const requireMedia=REQUIRE_MEDIA;
 const pc=new RTCPeerConnection(stun?{iceServers:[{urls:stun}]}:{});
 const tracks=new Set();
 pc.ontrack=e=>{tracks.add(e.track.kind);if(e.track.kind==='video')document.getElementById('v').srcObject=new MediaStream([e.track]);if(e.track.kind==='audio')document.getElementById('a').srcObject=new MediaStream([e.track]);};
 pc.addTransceiver('audio',{direction:'recvonly'});
 pc.addTransceiver('video',{direction:'recvonly'});
 let outcome;
 try {
  await pc.setLocalDescription(await pc.createOffer());
  if(pc.iceGatheringState!=='complete')await new Promise((resolve,reject)=>{let t=setTimeout(()=>reject(Error('ICE_TIMEOUT')),10000);pc.addEventListener('icegatheringstatechange',()=>{if(pc.iceGatheringState==='complete'){clearTimeout(t);resolve();}})});
  const r=await fetch('/api/v1/live-sessions/SID/webrtc/offer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'offer',sdp:pc.localDescription.sdp})});
  const answer=await r.json();if(!r.ok)throw Error(JSON.stringify(answer));
  await pc.setRemoteDescription(answer.data);
  for(let i=0;i<100;i++){if(pc.connectionState==='connected'&&tracks.has('audio')&&tracks.has('video'))break;await new Promise(x=>setTimeout(x,100));}
  if(pc.connectionState==='connected'&&tracks.has('audio')&&tracks.has('video')){
   let detail='';
   if(requireMedia){
    const stats=async()=>{let a=0,e=0,v=0;for(const s of (await pc.getStats()).values())if(s.type==='inbound-rtp'){
     if(s.kind==='audio'){a+=s.packetsReceived||0;e+=s.totalAudioEnergy||0;}
     if(s.kind==='video')v+=s.framesDecoded||0;
    }return {a,e,v};};
    const before=await stats();const start=performance.now();
    const speak=await fetch('/api/v1/live-sessions/SID/utterances',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':'gpu-browser-'+crypto.randomUUID()},body:JSON.stringify({text:'欢迎大家进入直播间，今天向大家介绍这件衣服。',priority:100,interruptPolicy:'NONE',source:'OPERATOR'})});
    if(!speak.ok)throw Error('SPEAK_FAILED '+await speak.text());
    let after,ms;
    for(let i=0;i<150;i++){after=await stats();if(after.a>before.a&&after.e>before.e&&after.v>before.v){ms=performance.now()-start;break;}await new Promise(x=>setTimeout(x,100));}
    if(ms===undefined)throw Error(`MEDIA_NOT_RECEIVED audioPackets=${after.a-before.a} audioEnergy=${after.e-before.e} framesDecoded=${after.v-before.v}`);
    detail=` browserMediaStartMs=${ms.toFixed(1)} audioPackets=${after.a-before.a} audioEnergy=${(after.e-before.e).toExponential(3)} framesDecoded=${after.v-before.v}`;
   }
   outcome='BROWSER_WEBRTC_PASS'+detail;
  }else outcome=`BROWSER_WEBRTC_FAIL state=${pc.connectionState} ice=${pc.iceConnectionState} tracks=${[...tracks]} offer=${pc.localDescription.sdp.split('\\r\\n').filter(x=>x.startsWith('a=candidate:')).join('|')} answer=${answer.data.sdp.split('\\r\\n').filter(x=>x.startsWith('a=candidate:')).join('|')}`;
 }catch(e){outcome='BROWSER_WEBRTC_FAIL '+e.message;}
 result.textContent=outcome;
 await fetch('/report',{method:'POST',body:outcome});
 pc.close();
})();
</script></body></html>'''.replace('SID', sid).replace('STUN_URL', repr(os.getenv('ASTRALIVE_BROWSER_STUN_URL', ''))).replace('REQUIRE_MEDIA', 'true' if os.getenv('ASTRALIVE_BROWSER_REQUIRE_MEDIA') == '1' else 'false')
            raw = page.encode()
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            if self.path == '/report':
                result['value'] = body.decode()
                finished.set()
                self.send_response(200); self.send_header('Content-Length', '0'); self.end_headers()
                return
            headers = {'Content-Type': 'application/json'}
            if self.headers.get('Idempotency-Key'):
                headers['Idempotency-Key'] = self.headers['Idempotency-Key']
            req = urllib.request.Request(base + self.path, body, headers, method='POST')
            try:
                with urllib.request.urlopen(req, timeout=35) as response:
                    status, raw = response.status, response.read()
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read()
            self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='astralive-chrome-') as profile:
        command = [CHROME, '--headless=new', '--no-first-run', '--no-default-browser-check',
                   '--disable-background-networking', '--autoplay-policy=no-user-gesture-required',
                   '--user-data-dir=' + profile, f'http://127.0.0.1:{server.server_port}/']
        if os.getenv('ASTRALIVE_BROWSER_DIRECT_IP') == '1':
            command.insert(-1, '--disable-features=WebRtcHideLocalIpsWithMdns')
        chrome = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            if not finished.wait(30):
                raise AssertionError('Chrome did not report a WebRTC outcome within 30 seconds')
            if not result['value'].startswith('BROWSER_WEBRTC_PASS'):
                raise AssertionError(result['value'])
            print(result['value'])
        finally:
            chrome.terminate()
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome.kill(); chrome.wait()
            server.shutdown(); server.server_close()
