import asyncio, subprocess, sys, socket, time, threading, numpy as np, av
from fractions import Fraction
from output_guardian.v2.rtmp import Publisher, avc_config, avcc
from runtime.app.receiver1.rtmp_observer import RTMPObserver
S=sys.argv[1]
def fp():
    s=socket.socket(); s.bind(("127.0.0.1",0)); p=s.getsockname()[1]; s.close(); return p
def publish(url, sent):
    v=av.CodecContext.create("libx264","w"); v.width=v.height=64; v.pix_fmt="yuv420p"; v.time_base=Fraction(1,1000000); v.framerate=25
    v.flags|=av.codec.context.Flags.global_header; v.options={"preset":"ultrafast","tune":"zerolatency","bf":"0","g":"25"}; v.open()
    p=Publisher(url,1.0); p.open(dict(duration=0.0,width=64.0,height=64.0,videocodecid=7.0,framerate=25.0,audiocodecid=3.0,audiosamplerate=16000.0,audiosamplesize=16.0,stereo=False))
    first=True
    for i in range(150):
        a=(np.sin(np.arange(640)/7+i)*8000).astype("<i2").tobytes(); sent.append(a)
        p.audio((i*640*1000+8000)//16000, a)
        f=av.VideoFrame.from_ndarray(np.full((64,64,3),i%256,np.uint8),format="rgb24").reformat(format="yuv420p"); f.pts=i*40000; f.time_base=Fraction(1,1000000)
        pk=v.encode(f)[0]
        if first: p.video(i*40,True,0,avc_config(v.extradata)); first=False
        p.video(i*40,pk.is_keyframe,1,avcc(bytes(pk)))
        time.sleep(0.04)
    time.sleep(1.0); p.sock.close()
def read(url, out):
    for _ in range(400):
        try: c=av.open(url,options={"rw_timeout":"3000000"},timeout=3); break
        except Exception: time.sleep(0.02)
    try:
        for pk in c.demux():
            for fr in pk.decode():
                if isinstance(fr, av.AudioFrame): out.append(fr.to_ndarray().astype("<i2").tobytes())
    except Exception as e: out.append(type(e).__name__)
async def main():
    mp=fp(); open(f"{S}/m2.yml","w").write(f"logLevel: info\nrtmpAddress: 127.0.0.1:{mp}\napi: no\nrtsp: no\nhls: no\nwebrtc: no\nsrt: no\nplayback: no\nmoq: no\npaths:\n  all_others:\n")
    m=subprocess.Popen(["/tmp/astralive-guardian-tools/mediamtx",f"{S}/m2.yml"],stdout=open(f"{S}/m2.log","w"),stderr=subprocess.STDOUT); await asyncio.sleep(0.5)
    o=RTMPObserver(sink_id="s",upstream=("127.0.0.1",mp),audio_origin=0,sample_rate=16000,guardian=None); tp=await o.listen()
    sent=[]; got=[]
    rt=threading.Thread(target=read,args=(f"rtmp://127.0.0.1:{mp}/live/room",got),daemon=True); rt.start()
    await asyncio.to_thread(publish, f"rtmp://127.0.0.1:{tp}/live/room", sent)
    await asyncio.to_thread(rt.join, 5)
    whole=b"".join(sent); tail=got[-1] if got and isinstance(got[-1],str) else None
    g=b"".join(x for x in got if isinstance(x,bytes))
    print("tap bit-exact:", bytes(o.ledger.pcm)==whole, "frames", len(o.ledger.video), "fault", o.ledger.fault)
    at=whole.find(g); print("mediamtx reader: got", len(g)//2, "samples; contiguous slice at sample", at//2 if at>=0 else None, "missing tail samples", (len(whole)-at-len(g))//2 if at>=0 else None, "end", tail)
    m.terminate()
asyncio.run(main())
