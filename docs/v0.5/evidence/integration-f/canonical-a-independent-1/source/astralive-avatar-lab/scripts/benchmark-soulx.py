"""Resident Lite benchmark using official stream-chunk inference functions."""
import collections,csv,json,os,pathlib,queue,subprocess,sys,threading,time,traceback
import numpy as np,torch,librosa
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');R=L/'repositories/SoulX-FlashHead'
os.chdir(R);sys.path.insert(0,str(R))
from flash_head.inference import get_pipeline,get_base_data,get_infer_params,get_audio_embedding,run_pipeline
d={'model':'SoulX-FlashHead Lite','commit':subprocess.check_output(['git','-c',f'safe.directory={R}','rev-parse','HEAD'],text=True).strip(),'pid':os.getpid(),'status':'RUNNING','clips':[]}
dest=L/'benchmarks/soulx.json'
def save():dest.write_text(json.dumps(d,indent=2))
save();t=time.perf_counter()
p=get_pipeline(1,str(L/'models/soulx/SoulX-FlashHead-1_3B'),'lite',str(L/'models/soulx/wav2vec2-base-960h'))
torch.cuda.synchronize();d['model_load_seconds']=time.perf_counter()-t
core_events=[]
class TimedDenoiser(torch.nn.Module):
    def __init__(self,inner):super().__init__();self.inner=inner
    def forward(self,*args,**kwargs):
        a=torch.cuda.Event(enable_timing=True);b=torch.cuda.Event(enable_timing=True);a.record()
        out=self.inner(*args,**kwargs);b.record();core_events.append((a,b));return out
p.model=TimedDenoiser(p.model)
image=L/'assets/soulx/original/official_girl.png'
cfg=get_infer_params();d['infer_params']=cfg;save()
def clip(name,audio,emit=True):
    t=time.perf_counter();get_base_data(p,str(image),42,False);torch.cuda.synchronize();prep=time.perf_counter()-t
    samples,sr=librosa.load(str(audio),sr=cfg['sample_rate'],mono=True)
    fps=cfg['tgt_fps'];frames_per=cfg['frame_num']-cfg['motion_frames_num'];step=frames_per*sr//fps
    target_frames=round(len(samples)/sr*fps);samples=np.pad(samples,(0,(-len(samples))%step))
    dq=collections.deque([0.0]*(sr*cfg['cached_audio_duration']),maxlen=sr*cfg['cached_audio_duration'])
    end=cfg['cached_audio_duration']*fps;begin=end-cfg['frame_num']
    out=L/'outputs/soulx'/f'{name}.mp4';out.parent.mkdir(parents=True,exist_ok=True)
    cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{cfg["width"]}x{cfg["height"]}','-framerate',str(fps),'-i','pipe:0','-i',str(audio),'-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(out)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE) if emit else None
    torch.cuda.reset_peak_memory_stats();core_events.clear();t0=time.perf_counter();core=[];audio_times=[];write_s=0;n=0;first=None
    for i,slice_ in enumerate(samples.reshape(-1,step)):
        a=time.perf_counter();dq.extend(slice_.tolist());emb=get_audio_embedding(p,np.asarray(dq),begin,end);torch.cuda.synchronize();audio_times.append(time.perf_counter()-a)
        a=time.perf_counter();video=run_pipeline(p,emb)[cfg['motion_frames_num']:];torch.cuda.synchronize();core.append(time.perf_counter()-a)
        arr=video.cpu().numpy().astype(np.uint8);arr=arr[:target_frames-n]
        if first is None:first=time.perf_counter()-t0
        if proc:
            a=time.perf_counter();proc.stdin.write(arr.tobytes());write_s+=time.perf_counter()-a
        n+=len(arr);print('CHUNK',name,i,'frames',n,'pipeline_seconds',round(core[-1],4),flush=True)
    if proc:
        proc.stdin.close()
        if proc.wait()!=0:raise RuntimeError('encoder failed')
    wall=time.perf_counter()-t0
    c={'name':name,'input':str(audio),'image':str(image),'frames_generated':n,'model_pipeline_fps':n/sum(core),'pipeline_scope':'diffusion model + VAE + GPU pixel conversion, excludes audio encoder and CPU transfer','audio_encoder_seconds':sum(audio_times),'end_to_end_seconds':wall,'end_to_end_fps':n/wall,'first_chunk_available_seconds':first,'avatar_prepare_seconds':prep,'encoder_pipe_write_seconds':write_s,'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),'chunk_pipeline_seconds':core,'status':'GENERATED_PENDING_VISUAL_ACCEPTANCE','output':str(out) if emit else None,'command':cmd if emit else None}
    denoiser_s=sum(a.elapsed_time(b) for a,b in core_events)/1000
    c.update(core_denoiser_cuda_seconds=denoiser_s,core_denoiser_fps=n/denoiser_s if denoiser_s else None,effective_audio_model_vae_transfer_fps=n/max(wall-write_s,1e-9))
    if proc:
        raw=subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(out)],text=True);out.with_name(out.stem+'-ffprobe.json').write_text(raw);meta=json.loads(raw)
        v=next(x for x in meta['streams'] if x['codec_type']=='video');a=next(x for x in meta['streams'] if x['codec_type']=='audio')
        if int(v['nb_read_frames'])!=target_frames:raise RuntimeError('frame count mismatch')
        subprocess.run(['ffmpeg','-v','error','-i',str(out),'-f','null','-'],check=True)
        c.update(encoded_video_frames=int(v['nb_read_frames']),encoded_declared_fps=v['avg_frame_rate'],output_duration_seconds=float(meta['format']['duration']))
    d['clips'].append(c);save()
clip('warmup',L/'assets/audio/exact/short_10s.wav',False)
for name,audio in [('soulx-short','short_10s.wav'),('soulx-medium','medium_30s.wav'),('soulx-long','long_60s.wav')]:clip(name,L/'assets/audio/exact'/audio)
if min(c['end_to_end_fps'] for c in d['clips'][1:]) >= cfg['tgt_fps']:
    # Match MuseTalk's paced composited-frame sink. No encoder/network in timed soak.
    get_base_data(p,str(image),42,False);torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
    core_events.clear()
    fps=cfg['tgt_fps'];total=600*fps;step=(cfg['frame_num']-cfg['motion_frames_num'])*cfg['sample_rate']//fps
    src,_=librosa.load(str(L/'assets/audio/exact/long_60s.wav'),sr=cfg['sample_rate'],mono=True)
    dq=collections.deque([0.0]*(cfg['sample_rate']*cfg['cached_audio_duration']),maxlen=cfg['sample_rate']*cfg['cached_audio_duration'])
    end=cfg['cached_audio_duration']*fps;begin=end-cfg['frame_num'];q=queue.Queue(maxsize=48);stop=threading.Event();errors=[];generated=[0]
    def produce():
        try:
            offset=0
            while generated[0]<total and not stop.is_set():
                indices=np.arange(offset,offset+step)%len(src);dq.extend(src[indices].tolist());offset+=step
                emb=get_audio_embedding(p,np.asarray(dq),begin,end)
                arr=run_pipeline(p,emb)[cfg['motion_frames_num']:].cpu().numpy().astype(np.uint8)
                for frame in arr:
                    if generated[0]>=total or stop.is_set():break
                    while not stop.is_set():
                        try:q.put((generated[0],frame),timeout=.5);generated[0]+=1;break
                        except queue.Full:pass
        except Exception:errors.append(traceback.format_exc())
    t0=time.perf_counter();thread=threading.Thread(target=produce,daemon=True);thread.start();consumed=0;late=0;maxlag=0;timeline=[]
    windows={'start':(0,10*fps),'middle':(295*fps,305*fps),'end':(590*fps,600*fps)};samples={k:[] for k in windows}
    first=None
    while consumed<total:
        try:index,frame=q.get(timeout=10)
        except queue.Empty:
            if errors:raise RuntimeError(errors[0])
            if not thread.is_alive():raise RuntimeError('producer stopped')
            continue
        if first is None:first=time.perf_counter()-t0
        target=t0+first+index/fps;remaining=target-time.perf_counter()
        if remaining>0:time.sleep(remaining)
        elapsed=time.perf_counter()-t0;lag=max(0,time.perf_counter()-target);maxlag=max(maxlag,lag);late+=int(lag>.04)
        for key,(a,b) in windows.items():
            if a<=index<b:samples[key].append(frame.copy())
        consumed+=1
        if consumed%fps==0:
            timeline.append(dict(frame=index,elapsed_seconds=elapsed,lag_seconds=lag,queue_depth=q.qsize()))
            print('SOAK',consumed,'elapsed',round(elapsed,3),'lag',round(lag,4),flush=True)
    thread.join(timeout=15);wall=time.perf_counter()-t0
    d['soak']=dict(same_pid=os.getpid(),wall_seconds=wall,generated_frames=generated[0],consumed_frames=consumed,dropped_frames=generated[0]-consumed,late_over_40ms_frames=late,maximum_lag_seconds=maxlag,effective_fps=consumed/wall,first_chunk_seconds=first,queue_bound=48,peak_allocated_bytes=torch.cuda.max_memory_allocated(),peak_reserved_bytes=torch.cuda.max_memory_reserved(),sink='paced generated-frame consumer, no encoder/network',status='PASS' if wall>=600 and late==0 and consumed==total and not errors else 'PERFORMANCE_NOT_PASS');save()
    with (L/'benchmarks/soulx-soak-timeline.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=timeline[0]);writer.writeheader();writer.writerows(timeline)
    # Encode actual beginning/middle/end generated frames only AFTER timing stops.
    for key,frames in samples.items():
        a,b=windows[key];audio=L/'outputs/soulx'/f'soak-{key}-audio.wav';out=L/'outputs/soulx'/f'soulx-soak-{key}.mp4'
        subprocess.run(['ffmpeg','-nostdin','-y','-v','error','-stream_loop','-1','-i',str(L/'assets/audio/exact/long_60s.wav'),'-ss',str(a/fps),'-t','10',str(audio)],check=True)
        cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{cfg["width"]}x{cfg["height"]}','-framerate',str(fps),'-i','pipe:0','-i',str(audio),'-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(out)]
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
        for frame in frames:proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        if proc.wait()!=0:raise RuntimeError('soak sample encoding failed')
        print('SOAK_SAMPLE',key,str(out),flush=True)
d['status']='COMPLETED_PENDING_VISUAL_ACCEPTANCE';save()
