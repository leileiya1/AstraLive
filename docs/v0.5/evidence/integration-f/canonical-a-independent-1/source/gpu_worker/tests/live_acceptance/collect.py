"""Immutable end-of-run evidence collection and independently scoped summary."""
import json,pathlib,subprocess,sys,collections,numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[3];p=ROOT/'astralive-avatar-lab/streaming/integration'/sys.argv[1];remote='/home/sapiece/AstraLive/experiments/real-avatar/'+p.name
capture=p/'runtime-capture';capture.mkdir(exist_ok=True)
subprocess.run(['rsync','-a',f'school-linux:{remote}/integration/',str(capture)+'/'],check=True,timeout=120)
# Decode the complete stopped RTMP recording beside its receiver. Keep original
# bytes there, with hash/size/path in the local evidence; avoid a multi-GB VPN copy.
subprocess.run(['rsync','-a',str(pathlib.Path(__file__).with_name('decode_media.py')),f'school-linux:{remote}/decode_received_media.py'],check=True,timeout=30)
result=subprocess.run(['ssh','-o','BatchMode=yes','school-linux',f'nice -n 10 /home/sapiece/AstraLive/runtime/.venv/bin/python {remote}/decode_received_media.py {remote}/rtmp-received.mkv --single'],check=True,capture_output=True,text=True,timeout=600)
(p/'rtmp-remote-decode.json').write_text(json.dumps(json.loads(result.stdout),indent=2))
s=json.loads((p/'browser-summary.json').read_text());ready=json.loads((p/'formal-ready.json').read_text());stats=[json.loads(x) for x in (p/'browser-stats.jsonl').read_text().splitlines()];formal=[x for x in stats if x['browserMonotonic']>=ready['begin']];rows=[json.loads(x) for x in (p/'browser-events.jsonl').read_text().splitlines()];runtime=[json.loads(x) for x in (capture/'avatar-events.jsonl').read_text().splitlines()]
failures=[x for x in rows if x['event']=='RuntimeBusinessEvent' and (x['runtimeEvent']['eventType'] in {'UTTERANCE_FAILED','MEDIA_FAILED','SESSION_FAILED','RUNTIME_ERROR'} or x['runtimeEvent']['eventType']=='RUNTIME_WARNING' and x['runtimeEvent'].get('payload',{}).get('code') in {'LLM_FAILED','TTS_FAILED','AVATAR_RENDER_FAILED'})]
forces=[x for x in rows if x['event']=='FORCE_DisplayFence'];displayed=[x for x in rows if x['event']=='BrowserFrameDisplayed'];fence=1;violations=[]
for x in rows:
 if x['event']=='FORCE_DisplayFence':fence=x['minimumGeneration']
 elif x['event']=='BrowserFrameDisplayed' and x['generation']<fence:violations.append(x)
gpu=[json.loads(x) for x in (p/'gpu-stats.jsonl').read_text().splitlines()];health=[x['health'] for x in gpu if 'ready' in x.get('health',{})];epochs=sorted({x['workerEpoch'] for x in health});bounds=[x for x in health if x['queueDepth']['audioSamples']>32000 or x['queueDepth']['videoFrames']>24]
def peak(field):
 return max((x[field] for x in health if isinstance(x.get(field),(int,float))),default=None)
checkpoints={f.name:json.loads(f.read_text()) for f in p.glob('checkpoint-*.json')}
target=s.get('requestedDurationSeconds',3600)
required={'checkpoint-90s.json','checkpoint-5m.json'}
if target>=3600:required.update({'checkpoint-15m.json','checkpoint-30m.json','checkpoint-45m.json','checkpoint-60m.json'})
values=[x['nativeEstimatedAVOffsetMs'] for x in formal if x.get('nativeEstimatedAVOffsetMs') is not None]
summary={'scope':'isolated Go public API / real LLM / real Sherpa TTS / product SoulX GPU Worker 1.1 / real Chrome WebRTC / test RTMP receiver; operator-authorized lab binding, not production configuration route acceptance','run':p.name,'sessionId':s.get('sessionId'),'browserStatus':s['status'],'durationSeconds':s.get('actualDurationSeconds'),'formalPeerCount':1,'workerEpochs':epochs,'allCheckpointsPassed':bool(checkpoints) and all(c['passed'] for c in checkpoints.values()),'checkpointResults':{n:{'passed':c['passed'],'reason':c['reason'],'nativeEstimatedSync':c['nativeEstimatedSync'],'recordingSync':c.get('recordingSync')} for n,c in checkpoints.items()},'businessFailureCount':len(failures),'businessFailures':failures,'canvasFenceViolations':violations,'queueBoundsViolations':bounds,'forceCountTotal':len(forces),'formalForceCount':s.get('formalForceCount'),'runtimeEventCounts':dict(collections.Counter(x['event'] for x in runtime)),'browserEventCounts':dict(collections.Counter(x['event'] for x in rows)),'nativeEstimatedAVOffsetP50P95MaxMs':np.percentile(np.abs(values),[50,95,100]).tolist() if values else None,'gpuAllocatedPeakBytes':peak('gpuAllocatedBytes'),'gpuReservedPeakBytes':peak('gpuReservedBytes'),'gpuDeviceMemoryPeakBytes':peak('gpuDeviceMemoryUsedBytes'),'trueGeneratedFPSSampledRange':[min((x['trueGeneratedFPS'] for x in health),default=None),max((x['trueGeneratedFPS'] for x in health),default=None)],'modelComputeFPSSampledMax':max((x['modelComputeFPS'] for x in health),default=None),'nativeVideoDecoded':s.get('finalStats',{}).get('videoFrames'),'nativeAudioPackets':s.get('finalStats',{}).get('audioPackets'),'normalStop':s.get('normalStop'),'stopError':s.get('stopError'),'markerScope':'lab-only colored packet markers overlay top24px, not unmarked visual quality approval'}
summary['requiredCheckpointsPresent']=required.issubset(checkpoints)
summary['passed']=s['status']=='CONTINUOUS_SESSION_COMPLETED' and summary['requiredCheckpointsPresent'] and summary['allCheckpointsPassed'] and (s.get('actualDurationSeconds') or 0)>=target and (s.get('formalForceCount') or 0)>=(30 if target>=3600 else 2) and not failures and not violations and not bounds and len(epochs)==1 and bool(s.get('normalStop')) and not s.get('stopError')
if s['status'] in {'RECOVERY_COMPLETED','NETWORK_RECOVERY_COMPLETED'}:
 network=s['status']=='NETWORK_RECOVERY_COMPLETED'
 fault=json.loads((p/'fault-injection.json').read_text())
 last_force=forces[-1] if forces else None
 future_gpu=[x for x in displayed if last_force and x['browserMonotonic']>last_force['browserMonotonic'] and x.get('source')=='GPU_INFERENCE' and x['generation']>=last_force['minimumGeneration']]
 lightweight=[x for x in displayed if x.get('source')=='LIGHTWEIGHT_AVATAR']
 summary.update(scope=summary['scope']+'; separate controlled '+('inference-tunnel disconnect' if network else 'owned Worker child crash'),samePeer=s.get('samePeer'),sessionStayedLive=s.get('sessionStayedLive'),oldEpoch=s.get('oldEpoch'),recoveredEpoch=s.get('recoveredEpoch'),reconnectSeconds=s.get('reconnectSeconds'),lightweightDisplayed=len(lightweight),futureGPUDisplayed=len(future_gpu),allFormalStatsConnected=bool(formal) and all(x['connection']=='connected' for x in formal))
 epoch_ok=(s['oldEpoch']==s['recoveredEpoch'] and epochs==[s['oldEpoch']]) if network else (s['oldEpoch']!=s['recoveredEpoch'] and set(epochs)=={s['oldEpoch'],s['recoveredEpoch']})
 restore_ok=not network or json.loads((p/'tunnel-restored.json').read_text()).get('restored') is True
 summary['passed']=fault.get('injected') is True and restore_ok and epoch_ok and bool(lightweight) and bool(future_gpu) and s.get('samePeer') is True and s.get('sessionStayedLive') is True and summary['allFormalStatsConnected'] and not failures and not violations and not bounds and bool(s.get('normalStop')) and not s.get('stopError')
(p/'acceptance-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:summary[k] for k in ['passed','durationSeconds','businessFailureCount','formalForceCount','nativeEstimatedAVOffsetP50P95MaxMs','gpuAllocatedPeakBytes','gpuReservedPeakBytes']}))
