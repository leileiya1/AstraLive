"""Offline content/timestamp audit of an owned real-GPU soak recording.

AAC waveform correlation measures source-aligned onset, not facial lip quality.
Chrome nearest-onset pairing is explicitly heuristic, separately from RTC stats.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile
import wave
import av
import numpy as np
from runtime.tests.timeline_media_benchmark import percentile


def events(directory):
    rows = []
    for path in directory.glob('avatar-v05-b-soulx.log*'):
        for line in path.read_text().splitlines():
            try: rows.append(json.loads(line))
            except ValueError: pass
    return sorted(rows, key=lambda r: r.get('monotonic_s', 0))


def audit(directory, source_wave):
    rows = events(directory)
    jobs = {e['marker']: e for e in rows if e['event'] == 'BeginSpeechJob'}
    first_pcm = []
    first_gpu = []
    origin = None
    pending = False
    for e in rows:
        if e['event'] == 'FirstPCM':
            origin = e['monotonic_s']; pending = True
        if e['event'] == 'FrameEnqueued' and e.get('activity') == 'TALKING' and e.get('source') == 'GPU_INFERENCE' and pending:
            first_gpu.append((e['monotonic_s'] - origin) * 1000); pending = False
            first_pcm.append({'marker': e['marker'], 'firstGpuMs': first_gpu[-1]})
    markers = {}; stale_epoch_frames = 0
    with av.open(str(directory/'rtmp.flv')) as container:
        for frame in container.decode(video=0):
            pixels = frame.to_ndarray(format='rgb24')
            marker = sum(1 << b for b in range(12) if pixels[4, b*8+4, 0] > pixels[4, b*8+4, 1])
            stale_epoch_frames += marker == 4095
            if marker in jobs and marker not in markers:
                markers[marker] = float(frame.pts * frame.time_base)
    with wave.open(str(source_wave)) as source:
        assert (source.getframerate(), source.getnchannels(), source.getsampwidth()) == (16000, 1, 2)
        source_pcm = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(np.float64)
    # First 500ms contains the utterance's distinct phonetic waveform, including
    # its initial silence. A correlation peak identifies sample zero directly.
    template = source_pcm[:8000]
    threshold_offset_ms = float(np.flatnonzero(np.abs(source_pcm/32768) > .025)[0]) / 16
    with tempfile.TemporaryDirectory(prefix='astralive-pcm-audit-') as temporary:
        decoded = pathlib.Path(temporary)/'audio.s16'
        subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(directory/'rtmp.flv'),
                        '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-f', 's16le', str(decoded)], check=True)
        audio = np.memmap(decoded, dtype='<i2', mode='r')
        pairs = []
        for marker, video_at in sorted(markers.items(), key=lambda item: item[1]):
            lower = max(0, int((video_at-2)*16000))
            upper = min(len(audio), int((video_at+2.5)*16000))
            region = audio[lower:upper].astype(np.float64)
            n = len(region); m = len(template)
            if n < m: continue
            size = 1 << (n+m-1).bit_length()
            dot = np.fft.irfft(np.fft.rfft(region, size)*np.conj(np.fft.rfft(template, size)), size)[:n-m+1]
            squares = np.concatenate(([0.], np.cumsum(region*region)))
            energy = squares[m:] - squares[:-m]
            score = dot / np.sqrt(np.maximum(1., energy * np.sum(template*template)))
            index = int(np.argmax(score)); audio_at = (lower+index)/16000
            pairs.append({'marker': marker, 'audioStartSeconds': audio_at, 'videoStartSeconds': video_at,
                          'audioMinusVideoMs': (audio_at-video_at)*1000,
                          'waveformCorrelation': float(score[index]), 'verified': bool(score[index] >= .8)})
        del audio
    chrome = json.loads((directory/'chrome.json').read_text())
    chrome_pairs = []
    for video in chrome['video']:
        if video['marker'] not in jobs or not chrome['audio']: continue
        audio = min(chrome['audio'], key=lambda a: abs(a['at']-video['at']-threshold_offset_ms))
        chrome_pairs.append({'marker': video['marker'], 'audioAt': audio['at'], 'videoAt': video['at'],
                             'sourceOffsetAdjustedMs': audio['at']-video['at']-threshold_offset_ms})
    verified = [p for p in pairs if p['verified']]
    result = {'expectedSpeechMarkers': len(jobs), 'rtmpObservedSpeechMarkers': len(markers),
              'rtmpStaleEpochMarkerFrames': stale_epoch_frames,
              'rtmpVerifiedWaveformPairs': len(verified), 'rtmpPairs': pairs,
              'rtmpContentOnsetDriftMs': percentile([abs(p['audioMinusVideoMs']) for p in verified]),
              'rtmpUnverifiedMarkers': sorted(set(jobs)-{p['marker'] for p in verified}),
              'chromeHeuristicOnsetDriftMs': percentile([abs(p['sourceOffsetAdjustedMs']) for p in chrome_pairs]),
              'chromeHeuristicPairs': chrome_pairs, 'sourceThresholdOffsetMs': threshold_offset_ms,
              'firstPCMToFirstGPUFrameMs': percentile(first_gpu), 'firstGPUPairs': first_pcm,
              'waveSHA256': hashlib.sha256(source_wave.read_bytes()).hexdigest(),
              'scope': '500ms known PCM/AAC waveform alignment +/-2s; Chrome nearest threshold onset is heuristic; neither is lip-quality or physical-audibility proof'}
    (directory/'content-audit.json').write_text(json.dumps(result, indent=2))
    return {k: v for k, v in result.items() if k not in ('rtmpPairs', 'chromeHeuristicPairs', 'firstGPUPairs')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=pathlib.Path, required=True)
    parser.add_argument('--wave', type=pathlib.Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory, args.wave)))
