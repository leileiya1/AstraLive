"""Hash only deliverables, excluding keys, model caches and wheel downloads."""
import argparse,hashlib,json,pathlib
ap=argparse.ArgumentParser();ap.add_argument('root');ap.add_argument('--verify',action='store_true');ap.add_argument('--site',default='local');a=ap.parse_args();root=pathlib.Path(a.root).resolve();manifest=root/'reports/RESULT-SHA256SUMS.txt'
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        while chunk:=f.read(4*1024*1024):h.update(chunk)
    return h.hexdigest()
if a.verify:
    failures=[];n=0;videos=0
    for line in manifest.read_text().splitlines():
        sha,name=line.split('  ',1);p=root/name;n+=1;videos+=int(p.suffix=='.mp4')
        if not p.is_file() or digest(p)!=sha:failures.append(name)
    result=dict(site=a.site,files_checked=n,mp4_checked=videos,failures=failures,status='PASS' if not failures else 'FAIL')
    (root/'reports'/f'backup-verification-{a.site}.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));raise SystemExit(bool(failures))
files=[]
for folder in ['outputs','benchmarks','reports','scripts','inputs','logs']:
    for p in (root/folder).rglob('*'):
        if not p.is_file() or p.is_symlink():continue
        if any(x in p.parts for x in ['__pycache__','official-normal','same-source-normal']):continue
        if p.name in ['gpu-ssh.sh','RESULT-SHA256SUMS.txt','BACKUP-VALIDATION.md'] or p.name.startswith('backup-verification-'):continue
        files.append(p)
manifest.write_text(''.join(f'{digest(p)}  {p.relative_to(root)}\n' for p in sorted(files)))
print(json.dumps(dict(files=len(files),mp4=sum(p.suffix=='.mp4' for p in files),manifest=str(manifest))))
