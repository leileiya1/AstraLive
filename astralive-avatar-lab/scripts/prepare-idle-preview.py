"""Visual-only assembly of already generated clips, never counted as inference."""
import json,pathlib,subprocess
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');names=['idle-silence-1','talking-after-idle-1','idle-silence-2','talking-after-idle-2'];clips={c['name']:c for c in json.loads((L/'benchmarks/musetalk.json').read_text())['clips']}
base=['ffmpeg','-nostdin','-y','-v','error'];cmd=base.copy()
for name in names:cmd+=['-i',str(L/'outputs/musetalk'/f'{name}.mp4')]
cmd+=['-i',str(L/'outputs/musetalk/idle-talking-sequence-audio.wav'),'-filter_complex','[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v]','-map','[v]','-map','4:a','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-ar','16000','-shortest',str(L/'outputs/musetalk/idle-talking-sequence.mp4')]
audio=base.copy()
for name in names:audio+=['-i',clips[name]['input']]
audio+=['-filter_complex','[0:a][1:a][2:a][3:a]concat=n=4:v=0:a=1[a]','-map','[a]','-ar','16000',str(L/'outputs/musetalk/idle-talking-sequence-audio.wav')]
subprocess.run(audio,check=True)
subprocess.run(cmd,check=True)
(L/'benchmarks/idle-preview-command.json').write_text(json.dumps(dict(status='VISUAL_PREVIEW_ONLY',video_command=cmd,audio_command=audio,inference_frames_added=0,limitations='Offline assembly of four independently generated clips; not a live state-transition test'),indent=2))
