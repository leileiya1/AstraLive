/* Experimental readiness; never admit a historical GPU frame or a degraded room. */
const SoulXFinalGate = {
 businessFailure(events, sessionId) {
  return (events||[]).find(e=>e.sessionId===sessionId &&
   (['UTTERANCE_FAILED','MEDIA_FAILED','SESSION_FAILED','RUNTIME_ERROR'].includes(e.eventType)||
    (e.eventType==='RUNTIME_WARNING'&&['LLM_FAILED','TTS_FAILED','AVATAR_RENDER_FAILED'].includes(e.payload?.code))));
 },
 ready(snapshot, monitor, displayed) {
  const reasons=[];
  if(snapshot?.state!=='LIVE')reasons.push('session is not LIVE');
  if(snapshot?.degraded)reasons.push('session already degraded');
  if(!snapshot?.workerEpoch)reasons.push('worker epoch is unavailable');
  if(snapshot?.lastFrame?.source!=='GPU_INFERENCE')reasons.push('latest consumed frame is not live GPU output');
  if(!monitor?.workerAlive)reasons.push('worker is not alive');
  if(!monitor?.rtmpPublisherReady)reasons.push('RTMP publisher is not ready');
  if(!Number.isFinite(monitor?.ageSeconds)||monitor.ageSeconds>45)reasons.push('host readiness snapshot is stale');
  if(displayed<50)reasons.push('insufficient real GPU canvas frames');
  return {ready:reasons.length===0,reasons};
 }
};
globalThis.SoulXFinalGate=SoulXFinalGate;
if(typeof module!=='undefined')module.exports=SoulXFinalGate;
