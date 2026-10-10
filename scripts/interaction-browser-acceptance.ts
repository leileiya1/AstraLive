// Opt-in real Chrome acceptance. Reads private files; never exports credentials/text.
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
const root = process.env.INTERACTION_PRIVATE_DIR;
if (!root || process.env.RUN_REAL_INTERACTION !== '1') throw Error('Explicit real acceptance opt-in and private directory required');
const origin = process.env.INTERACTION_ORIGIN ?? 'https://localhost:26843';
const output = process.env.INTERACTION_EVIDENCE ?? `${root}/browser-real.json`;
if (existsSync(output)) throw Error('Evidence file already exists; choose a new trial filename');
const port = Number(process.env.INTERACTION_CDP_PORT ?? 26892);
const sleep = (ms:number) => new Promise(r=>setTimeout(r,ms));
let randomSeed=Number(process.env.INTERACTION_RANDOM_SEED??20261010)>>>0;
const seededRandom=()=>{randomSeed=(1664525*randomSeed+1013904223)>>>0;return randomSeed/4294967296};
const chrome = Bun.spawn(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '--headless=new', '--no-first-run', '--no-default-browser-check', '--ignore-certificate-errors', '--autoplay-policy=no-user-gesture-required', `--remote-debugging-port=${port}`, `--user-data-dir=${root}/chrome-${process.pid}`, 'about:blank'], {stdout:'ignore',stderr:Bun.file(`${root}/chrome.log`)});
let ws:WebSocket, sid='', next=1, workerStopped=false;
async function workerAction(action:'stop'|'start') {
 const file=process.env.INTERACTION_WORKER_COMMANDS_FILE;if(!file)throw Error('Private, explicit Worker command file required');
 const commands=JSON.parse(readFileSync(file,'utf8'));
 const child=Bun.spawn(commands[action],{stdout:Bun.file(`${root}/worker-${action}.log`),stderr:Bun.file(`${root}/worker-${action}.err`)});
 if(await child.exited!==0)throw Error('Worker lifecycle '+action+' failed');
 workerStopped=action==='stop';
}
const pending=new Map<number,(v:any)=>void>();
const result:any={classification:'MOCK_COMMENTS_REAL_DEEPSEEK_XIAOYA_SOULX_CHROME',samples:[],attempts:[],errors:[],clockBoundary:'Chrome performance.now; remote stages aligned by request/response bounds, no cross-host wall subtraction',audioBoundary:'Chrome decoded stream analyser plus native playout stats; physical speaker NOT TESTED'};
async function call(method:string,params:any={}) { const id=next++;const m:any=await new Promise(r=>{pending.set(id,r);ws.send(JSON.stringify({id,method,params}));});if(m.error)throw Error(method+': '+m.error.message);return m.result; }
async function evaluate(expression:string) {const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description??'Browser evaluation failed');return r.result.value;}
async function until(expression:string,ms=30000) {const end=Date.now()+ms;while(Date.now()<end){const v=await evaluate(expression);if(v)return v;await sleep(100);}throw Error('Browser condition timed out');}
async function api(path:string,method='GET',data?:unknown) {return await evaluate(`window.__api(${JSON.stringify(path)},${JSON.stringify(method)},${JSON.stringify(data)??'undefined'})`);}
async function snapshot() {return await evaluate(`(async()=>{const start=performance.now();const data=await window.__api('/api/v0.4/interaction/${sid}/');return {start,end:performance.now(),data}})()`);}
async function receiver() {
  const start=await evaluate('performance.now()');
  const r=await fetch('http://127.0.0.1:26836/snapshot',{headers:{Authorization:'Bearer '+readFileSync(`${root}/runtime-control-token`,'utf8').trim()}});
  if(!r.ok)throw Error('Authenticated receiver query failed');const data=await r.json();const end=await evaluate('performance.now()');return {start,end,data};
}
async function traces() {
  const start=await evaluate('performance.now()');
  const r=await fetch(`http://127.0.0.1:26800/internal/v0.4/sessions/${sid}/interaction-traces`,{headers:{Authorization:'Bearer '+readFileSync(`${root}/runtime-control-token`,'utf8').trim()}});
  if(!r.ok)throw Error('Protected trace query failed');const data=await r.json();const end=await evaluate('performance.now()');return {start,end,data};
}
function aligned(q:any,age:number,span=0) {return {valueMs:(q.start+q.end)/2-age+span,uncertaintyMs:(q.end-q.start)/2};}
function stats(v:number[]) {const a=[...v].sort((a,b)=>a-b);return {samples:a.length,meanMs:a.length?a.reduce((x,y)=>x+y,0)/a.length:null,p50Ms:a[Math.ceil(a.length*.5)-1]??null,p95Ms:a[Math.ceil(a.length*.95)-1]??null,maxMs:a.at(-1)??null};}
function save(){
 result.receiveToCorrelatedAV=stats(result.samples.filter((s:any)=>s.receiveToCorrelatedAVMs!==undefined).map((s:any)=>s.receiveToCorrelatedAVMs));
 result.receiveToRTMPAV=stats(result.samples.filter((s:any)=>s.receiveToRTMPAVMs!==undefined).map((s:any)=>s.receiveToRTMPAVMs));
 result.failedAttempts=result.attempts.filter((a:any)=>a.status!=='COMPLETED').length;
 result.failureRatio=result.attempts.length?result.failedAttempts/result.attempts.length:null;
writeFileSync(output,JSON.stringify(result,null,2)+'\n');}
try {
  let tabs:any[]=[];for(let i=0;i<60;i++){try{tabs=await(await fetch(`http://127.0.0.1:${port}/json`)).json();if(tabs.length)break;}catch{}await sleep(100);}
  const tab=tabs.find(t=>t.type==='page');if(!tab)throw Error('Native Chrome unavailable');
  ws=new WebSocket(tab.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
  ws.onmessage=e=>{const m=JSON.parse(String(e.data));if(m.id){pending.get(m.id)?.(m);pending.delete(m.id);}};
  await call('Page.enable');await call('Runtime.enable');
  await call('Page.addScriptToEvaluateOnNewDocument',{source:`const Native=window.RTCPeerConnection;window.RTCPeerConnection=class extends Native{constructor(c){super(c);window.__peer=this}};`});
  await call('Page.navigate',{url:origin});await until(`!!document.querySelector('nav')`);
  await evaluate(`window.__api=async(path,method='GET',data)=>{const r=await fetch(path,{method,headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:data===undefined?undefined:JSON.stringify(data)});const p=await r.json();if(!r.ok)throw Error(path+': '+r.status+' '+p.code);return p.data};void 0;`);
  let password=readFileSync(`${root}/operator-password`,'utf8');await api('/api/v0.4/auth/login','POST',{username:'operator',password});password='';
  const suffix=crypto.randomUUID().slice(0,8), name=`Agent B real ${suffix}`;
  const avatar=await api('/api/v1/avatars','POST',{name,engine:'SOULX'});
  const voice=await api('/api/v1/voices','POST',{name,provider:'XIAOYA',providerVoiceId:'xiao_ya'});
  const product=await api('/api/v1/products','POST',{name:'验收卫衣',description:'纯棉卫衣，测试事实来自独立数据库。',price:129,currency:'CNY',stock:27,sizes:['M','L','XL']});
  const room=await api('/api/v1/live-rooms','POST',{name,avatarId:avatar.avatarId,voiceId:voice.voiceId,activeProductId:product.productId,systemPrompt:'你是直播主播。每次用一句简短中文回答，最多25个字；只依据工具事实回答商品问题。'});
  result.roomId=room.roomId;result.productId=product.productId;
  await evaluate(`Array.from(document.querySelectorAll('nav button')).find(b=>b.textContent.includes('Live Rooms')).click()`);
  await until(`Array.from(document.querySelectorAll('h2')).some(h=>h.textContent===${JSON.stringify(name)})`);
  await evaluate(`Array.from(document.querySelectorAll('h2')).find(h=>h.textContent===${JSON.stringify(name)}).parentElement.parentElement.querySelector('button:last-child').click()`);
  await until(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='创建 Session')`);
  await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='创建 Session').click()`);
  sid=await until(`Array.from(document.querySelectorAll('dt')).find(d=>d.textContent==='Session')?.nextElementSibling.textContent.match(/session_[a-z0-9]+/)?.[0]`);
  result.sessionId=sid;writeFileSync(`${root}/active-session`,sid);
  await until(`Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Start Live'&&!b.disabled)`);
  await evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Start Live').click()`);
  await until(`window.__peer?.connectionState==='connected'`,60000);
  await until(`document.querySelector('video')?.videoWidth>0`);
  await evaluate(`(async()=>{const v=document.querySelector('video');v.muted=false;await v.play();const c=new AudioContext();await c.resume();const source=c.createMediaStreamSource(v.srcObject);const analyser=c.createAnalyser();analyser.fftSize=2048;source.connect(analyser);const mute=c.createGain();mute.gain.value=0;analyser.connect(mute).connect(c.destination);const canvas=document.createElement('canvas');canvas.width=v.videoWidth;canvas.height=v.videoHeight;const g=canvas.getContext('2d',{willReadFrequently:true});window.__obs={audio:[],video:[],ctx:c};setInterval(()=>{const a=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(a);const peak=Math.max(...a.map(Math.abs));if(peak>.003&&window.__obs.audio.length<30000)window.__obs.audio.push({at:performance.now(),contextTime:c.currentTime,peak});},10);function frame(now,m){g.drawImage(v,0,0);const pixel=g.getImageData(0,0,canvas.width,24).data;const value=(row,bits)=>{let n=0;for(let b=0;b<bits;b++){const i=((row+4)*canvas.width+b*8+4)*4;if(pixel[i]>pixel[i+1])n+=2**b;}return n};if(window.__obs.video.length<30000)window.__obs.video.push({at:now,displayAt:m.expectedDisplayTime,mediaTime:m.mediaTime,marker:value(0,16),sequence:value(8,24),generation:value(16,16)});v.requestVideoFrameCallback(frame)}v.requestVideoFrameCallback(frame);window.__events=[];window.__sse=new EventSource('/api/v1/live-sessions/${sid}/events');for(const name of ['utterance.completed','utterance.failed','utterance.interrupted','utterance.playing','runtime.warning','session.degraded','session.started','session.ended','session.failed'])window.__sse.addEventListener(name,e=>{const p=JSON.parse(e.data);window.__events.push({name,at:performance.now(),utteranceId:p.utteranceId,code:p.payload?.code})});return c.state})()`);
  if(process.env.INTERACTION_RECORD==='1')await evaluate(`(()=>{const stream=document.querySelector('video').srcObject;window.__recordChunks=[];window.__recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8,opus'});window.__recorder.ondataavailable=e=>{if(e.data.size)window.__recordChunks.push(e.data)};window.__recorder.start(1000);return true})()`);
  result.providers=await api(`/api/v0.4/sessions/${sid}/providers`);if(result.providers.mode!=='REAL')throw Error('Provider bundle is not REAL');
  // No selected speech is admitted while the operator owns interaction.
  await api(`/api/v0.4/interaction/${sid}/mode`,'PUT',{mode:'OPERATOR_OVERRIDE'});
  await api(`/api/v0.4/interaction/${sid}/mock`,'POST',{text:'价格多少？',users:10});await sleep(700);
  const held=await snapshot();result.operatorHeld={selected:held.data.counters.selected,merged:held.data.counters.merged,candidates:held.data.candidates};if(held.data.counters.selected!==0)throw Error('Operator override admitted automatic speech');
  await api(`/api/v0.4/interaction/${sid}/mode`,'PUT',{mode:'IDLE'});
  const first=await until(`window.__events.find(e=>e.name==='utterance.completed')`,60000);result.mergedUtterance=first.utteranceId;await sleep(2000);
  if(process.env.INTERACTION_RTMP_OBSERVER==='1') {
    const r=await receiver();result.receiverInitial=r.data.counts;
  }
  const topics=process.env.INTERACTION_PATH==='complex'?['complex_price_stock','complex_size_price_stock']:process.env.INTERACTION_PATH==='llm'?['chat','consultation']:['price','sizes','stock','size_stock','chat','consultation'];
  result.arrivalPolicy=process.env.INTERACTION_RANDOM_ARRIVAL==='1'?{kind:'seeded-uniform-gap-after-previous-completion',seed:Number(process.env.INTERACTION_RANDOM_SEED??20261010),minMs:600,maxMs:2200}:{kind:'fixed-gap-after-completion',gapMs:1800};
  const comments=process.env.INTERACTION_PATH==='complex'?['价格和整体库存是多少？再给一句搭配建议。','XL有没有，价格和库存是多少？帮我判断值不值得买。']:process.env.INTERACTION_PATH==='llm'?['你好，请说一句欢迎观众的话。','帮我想一句直播开场白。']:['价格多少？','这款提供 XL 吗？','商品整体库存有多少？','XL 单码有多少库存？','你好，请说一句欢迎观众的话。','帮我想一句直播开场白。'];
  const normalCount=Number(process.env.INTERACTION_SAMPLES??20);
  const extraCount=Number(process.env.INTERACTION_EXTRA_LLM??0);
  const extraComments=['价格和整体库存是多少？再给一句搭配建议。','XL有没有，价格和库存是多少？帮我判断值不值得买。'];
  const topicAt=(i:number)=>i<normalCount?topics[i%topics.length]:['complex_price_stock','complex_size_price_stock'][(i-normalCount)%2];
  const commentAt=(i:number)=>i<normalCount?comments[i%comments.length]:extraComments[(i-normalCount)%2];
  const count=normalCount+extraCount;result.samplePlan={normalCount,extraCount};
  for(let i=0;i<count;i++){
    // More than merge window between repeats of the same test viewer/topic.
    await sleep(process.env.INTERACTION_RANDOM_ARRIVAL==='1'?600+seededRandom()*1600:1800);const before=await snapshot();const selected=before.data.counters.selected;
    const attempt:any={index:i+1,topic:topicAt(i),status:'INCOMPLETE'};result.attempts.push(attempt);save();
    const sent=await evaluate(`(async()=>{const at=performance.now();await window.__api('/api/v0.4/interaction/${sid}/mock','POST',{text:${JSON.stringify(commentAt(i))},users:1});return {at,ackAt:performance.now()}})()`);
    let q:any;for(let j=0;j<200;j++){q=await snapshot();if(q.data.counters.selected>selected&&q.data.utteranceId)break;await sleep(100);}
    if(q.data.counters.selected!==selected+1)throw Error('Comment did not yield exactly one selected task');
    const uid=q.data.utteranceId,traceId=q.data.current.event.traceId;const recv=aligned(q,q.data.observation.receiptAgeMs);const choice=aligned(q,q.data.observation.receiptAgeMs,q.data.observation.receiveToSelectedMs);
    const terminal=await until(`window.__events.find(e=>e.utteranceId===${JSON.stringify(uid)}&&['utterance.completed','utterance.failed'].includes(e.name))`,60000);
    const tq=await traces();const trace=tq.data.traces.find((t:any)=>t.utteranceId===uid);if(!trace)throw Error('Selected trace missing');
    const obs=await evaluate(`(()=>({audio:window.__obs.audio.filter(x=>x.at>=${sent.at}),video:window.__obs.video.filter(x=>x.marker===${trace.media.speechMarker}&&x.generation===${trace.media.generationId}&&x.at>=${sent.at})}))()`);
    const audio=obs.audio[0],video=obs.video[0];const pcm=trace.points.tts_first_pcm,gpu=trace.points.avatar_first_generated_frame;
    const text=aligned(tq,trace.clockOriginAgeMs,trace.points.first_speakable_segment);
    const sample:any={clockExchanges:{backend:{start:q.start,end:q.end,receiptAgeMs:q.data.observation.receiptAgeMs,receiveToSelectedMs:q.data.observation.receiveToSelectedMs},runtime:{start:tq.start,end:tq.end,clockOriginAgeMs:trace.clockOriginAgeMs}},index:i+1,topic:topicAt(i),traceId,utteranceId:uid,terminal:terminal.name,selectionMs:q.data.observation.receiveToSelectedMs,receiptAlignmentUncertaintyMs:recv.uncertaintyMs,selectedToSpeakableMs:text.valueMs-choice.valueMs,selectedToSpeakableUncertaintyMs:text.uncertaintyMs+choice.uncertaintyMs,speakableToPCMMS:pcm-trace.points.first_speakable_segment,pcmToGPUFrameMS:gpu-pcm,runtimePoints:trace.points,media:trace.media,firstCorrelatedAudio:audio??null,firstCorrelatedVideo:video??null};
    if(audio&&video){const av=Math.max(audio.at,video.displayAt);sample.receiveToCorrelatedAVMs=av-recv.valueMs;sample.firstAudioVideoDetectionDifferenceMs=video.displayAt-audio.at;sample.gpuToBrowserVideoMs=video.displayAt-aligned(tq,trace.clockOriginAgeMs,gpu).valueMs;sample.gpuToBrowserUncertaintyMs=tq.end-tq.start;}
    else sample.failure='CORRELATED_AV_NOT_OBSERVED';
    if(process.env.INTERACTION_RTMP_OBSERVER==='1') {
      const rq=await receiver();sample.clockExchanges.receiver={start:rq.start,end:rq.end,clockOriginAgeMs:rq.data.clockOriginAgeMs};const rv=rq.data.rows.find((r:any)=>r.kind==='video'&&r.marker===trace.media.speechMarker&&r.generation===trace.media.generationId);
      // This test admits one speech at a time. Match nonzero AAC in the decoded
      // media-PTS window of the same marked reply, never arbitrary received bytes.
      const ra=rv&&rq.data.rows.find((r:any)=>r.kind==='audio'&&r.pts>=rv.pts-.08&&r.pts<rv.pts+2);
      if(rv&&ra) {
        sample.rtmpFirstVideo=rv;sample.rtmpFirstAudio=ra;
        sample.receiveToRTMPAVMs=aligned(rq,rq.data.clockOriginAgeMs,Math.max(rv.at,ra.at)).valueMs-recv.valueMs;
        sample.rtmpAlignmentUncertaintyMs=(rq.end-rq.start)/2+recv.uncertaintyMs;
        sample.rtmpFirstAudioVideoPTSDifferenceMS=(rv.pts-ra.pts)*1000;
      } else sample.rtmpFailure='CORRELATED_DECODED_AV_NOT_OBSERVED';
    }
    sample.receiveToCorrelatedAVLowerMs=sample.receiveToCorrelatedAVMs-recv.uncertaintyMs;sample.receiveToCorrelatedAVUpperMs=sample.receiveToCorrelatedAVMs+recv.uncertaintyMs;
    result.samples.push(sample);attempt.status=sample.failure||sample.rtmpFailure||sample.terminal!=='utterance.completed'?'FAILED':'COMPLETED';save();console.log(JSON.stringify({index:i+1,topic:sample.topic,terminal:sample.terminal,avMs:sample.receiveToCorrelatedAVMs??null,clockUncertaintyMs:sample.receiptAlignmentUncertaintyMs}));
  }
  if(process.env.INTERACTION_FAULTS==='1') {
    result.faults={};
    async function comment(text:string) {
      const before=(await snapshot()).data.counters.selected;
      await api(`/api/v0.4/interaction/${sid}/mock`,'POST',{text,users:1});
      const uid=await until(`window.__api('/api/v0.4/interaction/${sid}/').then(s=>s.counters.selected===${before+1}&&s.utteranceId)`,15000);
      return uid;
    }
    async function terminal(uid:string) {
      return await until(`window.__events.find(e=>e.utteranceId===${JSON.stringify(uid)}&&['utterance.completed','utterance.failed'].includes(e.name))`,60000);
    }
    await sleep(2000);
    const old=await comment('XL 单码有多少库存？');
    await until(`window.__events.find(e=>e.utteranceId===${JSON.stringify(old)}&&e.name==='utterance.playing')`,30000);
    const oldTrace=(await traces()).data.traces.find((t:any)=>t.utteranceId===old);
    const forceAt=await evaluate('performance.now()');
    const force=await api(`/api/v1/live-sessions/${sid}/utterances`,'POST',{text:'价格多少？',priority:100,interruptPolicy:'FORCE',source:'OPERATOR'});
    const interrupted=await until(`window.__events.find(e=>e.utteranceId===${JSON.stringify(old)}&&e.name==='utterance.interrupted')`);
    const done=await terminal(force.utteranceId);
    if(done.name!=='utterance.completed')throw Error('Operator FORCE failed');
    const newTrace=(await traces()).data.traces.find((t:any)=>t.utteranceId===force.utteranceId);
    const fence=await evaluate(`(()=>{const first=window.__obs.video.find(v=>v.generation===${newTrace.media.generationId}&&v.at>=${forceAt});return {newGeneration:first?.generation,staleAfterNew:first?window.__obs.video.filter(v=>v.at>first.at&&v.generation===${oldTrace.media.generationId}).length:null}})()`);
    if(!fence.newGeneration||fence.staleAfterNew!==0)throw Error('Chrome generation fence did not hold');
    const held=(await snapshot()).data;
    if(held.mode!=='OPERATOR_OVERRIDE')throw Error('Operator FORCE did not own interaction');
    result.faults.force={oldUtterance:old,newUtterance:force.utteranceId,oldTerminal:interrupted.name,newTerminal:done.name,...fence,automaticForce:held.counters.force};
    // Explicit resume is required after an operator command.
    await api(`/api/v0.4/interaction/${sid}/mode`,'PUT',{mode:'IDLE'});
    if(process.env.INTERACTION_FORCE_ONLY!=='1') {
    const before=await api(`/api/v0.4/sessions/${sid}/providers`);
    await workerAction('stop');
    const fallback=await comment('商品整体库存有多少？');
    const fallbackDone=await terminal(fallback);
    const degraded=await until(`window.__api('/api/v0.4/sessions/${sid}/providers').then(p=>p.mode==='DEGRADED'&&p)`,20000);
    await workerAction('start');await sleep(16000);
    const recoveredUID=await comment('这款提供 XL 吗？');
    const recoveredDone=await terminal(recoveredUID);
    const recovered=await until(`window.__api('/api/v0.4/sessions/${sid}/providers').then(p=>p.mode==='REAL'&&p)`,20000);
    const recoveryTrace=(await traces()).data.traces.find((t:any)=>t.utteranceId===recoveredUID);
    if(fallbackDone.name!=='utterance.completed'||recoveredDone.name!=='utterance.completed'||recovered.workerEpoch===before.workerEpoch||!recoveryTrace.points.avatar_first_generated_frame)throw Error('Real Worker recovery did not complete');
    result.faults.recovery={fallbackTerminal:fallbackDone.name,recoveredTerminal:recoveredDone.name,degradedMode:degraded.mode,recoveredMode:recovered.mode,oldEpoch:before.workerEpoch,newEpoch:recovered.workerEpoch,bindingUnchanged:before.bindingId===recovered.bindingId&&JSON.stringify(before.profiles)===JSON.stringify(recovered.profiles),trace:recoveryTrace};
    }
    await api(`/api/v0.4/interaction/${sid}/mode`,'PUT',{mode:'OPERATOR_OVERRIDE'});
    await api(`/api/v0.4/interaction/${sid}/replay`,'POST',{rate:20,count:1000});await sleep(1300);
    await api(`/api/v0.4/interaction/${sid}/replay`,'DELETE');await sleep(400);
    const stoppedReplay=(await snapshot()).data;await sleep(500);const stable=(await snapshot()).data;
    if(stoppedReplay.counters.input!==stable.counters.input)throw Error('Cancelled Replay kept delivering');
    result.faults.replayCancellation={inputStable:stable.counters.input,candidates:stable.candidates,selected:stable.counters.selected,peak:stable.counters.peak};
    result.faults.sse=await evaluate('window.__events.filter(e=>["session.degraded","session.started","runtime.warning"].includes(e.name))');
    save();
  }
  if(['1','busy'].includes(process.env.INTERACTION_SCENARIOS??''))result.scenarios=await(await import('./interaction-real-scenarios.ts')).runScenarios({api,snapshot,traces,until,evaluate,sleep,sid,roomId:room.roomId,productId:product.productId,busyOnly:process.env.INTERACTION_SCENARIOS==='busy',progress:(v:any)=>{result.scenarios=v;save()}});
  result.finalSnapshot=(await snapshot()).data;result.afterProviders=await api(`/api/v0.4/sessions/${sid}/providers`);
  result.bundleUnchanged=result.providers.bindingId===result.afterProviders.bindingId&&JSON.stringify(result.providers.profiles)===JSON.stringify(result.afterProviders.profiles);
  if(process.env.INTERACTION_RTMP_OBSERVER==='1')result.receiverFinal=(await receiver()).data.counts;
  result.nativeStats=await evaluate(`(async()=>[...(await window.__peer.getStats()).values()].filter(s=>s.type==='inbound-rtp'||s.type==='media-playout').map(s=>({type:s.type,kind:s.kind,framesDecoded:s.framesDecoded,framesDropped:s.framesDropped,packetsReceived:s.packetsReceived,packetsLost:s.packetsLost,totalAudioEnergy:s.totalAudioEnergy,estimatedPlayoutTimestamp:s.estimatedPlayoutTimestamp,totalSamplesDuration:s.totalSamplesDuration})))()`);
  result.browserVersion=(await call('Browser.getVersion')).product;
  const image=await call('Page.captureScreenshot',{format:'png'});writeFileSync(`${output}.png`,Buffer.from(image.data,'base64'));
  result.receiveToCorrelatedAV=stats(result.samples.filter((s:any)=>s.receiveToCorrelatedAVMs!==undefined).map((s:any)=>s.receiveToCorrelatedAVMs));
  result.receiveToRTMPAV=stats(result.samples.filter((s:any)=>s.receiveToRTMPAVMs!==undefined).map((s:any)=>s.receiveToRTMPAVMs));
  result.failedSamples=result.samples.filter((s:any)=>s.failure||s.terminal!=='utterance.completed').length;
} catch(e:any) {result.errors.push(e.message);const pendingAttempt=result.attempts.findLast((a:any)=>a.status==='INCOMPLETE');if(pendingAttempt){pendingAttempt.status='FAILED';pendingAttempt.error=e.message;}console.error(e.message);process.exitCode=1;}
finally {
  if(process.env.INTERACTION_RECORD==='1'&&ws?.readyState===WebSocket.OPEN){try{const data=await evaluate(`(async()=>{const r=window.__recorder;if(!r)return null;if(r.state!=='inactive'){await new Promise(ok=>{r.onstop=ok;r.stop()})};const b=new Blob(window.__recordChunks,{type:'video/webm'});return await new Promise(ok=>{const f=new FileReader();f.onload=()=>ok(f.result);f.readAsDataURL(b)})})()`);if(data){const path=output+'.webm';writeFileSync(path,Buffer.from(data.split(',')[1],'base64'));result.recording={file:path,scope:'native Chrome decoded MediaStream capture; human review pending'}}}catch(e:any){result.errors.push('Recording: '+e.message)}}
  if(sid&&ws?.readyState===WebSocket.OPEN){try{await api(`/api/v1/live-sessions/${sid}/stop`,'POST',{});result.finalState=await until(`window.__api('/api/v1/live-sessions/${sid}').then(s=>s.status==='ENDED'&&s.status)`,20000);}catch(e:any){result.errors.push('Stop: '+e.message);}}
  if(workerStopped){try{await workerAction('start');result.workerRestored=true;}catch(e:any){result.errors.push('Worker restore failed');}}
  save();ws?.close();chrome.kill();
}
