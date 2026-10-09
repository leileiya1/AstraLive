import pathlib,json,requests,hashlib
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');r=next(x for x in json.loads((L/'reports/soulx-weight-manifest.json').read_text()) if x['file']=='pytorch_model.bin');p=L/'models/soulx/wav2vec2-base-960h/pytorch_model.bin';tmp=p.with_suffix('.bin.partial')
if not p.exists():
 n=tmp.stat().st_size if tmp.exists() else 0
 if n<r['bytes']:
  u=f"https://hf-mirror.com/{r['repo']}/resolve/{r['revision']}/{r['file']}"
  with requests.get(u,headers={'Range':f"bytes={n}-{r['bytes']-1}"},stream=True,timeout=(30,120)) as response:
   response.raise_for_status();assert response.status_code==206 and response.headers.get('Content-Range','').startswith(f'bytes {n}-')
   with tmp.open('ab') as f:
    for block in response.iter_content(8388608):f.write(block)
 assert tmp.stat().st_size==r['bytes'];tmp.replace(p)
assert p.stat().st_size==r['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'];print('EXACT_WAV2VEC_VERIFIED',flush=True)
