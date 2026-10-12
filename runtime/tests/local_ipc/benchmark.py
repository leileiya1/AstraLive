"""Owned subprocess benchmark. pip install psutil (benchmark only)."""
import argparse, hashlib, json, os, platform, secrets, socket, statistics, subprocess, sys, tempfile, time
from pathlib import Path
import psutil

ROOT=Path(__file__).resolve().parents[3]
def percentiles(values):
    a=sorted(values)
    return {f'p{p}':a[min(len(a)-1, max(0, __import__('math').ceil(len(a)*p/100)-1))] for p in (50,95,99)}
def snapshot(p):
    try: fds=p.num_fds() if hasattr(p,'num_fds') else None
    except psutil.AccessDenied: fds=None
    return {'cpuSeconds':sum(p.cpu_times()[:2]), 'rssBytes':p.memory_info().rss, 'fds':fds}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--transport',choices=['baseline','tcp','uds'],default='baseline');parser.add_argument('--count',type=int,default=200);a=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='al-ipc-',dir=os.path.realpath('/tmp') if os.name!='nt' else None) as directory:
        root=Path(directory);root.chmod(0o700)
        for name in ('control','worker'):
            (root/name).write_text(secrets.token_hex(24));(root/name).chmod(0o600)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        env={**os.environ,'PYTHONPATH':str(ROOT/'runtime')+os.pathsep+str(ROOT),'SESSION_BINDINGS_ENABLED':'true','CONFIG_BACKEND_URL':'http://127.0.0.1:1','CONFIG_WORKER_TOKEN_FILE':str(root/'worker'),'RUNTIME_CONTROL_TOKEN_FILE':str(root/'control'),'REDIS_URL':'','ASTRALIVE_LOCAL_TRANSPORT':a.transport if a.transport!='baseline' else 'tcp','ASTRALIVE_RUNTIME_UDS_PATH':str(root/'runtime.sock'),'ASTRALIVE_BENCH_LOCAL':str(a.transport!='baseline').lower(),'AI_RUNTIME_URL':f'http://127.0.0.1:{port}'}
        command=[sys.executable,'-m','uvicorn','runtime.tests.local_ipc.benchmark_app:app','--host','127.0.0.1','--port',str(port),'--no-access-log'] if a.transport=='baseline' else [sys.executable,'-m','app.local_listener','--app','runtime.tests.local_ipc.benchmark_app:app']
        with (root/'server.log').open('w') as log:
            server=subprocess.Popen(command,env=env,stdout=log,stderr=log,cwd=ROOT)
            try:
                for _ in range(200):
                    if server.poll() is not None:raise RuntimeError((root/'server.log').read_text())
                    try:
                        with socket.socket(socket.AF_UNIX if a.transport=='uds' else socket.AF_INET) as s:s.connect(str(root/'runtime.sock') if a.transport=='uds' else ('127.0.0.1',port))
                        break
                    except OSError:time.sleep(.05)
                else:raise RuntimeError('server startup timeout')
                proc=psutil.Process(server.pid);results=[]
                args=[str(ROOT/'runtime/tests/local_ipc/bench'),'--url',env['AI_RUNTIME_URL'],'--token-file',str(root/'control')]
                for cold,size,c in [(True,1024,1)]+[(False,size,c) for size in (1024,10240,102400) for c in (1,10,50)]:
                    before=snapshot(proc);begin=time.monotonic()
                    output_file=(root/'client.json').open('w+')
                    p=subprocess.Popen(args+['--size',str(size),'--concurrency',str(c),'--count',str(a.count)]+(['--cold'] if cold else []),env=env,stdout=output_file)
                    client=psutil.Process(p.pid);peaks={'clientRSSBytes':0,'clientFDs':0,'serverRSSBytes':0,'serverFDs':0}
                    clientCPU=0; inaccessible_fds=False
                    while p.poll() is None:
                        try:
                            info=snapshot(client);srv=snapshot(proc);clientCPU=info['cpuSeconds'];inaccessible_fds |= info['fds'] is None
                            for k,v in [('clientRSSBytes',info['rssBytes']),('clientFDs',info['fds']),('serverRSSBytes',srv['rssBytes']),('serverFDs',srv['fds'])]:
                                if v is not None:peaks[k]=max(peaks[k],v)
                        except psutil.NoSuchProcess:pass
                        time.sleep(.005)
                    p.wait();output_file.seek(0);raw=json.load(output_file);output_file.close();samples=raw['samples']
                    if p.returncode or any(s['status']!=409 or s.get('error') for s in samples):raise RuntimeError(f'unexpected response: {samples[:3]}')
                    if inaccessible_fds:peaks['clientFDs']=raw.get('resources',{}).get('selfSampledFDPeak')
                    after=snapshot(proc);duration=time.monotonic()-begin
                    results.append({'cold':cold,'requestedBytes':size,'payloadBytes':raw['payloadBytes'],'concurrency':c,'count':a.count,'durationSeconds':duration,'totalMs':percentiles([s['totalMs'] for s in samples]),'appMs':percentiles([s['serverMs'] for s in samples]),'residualMs':percentiles([max(0,s['totalMs']-s['serverMs']) for s in samples]),'connectMs':percentiles([s['connectMs'] for s in samples if not s['reused']]),'reused':sum(s['reused'] for s in samples),'serverCPUSeconds':after['cpuSeconds']-before['cpuSeconds'],'clientCPUSeconds':raw.get('resources',{}).get('cpuSeconds',clientCPU),'clientSelfResources':raw.get('resources',{}),'clientFDExternalAccessDenied':inaccessible_fds,'resourcePeaks':peaks,'samples':samples})
                Path(a.output).write_text(json.dumps({'platform':platform.platform(),'python':sys.version,'uvicorn':__import__('uvicorn').__version__,'transport':a.transport,'sourceSHA256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'backend/internal/runtime/client.go',ROOT/'backend/internal/runtime/local_transport.go',ROOT/'backend/internal/runtime/local_transport_unix.go',ROOT/'backend/internal/config/local_transport.go',ROOT/'backend/internal/userconfig/login.go',ROOT/'backend/cmd/local-ipc-bench/main.go',ROOT/'runtime/app/main.py',ROOT/'runtime/app/local_listener.py',ROOT/'runtime/tests/local_ipc/benchmark.py',ROOT/'runtime/tests/local_ipc/benchmark_app.py']},'flags':{'ASTRALIVE_LOCAL_TRANSPORT':env['ASTRALIVE_LOCAL_TRANSPORT'],'ASTRALIVE_LOCAL_FALLBACK':'disabled','factory':a.transport},'pool':'protected baseline http.Transport{Proxy:nil}; default per-host idle limit2; no tuning','logging':'client transport diagnostics suppressed equally; server access logs disabled','psutil':psutil.__version__,'scope':'actual Runtime missing-binding rejected Utterance; authenticated; no LLM/TTS/GPU','results':results},indent=2)+'\n')
            finally:
                server.terminate()
                try:server.wait(timeout=10)
                except subprocess.TimeoutExpired:server.kill();server.wait()
if __name__=='__main__':main()
