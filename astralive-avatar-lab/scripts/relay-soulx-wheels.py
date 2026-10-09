"""Relay exactly the wheels resolved by cloud pip, with official PyPI hashes."""
import concurrent.futures,hashlib,json,pathlib,re,urllib.request
L=pathlib.Path(__file__).resolve().parents[1]; log=(L/'artifacts/setup-soulx-resolver.log').read_text()
names=sorted(set(re.findall(r'([A-Za-z0-9_.+]+-[A-Za-z0-9_.+]+(?:-[A-Za-z0-9_.]+)?-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+\.whl)(?:\.metadata)?',log)))
names+=['yunchang-0.6.2-py3-none-any.whl','xfuser-0.4.3-py3-none-any.whl','distvae-0.1.0-py3-none-any.whl','pytest-9.1.1-py3-none-any.whl','pluggy-1.6.0-py3-none-any.whl','iniconfig-2.3.0-py3-none-any.whl','opencv_python-4.11.0.86-cp37-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl']
root=L/'artifacts/soulx-wheelhouse';root.mkdir(parents=True,exist_ok=True)
def fetch(name):
    dist,version=name.split('-')[:2]
    with urllib.request.urlopen(f'https://pypi.org/pypi/{dist}/{version}/json',timeout=30) as r:meta=json.load(r)
    info=next(x for x in meta['urls'] if x['filename']==name);out=root/name
    if not out.exists():
        with urllib.request.urlopen(info['url'],timeout=90) as r,out.open('wb') as f:
            while block:=r.read(4*1024*1024):f.write(block)
    digest=hashlib.sha256(out.read_bytes()).hexdigest()
    if digest!=info['digests']['sha256']:raise RuntimeError('Official wheel hash mismatch '+name)
    print('VERIFIED',name,flush=True);return dict(filename=name,sha256=digest,source=info['url'])
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:records=list(pool.map(fetch,names))
(root/'official-wheel-hashes.json').write_text(json.dumps(records,indent=2))
