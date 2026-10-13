"""school-linux isolated network consumer, outside the live AstraLive Runtime."""
import fractions,json,os,pathlib,queue,socket,sys,threading,time,wave
import av
from wire import send,receive
ROOT=pathlib.Path(__file__).parent
RUN=ROOT/'network'/os.environ.get('NETWORK_RUN','short')
RUN.mkdir(parents=True,exist_ok=True)
DURATION=int(os.environ.get('NETWORK_DURATION','10'));GEN=int(os.environ.get('NETWORK_GENERATION','100'))
TOKEN=(ROOT/'.private/token').read_text().strip()
SOURCE=pathlib.Path(os.environ.get('NETWORK_SOURCE',str(ROOT.parent/'inputs/chinese-long.wav')))
# Orchestrator explicitly sets the exact validated 60-second mono PCM input path.
sock=socket.create_connection(('127.0.0.1',17087),timeout=10);sock.settimeout(15);sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
sendlock=threading.Lock();cv=threading.Condition();events=[];f=(RUN/'events.jsonl').open('w',buffering=1)
loglock=threading.Lock();stop=threading.Event();complete=threading.Event();begun=threading.Event();video=queue.Queue(maxsize=4)
credit=0;pending={};errors=[];first_pcm=None;received=0;decoded=0;consumed=0;rtts=[];encodes=[];decode_times=[];health={};last_packet_time=time.monotonic()
summary=dict(status='RUNNING',scope='school-linux private Worker H264 decode/paced sink; no WebRTC/RTMP/browser',generation_id=GEN,duration_s=DURATION,queue_bound_frames=4,declared_playout_buffer_ms=120)
def save(): (RUN/'summary.json').write_text(json.dumps(summary,indent=2))
def log(event,**data):
    with loglock:
        row=dict(event=event,monotonic_s=time.monotonic(),generation_id=GEN,**data);events.append(row);f.write(json.dumps(row)+'\n')
def request(header,payload=b''):
    with sendlock:send(sock,header,payload)
request(dict(type='Auth',token=TOKEN,protocol_version=1));ready,_=receive(sock)
if ready.get('type')!='GPU_WORKER_READY':raise RuntimeError('worker is not ready')
EPOCH=ready['worker_epoch'];summary.update(worker_epoch=EPOCH,worker_ready=ready);log('GPU_WORKER_READY_received');save()
# Explicitly check authentication rejects a second unauthenticated stream after this test, not here (one-client worker).

def receiver():
    global credit,received,last_packet_time
    try:
        while not stop.is_set():
            h,p=receive(sock);last_packet_time=time.monotonic()
            if h['worker_epoch']!=EPOCH:raise RuntimeError('worker epoch changed')
            kind=h['type']
            if kind=='GenerationBegun':
                with cv:credit=h['audio_credit_samples'];begun.set();cv.notify_all()
            elif kind=='AudioAccepted':
                with cv:
                    pending.pop(h['chunk_sequence'],None)
                    credit=max(0,h['audio_credit_samples']-sum(pending.values()));cv.notify_all()
            elif kind=='VideoPacket':
                if h['generation_id']!=GEN:log('StalePacketRejected',packet_generation=h['generation_id']);continue
                if h['frame_sequence']!=received or h['pts_us']!=received*40000:raise RuntimeError('PTS/sequence mismatch')
                if received==0:
                    if not h['keyframe_flag']:raise RuntimeError('new generation lacks keyframe')
                    log('FirstFrameReceived',since_first_pcm_s=time.monotonic()-first_pcm)
                received+=1;encodes.append(h['encode_latency_ms'])
                log('VideoPacketReceived',frame_sequence=h['frame_sequence'],pts_us=h['pts_us'],bytes=len(p),audio_queue_ms=h['audio_queue_ms'],video_queue_ms=h['video_queue_ms'])
                video.put((h,p),timeout=3)
            elif kind=='GenerationComplete':log('GenerationComplete',frames=h['consumed_frames']);complete.set()
            elif kind=='Health':
                sent=health.pop(h['nonce'],None)
                if sent is not None:rtts.append((time.monotonic()-sent)*1000)
                log('Health',ready=h['ready'],audio_queue_ms=h['audio_queue_ms'],video_queue_ms=h['video_queue_ms'],network_rtt_ms=rtts[-1] if rtts else None)
                if not h['ready']:raise RuntimeError('worker inference failure')
            elif kind in ('AvatarPrepared','GenerationCancelled'):log(kind)
    except Exception as e:
        if not stop.is_set():errors.append(repr(e));log('ReceiverError',error=repr(e));stop.set()
        with cv:cv.notify_all()

def producer():
    global credit,first_pcm
    try:
        with wave.open(str(SOURCE),'rb') as w,wave.open(str(RUN/'received-input.wav'),'wb') as capture:
            assert (w.getframerate(),w.getnchannels(),w.getsampwidth())==(16000,1,2)
            capture.setnchannels(1);capture.setsampwidth(2);capture.setframerate(16000)
            begun.wait(10);start=time.monotonic();index=seq=0
            while index<DURATION*16000 and not stop.is_set():
                count=min(320,DURATION*16000-index);pcm=w.readframes(count)
                if len(pcm)<count*2:
                    w.rewind();pcm+=w.readframes(count-len(pcm)//2)
                time.sleep(max(0,start+(index+count)/16000-time.monotonic()))
                with cv:
                    while credit<count and not stop.is_set():cv.wait(.05)
                    if stop.is_set():break
                    credit-=count;pending[seq]=count
                capture.writeframesraw(pcm)
                if first_pcm is None:first_pcm=time.monotonic();log('FirstPCMProducerArrival')
                request(dict(type='AudioChunk',generation_id=GEN,sample_rate=16000,channels=1,pcm_format='s16le',chunk_sequence=seq,first_sample_index=index,sample_count=count,final_chunk=index+count==DURATION*16000),pcm)
                log('AudioSent',chunk_sequence=seq,first_sample_index=index,sample_count=count)
                index+=count;seq+=1
    except Exception as e:errors.append(repr(e));stop.set()

def heartbeat():
    nonce=0
    while not stop.wait(.5):
        try:
            nonce+=1;health[nonce]=time.monotonic();request(dict(type='Health',nonce=nonce))
            if time.monotonic()-last_packet_time>5:raise RuntimeError('worker health timeout')
        except Exception as e:errors.append(repr(e));stop.set();break

rt=threading.Thread(target=receiver,daemon=True);rt.start()
request(dict(type='PrepareAvatar',avatar_id='official-girl',input_asset_sha256=ready['input_asset_sha256']))
request(dict(type='BeginGeneration',generation_id=GEN,cache_id=ready['cache_id'],sample_rate=16000,channels=1,pcm_format='s16le',first_sample_index=0,output_fps=25))
pt=threading.Thread(target=producer,daemon=True);ht=threading.Thread(target=heartbeat,daemon=True);pt.start();ht.start()
decoder=av.CodecContext.create('h264','r');decoder.thread_count=1;decoder.open()
first_playout=None;max_lag=0;started=time.monotonic();bytecount=0
try:
    with (RUN/'received.h264').open('wb') as recording:
        while consumed<DURATION*25 and not stop.is_set():
            try:h,p=video.get(timeout=2)
            except queue.Empty:
                if errors:raise RuntimeError(errors)
                if time.monotonic()-last_packet_time>5:raise RuntimeError('no worker video progress')
                continue
            recording.write(p);bytecount+=len(p)
            packet=av.Packet(p);packet.pts=packet.dts=h['frame_sequence'];packet.time_base=fractions.Fraction(1,25)
            t=time.monotonic();frames=decoder.decode(packet);decode_times.append((time.monotonic()-t)*1000)
            if len(frames)!=1:raise RuntimeError('H264 decoder buffered/lost frame')
            if frames[0].pts!=h['frame_sequence']:raise RuntimeError('decoded PTS mismatch')
            decoded+=1
            if first_playout is None:
                log('FirstFrameDecoded',since_first_pcm_s=time.monotonic()-first_pcm)
                first_playout=time.monotonic()+.120
            target=first_playout+consumed/25
            time.sleep(max(0,target-time.monotonic()))
            lag=max(0,time.monotonic()-target);max_lag=max(max_lag,lag)
            if consumed==0:log('FirstPacedConsumerTick',since_first_pcm_s=time.monotonic()-first_pcm)
            log('FrameConsumed',frame_sequence=consumed,pts_us=h['pts_us'],lag_ms=lag*1000,consumer_queue_ms=video.qsize()*40)
            consumed+=1;request(dict(type='Credit',generation_id=GEN,latest_consumed_sequence=h['frame_sequence']))
            if consumed%750==0:
                summary.update(received_frames=received,decoded_frames=decoded,consumed_frames=consumed,maximum_pacing_lag_ms=max_lag*1000,wall_seconds=time.monotonic()-started);save();print('NETWORK_CHECKPOINT',consumed,flush=True)
    if not complete.wait(5):raise RuntimeError('missing normal completion acknowledgment')
    if errors:raise RuntimeError(errors)
    summary['status']='NETWORK_MECHANICAL_PASS' if max_lag<.040 else 'LATENCY_NOT_PASS'
except Exception as e:summary['status']='FAILED';summary['error']=repr(e)
finally:
    stop.set()
    with cv:cv.notify_all()
    try:sock.shutdown(socket.SHUT_RDWR)
    except OSError:pass
    sock.close();pt.join(5);rt.join(5);ht.join(5)
    def percentile(data,p):
        if not data:return None
        data=sorted(data);return data[min(len(data)-1,int((len(data)-1)*p))]
    rows=events
    arrival=next((e['monotonic_s'] for e in rows if e['event']=='FirstPCMProducerArrival'),None)
    summary.update(received_frames=received,decoded_frames=decoded,consumed_frames=consumed,maximum_pacing_lag_ms=max_lag*1000,wall_seconds=time.monotonic()-started,encoded_bytes=bytecount,encoded_mbit_per_media_second=bytecount*8/max(consumed/25,1)/1e6,encode_latency_ms_p95=percentile(encodes,.95),decode_latency_ms_p95=percentile(decode_times,.95),network_rtt_ms_p95=percentile(rtts,.95),network_rtt_samples=len(rtts),errors=errors,threads_stopped=not any(t.is_alive() for t in [pt,rt,ht]),first_pcm_to_stage_s={k:next((e['monotonic_s']-arrival for e in rows if e['event']==k),None) if arrival else None for k in ['FirstFrameReceived','FirstFrameDecoded','FirstPacedConsumerTick']})
    save();print(json.dumps(summary),flush=True);f.close()
