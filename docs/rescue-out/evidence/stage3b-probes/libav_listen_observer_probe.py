import sys, av, time
url=sys.argv[1]; n=0; t0=None
c=av.open(url, options={"listen":"1","rw_timeout":"5000000"}, timeout=10)
try:
    for pkt in c.demux():
        for f in pkt.decode():
            if isinstance(f, av.AudioFrame):
                n+=f.samples
                print(f"{time.time():.3f} audio_total={n}", flush=True)
except Exception as e: print("end", type(e).__name__, flush=True)
