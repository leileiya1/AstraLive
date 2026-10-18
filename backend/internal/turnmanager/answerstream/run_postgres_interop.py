#!/usr/bin/env python3
"""Owned PostgreSQL interop runner. No existing DSNs, shared service or GPU.
Default: focused real streaming tests. --full adds unmodified whole-Go test/race,
Authority, contract, Journal and official wire regressions on seven migrations.
"""
import argparse,json,os,pathlib,resource,socket,subprocess,tempfile,time

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--full',action='store_true');ap.add_argument('--output');args=ap.parse_args()
    repo=pathlib.Path(__file__).resolve().parents[4]
    out=pathlib.Path(args.output).resolve() if args.output else pathlib.Path(tempfile.mkdtemp(prefix='agent3-pg-evidence-'))
    out.mkdir(parents=True,exist_ok=True)
    root=pathlib.Path(tempfile.mkdtemp(prefix='astralive-agent3-stream-pg-',dir='/tmp'));(root/'AGENT3_OWNED').write_text('agent3 isolated streaming acceptance\n')
    data=root/'data';sock=root/'sockets';sock.mkdir()
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    env={k:os.environ[k]for k in ('PATH','HOME','TMPDIR','GOCACHE','GOPATH')if k in os.environ};env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(repo),GOMAXPROCS='4',LC_ALL='C')
    started=False;records=[];databases=['agent3_streaming_owned','agent2_v2_agent3_owned','agent2_v1_agent3_owned'];created=[]
    def run(label,cmd,cwd=repo):
        start=time.monotonic();before=resource.getrusage(resource.RUSAGE_CHILDREN)
        with (out/(label+'.txt')).open('w') as log:r=subprocess.run(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT)
        after=resource.getrusage(resource.RUSAGE_CHILDREN);record=dict(label=label,command=cmd,cwd=str(cwd),exitCode=r.returncode,elapsedSeconds=round(time.monotonic()-start,3),childUserSeconds=after.ru_utime-before.ru_utime,childSystemSeconds=after.ru_stime-before.ru_stime,childPeakRSSBytes=after.ru_maxrss);records.append(record);(out/'commands.json').write_text(json.dumps(records,indent=2)+'\n');print(label,r.returncode,flush=True);return r.returncode
    try:
        with (out/'initdb.txt').open('w') as log:subprocess.run(['initdb','-D',str(data),'-A','trust','-U','agent3_owner','--no-locale','-E','UTF8'],env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        with (out/'start.txt').open('w') as log:subprocess.run(['pg_ctl','-D',str(data),'-l',str(root/'postgres.log'),'-o',f'-h 127.0.0.1 -p {port} -k {sock}','-w','start'],env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        started=True
        for name in databases:subprocess.run(['createdb','-h','127.0.0.1','-p',str(port),'-U','agent3_owner',name],env=env,check=True);created.append(name)
        dsn=lambda name:f'postgres://agent3_owner@127.0.0.1:{port}/{name}?sslmode=disable'
        env.update(AGENT3_PG_OWNED_ROOT=str(root),AGENT3_STREAM_DATABASE_URL=dsn(databases[0]),DURABLE_V2_TEST_DATABASE_URL=dsn(databases[1]),DURABLE_LIVE_TEST_DATABASE_URL=dsn(databases[2]),DURABLE_LIVE_TEST_PYTHON='/tmp/astralive-agent2-python/bin/python')
        run('postgres-inventory',['psql',dsn(databases[0]),'-c',"SELECT version(),current_database(),inet_server_addr(),inet_server_port(); SHOW fsync; SHOW synchronous_commit; SHOW full_page_writes;"])
        result=run('streaming-pg-race',['go','test','-race','-json','-count=1','./internal/turnmanager/answerstream','-run','^TestPostgres'],repo/'backend')
        if args.full:
            run('go-test',['go','test','-p','2','-json','-count=1','./...'],repo/'backend')
            run('go-race',['go','test','-p','2','-race','-json','-count=1','./...'],repo/'backend')
            run('go-vet',['go','vet','./...'],repo/'backend')
            py='/tmp/astralive-agent2-python/bin/python'
            run('contracts137',[py,'-m','unittest','tests.test_contracts','tests.test_durable_live_contracts','tests.test_durable_answer_contracts','tests.test_answer_contract_repairs','tests.test_receiver_contracts','tests.test_receiver_stop_races','-v'])
            env['PYTHONPATH']=str(repo/'runtime')+os.pathsep+str(repo)
            run('journal11',[py,'-m','pytest','-p','no:cacheprovider','runtime/tests/test_durable_live_journal.py','-q'])
            env['PYTHONPATH']=str(repo)
            run('wire13',[py,'-m','unittest','tests.test_durable_live_v2_wire','-v'])
            for label,path in [('validator-v1','scripts/validate-durable-live-contracts.py'),('validator-v2','scripts/validate-answer-contract.py')]:run(label,[py,path])
            run('generated-check',[py,'scripts/durable-live/generate_v2_wire.py','--check'])
        run('migration-count',['psql',dsn(databases[0]),'-c','SELECT * FROM schema_migrations ORDER BY 1'])
    finally:
        removed=[]
        if started:
            for name in created:
                r=subprocess.run(['dropdb','-h','127.0.0.1','-p',str(port),'-U','agent3_owner',name],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                if r.returncode==0:removed.append(name)
            with (out/'stop.txt').open('w') as log:subprocess.run(['pg_ctl','-D',str(data),'-m','fast','-w','stop'],env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        (out/'cleanup.json').write_text(json.dumps(dict(ownedRoot=str(root),port=port,createdDatabases=created,droppedDatabases=removed,postgresStopped=not(data/'postmaster.pid').exists(),sharedServicesTouched=False,physicalAdapters='SYNTHETIC_FIXTURES',ipcTtsMediaGpu='NOT_TESTED'),indent=2)+'\n')
        (out/'postgres.log.txt').write_text((root/'postgres.log').read_text() if (root/'postgres.log').exists() else '')
        print('Evidence:',out,flush=True)
    return int(any(r['exitCode'] for r in records) or len(removed) != len(created) or (data/'postmaster.pid').exists())
if __name__=='__main__':raise SystemExit(main())
