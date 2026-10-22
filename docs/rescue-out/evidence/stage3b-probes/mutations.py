import subprocess, sys, shutil
R="runtime/app/receiver1/rtmp_observer.py"; G="output_guardian/v2/rtmp.py"
M=[
 ("M1 child drops last sample of each audio item", G, "publisher.audio(ts, item.payload)", "publisher.audio(ts, item.payload[:-2])"),
 ("M2 observer skips audio hash check", R, "if hashlib.sha256(audio).hexdigest() != request[\"audioHash\"]:", "if False:"),
 ("M3 observer skips evidence peer pin", R, "if pid != self.guardian.pid or identity(pid) != self.guardian:", "if False:"),
 ("M4 ledger skips audio continuity", R, "if timestamp != (samples * 1000 + self.rate // 2) // self.rate:", "if False:"),
 ("M5 prove does not wait for the tail", R, "            if len(ledger.pcm) >= hi and ledger.video and ledger.video[-1][0] >= wanted[-1]:\n                break", "            break"),
 ("M6 observer skips video PTS check", R, "if [ledger.video[i][0] for i in frames] != wanted:", "if False:"),
 ("M7a child ignores revocable edge before audio write", G, "                edge.check(item.lineage)  # revocable edge right before the pipe write\n                publisher.audio", "                publisher.audio"),
 ("M7b child ignores revocable edge before video write", G, "                edge.check(item.lineage)  # revocable edge right before the pipe write\n                if not configured", "                if not configured"),
]
for name, f, a, b in M:
    src=open(f).read(); assert src.count(a)>=1, name
    shutil.copy(f, f+".bak"); open(f,"w").write(src.replace(a,b,1))
    try:
        r=subprocess.run([sys.executable,"-m","pytest","-q","-x","output_guardian/tests/v2/test_rtmp_observer.py","output_guardian/tests/v2/test_rtmp_sink.py"],capture_output=True,text=True,timeout=300)
        print(name, "->", "DETECTED" if r.returncode else "SURVIVED", r.stdout.strip().splitlines()[-1])
    finally:
        shutil.move(f+".bak", f)
