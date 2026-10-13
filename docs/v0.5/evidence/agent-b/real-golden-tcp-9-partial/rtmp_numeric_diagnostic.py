#!/usr/bin/env python3
"""Offline numerical diagnosis only. Not a replacement formal AV acceptance."""
import importlib.util
import json
from pathlib import Path
import numpy as np

ROOT = Path('/private/tmp/astralive-f-real-golden-pilot-tcp-9/media')
OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('oracle', '/Users/sapiece/innovationProject/AstraLive-agent-f/integration/v0.5/observer_audit.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
observed = oracle.audio(ROOT/'rtmp.flv')
index = json.loads((ROOT/'staged-observer/refs.json').read_text())
markers = oracle.decode_video(ROOT/'rtmp.flv')
first = {}
for row in markers['markers']:
    first.setdefault(row['ordinal'], row['seconds'])
rows = []
for entry in index:
    expected = first[entry['ordinal']]
    reference = oracle.audio(ROOT/'staged-observer'/entry['sourceWav'])[:24000]
    ref = reference-reference.mean()
    norm = np.linalg.norm(ref)
    lo, hi = max(0,int((expected-10)*8000)), min(len(observed),int((expected+10)*8000)+len(ref))
    target = observed[lo:hi]
    size = 1 << (len(target)+len(ref)-2).bit_length()
    numerator = np.fft.irfft(np.fft.rfft(target,size)*np.fft.rfft(ref[::-1],size),size)[len(ref)-1:len(target)]
    # Wider accumulation and an explicit signal floor reject silent windows.
    cumulative = np.r_[np.longdouble(0), np.cumsum(target.astype(np.longdouble)**2)]
    energy = cumulative[len(ref):]-cumulative[:-len(ref)]
    valid = energy > len(ref)*1e-8  # explicitly diagnostic window RMS > 1e-4
    scores = np.full(len(energy), -np.inf)
    scores[valid] = numerator[valid]/(norm*np.sqrt(energy[valid]))
    invalid = np.isfinite(scores) & (np.abs(scores)>1.000001)
    scores[invalid] = -np.inf
    best = int(np.argmax(scores))
    competitors = scores.copy()
    competitors[max(0,best-2000):min(len(scores),best+2001)] = -np.inf
    second = int(np.argmax(competitors))
    def direct(position):
        window = target[position:position+len(ref)]
        return float(np.dot(window,ref)/(np.linalg.norm(window)*norm))
    score, competing = direct(best), direct(second)
    status = 'UNRESOLVED' if score<.65 else 'AMBIGUOUS' if competing>=score-.05 else 'MATCHED_DIAGNOSTIC_ONLY'
    rows.append({'ordinal':entry['ordinal'],'status':status,'videoFirstSeconds':expected,
        'referenceStartSeconds':(lo+best)/8000,'directCorrelation':score,
        'competingDirectCorrelation':competing,'audioMinusVideoMs':((lo+best)/8000-expected)*1000,
        'excludedLowEnergyWindows':int((~valid).sum()),'invalidFiniteCorrelationWindows':int(invalid.sum()),
        'sampleRate':8000,'referencePrefixSamples':len(ref)})
report = {'scope':'Numerical diagnostic on actual RTMP waveform; not approved formal oracle, audience sound or whole-run PASS',
    'clockDomain':'RTMP recording PTS only','rawObserverAudit':'INVALID_NORMALIZED_CORRELATION_ALL_SIX_ROWS',
    'method':'longdouble rolling energy, diagnostic RMS floor 1e-4, direct dot-product verification of best and competitor',
    'rows':rows,'wholeRunStatus':'FAIL','formalGolden1':'NOT_FORMAL'}
(OUT/'rtmp-numeric-diagnostic.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
