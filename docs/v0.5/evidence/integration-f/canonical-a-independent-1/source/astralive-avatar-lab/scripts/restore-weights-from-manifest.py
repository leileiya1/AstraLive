"""Restore the already-validated exact revisions, never discover latest weights."""
import concurrent.futures,hashlib,json,pathlib,requests,time
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');records=json.loads((L/'reports/soulx-weight-manifest.json').read_text())
def restore(r):
 folder='wav2vec2-base-960h' if r['repo'].startswith('facebook/') else 'SoulX-FlashHead-1_3B'
 out=L/'models/soulx'/folder/r['file'];out.parent.mkdir(parents=True,exist_ok=True)
 if not out.exists() or out.stat().st_size!=r['bytes']:
  tmp=out.with_suffix(out.suffix+'.partial');url=f"https://hf-mirror.com/{r['repo']}/resolve/{r['revision']}/{r['file']}"
  for attempt in range(3):
   try:
    with requests.get(url,stream=True,timeout=(30,180)) as resp:
     resp.raise_for_status()
     with tmp.open('wb') as f:
      for chunk in resp.iter_content(8388608):f.write(chunk)
    if tmp.stat().st_size!=r['bytes']:raise RuntimeError('size mismatch')
    tmp.replace(out);break
   except Exception:
    if attempt==2:raise
    time.sleep(2)
 h=hashlib.sha256()
 with out.open('rb') as f:
  for b in iter(lambda:f.read(8388608),b''):h.update(b)
 if h.hexdigest()!=r['sha256']:raise RuntimeError('SHA mismatch '+r['file'])
 print('VERIFIED',r['file'],out.stat().st_size,flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(restore,records))
print('ALL_EXACT_WEIGHTS_VERIFIED',flush=True)
