"""Live-paced finite PCM producer -> adapter -> bounded paced real-frame consumer."""
import json, os, pathlib, subprocess, sys, threading, time, wave
import numpy as np
import torch
from adapter import AudioChunk, StreamingAdapter, restore_published_pose
L=pathlib.Path(os.environ.get('SOULX_LAB','/root/autodl-tmp/astralive-avatar-lab'))
ROOT=L/'streaming'/os.environ.get('POC_RUN',''); (ROOT/'evidence').mkdir(parents=True,exist_ok=True); (ROOT/'outputs').mkdir(exist_ok=True)
R=L/'repositories/SoulX-FlashHead'; os.chdir(R);sys.path.insert(0,str(R))
from flash_head.inference import get_pipeline,get_base_data,get_audio_embedding,run_pipeline
start=time.monotonic(); events=[]; event_lock=threading.Lock()
f=(ROOT/'evidence/events.jsonl').open('w',buffering=1)
def log(event,generation_id=None,**data):
    row=dict(event=event,generation_id=generation_id,monotonic_s=time.monotonic(),elapsed_s=time.monotonic()-start,**data)
    with event_lock:
        events.append(row); f.write(json.dumps(row)+'\n')
summary=dict(status='RUNNING',pid=os.getpid(),cases=[],model_revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),scope='GPU-local incremental PCM PoC; no network/Runtime')
def save(): (ROOT/'evidence/summary.json').write_text(json.dumps(summary,indent=2))
save();log('ModelLoadStart')
p=get_pipeline(1,str(L/'models/soulx/SoulX-FlashHead-1_3B'),'lite',str(L/'models/soulx/wav2vec2-base-960h'))
log('ModelLoaded');get_base_data(p,str(L/'assets/soulx/original/official_girl.png'),42,False)
log('AvatarPrepared'); history=np.zeros(128000,dtype=np.float32)
for i in range(3):
    video=run_pipeline(p,get_audio_embedding(p,history,167,200)).cpu().numpy().astype(np.uint8)
    restore_published_pose(p,list(video[-9:]));torch.cuda.synchronize()
    log('WarmupBlock',block=i)
p.reset_person_name(); torch.cuda.synchronize(); log('GPU_WORKER_READY')
summary['startup_to_ready_s']=time.monotonic()-start;summary['ready_semantics']='model/avatar loaded; 3 compiled inference/feature blocks plus published-pose restoration completed before PCM';save()
adapter=StreamingAdapter(p,get_audio_embedding,run_pipeline,log)
generation=0

def run_case(seconds,pattern,label,jitter=False,slow=False,cancel=False,silence=False):
    global generation
    generation+=1;gid=generation;name=f'{gid:02d}-{label}-{seconds}s'
    path=L/'assets/audio/exact'/({10:'short_10s.wav',30:'medium_30s.wav',60:'long_60s.wav'}[seconds])
    out=ROOT/'outputs'/f'{name}.mp4'
    cmd=['/usr/bin/ffmpeg','-nostdin','-y','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size','512x512','-framerate','25','-i','pipe:0','-i',str(path),'-c:v','libx264','-preset','ultrafast','-tune','zerolatency','-bf','0','-g','25','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(out)]
    if silence:
        cmd=['/usr/bin/ffmpeg','-nostdin','-y','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size','512x512','-framerate','25','-i','pipe:0','-c:v','libx264','-preset','ultrafast','-tune','zerolatency','-bf','0','-g','25','-crf','20','-pix_fmt','yuv420p',str(out)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    adapter.inference_started.clear();adapter.begin(gid)
    done=threading.Event();err=[]
    def producer():
        try:
            with wave.open(str(path),'rb') as w:
                assert (w.getframerate(),w.getnchannels(),w.getsampwidth())==(16000,1,2)
                index=seq=0; t0=time.monotonic();delay=0
                while index<seconds*16000:
                    count=min(pattern[seq%len(pattern)]*16,seconds*16000-index)
                    pcm=w.readframes(count)
                    if silence: pcm=bytes(len(pcm))
                    if jitter and seq==12: delay=.35;log('InjectedAudioLate',gid,delay_ms=350)
                    deadline=t0+(index+count)/16000+delay
                    time.sleep(max(0,deadline-time.monotonic()))
                    c=AudioChunk(16000,1,'s16le',seq,index,count,gid,index+count==seconds*16000,pcm)
                    if not adapter.put(c): break
                    index+=count;seq+=1
        except Exception as e: err.append(repr(e))
        finally: done.set()
    th=threading.Thread(target=producer,daemon=True);th.start()
    consumed=0;first=None;lag=0;deltas=[];last=None;cancelled=False
    if cancel:
        if not adapter.inference_started.wait(30):raise RuntimeError('no inference to cancel')
        adapter.cancel(gid);cancelled=True
        th.join(3)
        # A producer holding an old task may still attempt to send: must be rejected.
        assert not adapter.put(AudioChunk(16000,1,'s16le',0,0,320,gid,False,bytes(640)))
        # Accept next task before the old submitted GPU block has returned.
        generation+=1; next_gid=generation
        adapter.begin(next_gid)
        adapter.put(AudioChunk(16000,1,'s16le',0,0,320,next_gid,True,bytes(640)))
        probe=adapter.consume(lambda packet: log('ForceProbeConsumed',packet['generation_id']))
        assert probe['generation_id']==next_gid
        adapter.finish(next_gid)
        log('ForceProbeFinished',next_gid,old_generation_id=gid)
    else:
        while consumed<seconds*25:
            if first is not None:
                due=first+consumed/(20 if slow else 25)
                time.sleep(max(0,due-time.monotonic()))
            def publish(packet):
                nonlocal consumed,first,lag,last
                if packet['generation_id']!=gid or packet['pts_us']!=consumed*40000: raise RuntimeError('PTS/generation mismatch')
                if first is None:first=time.monotonic();log('FirstFrameConsumed',gid)
                lag=max(lag,max(0,time.monotonic()-(first+consumed/(20 if slow else 25))))
                if last is not None:
                    # Numeric pixel discontinuity diagnostic, never a naturalness score.
                    deltas.append(dict(frame=consumed,mean_abs_pixel_delta=float(np.abs(packet['frame'].astype(np.float32)-last).mean()),block_boundary=consumed%24==0))
                last=packet['frame'].astype(np.float32)
                consumed+=1
            packet=adapter.consume(publish)
            proc.stdin.write(packet['frame'].tobytes())
            if consumed==1:
                log('FirstEncoderInput',gid) # input receipt is NOT encoded packet output
                time.sleep(.120) # declared jitter buffer; arrival timing remains unchanged
                first=time.monotonic()
                log('FirstLocalDisplay',gid,playout_buffer_ms=120)
        th.join(5)
        if err:raise RuntimeError(err)
        if not done.is_set():raise RuntimeError('producer not finished')
        adapter.finish(gid)
    proc.stdin.close();rc=proc.wait(timeout=20)
    rows=[e for e in events if e['generation_id']==gid]
    def firstevent(key):return next((e['monotonic_s'] for e in rows if e['event']==key),None)
    arrival=firstevent('PCM_Arrival')
    stages={k:(firstevent(k)-arrival if firstevent(k) is not None and arrival else None) for k in ['AudioBlockReady','AudioFeatureReady','GPUInferenceStart','GPUOutput','FirstFrameConsumed','FirstEncoderInput','FirstLocalDisplay']}
    gpu=[e['elapsed_ms']/1000 for e in rows if e['event']=='GPUOutput']
    result=dict(name=name,generation_id=gid,seconds=seconds,chunk_pattern_ms=pattern,late=jitter,slow_consumer=slow,cancelled=cancelled,silence_gpu_generated=silence,consumed_frames=consumed,first_pcm_to_stage_s=stages,maximum_pacing_lag_s=lag,audio_queue_max_ms=max([e.get('audio_queue_ms',0) for e in rows] or [0]),video_queue_max_ms=max([e.get('video_queue_ms',0) for e in rows] or [0]),gpu_pipeline_fps=24*len(gpu)/sum(gpu) if gpu else None,queue_drops=0,stale_gpu_frames_discarded=sum(e.get('frames',0) for e in rows if e['event']=='stale_gpu_output_rejected'),output=str(out) if consumed else None,encoder_exit=rc,errors=err)
    if consumed:
        subprocess.run(['/usr/bin/ffmpeg','-v','error','-i',str(out),'-f','null','-'],check=True)
        meta=json.loads(subprocess.check_output(['/usr/bin/ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(out)],text=True))
        v=next(x for x in meta['streams'] if x['codec_type']=='video')
        assert int(v['nb_read_frames'])==consumed
        result['decoded_frames']=int(v['nb_read_frames']);result['status']='MECHANICAL_PASS_VISUAL_PENDING'
        (ROOT/'evidence'/f'{name}-pixel-deltas.json').write_text(json.dumps(deltas))
        (ROOT/'evidence'/f'{name}-ffprobe.json').write_text(json.dumps(meta,indent=2))
    else:result['status']='CANCEL_FENCE_PASS' if any(e['event']=='stale_gpu_output_rejected' for e in rows) else 'CANCEL_PENDING_AUDIT'
    summary['cases'].append(result);save();print('CASE_RESULT',json.dumps(result),flush=True)

try:
    for seconds in ((30,60) if os.environ.get('POC_RECHECK') else (10,30,60)):
        for ms in ((100,) if os.environ.get('POC_RECHECK') else (20,40,100)):run_case(seconds,[ms],str(ms)+'ms')
    run_case(10,[20,40,100,60,20,80],'variable-late',jitter=True)
    run_case(10,[20,40,100],'slow-consumer',slow=True)
    run_case(10,[20],'force-during-inference',cancel=True)
    run_case(10,[40],'force-restart')
    run_case(10,[40],'talking-to-idle',silence=True)
    run_case(10,[40],'idle-to-talking')
    summary['status']='MECHANICAL_COMPLETE_VISUAL_PENDING'
except Exception:
    import traceback
    summary['status']='FAILED';summary['error']=traceback.format_exc();print(summary['error'],flush=True)
finally:
    adapter.close();summary['gpu_thread_stopped']=not adapter.thread.is_alive();save();f.close()
