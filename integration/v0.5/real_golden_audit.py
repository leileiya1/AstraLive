#!/usr/bin/env python3
"""Independent real-Golden artifact oracle, never a live/provider controller.

Accepts Go to_jsonb SQL arrays and C's actual staging observer references.
Old synthetic journal layouts are rejected. PASS means consistency of the
specified machine evidence, not physical audibility, naturalness, SLA, LLM
fact generation, or cryptographic hardware attestation. Short runs are never G1.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import struct
import sys
import wave

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from gpu_worker import staging_contract as contract
from gpu_worker.config import REVISION as NATIVE_MODEL_REVISION

HASH = re.compile(r'sha256:[0-9a-f]{64}\Z')
LAYOUT = 'astralive-golden-barcode-24-v1'
SQL_ARRAYS = ('sessions', 'narrations', 'segments', 'attempts', 'turns', 'commits', 'runs', 'bindingRelease')
BUSINESS_FIELDS = ('sessionId', 'runEpoch', 'timelineEpoch', 'generationId', 'segmentId',
                   'utteranceId', 'lane', 'workerEpoch', 'workerGenerationId')
ATTEMPT_FIELDS = {'sessionId':'session_id', 'runEpoch':'run_epoch', 'timelineEpoch':'timeline_epoch',
    'narrationId':'narration_id', 'segmentId':'segment_id', 'attemptId':'attempt_id',
    'generationId':'generation_id', 'commandId':'command_id', 'utteranceId':'utterance_id',
    'lane':'lane', 'workerEpoch':'worker_epoch', 'workerGenerationId':'worker_generation_id'}
COMMAND_FIELDS = ('commandId', 'sessionId', 'runEpoch', 'traceId', 'narrationId', 'segmentId',
                  'lane', 'timelineEpoch', 'beatId', 'interactionTurnId', 'attemptId', 'utteranceId')


class AuditFailure(Exception):
    def __init__(self, code, status='FAIL'):
        self.code, self.status = code, status
        super().__init__(code)


def require(condition, code, status='FAIL'):
    if not condition:
        raise AuditFailure(code, status)


def sha(data):
    return 'sha256:'+hashlib.sha256(data).hexdigest()


def exact_int(value, minimum=0):
    require(type(value) is int and minimum <= value <= contract.MAX_INTEGER, 'INVALID_EXACT_INTEGER')
    return value


def percentile(values, quantile):
    ordered = sorted(values)
    if not ordered:
        return None
    index = (len(ordered)-1)*quantile
    lower, upper = math.floor(index), math.ceil(index)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(index-lower)


def unique(rows, key):
    require(type(rows) is list, 'EXPECTED_ACTUAL_SQL_ARRAY')
    result = {}
    for row in rows:
        require(type(row) is dict and key in row and row[key] not in result, 'MISSING_OR_DUPLICATE_SQL_KEY')
        result[row[key]] = row
    return result


def read_json(path):
    require(path.is_file(), 'MISSING_ARTIFACT', 'NOT_VERIFIABLE')
    require(path.stat().st_size <= 64*1024*1024, 'JSON_ARTIFACT_LIMIT')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def nonfinite(_):
        raise AuditFailure('NONFINITE_JSON_VALUE')
    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_constant=nonfinite)


def contained(root, relative):
    require(type(relative) is str and not Path(relative).is_absolute(), 'UNSAFE_REFERENCE_PATH')
    path = (root/relative).resolve()
    require(path.is_relative_to(root.resolve()), 'REFERENCE_ESCAPES_ARTIFACT')
    require(path.is_file(), 'MISSING_REFERENCE_FILE', 'NOT_VERIFIABLE')
    return path


def stage_descriptor(reference):
    header = reference['stageDescriptor']
    contract.validate_message(header)
    require(header['type']=='StageProduced', 'NOT_FROZEN_STAGE_PRODUCED')
    d = header['descriptor']
    require(reference['identity']==header['identity']==d['identity'], 'REFERENCE_17_TUPLE_MISMATCH')
    require(d['provenance']['source']=='GPU_INFERENCE', 'SYNTHETIC_GPU_PROVENANCE')
    require(d['provenance']['model_source_revision']==NATIVE_MODEL_REVISION, 'UNPINNED_NATIVE_MODEL_REVISION')
    require(all(d['resources'][k] is not None for k in d['resources'] if k.startswith('gpu_')),
            'MISSING_REAL_GPU_RESOURCE_FIELDS')
    require(reference['scope']=='TEST_ONLY_REAL_GPU_OUTPUT_INSTRUMENTATION', 'NOT_REAL_OBSERVER_REFERENCE')
    require(reference['layoutRevision']==LAYOUT, 'OBSERVER_LAYOUT_MISMATCH')
    # The authoritative hash has its frozen domain prefix, not a raw JSON hash.
    require(contract.descriptor_hash(d)==header['descriptor_sha256'], 'FROZEN_DESCRIPTOR_HASH_MISMATCH')
    return d


def bind_identity(reference, commit, attempt, segment, command):
    identity = reference['identity']
    contract.validate_identity(identity)
    require(commit['identity_json']=={k:identity[k] for k in BUSINESS_FIELDS}, 'SQL_BUSINESS_IDENTITY_MISMATCH')
    for key, column in ATTEMPT_FIELDS.items():
        require(identity[key]==attempt[column], 'SQL_ATTEMPT_'+key.upper()+'_MISMATCH')
    require(command['commandType']=='COMMIT_SEGMENT', 'NOT_SAFE_MEDIA_COMMAND_PROJECTION')
    for key in COMMAND_FIELDS:
        require(identity[key]==command[key], 'SQL_COMMAND_'+key.upper()+'_MISMATCH')
    for key, column in ATTEMPT_FIELDS.items():
        if column in commit:
            require(identity[key]==commit[column], 'SQL_COMMIT_COLUMN_IDENTITY_MISMATCH')
    require(segment['segment_id']==identity['segmentId'] and segment['narration_id']==identity['narrationId'],
            'SQL_SEGMENT_SCOPE_MISMATCH')
    if identity['lane']=='NARRATION':
        require(identity['beatId']==segment['beat_id'] and identity['interactionTurnId'] is None,
                'NARRATION_BEAT_OR_TURN_MISMATCH')
    require(attempt['descriptor_json']==commit['descriptor_json'], 'ATTEMPT_COMMIT_DESCRIPTOR_MISMATCH')


def full_sink_receipts(commit, expected_sinks):
    require(type(expected_sinks) is list and len(expected_sinks)==len(set(expected_sinks)) and expected_sinks,
            'EMPTY_OR_DUPLICATE_REQUIRED_SINK')
    require(commit['required_sinks']==expected_sinks, 'CAPTURED_REQUIRED_SINKS_MISMATCH')
    require(commit['play_state']=='COMPLETED', 'UNPROVEN_PLAY_STATE')
    require(commit['installed_at'] and commit['completed_at'], 'MISSING_INSTALL_OR_COMPLETE_TIMESTAMP')
    start, end = exact_int(commit['start_sample']), exact_int(commit['end_sample'], 1)
    require(start < end, 'INVALID_COMMIT_INTERVAL')
    keys = set()
    for receipt in commit['sink_receipts']:
        key = (receipt['sinkId'], receipt['media'])
        require(key not in keys, 'DUPLICATE_SINK_RECEIPT')
        keys.add(key)
        require(receipt['identity']==commit['identity_json'], 'SINK_RECEIPT_FOREIGN_IDENTITY')
        require(receipt['startSample']==start and receipt['endSample']==end,
                'SINK_RECEIPT_GAP_OR_PARTIAL_TAIL')
        require(receipt['finalMarker'] is True and receipt['evidenceType']=='sink_consumed'
                and type(receipt['evidenceRef']) is str and receipt['evidenceRef'], 'UNPROVEN_SINK_RECEIPT')
    require(keys=={(sink, media) for sink in expected_sinks for media in ('audio','video')},
            'MISSING_OR_FOREIGN_REQUIRED_SINK_MEDIA')
    require(HASH.fullmatch(commit['completion_hash'] or '') is not None, 'MISSING_COMPLETION_HASH')


def emitted_rgb(decoded, ordinal, sequence):
    """Independent interpretation of the documented 24-bit observation band."""
    require(1 <= ordinal <= 4095 and 0 <= sequence <= 199, 'BARCODE_RANGE')
    value = (ordinal << 8) | sequence
    checksum = 0
    for offset in range(0, 20, 4):
        checksum ^= (value >> offset) & 15
    bits = (value << 4) | checksum
    output = bytearray(decoded)
    for cell in range(24):
        pixel = bytes((220,40,40) if bits & (1 << (23-cell)) else (40,220,40))
        for row in range(8):
            offset = 3*(row*512+cell*8)
            output[offset:offset+24] = pixel*8
    return bytes(output)


def audit_media_bytes(reference, wav_path, h264_path):
    d = stage_descriptor(reference)
    with wave.open(str(wav_path), 'rb') as source:
        require((source.getnchannels(),source.getsampwidth(),source.getframerate(),source.getcomptype())
                ==(1,2,16000,'NONE'), 'NOT_SOURCE_PCM16K_MONO_S16LE')
        require(source.getnframes()==d['source_samples'], 'SOURCE_SAMPLE_COUNT_MISMATCH')
        pcm = source.readframes(source.getnframes())
    require(len(pcm)==2*d['source_samples'], 'TRUNCATED_PCM_SOURCE')
    require(sha(pcm)==d['pcm_sha256']==reference['speechPCMHash']==reference['readyContentHash'],
            'ACTUAL_PCM_CONTENT_HASH_MISMATCH')
    require(reference['originalSamples']==d['original_samples'] and reference['padSamples']==d['pad_samples'],
            'ORIGINAL_OR_PAD_SAMPLE_MISMATCH')
    if d['pad_samples']:
        require(pcm[-2*d['pad_samples']:]==bytes(2*d['pad_samples']), 'NONZERO_FRAME_PADDING')
    require(h264_path.stat().st_size==d['video_bytes'] and d['video_bytes']<=d['limits']['runtime_artifact_bytes'],
            'H264_BYTE_COUNT_OR_ARTIFACT_LIMIT')
    frames = reference['frames']
    require(len(frames)==d['frame_count'], 'REFERENCE_FRAME_COUNT_MISMATCH')
    require(all('payloadBytes' in row and 'payloadSHA256' in row for row in frames),
            'MISSING_ACTUAL_PACKET_BOUNDARIES', 'NOT_VERIFIABLE')
    import av
    decoder = av.CodecContext.create('h264','r')
    decoder.thread_count = 1
    decoder.open()
    stream, emitted_stream = hashlib.sha256(), hashlib.sha256()
    with h264_path.open('rb') as video:
        for sequence, row in enumerate(frames):
            require(row['sequence']==sequence and row['ptsUs']==sequence*40000, 'REFERENCE_SEQUENCE_OR_PTS_GAP')
            size = exact_int(row['payloadBytes'],1)
            require(size<=d['video_bytes'], 'INVALID_PACKET_LENGTH')
            payload = video.read(size)
            require(len(payload)==size and sha(payload)==row['payloadSHA256'], 'ACTUAL_H264_PACKET_HASH_MISMATCH')
            stream.update(struct.pack('!Q',size));stream.update(payload)
            decoded = decoder.decode(av.Packet(payload))
            require(len(decoded)==1 and (decoded[0].width,decoded[0].height)==(512,512), 'H264_DECODE_COUNT_OR_SIZE')
            if sequence==0:
                require(decoded[0].key_frame, 'H264_FIRST_FRAME_NOT_KEYFRAME')
            rgb = decoded[0].to_ndarray(format='rgb24').tobytes()
            require(sha(rgb)==row['decodedRGBHash'], 'DECODED_RGB_HASH_MISMATCH')
            require(HASH.fullmatch(row['nativeRGBHash']) is not None, 'MALFORMED_NATIVE_RGB_HASH')
            emitted = emitted_rgb(rgb, reference['ordinal'], sequence)
            require(sha(emitted)==row['emittedRGBHash'], 'EMITTED_OBSERVER_RGB_HASH_MISMATCH')
            emitted_stream.update(emitted)
        require(not video.read(1), 'UNACCOUNTED_H264_TRAILING_BYTES')
    require(not decoder.decode(None), 'DELAYED_H264_TAIL')
    require('sha256:'+stream.hexdigest()==d['video_stream_sha256']==reference['readyVideoHash'],
            'ORDERED_LENGTH_PREFIX_H264_HASH_MISMATCH')
    require('sha256:'+emitted_stream.hexdigest()==reference['readyEmittedVideoHash'], 'EMITTED_RGB_STREAM_HASH_MISMATCH')
    return {'frames':len(frames), 'originalSeconds':d['original_samples']/16000,
            'nativeRGBStream':'NOT_VERIFIABLE_FROM_LOSSY_H264', 'decodedEmittedAndEncodedBytes':'PASS'}


def selected_turns(turn_rows, commits, references, plan, formal):
    turns = unique(turn_rows, 'turn_id')
    plan_segments = plan['segments']
    by_segment = {row['segment_id']:row for row in commits}
    ordered = sorted(commits,key=lambda row:row['start_sample'])
    require(len(by_segment)==len(commits), 'REPEATED_COMMITTED_SEGMENT')
    coverage = {}
    require(all('answer' in row['document_json'] for row in turns.values()), 'SELECTED_TURN_WITHOUT_ANSWER')
    for row in sorted(turns.values(), key=lambda row: by_segment.get(
            row['document_json']['answer']['segmentId'],{}).get('start_sample',-1)):
        turn = row['document_json']
        require(turn['interactionTurnId']==row['turn_id'] and turn['state']==row['state'], 'TURN_PROJECTION_MISMATCH')
        require(row['state']=='COMPLETED', 'SELECTED_TURN_NOT_TERMINAL_COMPLETED')
        require(turn['question']==row['question'] and sha(turn['question'].encode())==row['question_hash']==turn['questionHash'],
                'TURN_QUESTION_HASH_MISMATCH')
        require(turn['sourceIds']==row['source_ids'] and turn['sourceIds'], 'SELECTED_TURN_SOURCE_IDS_MISSING')
        require(turn['capturedProductHash']==plan['productSnapshotHash'], 'TURN_PRODUCT_SNAPSHOT_MISMATCH')
        answer = turn['answer']
        require(answer['status']=='COMPLETED' and answer['lane']=='AUDIENCE_ANSWER', 'TURN_ANSWER_NOT_COMPLETED')
        require(answer['text']==turn['answerText'] and answer['factIds']==turn['answerFactIds'], 'ANSWER_TEXT_OR_FACT_PROJECTION_MISMATCH')
        answer_commit = by_segment.get(answer['segmentId'])
        require(answer_commit is not None, 'SELECTED_ANSWER_WITHOUT_MEDIA_COMMIT')
        identity = references[answer_commit['attempt_id']]['identity']
        require(identity['interactionTurnId']==row['turn_id'] and identity['lane']=='AUDIENCE_ANSWER', 'ANSWER_TURN_MEDIA_BINDING_MISMATCH')
        require(answer_commit['descriptor_json']['textHash']==answer['textHash']==sha(answer['text'].encode()), 'ANSWER_IMMUTABLE_TEXT_HASH_MISMATCH')
        position = ordered.index(answer_commit)
        before = {c['segment_id'] for c in ordered[:position] if c['identity_json']['lane']=='NARRATION'}
        skipped = set(coverage)
        original_target = next((s for s in plan_segments if s['segmentId'] not in before|skipped),None)
        for segment in plan_segments:
            if segment['status']!='SATISFIED_BY_ANSWER' or segment['segmentId'] in before|skipped:
                continue
            if (segment['factIds'] and set(segment['factIds']).issubset(turn.get('mappedNarrationFactIds') or [])
                    and segment['text'] in turn['answerText']):
                coverage.setdefault(segment['segmentId'],[]).append(row['turn_id'])
                skipped.add(segment['segmentId'])
        expected = next((s for s in plan_segments if s['segmentId'] not in before|skipped),None)
        following = ordered[position+1:]
        same_turn_bridges = [c for c in following if c['identity_json']['lane']=='RESUME_BRIDGE'
                            and references[c['attempt_id']]['identity']['interactionTurnId']==row['turn_id']]
        require(len(same_turn_bridges)<=1, 'DUPLICATE_RESUME_BRIDGE')
        next_narration = next((c for c in following if c['identity_json']['lane']=='NARRATION'),None)
        if expected is not None:
            require(next_narration is not None, 'ANSWER_RESUME_NOT_OBSERVED', 'FAIL' if formal else 'CENSORED')
            require(next_narration['segment_id']==expected['segmentId'], 'ANSWER_RESUMED_WRONG_NEXT_SEGMENT')
            require(references[next_narration['attempt_id']]['identity']['beatId']==expected['beatId'], 'ANSWER_RESUMED_WRONG_BEAT')
        if original_target is not None:
            require(identity['beatId']==original_target['beatId'], 'ANSWER_CAPTURED_WRONG_RESUME_BEAT')
        if same_turn_bridges:
            bridge = same_turn_bridges[0]
            require(not next_narration or bridge['end_sample']<=next_narration['start_sample'], 'BRIDGE_AFTER_RESUMED_NARRATION')
            require(not bridge['descriptor_json']['factIds'], 'RESUME_BRIDGE_HAS_FACT_LABELS')
            if expected is not None:
                require(references[bridge['attempt_id']]['identity']['beatId']==expected['beatId'], 'BRIDGE_TARGET_BEAT_MISMATCH')
    return turns, coverage


class Auditor:
    def __init__(self, directory, fixture, correlate=False):
        directory = Path(directory).resolve()
        self.root = directory
        self.media = directory if (directory/'sql-proof.json').exists() else directory/'media'
        self.fixture_path, self.correlate = Path(fixture).resolve(), correlate
        self.report = {'scope':'Independent real SQL/staging bytes/recorded AV consistency oracle',
            'audienceAudible':False, 'humanNaturalness':'NOT_TESTED', 'llmGeneratedFacts':'NOT_TESTED',
            'busyCommentSLA':'NOT_TESTED', 'checks':[], 'clockRule':'recording PTS separately; no subtraction across clocks'}
        self.report['auditContractSHA256'] = sha(Path(contract.__file__).read_bytes())
        self.refs, self.facts_coverage = {}, {}

    def check(self, name, function):
        try:
            result = function()
            self.report['checks'].append({'name':name,'status':'PASS', 'result':result})
            return True
        except AuditFailure as error:
            self.report['checks'].append({'name':name,'status':error.status,'code':error.code})
        except contract.ContractError:
            self.report['checks'].append({'name':name,'status':'FAIL','code':'FROZEN_STAGING_CONTRACT_REJECTED'})
        except (KeyError,TypeError,ValueError,IndexError) as error:
            self.report['checks'].append({'name':name,'status':'FAIL','code':'ACTUAL_ARTIFACT_SHAPE_INVALID',
                                         'exceptionType':type(error).__name__})
        except Exception as error:
            self.report['checks'].append({'name':name,'status':'NOT_VERIFIABLE','code':'LOCAL_AUDIT_DEPENDENCY_OR_IO_FAILED',
                                         'exceptionType':type(error).__name__})
        return False

    def load(self):
        self.sql = read_json(self.media/'sql-proof.json')
        require(type(self.sql) is dict and all(type(self.sql.get(key)) is list for key in SQL_ARRAYS),
                'NOT_ACTUAL_GO_SQL_PROOF_ARRAYS')
        self.observer = read_json(self.media/'observer/result.json')
        self.chrome = read_json(self.media/'observer/chrome.json')
        processes = read_json(self.media/'processes.json')
        pids = [exact_int(processes[key],1) for key in ('goPID','runtimePID','rtmpReceiverPID')]
        require(len(set(pids))==3, 'PROCESS_COMPONENTS_NOT_DISTINCT')
        require(processes['localTransport'] in ('tcp','uds'), 'UNSUPPORTED_LOCAL_TRANSPORT_EVIDENCE')
        self.report['processes'] = processes
        self.fixture = read_json(self.fixture_path)
        require(self.observer['scope']=='REAL_BOUND_PROVIDER_PUBLIC_API_CHROME_OBSERVER', 'NOT_REAL_PUBLIC_OBSERVER')
        require(self.observer['status']!='FAIL', 'REAL_OBSERVER_FAILED')
        require(self.observer['capturedProviders']['mode']=='REAL', 'NOT_REAL_CAPTURED_PROVIDERS')
        self.sid, self.nid = self.observer['sessionId'], self.observer['narrationId']
        self.formal = self.observer['mode']=='ten-minute'
        gate_path = self.root/'result.json' if self.root!=self.media else self.media.parent/'result.json'
        if gate_path.is_file():
            gate = read_json(gate_path)
            require(gate.get('status')=='PASS_EXECUTED_SOFTWARE_GATE' and all(c['exitCode']==0 for c in gate.get('checks',[])),
                    'OWNED_REAL_GATE_FAILED_OR_UNFINISHED')
            self.report['source'] = gate['source']
            require(gate['mode']==self.observer['mode'], 'GATE_OBSERVER_MODE_MISMATCH')
            require(processes['source']==gate['source'], 'ACTUAL_PROCESS_SOURCE_PIN_MISMATCH')
        self.report.update(sessionId=self.sid,narrationId=self.nid,mode=self.observer['mode'],
            formalGolden1='PENDING' if self.formal else 'NOT_FORMAL',fixtureSHA256=sha(self.fixture_path.read_bytes()))
        require(self.observer['mode'] in ('short','ten-minute','soak'), 'UNSUPPORTED_REAL_RUN_MODE')
        require(processes['localTransport']==self.observer['localTransport'], 'PROCESS_OBSERVER_LOCAL_TRANSPORT_MISMATCH')
        narrations = [r for r in self.sql['narrations'] if r['session_id']==self.sid]
        require(len(narrations)==1 and narrations[0]['narration_id']==self.nid, 'MULTIPLE_OR_WRONG_NARRATION')
        self.narration = narrations[0]
        self.document = self.narration['document_json']
        self.plan = self.document['plan']
        require(self.plan['sessionId']==self.sid and self.plan['narrationId']==self.nid, 'PLAN_SCOPE_MISMATCH')
        require(self.plan['scriptVersion']==self.fixture['scriptVersion'], 'ACTUAL_FIXTURE_SCRIPT_VERSION_MISMATCH')
        self.segments = unique([r for r in self.sql['segments'] if r['session_id']==self.sid], 'segment_id')
        self.attempts = unique([r for r in self.sql['attempts'] if r['session_id']==self.sid], 'attempt_id')
        self.commits = [r for r in self.sql['commits'] if r['session_id']==self.sid]
        unique(self.commits,'command_id')
        require('commandIdentities' in self.sql and 'observations' in self.sql, 'MISSING_SAFE_SQL_BINDING_PROJECTIONS', 'NOT_VERIFIABLE')
        self.commands = unique(self.sql['commandIdentities'],'commandId')
        self.observations = {}
        for row in self.sql['observations']:
            key = row['command_id'],row['operation']
            require(key not in self.observations,'DUPLICATE_SQL_OBSERVATION')
            self.observations[key] = row
        self.index_path = self.media/'staged-observer/refs.json'
        self.index = read_json(self.index_path)
        unique(self.index,'ordinal')
        for entry in self.index:
            reference = read_json(contained(self.index_path.parent,entry['reference']))
            identity = reference['identity']
            require(entry['identity']==identity and entry['ordinal']==reference['ordinal'], 'INDEX_REFERENCE_IDENTITY_MISMATCH')
            for key in ('layoutRevision','speechPCMHash','readyContentHash','readyVideoHash',
                        'readyEmittedVideoHash','originalSamples','padSamples'):
                require(entry[key]==reference[key], 'INDEX_REFERENCE_CONTENT_MISMATCH')
            require(identity['sessionId']==self.sid and identity['narrationId']==self.nid, 'FOREIGN_REFERENCE_SESSION')
            require(identity['attemptId'] not in self.refs, 'DUPLICATE_REFERENCE_ATTEMPT')
            self.refs[identity['attemptId']] = reference
        require(self.commits and self.refs, 'NO_REAL_COMMITTED_STAGING_EVIDENCE')
        return {'commits':len(self.commits),'references':len(self.refs),'schema':'Go to_jsonb arrays/C staging-observer'}

    def bindings(self):
        completed = set()
        previous_end = None
        previous_generation = 0
        producer_incarnations = set()
        worker_ref = self.observer['profiles']['GPU_WORKER']['config']['workerRef']
        for commit in sorted(self.commits,key=lambda r:r['start_sample']):
            aid = commit['attempt_id']
            attempt, reference = self.attempts[aid], self.refs[aid]
            d = stage_descriptor(reference)
            bind_identity(reference, commit, attempt, self.segments[commit['segment_id']], self.commands[commit['command_id']])
            require(attempt['status']=='COMPLETED', 'NONCOMPLETED_COMMITTED_ATTEMPT')
            descriptor = commit['descriptor_json']
            require(descriptor['providerProvenance']=='GPU_INFERENCE' and descriptor['stagingDescriptor']==d
                    and descriptor['stagingDescriptorHash']==reference['stageDescriptor']['descriptor_sha256'], 'SQL_GPU_DESCRIPTOR_BINDING_MISMATCH')
            require(descriptor['workerEpoch']==reference['identity']['workerEpoch']
                    and descriptor['workerGenerationId']==reference['identity']['workerGenerationId']
                    and descriptor['videoFrameCount']==d['frame_count'] and descriptor['finalMarker'] is True,
                    'SQL_READY_WORKER_OR_FRAME_FINAL_BINDING_MISMATCH')
            for a,b in (('contentHash','readyContentHash'),('videoHash','readyVideoHash'),('stagingEmittedVideoHash','readyEmittedVideoHash')):
                require(descriptor[a]==reference[b], 'SQL_READY_CONTENT_HASH_MISMATCH')
            require(descriptor['sourceSampleRate']==16000 and descriptor['sourceSampleCount']==d['source_samples']
                    and descriptor['originalSampleCount']==d['original_samples'] and descriptor['padSamples']==d['pad_samples'], 'SQL_SOURCE_SAMPLE_BINDING_MISMATCH')
            require(descriptor['sampleCount']==commit['end_sample']-commit['start_sample']
                    ==d['source_samples']*commit['sample_rate']//16000, 'SOURCE_OUTPUT_CLOCK_DOMAINS_MIXED')
            segment = self.segments[commit['segment_id']]
            require(descriptor['textHash']==segment['text_hash']==sha(segment['text'].encode()), 'IMMUTABLE_SEGMENT_TEXT_HASH_MISMATCH')
            require(descriptor['factIds']==segment['fact_ids'] and descriptor['factVersion']==segment['product_version'], 'SEGMENT_FACT_OR_PRODUCT_VERSION_MISMATCH')
            require(descriptor['requiredSinks']==self.plan['requiredSinks']==self.observer['requiredSinks'], 'REQUIRED_SINK_CAPTURE_MISMATCH')
            full_sink_receipts(commit, self.plan['requiredSinks'])
            installed = self.observations[(commit['command_id'],'COMMIT_INSTALLED')]
            ack = installed['response_json']
            require(installed['session_id']==self.sid and installed['run_epoch']==commit['run_epoch']
                    and ack['observationHash']==installed['observation_hash'] and ack['durable'] is True,
                    'ACTUAL_A_INSTALLED_ACK_MISMATCH')
            contract.installed_reference(reference['identity'],ack)
            producer_incarnations.add(ack['producerIncarnation'])
            completion = self.observations[(commit['command_id'],'SEGMENT_COMPLETED')]
            require(completion['observation_hash']==commit['completion_hash']
                    ==completion['response_json']['observationHash'], 'SQL_COMPLETION_ACK_HASH_MISMATCH')
            require(completion['response_json']['durable'] is True and completion['response_json']['state']=='completed'
                    and completion['response_json']['producerIncarnation']==ack['producerIncarnation']
                    and exact_int(completion['response_json']['receiptSeq'],1)>exact_int(ack['receiptSeq'],1),
                    'ACTUAL_A_COMPLETION_ACK_MISMATCH')
            require(reference['identity']['workerEpoch']==self.observer['capturedProviders']['workerEpoch'], 'CAPTURED_WORKER_EPOCH_MISMATCH')
            require(reference['identity']['workerRef']==worker_ref, 'CAPTURED_WORKER_REFERENCE_MISMATCH')
            require(reference['identity']['workerGenerationId']>previous_generation, 'NONMONOTONIC_WORKER_GENERATION')
            previous_generation = reference['identity']['workerGenerationId']
            require(previous_end is None or commit['start_sample']==previous_end, 'COMMITTED_LEDGER_INTERVAL_GAP_OR_OVERLAP')
            previous_end = commit['end_sample'];completed.add(aid)
        tails = [a for aid,a in self.attempts.items() if aid not in completed]
        if self.formal:
            require(not tails and set(self.refs)==completed, 'FORMAL_UNCOMPLETED_ATTEMPT_OR_UNCOMMITTED_REFERENCE')
            require(len(producer_incarnations)==1, 'FORMAL_RUNTIME_INCARNATION_CHANGED')
        self.report['uncompletedTail'] = [{'attemptId':a['attempt_id'],'state':a['status']} for a in tails]
        self.report['tailScope'] = 'NOT_FORMAL_CENSORED_TAIL' if tails else 'NO_UNCOMPLETED_TAIL'
        return {'completedBindings':len(completed),'uncompletedTail':len(tails),
                'stageIdScope':'Worker artifact identity; no invented SQL stageId column',
                'nativeRGBHashScope':'Worker original RGB claims; NOT recomputed from lossy decoded RGB'}

    def byte_references(self):
        rows = []
        for entry in self.index:
            aid = entry['identity']['attemptId']
            reference = self.refs[aid]
            wav_path = contained(self.index_path.parent,entry['sourceWav'])
            require(wav_path.name=='speech.wav', 'NOT_ACTUAL_SPEECH_REFERENCE')
            h264_path = contained(self.index_path.parent,str(Path(entry['reference']).parent/'native.h264'))
            result = audit_media_bytes(reference,wav_path,h264_path)
            rows.append({'ordinal':entry['ordinal'], 'attemptId':aid, **result})
        self.report['referenceArtifacts'] = rows
        return {'verified':len(rows),'nativeOriginalRGBStream':'NOT_VERIFIABLE_FROM_LOSSY_H264'}

    def continuity(self):
        turns, satisfied = selected_turns([r for r in self.sql['turns'] if r['session_id']==self.sid],
            self.commits,self.refs,self.plan,self.formal)
        expected_required = [f for beat in self.fixture['plan']['beats'] for f in beat['requiredFactIds']]
        actual_required = [f for beat in self.plan['beats'] for f in beat['requiredFactIds']]
        require(actual_required==expected_required and len(actual_required)==len(set(actual_required)), 'FIXTURE_REQUIRED_FACT_SET_MISMATCH_OR_DUPLICATE')
        authored_groups = [statement['factIds'] for beat in self.fixture['plan']['beats'] for statement in beat['statements']]
        require([s['factIds'] for s in self.plan['segments']]==authored_groups, 'AUTHORED_STATEMENT_FACT_GROUP_OR_ORDER_MISMATCH')
        require(set(expected_required).issubset(self.fixture['facts']), 'REQUIRED_FACT_MEANING_MISSING_FROM_FIXTURE')
        injected = Counter(e['question'] for e in self.observer['events'] if e['kind']=='COMMENT_INJECTED')
        selected = Counter(t['question'] for t in turns.values())
        require(not selected-injected, 'SELECTED_TURN_NOT_FROM_OBSERVED_REPLAY_COMMENT')
        metadata = {row['text']:row for row in self.fixture.get('questionsMetadata',[])}
        for turn in turns.values():
            if turn['question'] in metadata:
                require(set(metadata[turn['question']]['expectedFactIds']).issubset(turn['document_json']['answerFactIds']),
                        'ANSWER_FACT_METADATA_NOT_RELEVANT_TO_QUESTION')
        counts = Counter()
        completed_segments = set()
        narration_order = [c['segment_id'] for c in sorted(self.commits,key=lambda r:r['start_sample']) if c['identity_json']['lane']=='NARRATION']
        plan_order = []
        for segment in self.plan['segments']:
            sql_segment = self.segments[segment['segmentId']]
            require(sql_segment['status']==segment['status'] and sql_segment['text']==segment['text']
                    and sql_segment['text_hash']==segment['textHash'] and sql_segment['fact_ids']==segment['factIds'], 'PLAN_SQL_SEGMENT_PROJECTION_MISMATCH')
            if segment['status']=='COMPLETED':
                require(any(c['segment_id']==segment['segmentId'] and c['identity_json']['lane']=='NARRATION' for c in self.commits), 'COMPLETED_FACT_WITHOUT_MEDIA')
                counts.update(segment['factIds']);completed_segments.add(segment['segmentId']);plan_order.append(segment['segmentId'])
            elif segment['status']=='SATISFIED_BY_ANSWER':
                require(len(satisfied.get(segment['segmentId'],[]))==1, 'UNPROVEN_OR_DUPLICATE_SATISFIED_BY_ANSWER')
                require(not any(c['segment_id']==segment['segmentId'] for c in self.commits), 'SATISFIED_FACT_ALSO_NARRATED')
                counts.update(segment['factIds']);completed_segments.add(segment['segmentId'])
            elif self.formal:
                raise AuditFailure('FORMAL_UNCOMPLETED_PLAN_SEGMENT')
        require(narration_order==plan_order, 'NARRATION_REPLAY_OR_OMITTED_NEXT_POSITION')
        require(all(count<=1 for count in counts.values()), 'REPEATED_COMPLETED_NARRATION_FACT')
        cursor = self.document['cursor']
        require(not cursor.get('ambiguousSegmentIds'), 'AMBIGUOUS_SEMANTIC_CURSOR')
        require(set(cursor['completedSegmentIds'] or [])==completed_segments
                and set(cursor['completedFactIds'] or [])==set(counts), 'DURABLE_CURSOR_MEDIA_COVERAGE_MISMATCH')
        if self.formal:
            require(len(actual_required)==140 and set(actual_required)==set(counts), 'FORMAL_140_UNIQUE_FACT_COVERAGE_INCOMPLETE')
            require(cursor['nextOrdinal']==len(self.plan['segments']), 'FORMAL_CURSOR_NOT_FINISHED')
            require(self.observer['finalNarrationBeforeStop']['reason']=='FINISHED', 'FORMAL_NOT_NATURALLY_FINISHED_BEFORE_STOP')
            require(len(turns)>=5, 'FORMAL_LESS_THAN_FIVE_COMPLETED_SELECTED_TURNS')
            require(selected==injected==Counter(self.fixture['questions']), 'FORMAL_REPLAY_QUESTION_SELECTION_INCOMPLETE')
            duration = self.observer['continuousDurationSeconds']
            require(type(duration) in (int,float) and math.isfinite(duration) and duration>=600,
                    'FORMAL_SESSION_SHORTER_THAN_TEN_MINUTES')
        self.report['factCoverage'] = {'required':len(actual_required),'completedUnique':len(counts),
            'metadataOnly':True,'naturalContinuationPerfect':False,'satisfiedByAnswerSegments':len(satisfied)}
        return {'selectedTerminalTurns':len(turns),'orderedNarrationSegments':len(plan_order),
                'resumeCorrectnessScope':'next authored segment/Beat metadata and completed media order; no human quality claim'}

    def stop(self):
        require(self.observer['normalStop'] is True, 'NORMAL_STOP_UNCONFIRMED')
        sessions = [r for r in self.sql['sessions'] if r['id']==self.sid]
        require(len(sessions)==1 and sessions[0]['status']=='ENDED', 'SESSION_NOT_ENDED')
        runs = [r for r in self.sql['runs'] if r['session_id']==self.sid]
        require(len(runs)==1 and runs[0]['status']=='SEALED' and runs[0]['sealed_at'], 'RUN_NOT_SINGLE_SEALED_INCARNATION')
        require(self.document['runEpoch']==runs[0]['run_epoch'], 'RUN_DOCUMENT_EPOCH_MISMATCH')
        released = [r for r in self.sql['bindingRelease'] if r['sessionId']==self.sid]
        require(released and all(r['released'] is True for r in released), 'BINDING_RELEASE_UNCONFIRMED')
        require(self.narration['state']==self.document['state']=='STOPPED' and self.document['stopBarrier'] is True, 'NARRATION_STOP_BARRIER_UNCONFIRMED')
        if self.formal:
            require(all(a['status']=='COMPLETED' for a in self.attempts.values()), 'FORMAL_UNKNOWN_OR_UNFINISHED_ATTEMPT')
            require(all(c['play_state']=='COMPLETED' for c in self.commits), 'FORMAL_UNKNOWN_PLAY_STATE')
            require(not any(o['operation']=='UNKNOWN' and o['session_id']==self.sid for o in self.sql['observations']), 'FORMAL_UNKNOWN_OBSERVATION')
            require(not any(r['state'].lower()=='unknown' and r['session_id']==self.sid for r in self.sql.get('receipts',[])),
                    'FORMAL_UNKNOWN_DURABLE_RECEIPT')
        require(runs[0]['required_sinks']==self.plan['requiredSinks'], 'RUN_REQUIRED_SINKS_MISMATCH')
        require(all(c['run_epoch']==runs[0]['run_epoch'] for c in self.commits), 'OLD_RUN_EPOCH_MEDIA_POLLUTION')
        return {'normalStop':True,'bindingReleased':True,'runEpoch':runs[0]['run_epoch']}

    def browser(self):
        require(self.chrome['clockDomain']=='chrome_performance_ms' and self.chrome['audienceAudible'] is False,
                'BROWSER_CLOCK_OR_AUDIBILITY_SCOPE_MISMATCH')
        require(self.chrome['recordedBytes']>0 and self.chrome['recordingChunks']>0, 'BROWSER_RECORDING_EMPTY')
        require(type(self.chrome.get('timeOrigin')) in (int,float) and self.chrome['timeOrigin']>0
                and type(self.chrome.get('recordingStartedAt')) in (int,float), 'MISSING_CHROME_CLOCK_ORIGIN', 'NOT_VERIFIABLE')
        require(len(self.chrome['chunkEvents'])==self.chrome['recordingChunks'], 'BROWSER_RECORDING_CHUNK_COUNT_MISMATCH')
        require([r['sequence'] for r in self.chrome['chunkEvents']]==list(range(self.chrome['recordingChunks'])), 'BROWSER_RECORDING_CHUNK_GAP')
        require(self.chrome['recordedBytes']==(self.media/'observer/chrome.webm').stat().st_size, 'BROWSER_RECORDED_FILE_SIZE_MISMATCH')
        require(any(row['rms']>.001 for row in self.chrome['audioEnergy']), 'BROWSER_AUDIO_NOT_OBSERVED')
        expected = {r['ordinal']:self.refs[r['identity']['attemptId']] for r in self.index}
        previous = None;seen = set()
        for row in self.chrome['video']:
            marker = row.get('barcode')
            if marker is None:
                continue
            ordinal, sequence = marker['ordinal'],marker['frameSequence']
            require(marker['layoutRevision']==LAYOUT and ordinal in expected, 'FOREIGN_CHROME_BARCODE')
            require(0<=sequence<len(expected[ordinal]['frames']), 'CHROME_FRAME_SEQUENCE_OUTSIDE_ARTIFACT')
            require(previous is None or (ordinal,sequence)>=previous, 'STALE_OR_REORDERED_CHROME_VIDEO')
            previous = ordinal,sequence;seen.add(ordinal)
        committed_ordinals = {self.refs[c['attempt_id']]['ordinal'] for c in self.commits}
        require(committed_ordinals.issubset(seen), 'COMMITTED_VIDEO_NOT_OBSERVED_IN_CHROME', 'CENSORED')
        return {'decodedCommittedOrdinals':len(committed_ordinals & seen), 'clockDomain':'Chrome performance only',
                'correlatedAV':'NOT_ANALYSED' if not self.correlate else 'SEPARATE_RECORDING_ORACLE'}

    def correlate_recordings(self):
        if not self.correlate:
            raise AuditFailure('RECORDING_CORRELATION_NOT_REQUESTED','NOT_TESTED')
        spec = importlib.util.spec_from_file_location('f_actual_recording_oracle',Path(__file__).with_name('observer_audit.py'))
        oracle = importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
        reports = []
        for label,path in (('chrome',self.media/'observer/chrome.webm'),('rtmp',self.media/'rtmp.flv')):
            require(path.is_file(), 'MISSING_REAL_RECORDING', 'NOT_TESTED')
            markers = oracle.decode_video(path)
            require(not markers['ptsRegressions'], 'RECORDING_VIDEO_PTS_REGRESSION')
            first = {};last = {}
            for marker in markers['markers']:
                key = marker['ordinal'],marker['sequence']
                if last:
                    previous = next(reversed(last.values()))
                    require(key>=previous,'STALE_OR_REORDERED_RECORDED_VIDEO')
                first.setdefault(marker['ordinal'],marker);last[marker['ordinal']] = key
            audio = oracle.audio(path)
            rows = []
            committed = {c['attempt_id'] for c in self.commits}
            for entry in self.index:
                if entry['identity']['attemptId'] not in committed:
                    continue
                marker = first.get(entry['ordinal'])
                if marker is None:
                    rows.append({'ordinal':entry['ordinal'],'status':'CENSORED','code':'VIDEO_NOT_OBSERVED'});continue
                found = oracle.match(oracle.audio(contained(self.index_path.parent,entry['sourceWav'])),audio,marker['seconds'])
                status = found['status']
                expected_last = self.refs[entry['identity']['attemptId']]['stageDescriptor']['descriptor']['last_sequence']
                if marker['sequence']!=0 or last[entry['ordinal']][1]!=expected_last:
                    status = 'CENSORED'
                row = {'ordinal':entry['ordinal'],**found,'status':status,
                    'correlationStatus':found['status'],'videoFirstSeconds':marker['seconds'],
                    'firstObservedSequence':marker['sequence'],'lastObservedSequence':last[entry['ordinal']][1],
                    'expectedLastSequence':expected_last}
                if status=='MATCHED':
                    row['audioMinusVideoMs']=(found['referenceStartSeconds']-marker['seconds'])*1000
                rows.append(row)
            drift = [abs(r['audioMinusVideoMs']) for r in rows if r['status']=='MATCHED']
            reports.append({'recording':label,'clockDomain':'this recording PTS only','rows':rows,
                'statusCounts':dict(Counter(r['status'] for r in rows)),
                'speechPrefixOnsetAbsoluteAudioVideoMs':{'count':len(drift),'P50':percentile(drift,.5),
                    'P95':percentile(drift,.95),'P99':percentile(drift,.99),'max':max(drift) if drift else None,
                    'scope':'actual speech prefix / observation band onset; not phoneme lip-sync drift'},
                'status':'PASS' if rows and all(r['status']=='MATCHED' for r in rows) else 'CONDITIONAL'})
        self.report['recordedAV'] = reports
        require(all(r['status']=='PASS' for r in reports),'AMBIGUOUS_UNRESOLVED_OR_CENSORED_RECORDED_AV','CONDITIONAL')
        return {'recordings':2,'scope':'actual speech-prefix waveform correlation/post-GPU barcode onset, not lip-sync/physical audible/SLA'}

    def run(self):
        if self.check('actual_artifact_shape',self.load):
            bindings = self.check('sql_staging_bindings_and_full_required_sinks',self.bindings)
            self.check('actual_pcm_h264_decoded_emitted_hash_domains',self.byte_references)
            if bindings:
                self.check('selected_turn_answer_resume_and_unique_fact_metadata',self.continuity)
            else:
                self.report['checks'].append({'name':'selected_turn_answer_resume_and_unique_fact_metadata',
                    'status':'NOT_VERIFIABLE','code':'DEPENDENCY_SQL_STAGING_BINDING_UNPROVEN'})
            self.check('normal_stop_and_binding_release',self.stop)
            self.check('actual_chrome_decoded_video_and_recording',self.browser)
            self.check('same_recording_actual_waveform_and_barcode',self.correlate_recordings)
        statuses = {row['status'] for row in self.report['checks']}
        self.report['automatedEvidenceStatus'] = 'FAIL' if 'FAIL' in statuses else 'CONDITIONAL' if statuses-{'PASS'} else 'PASS'
        if getattr(self,'formal',False):
            self.report['formalGolden1'] = 'FAIL' if 'FAIL' in statuses else 'CONDITIONAL_REQUIRES_HUMAN_AV_AND_NATURALNESS_REVIEW'
        elif hasattr(self,'formal'):
            self.report['formalGolden1'] = 'NOT_FORMAL'
        else:
            self.report['formalGolden1'] = 'NOT_VERIFIABLE'
        return self.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir',type=Path,required=True,help='Golden gate root or its media directory')
    parser.add_argument('--fixture',type=Path,required=True,help='exact authored fixture used for this run')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--correlate-recordings',action='store_true')
    args = parser.parse_args()
    report = Auditor(args.artifact_dir,args.fixture,args.correlate_recordings).run()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'automatedEvidenceStatus':report['automatedEvidenceStatus'],'formalGolden1':report['formalGolden1']}))
    return {'PASS':0,'FAIL':1,'CONDITIONAL':2}[report['automatedEvidenceStatus']]


if __name__=='__main__':
    raise SystemExit(main())
