"""Owns disposable PostgreSQL/Redis; never reads business .env or kills shared PIDs.

Requires initdb/pg_ctl/createdb/redis-server/redis-cli/go and a supplied Python
venv containing tests/requirements.txt + runtime requirements + pytest plugins.
Fixed loopback ports are checked free before any process starts.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('--python',required=True)
parser.add_argument('--evidence-dir',required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
evidence=Path(args.evidence_dir).resolve();evidence.mkdir(parents=True,exist_ok=True)
for port in (55462,56382):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:s.bind(('127.0.0.1',port))
        except OSError:raise SystemExit(f'refuse to touch occupied isolated port {port}')
subprocess.run([args.python,'-c','import httpx,jsonschema,pytest,fastapi'],check=True)
owned=Path(tempfile.mkdtemp(prefix='astralive-agent2-',dir='/tmp'))
pg=owned/'pg';rd=owned/'redis';rd.mkdir();(rd/'AGENT2_OWNED').touch()
env={k:v for k,v in os.environ.items() if 'DATABASE' not in k and 'REDIS' not in k and not k.startswith(('DURABLE_LIVE_','RUN_','GPU_','CONFIG_','LLM_','TTS_'))}
env.update(DURABLE_LIVE_TEST_DATABASE_URL='postgres://127.0.0.1:55462/agent2_acceptance?sslmode=disable',
           DURABLE_LIVE_TEST_REDIS_URL='redis://127.0.0.1:56382/0',DURABLE_LIVE_TEST_PYTHON=str(Path(args.python).absolute()),
           DURABLE_LIVE_ISOLATED_PGDATA=str(pg),DURABLE_LIVE_ISOLATED_REDISDIR=str(rd),PYTHONPATH=str(root/'runtime'))
commands=[]
def run(cmd,name,cwd=root):
    with (evidence/name).open('w') as f:
        result=subprocess.run(cmd,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
    commands.append(dict(command=cmd,cwd=str(cwd.relative_to(root)) if cwd!=root else '.',exitCode=result.returncode,log=name))
    if result.returncode:raise RuntimeError(f'{name} failed; inspect evidence')
    print('PASS',name,flush=True)
pg_started=redis_started=False
try:
    run(['initdb','-D',str(pg),'--auth=trust','--no-locale','-E','UTF8'],'initdb.txt')
    (pg/'AGENT2_OWNED').touch()
    run(['pg_ctl','-D',str(pg),'-l',str(owned/'postgres.log'),'-o','-h 127.0.0.1 -p 55462 -k /tmp','-w','start'],'postgres-start.txt');pg_started=True
    run(['createdb','-h','127.0.0.1','-p','55462','agent2_acceptance'],'createdb.txt')
    run(['redis-server','--bind','127.0.0.1','--port','56382','--dir',str(rd),'--save','','--appendonly','no','--daemonize','yes','--pidfile',str(rd/'redis.pid'),'--logfile',str(rd/'redis.log')],'redis-start.txt');redis_started=True
    run(['go','test','-race','./internal/durablelive','-count=1','-v','-timeout','120s'],'durable-race.txt',root/'backend')
    run(['go','test','./...','-count=1'],'go-regression.txt',root/'backend')
    run([args.python,'-m','pytest','runtime/tests/test_durable_live_journal.py','-q'],'python-journal.txt')
    run([args.python,'-m','unittest','discover','-s','runtime/tests','-p','test_*.py','-v'],'runtime-regression.txt')
    run([args.python,'scripts/validate-durable-live-contracts.py'],'frozen-contracts.txt')
    run([args.python,'-m','unittest','tests.test_contracts','tests.test_durable_live_contracts','-v'],'contract-tests.txt')
    run([args.python,'scripts/durable-live/check_integration_patch.py'],'integration-patch.txt')
finally:
    if redis_started:
        subprocess.run(['redis-cli','-h','127.0.0.1','-p','56382','shutdown','nosave'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if pg_started:
        subprocess.run(['pg_ctl','-D',str(pg),'-m','fast','-w','stop'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    report=dict(contractRevision='durable-live-1',baseMain='7fe5d24810e2df348c58dd7748e97ffbe5cff384',
                contractCommit='ae28144d15afcf0e5f5ea8fa425fc42d27fc047b',ownedCluster=str(owned),
                commands=commands,realGPU='NOT TESTED',rtmpAudience='NOT TESTED',productionGuardian='NOT TESTED')
    (evidence/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Owned services stopped. Disposable data retained at',owned)
