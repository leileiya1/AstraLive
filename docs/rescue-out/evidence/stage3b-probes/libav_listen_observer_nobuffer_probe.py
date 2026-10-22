import sys, av, time
url=sys.argv[1]; n=0; v=0
c=av.open(url, options={"listen":"1","rw_timeout":"5000000","probesize":"32","analyzeduration":"0","fflags":"nobuffer"}, timeout=10)
print(f"{time.time():.3f} opened streams={[s.type for s in c.streams]}", flush=True)
try:
    for pkt in c.demux():
        if pkt.size==0: continue
        if pkt.stream.type=="audio":
            n+=pkt.size//2; print(f"{time.time():.3f} audio_total={n}", flush=True)
        else:
            v+=1; print(f"{time.time():.3f} video={v}", flush=True)
except Exception as e: print(f"{time.time():.3f} end", type(e).__name__, e, flush=True)
