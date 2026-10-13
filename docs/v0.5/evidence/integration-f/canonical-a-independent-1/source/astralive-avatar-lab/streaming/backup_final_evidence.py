"""Create an explicit credential-free result bundle and verify every cloud copy."""
import pathlib,json,os,hashlib,shutil,subprocess,time
ROOT=pathlib.Path(__file__).parent;OUT=ROOT/'integration/soulx-final-one-hour-paired-20261009';BUNDLE=ROOT.parent/'backups/soulx-final-one-hour-paired-20261009';BUNDLE.mkdir(parents=True,exist_ok=True)
secret_values=[os.environ.get('DEEPSEEK_API_KEY',''),(ROOT/'.private/token').read_text().strip()];allowed={'.json','.jsonl','.csv','.txt','.log','.md','.py','.js','.html','.yml','.diff','.wav','.webm','.mkv','.mp4','.png','.sse'};files=[]
for p in OUT.rglob('*'):
 if not p.is_file() or p.is_symlink() or p.suffix not in allowed or p.name=='backup.log':continue
 if any(x in p.relative_to(OUT).parts for x in ['profile','chrome-profile','.private','__pycache__']):continue
 files.append((p,pathlib.Path('evidence')/p.relative_to(OUT)))
for name in ['SOULX-AV-SYNC-ROOT-CAUSE.md','SOULX-FINAL-ONE-HOUR-ACCEPTANCE.md','SOULX-DEGRADATION-ROOT-CAUSE.md']:files.append((ROOT.parent/'reports'/name,pathlib.Path('reports')/name))
for p in (ROOT/'integration/latency-gate-evidence-20261009').iterdir():
 if p.is_file():files.append((p,pathlib.Path('original-failure-excerpts')/p.name))
for name in ['summary.json','manual-gate-stop.json','public-session-final.json','sync-analysis.json','browser-events.jsonl']:files.append((ROOT/'integration/public-dual-one-hour-20261009'/name,pathlib.Path('original-failure-records')/name))
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
for p,relative in files:
 target=BUNDLE/relative;target.parent.mkdir(parents=True,exist_ok=True)
 if p.suffix in {'.wav','.webm','.mkv','.mp4','.png'}:
  if not target.exists() or target.stat().st_size!=p.stat().st_size or digest(target)!=digest(p):shutil.copyfile(p,target)
  continue
 data=p.read_bytes()
 if p.suffix not in {'.wav','.webm','.mkv','.mp4','.png'}:
  for value in secret_values:
   if value and value.encode() in data:raise RuntimeError('Credential present in selected artifact: '+str(relative))
  data=data.replace(b'soulx-isolated-lab',b'REDACTED_EXPERIMENT_STREAM')
 if not target.exists() or target.read_bytes()!=data:target.write_bytes(data)
manifest={str(p.relative_to(BUNDLE)):digest(p) for p in BUNDLE.rglob('*') if p.is_file() and p.name not in ['sha256-manifest.json','backup-verification.json']};(BUNDLE/'sha256-manifest.json').write_text(json.dumps(manifest,indent=2))
remote='AstraLive/experiments/real-avatar/results/soulx-final-one-hour-paired-20261009';subprocess.run(['ssh','-o','ControlPath=/tmp/astralive-soulx-repair-school.sock','school-linux','mkdir','-p',remote],check=True);subprocess.run(['rsync','-a','-e','ssh -o ControlPath=/tmp/astralive-soulx-repair-school.sock',str(BUNDLE)+'/',f'school-linux:{remote}/'],check=True)
code='''import json,pathlib,hashlib
p=pathlib.Path.home()/"AstraLive/experiments/real-avatar/results/soulx-final-one-hour-paired-20261009";m=json.loads((p/"sha256-manifest.json").read_text());fail=[]
for f,h in m.items():
 q=p/f
 if not q.exists():fail.append(f);continue
 digest=hashlib.sha256()
 with q.open('rb') as stream:
  for block in iter(lambda:stream.read(1048576),b''):digest.update(block)
 if digest.hexdigest()!=h:fail.append(f)
print(json.dumps({"verifiedFiles":len(m),"mismatches":fail,"status":"VERIFIED" if not fail else "FAILED"}))
'''
r=subprocess.run(['ssh','-o','ControlPath=/tmp/astralive-soulx-repair-school.sock','school-linux','python3','-'],input=code,capture_output=True,text=True,check=True);check=json.loads(r.stdout);assert check['status']=='VERIFIED';check.update(localBundle=str(BUNDLE.resolve()),schoolDirectory='~/'+remote,manifestSHA256=hashlib.sha256((BUNDLE/'sha256-manifest.json').read_bytes()).hexdigest(),verifiedUtc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),redaction='credentials excluded; test RTMP stream identifier redacted in textual backup copies; raw local evidence retained unchanged')
for p in [OUT/'backup-verification.json',BUNDLE/'backup-verification.json']:p.write_text(json.dumps(check,indent=2))
subprocess.run(['scp','-o','ControlPath=/tmp/astralive-soulx-repair-school.sock','-q',str(BUNDLE/'backup-verification.json'),f'school-linux:{remote}/backup-verification.json'],check=True);print(json.dumps(check,indent=2))
