#!/usr/bin/env python3
"""Read-only component evidence audit. Never promotes the failed tcp-9 run."""
import importlib.util
import json
from pathlib import Path
import sys

F = Path('/Users/sapiece/innovationProject/AstraLive-agent-f')
ROOT = Path('/private/tmp/astralive-f-real-golden-pilot-tcp-9')
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(F))

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

a = module('partial_oracle', F/'integration/v0.5/real_golden_audit.py')
av = module('recorded_av_oracle', F/'integration/v0.5/observer_audit.py')
media = ROOT/'media'
sql = a.read_json(media/'sql-proof.json')
observer = a.read_json(media/'observer/result.json')
index_path = media/'staged-observer/refs.json'
index = a.read_json(index_path)
plan = sql['narrations'][0]['document_json']['plan']
attempts = a.unique(sql['attempts'], 'attempt_id')
segments = a.unique(sql['segments'], 'segment_id')
commands = a.unique(sql['commandIdentities'], 'commandId')
commits = {row['attempt_id']: row for row in sql['commits']}
observations = {(row['command_id'], row['operation']): row for row in sql['observations']}
report = {'wholeRunStatus': 'FAIL', 'formalGolden1': 'NOT_FORMAL',
          'scope': 'Read-only partial evidence, failed Chrome and UNKNOWN tail retained',
          'source': a.read_json(ROOT/'result.json')['source'],
          'audible': 'NOT_VERIFIABLE', 'humanNaturalness': 'NOT_TESTED',
          'rawPoseAckBytes': 'NOT_CAPTURED', 'actualRTPTimestamps': 'NOT_CAPTURED',
          'components': []}
for entry in index:
    reference = a.read_json(a.contained(index_path.parent, entry['reference']))
    aid = reference['identity']['attemptId']
    commit, attempt = commits[aid], attempts[aid]
    d = a.stage_descriptor(reference)
    a.require(entry['identity'] == reference['identity'], 'INDEX_IDENTITY_MISMATCH')
    for key in ('ordinal', 'layoutRevision', 'speechPCMHash', 'readyContentHash',
                'readyVideoHash', 'readyEmittedVideoHash', 'originalSamples', 'padSamples'):
        a.require(entry[key] == reference[key], 'INDEX_CONTENT_MISMATCH')
    segment = segments[commit['segment_id']]
    a.bind_identity(reference, commit, attempt, segment, commands[commit['command_id']])
    desc = commit['descriptor_json']
    a.require(desc['stagingDescriptor'] == d and desc['stagingDescriptorHash'] == reference['stageDescriptor']['descriptor_sha256'], 'SQL_DESCRIPTOR_MISMATCH')
    a.require(desc['providerProvenance'] == 'GPU_INFERENCE' and desc['finalMarker'] is True
              and desc['videoFrameCount'] == d['frame_count'], 'SQL_GPU_FINAL_MISMATCH')
    a.require(desc['workerEpoch'] == reference['identity']['workerEpoch'] and desc['workerGenerationId'] == reference['identity']['workerGenerationId'], 'SQL_WORKER_IDENTITY_MISMATCH')
    a.require(desc['textHash'] == segment['text_hash'] == a.sha(segment['text'].encode()), 'IMMUTABLE_TEXT_MISMATCH')
    a.require(desc['factIds'] == segment['fact_ids'] and desc['factVersion'] == segment['product_version'] == plan['factVersion'], 'FACT_VERSION_MISMATCH')
    a.require(desc['requiredSinks'] == plan['requiredSinks'] == observer['requiredSinks'], 'CAPTURED_REQUIRED_SINKS_MISMATCH')
    for key, refkey in (('contentHash','readyContentHash'), ('videoHash','readyVideoHash'), ('stagingEmittedVideoHash','readyEmittedVideoHash')):
        a.require(desc[key] == reference[refkey], 'SQL_HASH_MISMATCH')
    a.require(desc['sourceSampleCount'] == d['source_samples'] and desc['sourceSampleRate'] == 16000,
              'SOURCE_CLOCK_MISMATCH')
    a.require(desc['originalSampleCount'] == d['original_samples'] and desc['padSamples'] == d['pad_samples'], 'SQL_PADDING_MISMATCH')
    a.require(desc['sampleCount'] == commit['end_sample'] - commit['start_sample'] == d['source_samples'] * commit['sample_rate'] // 16000, 'OUTPUT_CLOCK_MISMATCH')
    a.require(reference['identity']['workerEpoch'] == observer['capturedProviders']['workerEpoch'] and reference['identity']['workerRef'] == observer['profiles']['GPU_WORKER']['config']['workerRef'], 'CAPTURED_WORKER_MISMATCH')
    wav = a.contained(index_path.parent, entry['sourceWav'])
    h264 = a.contained(index_path.parent, str(Path(entry['reference']).parent/'native.h264'))
    byte_result = a.audit_media_bytes(reference, wav, h264)
    installed = observations[(commit['command_id'], 'COMMIT_INSTALLED')]
    ack = installed['response_json']
    a.require(installed['session_id'] == reference['identity']['sessionId'] and installed['run_epoch'] == reference['identity']['runEpoch'], 'INSTALLED_SCOPE_MISMATCH')
    a.require(ack['durable'] is True and ack['observationHash'] == installed['observation_hash'], 'INSTALLED_HASH_MISMATCH')
    a.contract.installed_reference(reference['identity'], ack)
    receipt_status = 'UNPROVEN_UNKNOWN_TAIL'
    if commit['play_state'] == 'COMPLETED':
        a.require(attempt['status'] == 'COMPLETED', 'ATTEMPT_NOT_COMPLETED')
        a.full_sink_receipts(commit, plan['requiredSinks'])
        completion = observations[(commit['command_id'], 'SEGMENT_COMPLETED')]
        ca = completion['response_json']
        a.require(ca['durable'] is True and ca['state'] == 'completed' and ca['observationHash'] == completion['observation_hash'] == commit['completion_hash'] and ca['producerIncarnation'] == ack['producerIncarnation'] and ca['receiptSeq'] > ack['receiptSeq'], 'COMPLETION_ACK_MISMATCH')
        receipt_status = 'PASS_SERVER_SINK_CONSUMED_ONLY'
    else:
        a.require(commit['play_state'] == attempt['status'] == 'UNKNOWN' and not commit['sink_receipts'], 'UNEXPECTED_TAIL_STATE')
    ident = reference['identity']
    report['components'].append({'ordinal': entry['ordinal'], 'attemptId': aid,
        'lane': ident['lane'], 'attemptState': attempt['status'], 'playState': commit['play_state'],
        'byteAudit': byte_result, 'installedACK': 'PASS', 'fullSinkReceipts': receipt_status,
        'receiptCount': len(commit['sink_receipts']),
        'epochs': {k: ident[k] for k in ('runEpoch','timelineEpoch','generationId','workerEpoch','workerGenerationId')},
        'resources': d['resources']})
ordered = sorted(sql['commits'], key=lambda row: row['start_sample'])
for before, after in zip(ordered, ordered[1:]):
    a.require(before['end_sample'] == after['start_sample'], 'LEDGER_GAP_OR_OVERLAP')
    a.require(before['identity_json']['workerGenerationId'] < after['identity_json']['workerGenerationId'], 'NONMONOTONIC_WORKER_GENERATION')
try:
    a.reject_replayed_mapped_answer_facts(sql['turns'], sql['commits'], plan)
    report['factReplayOracle'] = {'status': 'PASS'}
except a.AuditFailure as exc:
    report['factReplayOracle'] = {'status': exc.status, 'code': exc.code}
report['normalStop'] = {'sessionStates': [r['status'] for r in sql['sessions']],
    'runStates': [r['status'] for r in sql['runs']], 'narrationStates': [r['document_json']['state'] for r in sql['narrations']],
    'bindingReleased': [r['released'] for r in sql['bindingRelease']]}
chrome = a.read_json(media/'observer/chrome.json')
report['chrome'] = {'audioRows': len(chrome['audioEnergy']),
    'maxRMS': max(r['rms'] for r in chrome['audioEnergy']),
    'maxAudioContextTime': max(r['contextTime'] for r in chrome['audioEnergy']),
    'videoFrames': len(chrome['video']), 'recordedBytes': chrome['recordedBytes'],
    'webmBytes': (media/'observer/chrome.webm').stat().st_size, 'status': 'FAIL'}
markers = av.decode_video(media/'rtmp.flv')
audio = av.audio(media/'rtmp.flv')
first = {}
for row in markers['markers']:
    first.setdefault(row['ordinal'], row['seconds'])
rtmp_rows = []
for entry in index:
    seqs = [r['sequence'] for r in markers['markers'] if r['ordinal'] == entry['ordinal']]
    if entry['ordinal'] not in first:
        rtmp_rows.append({'ordinal': entry['ordinal'], 'status': 'VIDEO_NOT_OBSERVED'})
        continue
    found = av.match(av.audio(a.contained(index_path.parent, entry['sourceWav'])), audio, first[entry['ordinal']])
    if abs(found.get('correlation', 0)) > 1.000001:
        found = {'status': 'NOT_VERIFIABLE_INVALID_NORMALIZED_CORRELATION',
                 'originalOracleOutput': found}
    row = {'ordinal': entry['ordinal'], 'videoFirstSeconds': first[entry['ordinal']],
           'videoSequenceMin': min(seqs), 'videoSequenceMax': max(seqs), 'videoMarkerCount': len(seqs), **found}
    if found['status'] == 'MATCHED':
        row['audioMinusVideoMs'] = (found['referenceStartSeconds']-first[entry['ordinal']])*1000
    rtmp_rows.append(row)
report['rtmp'] = {'scope': 'Actual decoded recording; not audience speakers or physical lip sync',
    'clockDomain': 'RTMP recording PTS only', 'recordingBytes': (media/'rtmp.flv').stat().st_size,
    'decodedAudioSeconds': len(audio)/8000, 'decodedAudioRMS': float(av.np.sqrt(av.np.mean(audio*audio))),
    'decodedAudioPeak': float(av.np.max(av.np.abs(audio))), 'videoMarkers': len(markers['markers']),
    'ptsRegressions': markers['ptsRegressions'], 'rows': rtmp_rows}
(OUT/'partial-verification.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
