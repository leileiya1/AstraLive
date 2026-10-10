"""Independent, offline audit of retained Agent B samples; no Provider/GPU calls.

Recompute empirical nearest-rank percentiles and conservative per-sample clock
bounds. Do not manufacture the request/response clock brackets absent from JSON.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def stats(values):
    values = sorted(values)
    if not values:
        return dict(samples=0, p50Ms=None, p95Ms=None, maxMs=None)
    return dict(samples=len(values), meanMs=sum(values)/len(values),
                p50Ms=values[math.ceil(len(values)*.5)-1],
                p95Ms=values[math.ceil(len(values)*.95)-1], maxMs=values[-1])


def group(samples, key, uncertainty):
    values = [s[key] for s in samples]
    lows = [s[key]-s[uncertainty] for s in samples]
    highs = [s[key]+s[uncertainty] for s in samples]
    estimate, lower, upper = stats(values), stats(lows), stats(highs)
    result = dict(estimate=estimate, lower=lower, upper=upper)
    for percentile, target in [('p50Ms', 3000), ('p95Ms', 5000)]:
        result[percentile+'Gate'] = ('FAIL' if lower[percentile] > target else
                                    'PASS_WITH_RETAINED_BOUND' if upper[percentile] <= target else
                                    'BLOCKED_CLOCK_BOUND')
    return result


def audit(evidence):
    names = ['agent-b-real-browser', 'agent-b-real-summary', 'agent-b-real-prior-trials',
             'agent-b-real-faults', 'agent-b-real-headless']
    docs = {name: json.loads((evidence/(name+'.json')).read_text()) for name in names}
    normal = docs[names[0]]
    samples = normal['samples']
    assert len(samples) == len(normal['attempts']) == 20
    assert {s['index'] for s in samples} == {a['index'] for a in normal['attempts']}
    assert len({s['traceId'] for s in samples}) == len(samples)
    assert len({s['utteranceId'] for s in samples}) == len(samples)
    for sample in samples:
        assert sample['terminal'] == 'utterance.completed'
        assert all(math.isfinite(value) and value >= 0 for value in sample['runtimePoints'].values())
        stages = ['runtime_utterance_accepted', 'first_speakable_segment', 'tts_first_pcm',
                  'avatar_first_generated_frame', 'media_first_video', 'utterance_completed']
        points = sample['runtimePoints']
        assert all(points[a] <= points[b] for a, b in zip(stages, stages[1:]))
        media = sample['media']
        for video in [sample['firstCorrelatedVideo'], sample['rtmpFirstVideo']]:
            assert video['marker'] == media['speechMarker']
            assert video['generation'] == media['generationId']
        assert abs(media['firstVideoPTSUS']/1000-media['speechOriginSample']/16) < 1e-6
        assert abs(sample['receiveToCorrelatedAVLowerMs']-(sample['receiveToCorrelatedAVMs']-sample['receiptAlignmentUncertaintyMs'])) < 1e-6
        assert abs(sample['receiveToCorrelatedAVUpperMs']-(sample['receiveToCorrelatedAVMs']+sample['receiptAlignmentUncertaintyMs'])) < 1e-6
    paths = {'all': samples,
             'fast': [s for s in samples if 'llm_first_token' not in s['runtimePoints']],
             'llm': [s for s in samples if 'llm_first_token' in s['runtimePoints']]}
    results = {}
    for name, subset in paths.items():
        results[name] = dict(
            indices=[s['index'] for s in subset],
            chrome=group(subset, 'receiveToCorrelatedAVMs', 'receiptAlignmentUncertaintyMs'),
            rtmp=group(subset, 'receiveToRTMPAVMs', 'rtmpAlignmentUncertaintyMs'),
            decomposition={key: stats([s[key] for s in subset]) for key in
                           ['selectionMs', 'selectedToSpeakableMs', 'speakableToPCMMS', 'pcmToGPUFrameMS', 'gpuToBrowserVideoMs']})
    for field in ['p50Ms', 'p95Ms', 'maxMs']:
        assert abs(results['all']['chrome']['estimate'][field]-normal['receiveToCorrelatedAV'][field]) < 1e-6
    return dict(
        sourceSHA256={name+'.json': hashlib.sha256((evidence/(name+'.json')).read_bytes()).hexdigest() for name in names},
        algorithm='empirical nearest rank: sorted[ceil(n*p)-1]; bounds are quantiles of per-sample lower/upper values',
        normalAttempts=normal['attempts'], groups=results,
        priorTrials=[{k: trial.get(k) for k in ['trial', 'completedSamples', 'requestedSamples', 'cause', 'errors', 'failedSelectionExpectations', 'setupFailures']} for trial in docs[names[2]]],
        evidenceLimits=[
            'Request/response start/end brackets and raw monotonic receipt origins are not retained in committed JSON; offset half-widths can be checked for consistency but not independently recreated.',
            'Audio association uses first nonzero analyser/decoded PCM after input, without an audio trace marker; previous-speech/random-arrival trials require stronger audio correlation.',
            'Chrome analyser and expectedDisplayTime are browser observations, not physical speaker or actual display hardware timestamps.',
            'RTMP is a local decoded receiver, not a live-platform audience.',
            'Only six LLM samples. These cannot establish the sustained LLM-path distribution; the observed P50/P95 fail even optimistic retained clock bounds.',
            'Prior trials and fault phases remain separately visible and are not silently pooled with the final patched normal run.'],
        strictEndToEndGate='BLOCKED', llmObservedGoal='FAIL')


def audit_current(path):
    normal = json.loads(path.read_text())
    samples = normal['samples']
    assert len(samples) == len(normal['attempts'])
    assert len({s['utteranceId'] for s in samples}) == len(samples)
    assert len({s['traceId'] for s in samples}) == len(samples)
    for sample in samples:
        assert sample['terminal'] == 'utterance.completed'
        points, media = sample['runtimePoints'], sample['media']
        stages = ['runtime_utterance_accepted', 'first_speakable_segment', 'tts_first_pcm', 'media_first_video', 'utterance_completed']
        assert all(math.isfinite(v) and v >= 0 for v in points.values())
        assert all(points[a] <= points[b] for a, b in zip(stages, stages[1:]))
        assert abs(media['firstVideoPTSUS']/1000-media['speechOriginSample']/16) < 1e-6
        clock = sample['clockExchanges']['backend']
        receipt = (clock['start']+clock['end'])/2-clock['receiptAgeMs']
        assert abs(sample['receiptAlignmentUncertaintyMs']-(clock['end']-clock['start'])/2) < 1e-6
        if sample.get('receiveToCorrelatedAVMs') is not None:
            audio, video = sample['firstCorrelatedAudio'], sample['firstCorrelatedVideo']
            assert video['marker'] == sample['media']['speechMarker']
            assert video['generation'] == sample['media']['generationId']
            assert abs(sample['receiveToCorrelatedAVMs']-(max(audio['at'],video['displayAt'])-receipt)) < 1e-6
        if sample.get('receiveToRTMPAVMs') is not None:
            video = sample['rtmpFirstVideo']
            assert video['marker'] == media['speechMarker']
            assert video['generation'] == media['generationId']
            c = sample['clockExchanges']['receiver']
            base = (c['start']+c['end'])/2-c['clockOriginAgeMs']
            assert abs(sample['receiveToRTMPAVMs']-(base+max(sample['rtmpFirstAudio']['at'],sample['rtmpFirstVideo']['at'])-receipt)) < 1e-6
            assert abs(sample['rtmpAlignmentUncertaintyMs']-((c['end']-c['start'])/2+sample['receiptAlignmentUncertaintyMs'])) < 1e-6
    paths = {'all':samples,'fast':[s for s in samples if 'llm_first_token' not in s['runtimePoints']], 'llm':[s for s in samples if 'llm_first_token' in s['runtimePoints']]}
    paths['complex'] = [s for s in samples if str(s.get('topic', '')).startswith('complex_')]
    results={}
    for name, subset in paths.items():
        results[name]={'samples':len(subset),'indices':[s['index'] for s in subset]}
        for sink,key,uncertainty in [('chrome','receiveToCorrelatedAVMs','receiptAlignmentUncertaintyMs'),('rtmp','receiveToRTMPAVMs','rtmpAlignmentUncertaintyMs')]:
            observed=[s for s in subset if s.get(key) is not None]
            if observed:results[name][sink]=group(observed,key,uncertainty)
        results[name]['decomposition']={key:stats([s[key] for s in subset if s.get(key) is not None]) for key in ['selectionMs','selectedToSpeakableMs','speakableToPCMMS','pcmToGPUFrameMS','gpuToBrowserVideoMs']}
    return dict(source=path.name,sourceSHA256=hashlib.sha256(path.read_bytes()).hexdigest(),algorithm='empirical nearest rank ceil(n*p)-1; independent quantiles of per-sample uncertainty bounds',groups=results,attempts=normal['attempts'],failedAttempts=sum(a['status']!='COMPLETED' for a in normal['attempts']),errors=normal['errors'],arrivalPolicy=normal.get('arrivalPolicy'),clockExchangesRetained=True,limits=['Chrome decoded/analyser + expectedDisplayTime, not physical speaker/display hardware','Audio association uses first analyser nonzero after input; sequential completed speech only','RTMP when present is a local decoder, not an official platform audience','Subgroups are reported separately; bounded samples do not establish a sustained service SLA'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-dir', type=Path, default=Path(__file__).resolve().parents[1]/'docs/v0.4/evidence')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--trial', type=Path, help='Audit a new trial retaining raw clock exchanges')
    args = parser.parse_args()
    args.output.write_text(json.dumps(audit_current(args.trial) if args.trial else audit(args.evidence_dir), indent=2, ensure_ascii=False)+'\n')
