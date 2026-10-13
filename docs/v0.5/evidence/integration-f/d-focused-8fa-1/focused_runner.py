import hashlib,json,os,platform,shutil,socket,subprocess,tarfile,tempfile,time,uuid
from pathlib import Path
source='8fa0eb27b132234be9bd2afcccfeb8980ad4ca7a'
repo=Path('/Users/sapiece/innovationProject/AstraLive-agent-d')
python='/private/tmp/astralive-f-media-venv-1/bin/python'
pgbin=Path('/opt/homebrew/opt/postgresql@17/bin')
out=Path('/private/tmp/astralive-d-focused-8fa0eb2-2');out.mkdir(mode=0o700,exist_ok=False)
env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR','LANG') if k in os.environ}
report={'source':source,'scope':'D actual local Go/Python TCP/UDS and real owned PostgreSQL process/auth/default-off focused regression; CPU fixture providers/sinks only; no GPU/Chrome/live performance acceptance','platform':platform.platform(),'checks':[],'status':'RUNNING','notTested':['Linux actual runtime','Windows actual runtime','real GPU through UDS','Chrome/RTMP through UDS','Speak performance']}
pgdata=Path(tempfile.mkdtemp(prefix='al-d-pg-'));marker=uuid.uuid4().hex;started=False
archive=Path(tempfile.mkdtemp(prefix='al-d-source-'))
def save(): (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
def run(name,argv,cwd=None):
    began=time.monotonic()
    with (out/(name+'.log')).open('wb') as f:
        p=subprocess.run([str(x) for x in argv],env=env,cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
    raw=(out/(name+'.log')).read_bytes()
    report['checks'].append({'name':name,'command':[str(x) for x in argv],'exitCode':p.returncode,'seconds':round(time.monotonic()-began,3),'log':name+'.log','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
    save();print(json.dumps({'check':name,'exitCode':p.returncode}),flush=True)
    if p.returncode: raise RuntimeError(name+' failed')
try:
    report['versions']={tool:subprocess.check_output(argv,env=env,text=True).splitlines()[0] for tool,argv in [('go',['go','version']),('python',[python,'--version']),('postgres',[str(pgbin/'postgres'),'--version'])]}
    p=subprocess.Popen(['git','-C',str(repo),'archive',source],stdout=subprocess.PIPE)
    with tarfile.open(fileobj=p.stdout,mode='r|*') as tar:tar.extractall(archive,filter='data')
    if p.wait():raise RuntimeError('archive failed')
    run('pg-init',[pgbin/'initdb','-D',pgdata,'-A','trust','--no-locale','-E','UTF8'])
    (pgdata/'.al-d-owner').write_text(marker)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    with (pgdata/'postgresql.conf').open('a') as f:f.write(f"\nport={port}\nlisten_addresses='127.0.0.1'\nunix_socket_directories='{pgdata}'\n")
    run('pg-start',[pgbin/'pg_ctl','-D',pgdata,'-l',pgdata/'postgres.log','start']);started=True
    run('pg-database',[pgbin/'createdb','-h','127.0.0.1','-p',port,'astralive_d_review'])
    username=subprocess.check_output(['id','-un'],text=True).strip()
    address=f'postgres://{username}@127.0.0.1:{port}/astralive_d_review?sslmode=disable'
    env.update(DURABILITY_TEST_DATABASE_URL=address,CONFIG_TEST_DATABASE_URL=address,DURABILITY_TEST_PYTHON=python,ASTRALIVE_IPC_TEST_PYTHON=python)
    run('go-auth-local-race',['go','test','-race','-p','1','-count=1','-v','./internal/config','./internal/runtime','./internal/userconfig'],archive/'backend')
    run('go-production-startup-race',['go','test','-race','-p','1','-count=1','-v','./internal/durability','-run','^(TestLocalIPCProductionServerStartup|TestPostgresOnlyServerStartup)$'],archive/'backend')
    run('go-feature-flags-race',['go','test','-race','-count=1','-v','./internal/narration','-run','^(TestFrozenFlag|TestTimelineConfiguration|TestStagingCaptureFrozenProfiles)$'],archive/'backend')
    env['PYTHONPATH']=str(archive/'runtime')+os.pathsep+str(archive)
    run('python-auth-local-lifecycle',[python,'-m','unittest','-v','runtime.tests.test_local_listener','runtime.tests.test_production_launcher_transport','runtime.tests.test_session_binding','runtime.tests.test_durability','runtime.tests.test_narration_lifecycle','runtime.tests.test_staging_runtime.CaptureTests'],archive)
    critical=['backend/cmd/server/main.go','backend/internal/runtime/client.go','backend/internal/runtime/local_transport.go','backend/internal/config/local_transport.go','backend/internal/userconfig/local_transport.go','backend/internal/userconfig/login.go','backend/internal/userconfig/environment.go','backend/internal/userconfig/provider_probe.go','backend/internal/userconfig/session_binding.go','runtime/app/local_listener.py','runtime/app/production_launcher.py','runtime/app/main.py','runtime/app/durability_client.py','runtime/app/session_binding.py','backend/internal/narration/staging_config.go','runtime/app/staging_settings.py']
    report['sourceHashes']={name:hashlib.sha256((archive/name).read_bytes()).hexdigest() for name in critical}
    report['status']='PASS'
except Exception as e:
    report.update(status='FAIL',error=str(e))
finally:
    clean=not started
    if started and (pgdata/'.al-d-owner').read_text()==marker:
        with (out/'pg-stop.log').open('wb') as f:p=subprocess.run([str(pgbin/'pg_ctl'),'-D',str(pgdata),'-m','fast','stop'],env=env,stdout=f,stderr=subprocess.STDOUT)
        clean=p.returncode==0
    report['ownedPGCleanup']='PASS' if clean else 'FAIL'
    if not clean:report['status']='FAIL'
    if clean:shutil.rmtree(pgdata)
    shutil.rmtree(archive)
    report['artifacts']={p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in sorted(out.glob('*.log'))}
    save();print(json.dumps({'source':source,'status':report['status'],'output':str(out)}),flush=True)
raise SystemExit(report['status']!='PASS')
