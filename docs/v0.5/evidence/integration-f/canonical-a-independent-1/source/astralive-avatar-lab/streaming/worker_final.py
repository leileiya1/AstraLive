"""Private, one-avatar experimental Worker. No AstraLive commercial-session control."""
import collections,fractions,hashlib,hmac,json,os,pathlib,socket,sys,threading,time,uuid
import numpy as np
import torch
from adapter import AudioChunk,StreamingAdapter,restore_published_pose
from wire import send,receive
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');ROOT=L/'streaming'
sys.path.insert(0,str(ROOT/'worker-deps'));import av
R=L/'repositories/SoulX-FlashHead';os.chdir(R);sys.path.insert(0,str(R))
from flash_head.inference import get_pipeline,get_base_data,get_audio_embedding,run_pipeline
diag={'inference_started_s':None,'inference_generation':None,'last_gpu_output_s':None}
EPOCH=uuid.uuid4().hex;TOKEN=(ROOT/'.private/token').read_text().strip()
FINAL=ROOT/'evidence'/os.environ.get('SOULX_FINAL_RUN_DIR','soulx-final-one-hour-pinned-20261009');FINAL.mkdir(exist_ok=True)
logfile=(FINAL/'worker-events.jsonl').open('w',buffering=1);loglock=threading.Lock()
def log(event,generation_id=None,**data):
    if event=='GPUInferenceStart':diag.update(inference_started_s=time.monotonic(),inference_generation=generation_id)
    elif event=='GPUOutput':diag.update(inference_started_s=None,last_gpu_output_s=time.monotonic())
    with loglock:logfile.write(json.dumps(dict(event=event,generation_id=generation_id,worker_epoch=EPOCH,monotonic_s=time.monotonic(),**data))+'\n')
started=time.monotonic();log('WeightValidationStart')
manifest_bytes=(L/'reports/soulx-weight-manifest.json').read_bytes()
manifest=json.loads(manifest_bytes)
for record in manifest:
    folder=L/'models/soulx'/('wav2vec2-base-960h' if record['repo'].startswith('facebook/') else 'SoulX-FlashHead-1_3B')
    file=folder/record['file'];digest=hashlib.sha256()
    with file.open('rb') as source:
        for block in iter(lambda:source.read(1048576),b''):digest.update(block)
    if digest.hexdigest()!=record['sha256']:raise RuntimeError('validated model weight identity changed')
weights_identity=hashlib.sha256(manifest_bytes).hexdigest()
log('WeightsVerified',manifest_sha256=weights_identity,files=len(manifest));log('ModelLoadStart')
p=get_pipeline(1,str(L/'models/soulx/SoulX-FlashHead-1_3B'),'lite',str(L/'models/soulx/wav2vec2-base-960h'))
image=L/'assets/soulx/original/official_girl.png';imagehash=hashlib.sha256(image.read_bytes()).hexdigest()
get_base_data(p,str(image),42,False)
for i in range(3):
    frames=run_pipeline(p,get_audio_embedding(p,np.zeros(128000,np.float32),167,200)).cpu().numpy().astype(np.uint8)
    restore_published_pose(p,list(frames[-9:]));torch.cuda.synchronize()
    log('WarmupBlock',block=i)
def encoder():
    c=av.CodecContext.create('libx264','w');c.width=c.height=512;c.pix_fmt='yuv420p'
    c.time_base=fractions.Fraction(1,25);c.framerate=fractions.Fraction(25,1);c.thread_count=2
    c.options={'preset':'ultrafast','tune':'zerolatency','bf':'0','g':'25','crf':'20','x264-params':'repeat-headers=1:scenecut=0'};c.open();return c
c=encoder();frame=av.VideoFrame.from_ndarray(frames[-1],format='rgb24');frame.pts=0
assert len(c.encode(frame))==1
p.reset_person_name();torch.cuda.synchronize()
CACHE=hashlib.sha256((weights_identity+imagehash+'9bc03de06bb0de82cd6bc477804512ae06144bf2:512:33:9:4:seed42').encode()).hexdigest()
ready=dict(status='GPU_WORKER_READY',worker_epoch=EPOCH,cache_id=CACHE,input_asset_sha256=imagehash,startup_to_ready_s=time.monotonic()-started,model_revision='9bc03de06bb0de82cd6bc477804512ae06144bf2',codec='h264',av_version=av.__version__,weights_manifest_sha256=weights_identity,torch_version=torch.__version__)
(FINAL/'worker-ready.json').write_text(json.dumps(ready,indent=2));log('GPU_WORKER_READY',startup_to_ready_s=ready['startup_to_ready_s'])
listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('127.0.0.1',17087));listener.listen(1);highest_generation=-1

def handle(sock):
    global highest_generation
    sock.settimeout(5);sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);sock.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,65536)
    header,payload=receive(sock)
    if header.get('type')!='Auth' or header.get('protocol_version')!=1 or not hmac.compare_digest(str(header.get('token','')),TOKEN):
        log('AuthenticationRejected');sock.close();return
    send(sock,dict(type='GPU_WORKER_READY',**ready));sock.settimeout(15)
    adapter=StreamingAdapter(p,get_audio_embedding,run_pipeline,log)
    state=threading.Condition();sendlock=threading.Lock();stopped=threading.Event()
    active=None;slots=0;ack=-1;last_sent=-1;target=None;outstanding={}
    def reply(header,payload=b''):
        with sendlock:send(sock,dict(worker_epoch=EPOCH,**header),payload)
    def sender():
        nonlocal slots,last_sent
        ctx=None;ctxgid=None
        try:
            while not stopped.is_set():
                with state:
                    if active is None or slots==0:
                        state.wait(.05);continue
                    gid=active
                try:packet=adapter.consume(lambda p:None,timeout=.1,commit=False,expected_generation=gid)
                except TimeoutError:continue
                if packet is None:continue
                if ctxgid!=gid:ctx=encoder();ctxgid=gid
                t=time.monotonic();f=av.VideoFrame.from_ndarray(packet['frame'],format='rgb24');f.pts=packet['frame_sequence']
                encoded=ctx.encode(f);elapsed=(time.monotonic()-t)*1000
                if len(encoded)!=1:raise RuntimeError('low latency encoder buffered/reordered frame')
                encoded=encoded[0]
                with state:
                    if active!=gid or packet['generation_id']!=gid:
                        log('stale_encoded_frame_rejected',gid);continue
                    slots-=1;last_sent=packet['frame_sequence'];outstanding[last_sent]=packet['frame']
                    if len(outstanding)>4:raise RuntimeError('credit bound exceeded')
                    log('EncodedFrameAdmitted',gid,frame_sequence=last_sent,pts_us=packet['pts_us'],encode_latency_ms=elapsed,keyframe=encoded.is_keyframe,bytes=encoded.size)
                reply(dict(type='VideoPacket',source='GPU_INFERENCE',generation_id=gid,frame_sequence=packet['frame_sequence'],pts_us=packet['pts_us'],duration_us=40000,codec='h264',keyframe_flag=encoded.is_keyframe,encode_latency_ms=elapsed,audio_queue_ms=adapter.pending_samples/16,video_queue_ms=len(adapter.video)*40),bytes(encoded))
                log('VideoPacketPublished',gid,frame_sequence=packet['frame_sequence'],pts_us=packet['pts_us'])
        except Exception as e:
            log('TransportSenderError',active,error_type=type(e).__name__,error=str(e));stopped.set()
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
    th=threading.Thread(target=sender,daemon=True);th.start()
    try:
        while not stopped.is_set():
            h,payload=receive(sock);kind=h['type']
            if kind=='PrepareAvatar':
                if h['input_asset_sha256']!=imagehash:raise ValueError('only authorized cached avatar supported')
                reply(dict(type='AvatarPrepared',cache_id=CACHE))
            elif kind=='BeginGeneration':
                gid=h['generation_id']
                if gid<=highest_generation or h['cache_id']!=CACHE:raise ValueError('generation/cache mismatch')
                if (h['sample_rate'],h['channels'],h['pcm_format'])!=(16000,1,'s16le'):raise ValueError('unsupported PCM')
                adapter.begin(gid,h['first_sample_index']);highest_generation=gid
                with state:
                    if active is not None:raise ValueError('generation already active')
                    active=gid;slots=4;ack=-1;last_sent=-1;target=None;outstanding.clear();state.notify_all()
                reply(dict(type='GenerationBegun',generation_id=gid,audio_credit_samples=32000))
            elif kind=='AudioChunk':
                c=AudioChunk(h['sample_rate'],h['channels'],h['pcm_format'],h['chunk_sequence'],h['first_sample_index'],h['sample_count'],h['generation_id'],h['final_chunk'],payload)
                # Fail fast on capacity: inbound control dispatch must not block behind PCM.
                with adapter.cv:
                    if adapter.pending_samples+c.sample_count>adapter.AUDIO_BOUND:raise ValueError('audio credit exhausted')
                    accepted=adapter.put(c)
                if accepted and c.final_chunk:
                    target=((adapter.next_sample-adapter.first_sample)*25+15999)//16000
                    if target==0:
                        adapter.finish(active);reply(dict(type='GenerationComplete',generation_id=active,consumed_frames=0));active=None;slots=0
                reply(dict(type='AudioAccepted',generation_id=c.generation_id,chunk_sequence=c.chunk_sequence,audio_credit_samples=adapter.AUDIO_BOUND-adapter.pending_samples,accepted=accepted))
            elif kind=='Credit':
                with state:
                    if h['generation_id']!=active:continue
                    latest=h['latest_consumed_sequence']
                    if latest!=ack+1 or latest>last_sent:raise ValueError('invalid video acknowledgment')
                    with adapter.cv:
                        adapter.committed.append(outstanding.pop(latest).copy())
                    ack=latest;slots+=1
                    if slots>4:raise ValueError('credit overflow')
                    if target is not None and ack+1==target:
                        adapter.finish(active);log('GenerationComplete',active,consumed_frames=target)
                        reply(dict(type='GenerationComplete',generation_id=active,consumed_frames=target));active=None;slots=0
                    state.notify_all()
            elif kind=='CancelGeneration':
                with state:
                    if active==h['generation_id']:
                        adapter.cancel(active);active=None;slots=0;outstanding.clear();state.notify_all()
                reply(dict(type='GenerationCancelled',generation_id=h['generation_id']))
            elif kind=='Health':
                if h['nonce']%60==0:log('WorkerHealth',active,vram_allocated_bytes=torch.cuda.memory_allocated(),vram_reserved_bytes=torch.cuda.memory_reserved(),audio_queue_ms=adapter.pending_samples/16,video_queue_ms=len(adapter.video)*40,last_completed_frame=last_sent)
                stalled=diag['inference_started_s'] is not None and time.monotonic()-diag['inference_started_s']>5
                reply(dict(type='Health',nonce=h['nonce'],ready=adapter.error is None and not stalled,active_generation_id=active,last_completed_frame=last_sent,audio_queue_ms=adapter.pending_samples/16,video_queue_ms=len(adapter.video)*40,error=adapter.error or ('INFERENCE_STALLED' if stalled else None),inference_active_since_monotonic_s=diag['inference_started_s']))
            else:raise ValueError('unknown message type')
    except Exception as e:log('TransportReceiverClosed',active,error_type=type(e).__name__,error=str(e))
    finally:
        stopped.set()
        with state:state.notify_all()
        try:adapter.close()
        except Exception as exc:
            log('UnrecoverableGPUThread',error_type=type(exc).__name__)
            os._exit(70) # no new connection may reuse a model with an unresolved GPU thread
        try:sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        th.join(20);sock.close();log('ConnectionCleaned',sender_stopped=not th.is_alive())
        if adapter.error:
            log('WorkerRestartRequired',error=adapter.error)
            os._exit(70)

while True:
    sock,_=listener.accept()
    try:handle(sock)
    except Exception as e:log('ConnectionRejected',error_type=type(e).__name__);sock.close()
