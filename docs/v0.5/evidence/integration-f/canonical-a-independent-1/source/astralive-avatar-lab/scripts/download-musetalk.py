"""Download only inference weights from official repositories via official-script mirror."""
import hashlib,json,pathlib,time,requests
LAB=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab')
ROOT=LAB/'models/musetalk'
ENDPOINT='https://hf-mirror.com'
SPEC=[('TMElyralab/MuseTalk','',['musetalkV15/musetalk.json','musetalkV15/unet.pth']),
      ('stabilityai/sd-vae-ft-mse','sd-vae',['config.json','diffusion_pytorch_model.bin']),
      ('openai/whisper-tiny','whisper',['config.json','pytorch_model.bin','preprocessor_config.json']),
      ('yzd-v/DWPose','dwpose',['dw-ll_ucoco_384.pth'])]
records=[]
for repo,sub,files in SPEC:
    meta=requests.get(f'{ENDPOINT}/api/models/{repo}',params={'blobs':'true'},timeout=30)
    meta.raise_for_status();meta=meta.json();revision=meta['sha']
    siblings={x['rfilename']:x for x in meta['siblings']}
    for name in files:
        out=ROOT/sub/name;out.parent.mkdir(parents=True,exist_ok=True)
        info=siblings[name];expected=info.get('size') or info.get('lfs',{}).get('size')
        expected_sha=info.get('lfs',{}).get('sha256')
        url=f'{ENDPOINT}/{repo}/resolve/{revision}/{name}'
        print('DOWNLOAD',repo,revision,name,'expected',expected,flush=True)
        if not out.exists() or (expected and out.stat().st_size!=expected):
            temp=out.with_name(out.name+'.partial')
            for attempt in range(2):
                try:
                    with requests.get(url,stream=True,timeout=(30,90)) as resp:
                        resp.raise_for_status()
                        with temp.open('wb') as f:
                            for chunk in resp.iter_content(4*1024*1024):f.write(chunk)
                    if expected and temp.stat().st_size!=expected:raise RuntimeError('size mismatch')
                    temp.replace(out);break
                except Exception as exc:
                    print('download failure',type(exc).__name__,'attempt',attempt+1,flush=True)
                    if attempt==1:raise RuntimeError(f'Download failed: {repo}/{name}') from None
                    time.sleep(2)
        h=hashlib.sha256()
        with out.open('rb') as f:
            first=f.read(256)
            if first.startswith(b'version https://git-lfs'):raise RuntimeError('LFS pointer')
            h.update(first)
            for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
        digest=h.hexdigest()
        if expected_sha and digest!=expected_sha:raise RuntimeError('SHA256 mismatch')
        records.append({'repo':repo,'revision':revision,'file':name,'bytes':out.stat().st_size,'sha256':digest,'sha256_matches_upstream':digest==expected_sha if expected_sha else None,'official_source':f'https://huggingface.co/{repo}/resolve/{revision}/{name}','transport':ENDPOINT})
        (LAB/'reports/musetalk-weight-manifest.json').write_text(json.dumps(records,indent=2))
        print('VERIFIED',name,out.stat().st_size,digest,flush=True)
print('Required UNet/VAE/Whisper/DWPose downloads complete. Face parser remains separate.',flush=True)
