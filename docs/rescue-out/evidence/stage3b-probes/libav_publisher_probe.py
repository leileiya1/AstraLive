import sys, time, av, numpy as np
from fractions import Fraction
url=sys.argv[1]
out=av.open(url,"w",format="flv",options={"flvflags":"no_duration_filesize","flush_packets":"1","max_interleave_delta":"1"},timeout=(2,2))
vs=out.add_stream("libx264",rate=25); vs.width=vs.height=64; vs.pix_fmt="yuv420p"; vs.time_base=vs.codec_context.time_base=Fraction(1,1000000)
vs.options={"preset":"ultrafast","tune":"zerolatency","bf":"0","g":"25"}
aus=out.add_stream("pcm_s16le",rate=16000); aus.layout="mono"; aus.time_base=Fraction(1,16000)
out.start_encoding(); sent=[]
for i in range(25):
    a=(np.sin(np.arange(640)/7+i)*8000).astype("<i2"); sent.append(a)
    fr=av.AudioFrame.from_ndarray(a.reshape(1,-1),format="s16",layout="mono"); fr.sample_rate=16000; fr.pts=i*640; fr.time_base=Fraction(1,16000)
    for p in aus.encode(fr): out.mux(p)
    vf=av.VideoFrame.from_ndarray(np.zeros((64,64,3),np.uint8),format="rgb24"); vf.pts=i*40000; vf.time_base=Fraction(1,1000000)
    for p in vs.encode(vf): out.mux(p)
    time.sleep(0.04)
print(f"{time.time():.3f} publisher wrote last packet; holding connection", flush=True); time.sleep(2.5); print(f"{time.time():.3f} publisher exit", flush=True)
