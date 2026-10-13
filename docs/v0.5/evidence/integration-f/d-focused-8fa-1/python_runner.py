from pathlib import Path
import hashlib,json,os,subprocess,tarfile,tempfile,time
source='8fa0eb27b132234be9bd2afcccfeb8980ad4ca7a'
repo='/Users/sapiece/innovationProject/AstraLive-agent-d'
python='/private/tmp/astralive-f-media-venv-1/bin/python'
out=Path('/private/tmp/astralive-d-focused-8fa0eb2-3');out.mkdir(mode=0o700,exist_ok=False)
env={k:os.environ[k] for k in ('PATH','HOME','TMPDIR','LANG') if k in os.environ}
report={'source':source,'scope':'corrected Python focused auth/local/lifecycle fixture import; exact source unchanged; no PostgreSQL/GPU/cloud required','checks':[],'relatedGoResult':'/private/tmp/astralive-d-focused-8fa0eb2-2/result.json','priorPythonError':'qualified unittest names excluded runtime/tests standalone fixture imports; execution error retained, no test deleted'}
with tempfile.TemporaryDirectory(prefix='al-d-py-source-') as tmp:
 root=Path(tmp)
 p=subprocess.Popen(['git','-C',repo,'archive',source],stdout=subprocess.PIPE)
 with tarfile.open(fileobj=p.stdout,mode='r|*') as tar:tar.extractall(root,filter='data')
 if p.wait():raise RuntimeError('archive failed')
 env['PYTHONPATH']=os.pathsep.join(map(str,(root/'runtime',root/'runtime/tests',root)))
 argv=[python,'-m','unittest','-v','test_local_listener','test_production_launcher_transport','test_session_binding','test_durability','test_narration_lifecycle','test_staging_runtime.CaptureTests']
 began=time.monotonic()
 with (out/'python-corrected.log').open('wb') as f:p=subprocess.run(argv,env=env,cwd=root,stdout=f,stderr=subprocess.STDOUT)
 raw=(out/'python-corrected.log').read_bytes();report['checks'].append({'name':'python-auth-local-lifecycle-corrected','command':argv,'exitCode':p.returncode,'seconds':round(time.monotonic()-began,3),'log':'python-corrected.log','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
 report['status']='PASS' if p.returncode==0 else 'FAIL'
 (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report),flush=True)
raise SystemExit(p.returncode)
