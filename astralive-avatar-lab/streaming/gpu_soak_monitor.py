import subprocess,time,json,pathlib
p=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab/streaming/evidence/gpu-soak-20261009.jsonl')
with p.open('w',buffering=1) as f:
 for _ in range(400):
  raw=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu,temperature.gpu','--format=csv,noheader,nounits'],text=True).strip().split(',')
  f.write(json.dumps(dict(monotonic_s=time.monotonic(),memory_mib=int(raw[0]),utilization_pct=int(raw[1]),temperature_c=int(raw[2])))+'\n');time.sleep(10)
