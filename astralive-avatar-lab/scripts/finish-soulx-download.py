"""Resume verified byte ranges of official Lite weights, retaining prior bytes."""
import concurrent.futures,hashlib,pathlib,requests
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab'); E='https://hf-mirror.com'
repo='Soul-AILab/SoulX-FlashHead-1_3B';rev='59119b6c681230c3eeee157e224ae1941746711e'
for name,size,sha in [('Model_Lite/diffusion_pytorch_model.safetensors',6107542048,'aaf1cde6e80ca23f740aae236c47954249f65b151db133cc0f77d3a138ccdf6e'),('VAE_LTX/diffusion_pytorch_model.safetensors',1676798532,'265ca87cb5dff5e37f924286e957324e282fe7710a952a7dafc0df43883e2010')]:
    out=L/'models/soulx'/repo.split('/')[-1]/name;out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists() and out.stat().st_size==size:continue
    partial=out.with_suffix(out.suffix+'.partial');prefix=partial.with_suffix('.prefix')
    if partial.exists() and not prefix.exists():partial.replace(prefix)
    offset=prefix.stat().st_size if prefix.exists() else 0
    parts=[]
    for a in range(offset,size,256*1024*1024):
        b=min(a+256*1024*1024,size)-1;parts.append((a,b,out.with_name(f'{out.name}.range-{a}-{b}')))
    def fetch(spec):
        a,b,p=spec
        if p.exists() and p.stat().st_size==b-a+1:return p
        with requests.get(f'{E}/{repo}/resolve/{rev}/{name}',headers={'Range':f'bytes={a}-{b}'},stream=True,timeout=(40,120)) as r:
            r.raise_for_status()
            if r.status_code!=206 or not r.headers.get('Content-Range','').startswith(f'bytes {a}-{b}/'):raise RuntimeError('range not respected')
            with p.open('wb') as f:
                for chunk in r.iter_content(8*1024*1024):f.write(chunk)
        if p.stat().st_size!=b-a+1:raise RuntimeError('range size mismatch')
        print('RANGE COMPLETE',name,a,b,flush=True);return p
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(fetch,parts))
    h=hashlib.sha256()
    with partial.open('wb') as dst:
        for p in ([prefix] if prefix.exists() else [])+[p for _,_,p in parts]:
            with p.open('rb') as src:
                for chunk in iter(lambda:src.read(8*1024*1024),b''):dst.write(chunk);h.update(chunk)
    if partial.stat().st_size!=size or h.hexdigest()!=sha:raise RuntimeError('final SHA/size mismatch')
    partial.replace(out);print('VERIFIED',name,sha,flush=True)
