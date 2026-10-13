import argparse,datetime,json,os,pathlib,subprocess,time
LAB=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab')
p=argparse.ArgumentParser();p.add_argument('--label',required=True);p.add_argument('--repository',choices=['MuseTalk','SoulX-FlashHead'],default='MuseTalk');p.add_argument('command',nargs=argparse.REMAINDER);args=p.parse_args()
command=args.command
if command and command[0]=='--':command=command[1:]
os.environ['OMP_NUM_THREADS']='8';os.environ['MKL_NUM_THREADS']='8';os.environ['TOKENIZERS_PARALLELISM']='false'
env_name='astralive-soulx' if args.repository=='SoulX-FlashHead' else 'astralive-musetalk'
os.environ['PATH']=str(LAB/'tools/bin')+':'+str(LAB/'environments'/env_name/'bin')+':'+os.environ['PATH']
os.environ['HF_ENDPOINT']='https://hf-mirror.com'
os.environ['IMAGEIO_FFMPEG_EXE']='/usr/bin/ffmpeg';os.environ['TORCH_CUDA_ARCH_LIST']='8.9';os.environ['MAX_JOBS']='8';os.environ['TORCHINDUCTOR_COMPILE_THREADS']='4'
start=time.perf_counter();record={'command':command,'label':args.label,'status':'RUNNING','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
dest=LAB/'benchmarks'/f'{args.label}-command.json'
with (LAB/'logs'/f'{args.label}.log').open('wb') as logfile:
    proc=subprocess.Popen(command,cwd=LAB/'repositories'/args.repository,stdout=logfile,stderr=subprocess.STDOUT)
    record['pid']=proc.pid;dest.write_text(json.dumps(record,indent=2))
    sampler=subprocess.Popen(['/root/miniconda3/bin/python',str(LAB/'scripts/sample-gpu.py'),'--pid',str(proc.pid),'--label',args.label])
    code=proc.wait();sampler.wait(timeout=15)
record.update(exit_code=code,wall_seconds=time.perf_counter()-start,status='COMMAND_EXIT_ZERO_REQUIRES_OUTPUT_VALIDATION' if code==0 else 'FAILED')
dest.write_text(json.dumps(record,indent=2));print(json.dumps(record));raise SystemExit(code)
