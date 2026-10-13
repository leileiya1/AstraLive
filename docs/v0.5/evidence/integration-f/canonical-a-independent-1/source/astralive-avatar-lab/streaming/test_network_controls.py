"""Actual private-link cancellation while GPU inference is in flight; no business Session."""
import fractions,json,pathlib,socket,threading,time,wave
import av
from wire import send,receive
ROOT=pathlib.Path(__file__).parent;OUT=ROOT/'network/controls';OUT.mkdir(parents=True,exist_ok=True)
TOKEN=(ROOT/'.private/token').read_text().strip();SOURCE=ROOT.parent/'results/rtx4090d-2026-10-08/inputs/audio/long_60s.wav'
# Check bad auth first: no credentials in evidence.
s=socket.create_connection(('127.0.0.1',17087),timeout=5);send(s,dict(type='Auth',protocol_version=1,token='invalid-experiment-token'))
try:receive(s);raise RuntimeError('bad authentication accepted')
except (EOFError,ConnectionResetError):pass
finally:s.close()
s=socket.create_connection(('127.0.0.1',17087),timeout=5);s.settimeout(15)
send(s,dict(type='Auth',protocol_version=1,token=TOKEN));ready,_=receive(s);epoch=ready['worker_epoch']
lock=threading.RLock();stop=threading.Event();startnew=threading.Event();active=1000;rows=[];errors=[];received={1000:0,1001:0};dropped=0;forced=False
f=(OUT/'events.jsonl').open('w',buffering=1)
def log(event,**kw):
    r=dict(event=event,monotonic_s=time.monotonic(),**kw);rows.append(r);f.write(json.dumps(r)+'\n')
def request(h,p=b''):
    with lock:send(s,h,p)
def begin(g):request(dict(type='BeginGeneration',generation_id=g,cache_id=ready['cache_id'],sample_rate=16000,channels=1,pcm_format='s16le',first_sample_index=0,output_fps=25))
def producer():
    try:
        for g in (1000,1001):
            if g==1001:startnew.wait(10)
            t=time.monotonic()
            with wave.open(str(SOURCE),'rb') as w:
                for seq in range(300):
                    pcm=w.readframes(320);time.sleep(max(0,t+(seq+1)*.02-time.monotonic()))
                    with lock:
                        if active!=g:break
                        send(s,dict(type='AudioChunk',generation_id=g,sample_rate=16000,channels=1,pcm_format='s16le',chunk_sequence=seq,first_sample_index=seq*320,sample_count=320,final_chunk=seq==299),pcm)
    except Exception as e:errors.append(repr(e));stop.set()
begin(1000);th=threading.Thread(target=producer,daemon=True);th.start();decoder=av.CodecContext.create('h264','r');decoder.thread_count=1;decoder.open();newfirst=None
record=(OUT/'new-generation.h264').open('wb')
try:
    until=time.monotonic()+30
    while time.monotonic()<until and not stop.is_set():
        h,p=receive(s)
        if h['worker_epoch']!=epoch:raise RuntimeError('epoch changed')
        if h['type']=='AudioAccepted' and h['generation_id']==1000 and h['chunk_sequence']==143 and not forced:
            # The completing 0.96-second block is already on the GPU; observed via Worker log later.
            with lock:
                forced=True;active=1001;log('FORCE',old_generation=1000,new_generation=1001)
                send(s,dict(type='CancelGeneration',generation_id=1000));begin(1001)
                decoder=av.CodecContext.create('h264','r');decoder.thread_count=1;decoder.open();startnew.set()
        elif h['type']=='VideoPacket':
            g=h['generation_id']
            if g!=active:
                dropped+=1;log('StaleTransportPacketRejected',generation_id=g,frame_sequence=h['frame_sequence']);continue
            if h['frame_sequence']!=received[g] or h['pts_us']!=received[g]*40000:raise RuntimeError('new generation contaminated/sequence gap')
            if received[g]==0 and not h['keyframe_flag']:raise RuntimeError('first frame not IDR')
            packet=av.Packet(p);packet.pts=packet.dts=h['frame_sequence'];packet.time_base=fractions.Fraction(1,25)
            frames=decoder.decode(packet)
            if len(frames)!=1 or frames[0].pts!=h['frame_sequence']:raise RuntimeError('decoder continuity failure')
            if g==1001:
                record.write(p)
                if newfirst is None:newfirst=time.monotonic();log('NewGenerationFirstFrame',generation_id=g)
            received[g]+=1;log('PublishedFrame',generation_id=g,frame_sequence=h['frame_sequence'])
            request(dict(type='Credit',generation_id=g,latest_consumed_sequence=h['frame_sequence']))
        elif h['type']=='GenerationComplete' and h['generation_id']==1001:break
    if received[1001]!=150:raise RuntimeError('new task did not complete')
    log('NormalCompletion',generation_id=1001)
except Exception as e:errors.append(repr(e))
finally:
    stop.set();th.join(3);record.close();s.close();f.close()
    force=next((r['monotonic_s'] for r in rows if r['event']=='FORCE'),None)
    leaks=[r for r in rows if r['event']=='PublishedFrame' and r['generation_id']==1000 and force and r['monotonic_s']>=force]
    result=dict(status='CONTROL_MECHANICAL_PASS' if not errors and not leaks and forced else 'FAILED',bad_auth_rejected=True,worker_epoch=epoch,received_frames=received,stale_inflight_packets_rejected=dropped,old_frames_published_after_force=len(leaks),force_to_new_first_frame_s=newfirst-force if newfirst and force else None,errors=errors,producer_stopped=not th.is_alive(),scope='unpaced private decoder control probe; not live A/V or browser')
    (OUT/'summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
