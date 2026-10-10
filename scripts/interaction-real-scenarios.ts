// Opt-in supplement, called only by the isolated real browser acceptance driver.
export async function runScenarios(h:any) {
 const {api,snapshot,traces,until,evaluate,sleep,sid,roomId,productId}=h;
 const result:any={classification:'ISOLATED_REAL_BUSY_RANDOM_SINGLE_MOCK_VIEWER_AND_BURST',errors:[]};
 const state=async()=>(await snapshot()).data;
 const terminal=async(uid:string)=>await until(`window.__events.find(e=>e.utteranceId===${JSON.stringify(uid)}&&['utterance.completed','utterance.failed','utterance.interrupted'].includes(e.name))`,60000);
 // A previous Replay-cancellation phase can leave valid candidates. Keep that
 // evidence, then let its TTL expire before testing an isolated busy arrival.
 await api(`/api/v0.4/interaction/${sid}/mode`,'PUT',{mode:'OPERATOR_OVERRIDE'});
 if((await state()).candidates>0)await sleep(21000);
 if((await state()).candidates!==0)throw Error('Previous phase backlog did not expire before busy fixture');
 await api(`/api/v0.4/interaction/${sid}/mode`,'PUT',{mode:'PRODUCT_EXPLAINING'});
 const before=await state();
 const script=await api(`/api/v1/live-sessions/${sid}/utterances`,'POST',{text:'请介绍这款商品的详情和尺码。',priority:40,interruptPolicy:'NONE',source:'AUTO_SCRIPT'});
 await until(`window.__events.find(e=>e.utteranceId===${JSON.stringify(script.utteranceId)}&&e.name==='utterance.playing')`);
 const arrivedAt=await evaluate('performance.now()');
 await api(`/api/v0.4/interaction/${sid}/mock`,'POST',{text:'商品整体库存有多少？',users:1});
 await sleep(700);const busy=await state();const stillTalking=await evaluate(`!window.__events.some(e=>e.utteranceId===${JSON.stringify(script.utteranceId)}&&['utterance.completed','utterance.interrupted','utterance.failed'].includes(e.name))`);
 if(!stillTalking||busy.counters.selected!==before.counters.selected)throw Error('Busy ordinary comment interrupted/selected during existing AUTO_SCRIPT');
 const done=await terminal(script.utteranceId);if(done.name!=='utterance.completed')throw Error('AUTO_SCRIPT did not complete normally');
 const reply=await until(`window.__api('/api/v0.4/interaction/${sid}/').then(s=>s.counters.selected>${before.counters.selected}&&s.utteranceId)`,30000);
 const replyDone=await terminal(reply);if(replyDone.name!=='utterance.completed')throw Error('Waiting ordinary reply did not complete');
 const replyTrace=(await traces()).data.traces.find((t:any)=>t.utteranceId===reply);
 result.busy={source:'AUTO_SCRIPT',scriptUtterance:script.utteranceId,scriptTerminal:done.name,stillTalkingAtCheck:stillTalking,beforeSelected:before.counters.selected,busySelected:busy.counters.selected,replyUtterance:reply,replyTerminal:replyDone.name,replyTrace,arrivalAtBrowserMs:arrivedAt,completedAtBrowserMs:replyDone.at};
 h.progress?.(result);
 if(h.busyOnly){result.limitations=['Busy scenario only; random/burst/product-switch retained in previous complete trial'];return result;}
 let seed=20261010>>>0;const random=()=>{seed=(1664525*seed+1013904223)>>>0;return (seed+.5)/4294967296};
 const comments=['价格多少？','这款提供 XL 吗？','商品整体库存有多少？','XL 单码有多少库存？','XL 和 XXL 都有吗？','帮我写一句开场白。'];
 result.randomLoads=[];
 for(const [rate,count] of [[1,8],[5,30],[20,100]]) {
  await api(`/api/v0.4/interaction/${sid}/mode`,'PUT',{mode:'IDLE'});
  const start=await evaluate('performance.now()');const initial=await state();const requests=[];
  for(let i=0;i<count;i++) {
   await sleep(-Math.log(random())*1000/rate);
   const row=await evaluate(`(async()=>{const at=performance.now();const r=await fetch('/api/v0.4/interaction/${sid}/mock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:${JSON.stringify(comments[i%comments.length])},users:1})});const data=await r.json();return {at,ackAt:performance.now(),status:r.status,code:data.code}})()`);
   requests.push(row);
  }
  await sleep(21000);const final=await state();
  if(final.counters.force!==0||final.counters.peak>64)throw Error('Real load forced speech or exceeded capacity');
  result.randomLoads.push({targetRate:rate,requested:count,seed:20261010,viewerScope:'same Mock endpoint viewer id; user rate limit applies; not a many-user throughput claim',durationMs:(requests.at(-1).at-start),requests,initial,final});h.progress?.(result);
 }
 await api(`/api/v0.4/interaction/${sid}/mode`,'PUT',{mode:'IDLE'});
 const burstBefore=await state();await api(`/api/v0.4/interaction/${sid}/mock`,'POST',{text:'价格多少？',users:100});await sleep(21000);const burstAfter=await state();
 if(burstAfter.counters.force!==0||burstAfter.counters.peak>64)throw Error('Burst queue/fence failed');
 result.burst={users:100,before:burstBefore,after:burstAfter};h.progress?.(result);
 // Captured facts remain immutable. Changing the owned room must clear old
 // candidates and request a new Session, rather than treating the new room as bound.
 const room=await api(`/api/v1/live-rooms/${roomId}`);
 const replacement=await api('/api/v1/products','POST',{name:'验收新商品',description:'不同商品的独立测试事实。',price:399,currency:'CNY',stock:5,sizes:['S']});
 const input={name:room.name,avatarId:room.avatarId,voiceId:room.voiceId,systemPrompt:room.systemPrompt,activeProductId:replacement.productId};
 const productBefore=await state();await api(`/api/v0.4/interaction/${sid}/mode`,'PUT',{mode:'OPERATOR_OVERRIDE'});await api(`/api/v0.4/interaction/${sid}/mock`,'POST',{text:'这款有什么材质？',users:4});await sleep(200);
 try {
  await api(`/api/v1/live-rooms/${roomId}`,'PUT',input);
  await api(`/api/v0.4/interaction/${sid}/mode`,'PUT',{mode:'IDLE'});await sleep(2500);
  const switched=await state();
  if(switched.mode!=='OPERATOR_OVERRIDE'||switched.lastError!=='PRODUCT_CHANGED_NEW_SESSION_REQUIRED'||switched.candidates!==0||switched.counters.selected!==productBefore.counters.selected)throw Error('Product change admitted stale/new-product speech');
  result.productSwitch={originalProductId:productId,replacementProductId:replacement.productId,before:productBefore,after:switched};
 } finally {await api(`/api/v1/live-rooms/${roomId}`,'PUT',{...input,activeProductId:productId});}
 result.traceCount=(await traces()).data.traces.length;
 result.limitations=['Native browser decoded media, not human speaker/lip-sync or official platform viewers','Random rate inputs use one Mock viewer; many-viewer steady rates are separate existing Replay/CPU tests','Bounded short run, not a production soak'];
 return result;
}
