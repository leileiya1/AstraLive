import datetime,json,pathlib,re,subprocess
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');out=L/'outputs/soulx/baseline.mp4'
raw=subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(out)],text=True);out.with_name('baseline-ffprobe.json').write_text(raw);meta=json.loads(raw)
v=next(s for s in meta['streams'] if s['codec_type']=='video');a=next(s for s in meta['streams'] if s['codec_type']=='audio')
subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(out),'-f','null','-'],check=True)
command=json.loads((L/'benchmarks/soulx-official-stream-command.json').read_text());log=(L/'logs/soulx-official-stream.log').read_text();costs=[float(x) for x in re.findall(r'Generate video chunk-\d+ done, cost time: ([\d.]+)s',log)]
line=next(s for s in log.splitlines() if 'Generate video chunk-0 done' in s)
stamp=datetime.datetime.strptime(line.split(' | ')[0],'%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
first=(stamp-datetime.datetime.fromisoformat(command['started_utc'])).total_seconds()
d=dict(status='DECODE_PASS_PENDING_VISUAL_ACCEPTANCE',video_frames=int(v['nb_read_frames']),video_duration=float(v['duration']),audio_duration=float(a['duration']),declared_fps=v['avg_frame_rate'],wall_seconds=command['wall_seconds'],cold_end_to_end_fps=int(v['nb_read_frames'])/command['wall_seconds'],first_gpu_chunk_from_process_launch_seconds=first,logged_chunk_cost_seconds=costs,warm_logged_audio_model_vae_fps=24*len(costs[2:])/sum(costs[2:]),logged_fps_scope='Audio encoder + model + VAE/GPU conversion/motion encode; excludes CPU video transfer and file encoding. First two chunks excluded from warm statistic.',actual_command=command['command'],audio_input=str(L/'assets/soulx/original/official_podcast_sichuan_16k.wav'),image_input=str(L/'assets/soulx/original/official_girl.png'))
out.with_name('baseline-metrics.json').write_text(json.dumps(d,indent=2));print(json.dumps(d,indent=2)[:1600])
