"""Preserve cloud prefix bytes and relay only missing VAE range tails."""
import concurrent.futures,json,pathlib,subprocess,urllib.request
L=pathlib.Path(__file__).resolve().parents[1];ssh=['bash',str(L/'scripts/gpu-ssh.sh')]
remote='/root/autodl-tmp/astralive-avatar-lab/models/soulx/SoulX-FlashHead-1_3B/VAE_LTX'
command="/root/miniconda3/bin/python -c 'import pathlib,json; root=pathlib.Path(\""+remote+"\"); out=[];\nfor p in root.glob(\"*.range-*\"):\n a,b=map(int,p.name.split(\"range-\")[1].split(\"-\")); n=p.stat().st_size;\n if n<b-a+1:out.append(dict(name=p.name,start=a+n,end=b,prefix_bytes=n))\nprint(json.dumps(out))'"
spec=json.loads(subprocess.check_output(ssh+[command],text=True));root=L/'artifacts/soulx-tails';root.mkdir(parents=True,exist_ok=True)
url='https://huggingface.co/Soul-AILab/SoulX-FlashHead-1_3B/resolve/59119b6c681230c3eeee157e224ae1941746711e/VAE_LTX/diffusion_pytorch_model.safetensors'
def fetch(s):
    req=urllib.request.Request(url,headers={'Range':f'bytes={s["start"]}-{s["end"]}'})
    out=root/(s['name']+'.tail')
    with urllib.request.urlopen(req,timeout=120) as r,out.open('wb') as f:
        if r.status!=206 or not r.headers.get('Content-Range','').startswith(f'bytes {s["start"]}-{s["end"]}/'):raise RuntimeError('Range not respected')
        while block:=r.read(4*1024*1024):f.write(block)
    if out.stat().st_size!=s['end']-s['start']+1:raise RuntimeError('tail size mismatch')
    print('TAIL DOWNLOADED',out.name,out.stat().st_size,flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(fetch,spec))
(root/'tail-manifest.json').write_text(json.dumps(spec,indent=2))
