#!/usr/bin/env python3
"""Read-only sink-clock and synthetic codec checks, explicitly not RTP capture."""
import json
from pathlib import Path
from fractions import Fraction
import importlib.metadata
import av
from aiortc.codecs.opus import OpusEncoder, OpusDecoder
from aiortc.jitterbuffer import JitterFrame

MEDIA = Path('/private/tmp/astralive-f-real-golden-pilot-tcp-9/media')
OUT = Path(__file__).resolve().parent
peers = {}
for line in (MEDIA/'runtime.log').read_text().splitlines():
    try:
        outer = json.loads(line)
        message = outer.get('message', '')
        if not message.startswith('runtime_media_metrics '):
            continue
        metrics = json.loads(message.removeprefix('runtime_media_metrics '))
    except (ValueError, TypeError):
        continue
    for session in metrics.get('sessions', []):
        for peer in session['media']['webrtc'].get('sink', {}).get('peers', []):
            clock = peer.get('mediaTimeline')
            if clock:
                peers.setdefault(peer['peerId'], []).append(clock)
encoder, decoder = OpusEncoder(), OpusDecoder()
codec_rows = []
for index in range(8):
    frame = av.AudioFrame(format='s16', layout='mono', samples=960)
    frame.sample_rate = 48000
    frame.pts = index*960
    frame.time_base = Fraction(1, 48000)
    frame.planes[0].update(bytes(frame.planes[0].buffer_size))
    packets, timestamp = encoder.encode(frame)
    decoded = [f for packet in packets for f in decoder.decode(JitterFrame(data=packet, timestamp=timestamp))]
    codec_rows.append({'inputPTS': frame.pts, 'encodedRelativeTimestamp': timestamp,
                       'decodedSamples': [f.samples for f in decoded]})
chrome = json.loads((MEDIA/'observer/chrome.json').read_text())
fields = ('kind','timestamp','packetsReceived','packetsDiscarded','totalSamplesReceived',
          'totalSamplesDuration','totalAudioEnergy','jitterBufferEmittedCount',
          'estimatedPlayoutTimestamp','framesDecoded','framesDropped')
report = {'source': '4f61a97d8cf5642f0d94b409e91277a000fb5936',
    'scope': 'Actual server clock snapshots; separate synthetic codec diagnostic. No actual RTP or RTCP capture.',
    'actualRTPTimestamps': 'NOT_CAPTURED', 'actualRTCPMapping': 'NOT_CAPTURED',
    'wholeRunStatus': 'FAIL', 'peers': [],
    'chromeInbound': [{key:r[key] for key in fields if key in r} for r in chrome['inbound']],
    'estimatedPlayoutTimestampRule': 'Do not subtract from performance/stat timestamps without mapping; values differ by approximately NTP-to-Unix epoch offset, not an established live delay.',
    'syntheticCodec': {'scope': 'CPU_SYNTHETIC_CODEC_DIAGNOSTIC_NOT_ACTUAL_TCP9_RTP',
        'aiortc': importlib.metadata.version('aiortc'), 'pyav': av.__version__, 'rows': codec_rows}}
for peer_id, rows in peers.items():
    report['peers'].append({'peerId':peer_id, 'snapshotCount':len(rows), 'first':rows[0], 'last':rows[-1],
        'outputSampleRegressions': sum(b['outputSamples']<a['outputSamples'] for a,b in zip(rows,rows[1:])),
        'maxOutputSeconds':max(row['outputSamples']/row['outputRate'] for row in rows)})
(OUT/'clock-diagnostic.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
