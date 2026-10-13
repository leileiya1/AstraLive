import hashlib,json,pathlib,subprocess
LAB=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab')
FF=LAB/'environments/astralive-musetalk/bin/ffmpeg'
OUT=LAB/'assets/audio/exact';OUT.mkdir(parents=True,exist_ok=True)
manifest=[]
for name,duration,mode in [('short_10s',10,'pad'),('medium_30s',30,'loop'),('long_60s',60,'trim')]:
    src=LAB/'assets/audio'/f'{name}.wav';out=OUT/f'{name}.wav'
    args=[str(FF),'-y','-v','error']
    if mode=='loop':args+=['-stream_loop','-1']
    args+=['-i',str(src)]
    if mode=='pad':args+=['-af','apad']
    args+=['-t',str(duration),'-ar','16000','-ac','1','-c:a','pcm_s16le',str(out)]
    subprocess.run(args,check=True)
    manifest.append({'file':str(out),'source':str(src),'derivation':mode,'duration_seconds':duration,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'command':args})
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest,indent=2))
