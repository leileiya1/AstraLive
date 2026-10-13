"""Restore missing exact manifest objects; resume ranges and verify SHA256.
No revision discovery. Never download an already verified weight again.
"""
import concurrent.futures,hashlib,json,pathlib,requests,time
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');records=json.loads((L/'reports/soulx-weight-manifest.json').read_text())
def digest(p):
 h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(8388608),b''):h.update(b)
 return h.hexdigest()
def restore(r):
 folder='wav2vec2-base-960h'if r['repo'].startswith('facebook/')else'SoulX-FlashHead-1_3B';p=L/'models/soulx'/folder/r['file'];p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists()and p.stat().st_size==r['bytes']and digest(p)==r['sha256']:print('REUSED_VERIFIED',r['file'],flush=True);return
 u=f"https://hf-mirror.com/{r['repo']}/resolve/{r['revision']}/{r['file']}";size=r['bytes'];block=128*1024*1024
 specs=[(a,min(a+block,size)-1,p.with_name(p.name+f'.range-{a}'))for a in range(0,size,block)]
 def fetch(spec):
  a,b,part=spec
  if part.exists()and part.stat().st_size==b-a+1:return
  for attempt in range(3):
   try:
    with requests.get(u+f'?download=true&range_start={a}',headers={'Range':f'bytes={a}-{b}'},stream=True,timeout=(30,120))as response:
     response.raise_for_status()
     if response.status_code!=206 and not(a==0 and b==size-1 and response.status_code==200):raise RuntimeError('range not respected')
     if response.status_code==206 and not response.headers.get('Content-Range','').startswith(f'bytes {a}-{b}/'):raise RuntimeError('incorrect range')
     tmp=part.with_suffix(part.suffix+'.partial')
     with tmp.open('wb')as f:
      for chunk in response.iter_content(8388608):f.write(chunk)
    if tmp.stat().st_size!=b-a+1:raise RuntimeError('range size mismatch')
    tmp.replace(part);print('RANGE_SAVED',r['file'],a,b,flush=True);return
   except Exception:
    if attempt==2:raise
    time.sleep(2)
 with concurrent.futures.ThreadPoolExecutor(max_workers=3)as pool:list(pool.map(fetch,specs))
 tmp=p.with_suffix(p.suffix+'.partial')
 with tmp.open('wb')as out:
  for a,b,part in specs:
   with part.open('rb')as f:
    for chunk in iter(lambda:f.read(8388608),b''):out.write(chunk)
 if tmp.stat().st_size!=size or digest(tmp)!=r['sha256']:raise RuntimeError('SHA256 mismatch '+r['file'])
 tmp.replace(p)
 for a,b,part in specs:part.unlink()
 print('EXACT_VERIFIED',r['file'],size,r['sha256'],flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3)as pool:list(pool.map(restore,records))
print('ALL_EXACT_WEIGHTS_VERIFIED',flush=True)
