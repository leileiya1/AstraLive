"""Small read-only progress report for a detached acceptance run."""
import pathlib,json,sys,time
root=pathlib.Path(__file__).resolve().parents[3];p=root/'astralive-avatar-lab/streaming/integration'/sys.argv[1];out={'run':p.name}
for name in ['progress.json','browser-summary.json']:
 if (p/name).exists():
  j=json.loads((p/name).read_text());out[name]={k:j[k] for k in ['status','error','event','elapsedSeconds','actualDurationSeconds','cycle','cycles','forceCount','formalForceCount','normalStop','stopError'] if k in j}
if (p/'browser-stats.jsonl').exists():
 with (p/'browser-stats.jsonl').open('rb') as f:
  f.seek(max(0,(p/'browser-stats.jsonl').stat().st_size-16000));rows=f.read().splitlines()
 try:
  j=json.loads(rows[-1]);out['latestMedia']={k:j.get(k) for k in ['browserMonotonic','connection','ice','videoFrames','audioPackets','nativeEstimatedAVOffsetMs']}
  ready=json.loads((p/'formal-ready.json').read_text());out['elapsedLatestSeconds']=round(j['browserMonotonic']-ready['begin'],1)
 except (ValueError,FileNotFoundError):pass
if (p/'monitor-latest.json').exists():
 j=json.loads((p/'monitor-latest.json').read_text());g=j['gpu'].get('health',{});out['health']={k:g.get(k) for k in ['ready','health','workerEpoch','queueDepth','trueGeneratedFPS','modelComputeFPS','lastError']};out['health']['allocatedGiB']=round(g['gpuAllocatedBytes']/2**30,3) if g.get('gpuAllocatedBytes') is not None else None;out['health']['reservedGiB']=round(g['gpuReservedBytes']/2**30,3) if g.get('gpuReservedBytes') is not None else None;out['rtmpPublisherReady']=j.get('rtmpPublisherReady');out['monitorAgeSeconds']=round(time.monotonic()-j.get('sampleMonotonic',0),1)
out['checkpoints']={}
for f in p.glob('checkpoint-*.json'):
 j=json.loads(f.read_text());out['checkpoints'][f.name]={'passed':j['passed'],'reason':j['reason'],'nativeP95Ms':j['nativeEstimatedSync']['absolute_ms_p50_p95_max'][1],'recordingP95Ms':{k:v['medianP95MaxMs'][1] if v.get('medianP95MaxMs') else None for k,v in j.get('recordingSync',{}).items() if isinstance(v,dict) and 'medianP95MaxMs' in v}}
print(json.dumps(out,ensure_ascii=False))
