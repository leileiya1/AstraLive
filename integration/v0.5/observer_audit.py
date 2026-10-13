#!/usr/bin/env python3
"""Offline true speech/video reference matching; no pulse or audible guarantee."""
import argparse
import json
from pathlib import Path
import subprocess

import av
import numpy as np


def barcode(rgb):
    if rgb.shape[0]<8 or rgb.shape[1]<192:
        return None
    value=0
    confidence=[]
    for bit in range(24):
        pixel=rgb[2:6,bit*8+2:bit*8+6,:3].mean(axis=(0,1))
        delta=float(pixel[0]-pixel[1])
        confidence.append(abs(delta))
        value=(value<<1)|int(delta>0)
    if min(confidence)<50:
        return None
    ordinal=value>>12;sequence=(value>>4)&255;crc=value&15
    expected=0
    core=value>>4
    for _ in range(5):expected^=core&15;core>>=4
    if ordinal<1 or sequence>199 or crc!=expected:
        return None
    return ordinal,sequence


def decode_video(path):
    rows=[];previous=None;regressions=[]
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            if frame.pts is None:continue
            pts=float(frame.pts*frame.time_base)
            if previous is not None and pts<previous:regressions.append({"previous":previous,"current":pts})
            previous=pts
            marker=barcode(frame.to_ndarray(format="rgb24"))
            if marker is not None:
                rows.append({"seconds":pts,"ordinal":marker[0],"sequence":marker[1]})
    return {"markers":rows,"ptsRegressions":regressions}


def audio(path,rate=8000):
    # Fixed decoded domain. This is recorded software output, not speakers.
    proc=subprocess.run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-i",str(path),
                         "-vn","-ac","1","-ar",str(rate),"-f","f32le","pipe:1"],capture_output=True,check=True)
    return np.frombuffer(proc.stdout,dtype="<f4").astype(np.float64)


def match(reference,observed,expected_seconds,rate=8000,window_seconds=10):
    # Locate a real reference prefix in the marker's bounded recording window.
    # Never silently fall back to any unrelated energy/onset or synthetic pulse.
    ref=reference[:min(len(reference),3*rate)]
    if len(ref)<rate//5 or np.sqrt(np.mean(ref*ref))<.001:
        return {"status":"MISSING_OR_SILENT_REFERENCE"}
    lo=max(0,int((expected_seconds-window_seconds)*rate))
    hi=min(len(observed),int((expected_seconds+window_seconds)*rate)+len(ref))
    target=observed[lo:hi]
    if len(target)<len(ref):return {"status":"MISSING_RECORDING_WINDOW"}
    ref=ref-ref.mean()
    norm=np.linalg.norm(ref)
    if norm==0:return {"status":"DEGENERATE_REFERENCE"}
    size=1<<(len(target)+len(ref)-2).bit_length()
    convolution=np.fft.irfft(np.fft.rfft(target,size)*np.fft.rfft(ref[::-1],size),size)
    numerator=convolution[len(ref)-1:len(target)]
    # Long silence after speech makes cumulative subtraction lose tiny window
    # energies. longdouble is only double on some platforms; reject low energy
    # and independently recompute candidates, never invent epsilon energy.
    target_extended=target.astype(np.longdouble)
    cumulative=np.r_[np.longdouble(0),np.cumsum(target_extended*target_extended,dtype=np.longdouble)]
    energy=cumulative[len(ref):]-cumulative[:-len(ref)]
    valid=energy>=len(ref)*.001**2
    if not np.any(valid):return {"status":"MISSING_OR_SILENT_RECORDING"}
    correlation=np.full(len(numerator),-np.inf)
    correlation[valid]=numerator[valid]/(norm*np.sqrt(energy[valid]))
    best=int(np.argmax(correlation))
    ref_extended=ref.astype(np.longdouble)
    ref_energy=np.sum(ref_extended*ref_extended,dtype=np.longdouble)
    def exact_score(index):
        window=target_extended[index:index+len(ref)]
        return float(np.sum(window*ref_extended,dtype=np.longdouble)/
                     np.sqrt(np.sum(window*window,dtype=np.longdouble)*ref_energy))
    score=exact_score(best)
    competitors=correlation.copy()
    competitors[max(0,best-rate//4):min(len(competitors),best+rate//4+1)]=-np.inf
    other=int(np.argmax(competitors))
    has_competitor=np.isfinite(competitors[other])
    second=exact_score(other) if has_competitor else -1
    if (not np.isfinite(score) or not np.isfinite(correlation[best]) or not np.isfinite(second)
        or abs(score)>1+1e-9 or abs(second)>1+1e-9
        or abs(score-float(correlation[best]))>1e-5
        or (has_competitor and abs(second-float(competitors[other]))>1e-5)):
        return {"status":"NUMERICAL_UNCERTAINTY"}
    status="UNRESOLVED" if score<.65 else "AMBIGUOUS" if second>=score-.05 else "MATCHED"
    return {"status":status, "correlation":round(score,6),"competingCorrelation":round(second,6),
            "referenceStartSeconds":(lo+best)/rate,"windowStartSeconds":lo/rate,"referenceSamples":len(ref),"sampleRate":rate}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--recording",type=Path,required=True)
    p.add_argument("--references",type=Path,required=True,help="JSON rows: ordinal and real sourceWav relative to this file")
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    markers=decode_video(a.recording);observed=audio(a.recording)
    first={}
    for row in markers["markers"]:first.setdefault(row["ordinal"],row["seconds"])
    rows=[]
    for item in json.loads(a.references.read_text()):
        ordinal=item["ordinal"]
        if ordinal not in first:
            rows.append({"ordinal":ordinal,"status":"VIDEO_NOT_OBSERVED"});continue
        source=(a.references.parent/item["sourceWav"]).resolve()
        found=match(audio(source),observed,first[ordinal])
        row={"ordinal":ordinal,"videoFirstSeconds":first[ordinal],**found}
        if found["status"]=="MATCHED":row["audioMinusVideoMs"]=(found["referenceStartSeconds"]-first[ordinal])*1000
        rows.append(row)
    report={"scope":"same-recording decoded actual speech reference and post-GPU observer barcode; no physical audience/lip-sync/SLA claim",
            "clockDomain":"each recording PTS, separately; do not subtract browser/encoder/remote clocks",
            "recording":str(a.recording),"ptsRegressions":markers["ptsRegressions"],"rows":rows,
            "matched":sum(row.get("status")=="MATCHED" for row in rows),"requested":len(rows)}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"matched":report["matched"],"requested":len(rows),"ptsRegressions":len(report["ptsRegressions"])}))
    return 0 if not markers["ptsRegressions"] and all(row.get("status")=="MATCHED" for row in rows) else 1


if __name__=="__main__":raise SystemExit(main())
