const assert=require('node:assert/strict');
const gate=require('./final_player_gate.js');
const room={state:'LIVE',generationId:2,workerEpoch:'epoch',degraded:false,lastFrame:{source:'GPU_INFERENCE'}};
const monitor={workerAlive:true,rtmpPublisherReady:true,ageSeconds:2};
assert.equal(gate.ready(room,monitor,100).ready,true);
assert.equal(gate.ready({...room,degraded:true},monitor,100).ready,false); // Actual failed-entry regression.
assert.equal(gate.ready({...room,lastFrame:{source:'LIGHTWEIGHT_AVATAR'}},monitor,100).ready,false);
assert.equal(gate.ready({...room,lastFrame:{source:'CACHED_IDLE'}},monitor,100).ready,false);
assert.equal(gate.ready({...room,workerEpoch:null},monitor,100).ready,false); // Fresh connection must establish its own epoch.
assert.equal(gate.ready(undefined,monitor,100).ready,false); // Refresh must not inherit old ready state.
assert.equal(gate.ready(room,{...monitor,ageSeconds:46},100).ready,false);
assert.equal(gate.ready(room,{...monitor,rtmpPublisherReady:false},100).ready,false);
assert.equal(gate.ready(room,{...monitor,workerAlive:false},100).ready,false);
assert.equal(gate.ready(room,monitor,0).ready,false);
console.log('10 readiness / fallback / refresh checks passed');
