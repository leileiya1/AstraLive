"""Measured lab adapter around pinned MuseTalk 1.5; no production imports.

Normal upstream CLI baseline must pass before invoking this cache benchmark.
Core FPS means synchronized UNet only. Decode includes VAE and CPU readback.
This adapter consumes every generated frame, unlike upstream's N-1 consumer.
"""
import argparse,copy,csv,json,os,pathlib,queue,subprocess,sys,threading,time,traceback
from types import SimpleNamespace
import numpy as np
import torch,cv2

LAB=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab')
REPO=LAB/'repositories/MuseTalk'
os.chdir(REPO);sys.path.insert(0,str(REPO))
ap=argparse.ArgumentParser();ap.add_argument('--soak-seconds',type=int,default=0);ap.add_argument('--batch-size',type=int,default=8)
opts=ap.parse_args()
report={'status':'RUNNING','model':'MuseTalk 1.5','commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'batch_size':opts.batch_size,'pid':os.getpid(),'clips':[]}
DEST=LAB/'benchmarks/musetalk.json'
def save():DEST.write_text(json.dumps(report,indent=2))
save()
start=time.perf_counter()
import scripts.realtime_inference as m
report['preprocessing_component_import_load_seconds']=time.perf_counter()-start
m.args=SimpleNamespace(version='v15',extra_margin=10,parsing_mode='jaw',left_cheek_width=90,right_cheek_width=90,audio_padding_length_left=2,audio_padding_length_right=2,skip_save_images=True)
m.device=torch.device('cuda:0')
start=time.perf_counter()
m.vae,m.unet,m.pe=m.load_all_model(unet_model_path='./models/musetalkV15/unet.pth',vae_type='sd-vae',unet_config='./models/musetalkV15/musetalk.json',device=m.device)
m.timesteps=torch.tensor([0],device=m.device)
m.pe=m.pe.half().to(m.device);m.vae.vae=m.vae.vae.half().to(m.device);m.unet.model=m.unet.model.half().to(m.device).eval()
m.audio_processor=m.AudioProcessor(feature_extractor_path='./models/whisper')
m.weight_dtype=m.unet.model.dtype
m.whisper=m.WhisperModel.from_pretrained('./models/whisper').to(device=m.device,dtype=m.weight_dtype).eval();m.whisper.requires_grad_(False)
m.fp=m.FaceParsing(left_cheek_width=90,right_cheek_width=90)
torch.cuda.synchronize();report['model_load_seconds']=time.perf_counter()-start
cache_path=REPO/'results/v15/avatars/astralive_lab_sun'
start=time.perf_counter()
avatar=m.Avatar('astralive_lab_sun',str(LAB/'assets/musetalk/real-human/sun_25fps.mp4'),0,opts.batch_size,not cache_path.exists())
torch.cuda.synchronize();report['cache_load_or_prepare_seconds']=time.perf_counter()-start
report['cache_path']=str(cache_path);report['resident_allocated_bytes']=torch.cuda.memory_allocated();save()

@torch.no_grad()
def audio_features(path):
    feats,length=m.audio_processor.get_audio_feature(str(path),weight_dtype=m.weight_dtype)
    return m.audio_processor.get_whisper_chunk(feats,m.device,m.weight_dtype,m.whisper,length,fps=25,audio_padding_length_left=2,audio_padding_length_right=2)

@torch.no_grad()
def batches(chunks):
    for wb,lb in m.datagen(chunks,avatar.input_latent_list_cycle,opts.batch_size):
        features=m.pe(wb.to(m.device));lb=lb.to(device=m.device,dtype=m.unet.model.dtype)
        torch.cuda.synchronize();t=time.perf_counter()
        pred=m.unet.model(lb,m.timesteps,encoder_hidden_states=features).sample
        torch.cuda.synchronize();core=time.perf_counter()-t
        t=time.perf_counter();recon=m.vae.decode_latents(pred.to(dtype=m.vae.vae.dtype));torch.cuda.synchronize()
        yield recon,core,time.perf_counter()-t

def blend(recon,index):
    k=index%len(avatar.coord_list_cycle);bbox=avatar.coord_list_cycle[k];x1,y1,x2,y2=bbox
    resized=cv2.resize(recon.astype(np.uint8),(x2-x1,y2-y1))
    return m.get_image_blending(copy.deepcopy(avatar.frame_list_cycle[k]),resized,bbox,avatar.mask_list_cycle[k],avatar.mask_coords_list_cycle[k])

def writer(name,audio):
    h,w=avatar.frame_list_cycle[0].shape[:2]
    output=LAB/'outputs/musetalk'/f'{name}.mp4'
    command=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','bgr24','-video_size',f'{w}x{h}','-framerate','25','-i','pipe:0','-i',str(audio),'-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-ar','16000','-shortest',str(output)]
    logfile=(LAB/'logs'/f'{name}-ffmpeg.log').open('wb')
    return subprocess.Popen(command,stdin=subprocess.PIPE,stderr=logfile),output,command,logfile

def verify(output):
    raw=subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(output)],text=True)
    output.with_name(output.stem+'-ffprobe.json').write_text(raw)
    data=json.loads(raw)
    if not any(x['codec_type']=='audio' for x in data['streams']):raise RuntimeError('Missing audio')
    if not any(x['codec_type']=='video' and int(x.get('nb_read_frames','0'))>0 for x in data['streams']):raise RuntimeError('Missing frames')
    subprocess.run(['ffmpeg','-v','error','-i',str(output),'-f','null','-'],check=True)
    return data

def clip(name,audio,emit=True):
    torch.cuda.reset_peak_memory_stats();t0=time.perf_counter();chunks=audio_features(audio);audio_s=time.perf_counter()-t0
    core_s=decode_s=blend_s=write_s=0;batch_fps=[];latencies=[];n=0;first=None
    proc=out=log=None;commands=None
    if emit:proc,out,commands,log=writer(name,audio)
    t_gen=time.perf_counter()
    for frames,core,decode in batches(chunks):
        core_s+=core;decode_s+=decode;tb=time.perf_counter()
        for frame in frames:
            ts=time.perf_counter();full=blend(frame,n);blend_s+=time.perf_counter()-ts
            if first is None:first=time.perf_counter()-t0
            if proc:
                ts=time.perf_counter();proc.stdin.write(full.tobytes());write_s+=time.perf_counter()-ts
            n+=1
        batch_s=core+decode+time.perf_counter()-tb
        batch_fps.append(len(frames)/batch_s);latencies.append(batch_s/len(frames)*1000)
    generation_s=time.perf_counter()-t_gen
    if proc:
        proc.stdin.close();rc=proc.wait(timeout=180);log.close()
        if rc:raise RuntimeError(f'FFmpeg exit {rc}')
    total=time.perf_counter()-t0
    rec={'name':name,'input':str(audio),'frames_generated':n,'audio_processing_seconds':audio_s,'first_composited_frame_seconds':first,'core_unet_seconds':core_s,'core_unet_fps':n/core_s,'vae_decode_and_readback_seconds':decode_s,'blend_seconds':blend_s,'effective_audio_model_decode_blend_fps':n/(audio_s+generation_s-write_s),'generation_with_encoder_pipe_seconds':generation_s,'end_to_end_seconds':total,'end_to_end_fps':n/total,'encoder_pipe_write_seconds':write_s,'batch_normalized_frame_latency_ms_p5':float(np.percentile(latencies,5)),'batch_normalized_frame_latency_ms_p95':float(np.percentile(latencies,95)),'batch_effective_fps_p5':float(np.percentile(batch_fps,5)),'batch_effective_fps_p95':float(np.percentile(batch_fps,95)),'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),'output':str(out) if out else None,'command':commands,'status':'GENERATED_PENDING_VISUAL_ACCEPTANCE'}
    if out:
        info=verify(out);rec['encoded_declared_fps']='25/1';rec['output_duration_seconds']=float(info['format']['duration'])
        rec['encoded_video_frames']=int(next(x for x in info['streams'] if x['codec_type']=='video')['nb_read_frames'])
    print(json.dumps(rec),flush=True);report['clips'].append(rec);save();return rec

try:
    short=LAB/'assets/audio/exact/short_10s.wav'
    clip('warmup',short,emit=False)
    for name,audio in [('musetalk-short',short),('musetalk-medium',LAB/'assets/audio/exact/medium_30s.wav'),('musetalk-long',LAB/'assets/audio/exact/long_60s.wav')]:clip(name,audio)
    for index in range(3):clip(f'continuous-{index+1}',short)
    for index in range(2):
        clip(f'idle-silence-{index+1}',LAB/'assets/audio/silence_10s.wav');clip(f'talking-after-idle-{index+1}',short)
    report['idle_switch_limit']='Silence/talking clips share one process/cache; seamless streaming idle transition is not implemented by this offline adapter.'
    if opts.soak_seconds:
        seconds=opts.soak_seconds;target=seconds*25;pending=queue.Queue(maxsize=16);errors=[];rows=[]
        torch.cuda.reset_peak_memory_stats();start=time.perf_counter();produced=[0]
        def producer():
            try:
                with torch.no_grad():
                    while produced[0]<target:
                        chunks=audio_features(short)
                        for frames,core,decode in batches(chunks):
                            for frame in frames:
                                if produced[0]>=target:return
                                full=blend(frame,produced[0]);pending.put((produced[0],time.perf_counter(),full),timeout=30);produced[0]+=1
            except BaseException as exc:errors.append(repr(exc));pending.put(None,timeout=30)
        thread=threading.Thread(target=producer);thread.start();first=None;late=0;maximum_lag=0
        # Real GPU generation and paced sink; no pre-generated playback.
        for expected in range(target):
            item=pending.get(timeout=60)
            if item is None:raise RuntimeError(str(errors))
            index,ready,frame=item
            if index!=expected:raise RuntimeError('Frame ordering violated')
            now=time.perf_counter()
            if first is None:first=now
            deadline=first+index/25
            if now<deadline:time.sleep(deadline-now)
            now=time.perf_counter();lag=max(0,now-deadline);late+=int(lag>0.04);maximum_lag=max(maximum_lag,lag)
            if index%25==0:
                rows.append([index,now-start,lag,pending.qsize(),produced[0]])
                print('SOAK',index,'elapsed',round(now-start,3),'lag',round(lag,4),flush=True)
        thread.join(timeout=30)
        if thread.is_alive() or errors:raise RuntimeError(f'Producer cleanup failed {errors}')
        elapsed=time.perf_counter()-start
        with (LAB/'benchmarks/musetalk-soak-timeline.csv').open('w') as f:
            w=csv.writer(f);w.writerow(['consumed_frame','elapsed_seconds','lateness_seconds','queue_depth','generated_frames']);w.writerows(rows)
        report['soak']={'same_pid':os.getpid(),'wall_seconds':elapsed,'paced_duration_seconds':time.perf_counter()-first,'generated_frames':produced[0],'consumed_frames':target,'dropped_frames':0,'late_over_40ms_frames':late,'maximum_lag_seconds':maximum_lag,'effective_fps':target/elapsed,'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),'queue_bound':16,'sink':'paced composited frame consumer, no network/encoder','status':'PASS' if elapsed>=600 and late==0 else 'PERFORMANCE_NOT_PASS'}
    report['status']='COMPLETED_PENDING_VISUAL_ACCEPTANCE';save()
except BaseException as exc:
    report['status']='FAILED';report['error']=repr(exc);save();traceback.print_exc();raise
