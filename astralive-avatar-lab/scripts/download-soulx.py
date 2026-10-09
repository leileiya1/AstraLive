"""Selective official Lite download; no Pro or training data."""
import argparse,hashlib,json,pathlib,requests
ap=argparse.ArgumentParser();ap.add_argument('--aux-only',action='store_true');args=ap.parse_args()
LAB=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab'); E='https://hf-mirror.com'
records=[]
for repo,sub,prefixes in [('Soul-AILab/SoulX-FlashHead-1_3B','SoulX-FlashHead-1_3B',('Model_Lite/','VAE_LTX/')),('facebook/wav2vec2-base-960h','wav2vec2-base-960h',('config.json','preprocessor_config.json','pytorch_model.bin'))]:
    r=requests.get(f'{E}/api/models/{repo}?blobs=true',timeout=40);r.raise_for_status();meta=r.json();rev=meta['sha']
    for info in meta['siblings']:
        name=info['rfilename']
        if not any(name.startswith(p) for p in prefixes):continue
        if args.aux_only and repo.startswith('Soul-AILab/') and name.endswith('.safetensors'):continue
        out=LAB/'models/soulx'/sub/name;out.parent.mkdir(parents=True,exist_ok=True)
        size=info.get('size') or info.get('lfs',{}).get('size'); sha=info.get('lfs',{}).get('sha256')
        print('DOWNLOAD',repo,rev,name,size,flush=True)
        if not out.exists() or out.stat().st_size!=size:
            tmp=out.with_suffix(out.suffix+'.partial')
            with requests.get(f'{E}/{repo}/resolve/{rev}/{name}',stream=True,timeout=(40,120)) as resp:
                resp.raise_for_status()
                with tmp.open('wb') as f:
                    for block in resp.iter_content(8*1024*1024):f.write(block)
            if size and tmp.stat().st_size!=size:raise RuntimeError('size mismatch')
            tmp.replace(out)
        h=hashlib.sha256()
        with out.open('rb') as f:
            for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
        digest=h.hexdigest()
        if sha and digest!=sha:raise RuntimeError('hash mismatch')
        records.append(dict(repo=repo,revision=rev,file=name,bytes=out.stat().st_size,sha256=digest,upstream_sha_match=digest==sha if sha else None,source=f'https://huggingface.co/{repo}/resolve/{rev}/{name}',transport=E))
        (LAB/'reports'/('soulx-aux-weight-manifest.json' if args.aux_only else 'soulx-weight-manifest.json')).write_text(json.dumps(records,indent=2))
        print('VERIFIED',name,digest,flush=True)
