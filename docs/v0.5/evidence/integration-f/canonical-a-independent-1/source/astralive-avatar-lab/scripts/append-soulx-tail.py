import json,pathlib
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');root=L/'models/soulx/SoulX-FlashHead-1_3B/VAE_LTX';tails=L/'artifacts/soulx-tails'
for s in json.loads((tails/'tail-manifest.json').read_text()):
    p=root/s['name'];tail=tails/(s['name']+'.tail')
    if p.stat().st_size!=s['prefix_bytes']:raise RuntimeError('prefix changed; do not append')
    with p.open('ab') as f,tail.open('rb') as src:
        while chunk:=src.read(8*1024*1024):f.write(chunk)
    print('APPENDED',p.name,p.stat().st_size)
