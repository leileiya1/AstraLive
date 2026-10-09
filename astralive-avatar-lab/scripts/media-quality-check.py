"""Decode/black-frame/audio checks; these do not assert perceptual naturalness."""
import json,pathlib,subprocess,numpy as np
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');rows=[]
inputs={str(L/'outputs/musetalk/baseline.mp4'):str(L/'assets/musetalk/real-human/sun.wav')}
inputs[str(L/'outputs/musetalk/musetalk-same-source.mp4')]=str(L/'assets/audio/exact/short_10s.wav')
inputs[str(L/'outputs/musetalk/idle-talking-sequence.mp4')]=str(L/'outputs/musetalk/idle-talking-sequence-audio.wav')
inputs[str(L/'outputs/soulx/baseline.mp4')]=str(L/'assets/soulx/original/official_podcast_sichuan_16k.wav')
for key in ['start','middle','end']:inputs[str(L/'outputs/soulx'/f'soulx-soak-{key}.mp4')]=str(L/'outputs/soulx'/f'soak-{key}-audio.wav')
for model in ['musetalk','soulx']:
    path=L/'benchmarks'/f'{model}.json'
    if path.exists():
        for c in json.loads(path.read_text()).get('clips',[]):
            if c.get('output'):inputs[c['output']]=c['input']
for model in ['musetalk','soulx']:
    for p in sorted((L/'outputs'/model).glob('*.mp4')):
        raw=subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(p)],text=True);p.with_name(p.stem+'-ffprobe.json').write_text(raw);probe=json.loads(raw)
        check=subprocess.run(['ffmpeg','-nostdin','-v','info','-i',str(p),'-vf','blackdetect=d=0.08:pix_th=0.10','-an','-f','null','-'],capture_output=True,text=True)
        black=[s for s in check.stderr.splitlines() if 'black_start:' in s]
        audio=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',str(p),'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1'])
        a=np.frombuffer(audio,dtype=np.float32)
        match={}
        if str(p) in inputs:
            source=inputs[str(p)];raw=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',source,'-ac','1','-ar','16000','-f','f32le','pipe:1']);b=np.frombuffer(raw,dtype=np.float32);n=min(len(a),len(b));aa=a[:n].astype(np.float64);bb=b[:n].astype(np.float64)
            energy=float(np.linalg.norm(aa)*np.linalg.norm(bb))
            cosine=float(np.dot(aa,bb)/energy) if energy>1e-12 else None
            silent=float(np.max(np.abs(aa)))<1e-4 and float(np.max(np.abs(bb)))<1e-4
            match=dict(expected_audio=source,waveform_cosine_aligned=cosine,audio_match_pass=silent or (cosine is not None and cosine>.97))
        rows.append(dict(model=model,file=str(p),duration=float(probe['format']['duration']),complete_decode_pass=check.returncode==0,black_intervals=black,audio_samples=len(a),audio_rms=float(np.sqrt(np.mean(a*a))) if len(a) else None,visual_naturalness='NOT_SCORED',**match))
        print(p.name,'decode',check.returncode,'black',len(black),flush=True)
(L/'reports/media-quality-check.json').write_text(json.dumps(rows,indent=2))
