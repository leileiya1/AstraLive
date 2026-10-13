"""Read-only GPU checkpoint monitor. Never dumps argv/environment/credentials."""
import pathlib,json,subprocess,time,sys
p=pathlib.Path(sys.argv[1]);pid=int((p/'worker.pid').read_text());records=[]
with(p/'worker-events.jsonl').open()as f:
 for line in f:
  try:records.append(json.loads(line))
  except ValueError:pass
outputs=[x for x in records if x['event']=='GPUOutput'];published=[x for x in records if x['event']=='VideoPacketPublished'];seconds=sum(x['elapsed_ms']for x in outputs)/1000;frames=sum(x['generated_frames']for x in outputs);health=next((x for x in reversed(records)if x['event']=='WorkerHealth'),None)
r=subprocess.run(['nvidia-smi','--query-gpu=name,memory.used,utilization.gpu,temperature.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True)
print(json.dumps({'pid':pid,'alive':pathlib.Path('/proc/'+str(pid)).exists(),'gpu':r.stdout.strip(),'ready':json.loads((p/'worker-ready.json').read_text()),'workerHealth':health,'modelLoadCount':sum(x['event']=='ModelLoadStart'for x in records),'generatedFrames':frames,'trueInferenceFPS':frames/seconds if seconds else None,'publishedFrames':len(published),'generationCancels':sum(x['event']=='CancelGeneration'for x in records),'staleGpuResultFrames':sum(x.get('frames',0)for x in records if x['event']=='stale_gpu_output_rejected'),'scope':'worker lifetime counters; compute FPS distinct from publish/playback FPS and cached frames','wall_time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}))
