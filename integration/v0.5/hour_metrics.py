#!/usr/bin/env python3
"""Post-run component metrics only; never changes or replaces the original gate.

Consumes closed JSON evidence and existing recording correlation rows. Does not
decode recordings, operate providers, read credentials or turn recv into audible
speech. Source-duration gap and UTC/render clock bridges are explicit estimates.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path

CHECKPOINTS = [90, 300, 900, 1800, 2700, 3600]
LAYOUT = 'astralive-golden-barcode-24-v1'


class MetricsError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code):
    if not value:
        raise MetricsError(code)


def number(value, minimum=0):
    require(type(value) in (int, float) and math.isfinite(value) and value >= minimum, 'INVALID_FINITE_NUMBER')
    return value


def utc_ms(value):
    require(type(value) is str, 'MISSING_ACTUAL_SELECTED_AT')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(dt.tzinfo is not None, 'SELECTED_AT_TIMEZONE_MISSING')
    return number(dt.timestamp()*1000, 1)


def unique(rows, key):
    result = {}
    for row in rows:
        require(row[key] not in result, 'DUPLICATE_'+key.upper())
        result[row[key]] = row
    return result


def quantiles(values):
    values = sorted(values)
    def percentile(q):
        if not values:
            return None
        i = (len(values)-1)*q
        lo, hi = math.floor(i), math.ceil(i)
        return values[lo]+(values[hi]-values[lo])*(i-lo)
    return {'count':len(values), 'P50':percentile(.5), 'P95':percentile(.95),
            'P99':percentile(.99), 'max':max(values) if values else None}


def protected(fn):
    try:
        return fn()
    except Exception as exc:
        return {'status':'NOT_VERIFIABLE', 'code':getattr(exc, 'code', 'MISSING_OR_INVALID_EVIDENCE')}


def oracle():
    path = Path(__file__).with_name('real_golden_audit.py')
    spec = importlib.util.spec_from_file_location('hour_existing_oracle', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def hour_observation(observer, chrome, sql):
    actual = observer.get('continuousDurationSeconds')
    failed_duration = observer.get('failureElapsedSeconds')
    if actual is not None:
        duration, duration_field = number(actual), 'continuousDurationSeconds'
    elif failed_duration is not None:
        duration, duration_field = number(failed_duration), 'failureElapsedSeconds'
    else:
        duration, duration_field = None, None
    checkpoints = observer.get('checkpoints', [])
    targets = [row['targetSeconds'] for row in checkpoints]
    reasons = []
    if observer.get('status') == 'FAIL':reasons.append('ORIGINAL_OBSERVER_FAILED')
    elif observer.get('status') != 'OBSERVED_PENDING_INDEPENDENT_SQL_AV_QUALITY_AUDIT':reasons.append('TERMINAL_OBSERVER_EVIDENCE_MISSING')
    if observer.get('normalStop') is not True:reasons.append('NORMAL_STOP_NOT_CONFIRMED_BY_OBSERVER')
    if duration is None or duration < 3600:reasons.append('OBSERVATION_SHORTER_THAN_HOUR_OR_MISSING')
    if targets != CHECKPOINTS:reasons.append('SIX_ORDERED_CHECKPOINTS_MISSING')
    sid = observer.get('sessionId')
    if len(sql.get('sessions', [])) != 1 or sql['sessions'][0]['id'] != sid:reasons.append('NOT_ONE_SQL_SESSION')
    if len(sql.get('runs', [])) != 1 or sql['runs'][0]['session_id'] != sid:reasons.append('NOT_ONE_SQL_RUN')
    if not chrome:
        reasons.append('CHROME_FINAL_EVIDENCE_MISSING')
    else:
        if type(chrome.get('peerCreations')) is not int or chrome['peerCreations'] != 1:reasons.append('PEER_RECREATED_OR_MISSING')
        stop_at = observer.get('browserStopRequestedAt')
        if stop_at is None:
            reasons.append('STOP_CLOCK_MISSING')
        else:
            stop_at = number(stop_at)
            if stop_at-number(chrome['startedAt']) < 3600000:reasons.append('CHROME_PEER_SPAN_SHORTER_THAN_HOUR')
            if stop_at-number(chrome['recordingStartedAt']) < 3600000:reasons.append('CHROME_RECORDING_SPAN_SHORTER_THAN_HOUR')
            connected = False
            previous = -1
            for event in chrome.get('connectionEvents', []):
                at = number(event['at']);require(at >= previous, 'CONNECTION_EVENT_CLOCK_REGRESSION');previous = at
                if at >= stop_at:continue
                if connected and (event['state'] != 'connected' or event['iceState'] not in ('connected', 'completed')):
                    reasons.append('BROWSER_CONNECTION_INTERRUPTED_BEFORE_STOP')
                connected = connected or event['state'] == 'connected'
            if not connected:reasons.append('CONNECTED_EVENT_MISSING')
        if chrome.get('recordingFailed') or not chrome.get('recordedBytes') or not chrome.get('recordingChunks'):
            reasons.append('RECORDING_FAILED_OR_EMPTY')
    previous_elapsed = previous_at = -1
    for row in checkpoints:
        elapsed, at = number(row['elapsedSeconds']), number(row['browser']['at'])
        if elapsed < row['targetSeconds'] or elapsed < previous_elapsed or at < previous_at:
            reasons.append('CHECKPOINT_CLOCK_OR_ORDER_INVALID')
        previous_elapsed, previous_at = elapsed, at
        b = row['browser']
        if type(b.get('peerCreations')) is not int or b['peerCreations'] != 1 or b.get('connectionState') != 'connected' or b.get('iceConnectionState') not in ('connected', 'completed') or b.get('recordingFailed'):
            reasons.append('CHECKPOINT_PEER_OR_RECORDING_INVALID')
    return {'status':'FAIL' if reasons else 'PASS_OBSERVED_COMPONENT', 'continuousHour':not reasons,
            'actualObservedSeconds':duration, 'durationSource':duration_field,
            'requestedSeconds':observer.get('requestedSeconds'), 'checkpointTargets':targets,
            'checkpoints':checkpoints, 'reasons':sorted(set(reasons)),
            'scope':'single Session/peer/recording observations; not continuous audibility, frame quality or human naturalness'}


def recording_rows(audit, name):
    found = [r for r in (audit or {}).get('recordedAV', []) if r['recording'] == name]
    require(len(found) <= 1, 'DUPLICATE_RECORDING_REPORT')
    return unique(found[0]['rows'], 'ordinal') if found else {}


def selected_av_estimate(turn, entry, row, chrome):
    require(row is not None and row.get('status') == 'MATCHED', 'NONMATCHED_OR_MISSING_RECORDED_AV')
    require(chrome and chrome.get('clockDomain') == 'chrome_performance_ms', 'CHROME_CLOCK_MAPPING_MISSING')
    origin = number(chrome['timeOrigin'], 1)
    selected = utc_ms(turn['document_json'].get('selectedAt'))
    sequence = row['firstObservedSequence']
    require(type(sequence) is int and sequence == 0, 'NONINITIAL_MARKER_CENSORED')
    candidates = [r for r in chrome.get('video', []) if r.get('barcode') ==
                  {'ordinal':entry['ordinal'], 'frameSequence':sequence, 'layoutRevision':LAYOUT}]
    require(len(candidates) == 1, 'MISSING_OR_AMBIGUOUS_RENDER_MARKER')
    video = candidates[0]
    field = 'presentationTime' if video.get('presentationTime') is not None else 'at'
    anchor = number(video[field])
    # Never assume MediaRecorder's first PTS is recorder.start(). This relative
    # difference uses the same ordinal/sequence observation band in each domain.
    delta = number(row['referenceStartSeconds'])-number(row['videoFirstSeconds'])
    score = row.get('correlation')
    require(type(score) in (int,float) and math.isfinite(score) and .65 <= score <= 1.000001,
            'INVALID_WAVEFORM_CORRELATION')
    video_latency = origin+anchor-selected
    audio_latency = origin+anchor+delta*1000-selected
    require(min(video_latency, audio_latency) >= 0, 'NEGATIVE_CLOCK_MAPPED_LATENCY')
    return {'status':'CONDITIONAL_CLOCK_ESTIMATE', 'selectedAt':turn['document_json']['selectedAt'],
            'selectedTimestampSource':'actual SQL Turn.document_json.selectedAt (Go scheduler)',
            'ordinal':entry['ordinal'], 'anchorSequence':sequence, 'anchorField':field,
            'selectedToVideoMs':video_latency, 'selectedToAudioMs':audio_latency,
            'selectedToBothCorrelatedAVMs':max(video_latency, audio_latency),
            'busyAtSelection':'NOT_VERIFIABLE', 'busyCommentSLA':'NOT_VERIFIABLE',
            'assumptions':['same-host Go UTC and Chrome.timeOrigin; independent clock/NTP jumps not calibrated',
                           'matched recording marker identifies the rendered occurrence',
                           'decoded recording audio/video relative timing maps to rendered/audio-device clocks; uncalibrated'],
            'audienceAudible':False}


def transitions(sql, observer, index, audit, chrome):
    a = oracle()
    narrations = [n for n in sql['narrations'] if n['session_id'] == observer['sessionId']]
    require(len(narrations) == 1, 'NARRATION_SCOPE_MISSING_OR_DUPLICATE')
    narration = narrations[0];plan = narration['document_json']['plan']
    commits = sorted([r for r in sql['commits'] if r['session_id'] == observer['sessionId']], key=lambda r:r['start_sample'])
    by_segment = unique(commits, 'segment_id')
    entries = unique(index, 'ordinal');by_attempt = {}
    for entry in entries.values():
        aid = entry['identity']['attemptId']
        require(aid not in by_attempt, 'DUPLICATE_INDEX_ATTEMPT');by_attempt[aid] = entry
    turns = [t for t in sql['turns'] if t['session_id'] == observer['sessionId']]
    unique(turns, 'turn_id')
    canonical = a.canonical_coverage_from_sql(sql, narration, turns, commits)
    chrome_av = recording_rows(audit, 'chrome')
    completed_before = set();covered = set();rows = []
    ordered_turns = sorted(turns, key=lambda t:by_segment.get(t['document_json'].get('answer',{}).get('segmentId'),{}).get('start_sample',math.inf))
    for turn in ordered_turns:
        doc = turn['document_json'];answer = doc.get('answer') or {}
        base = {'turnId':turn['turn_id'], 'question':turn['question'], 'state':turn['state'],
                'selectedAt':doc.get('selectedAt'), 'metadataOnly':True, 'naturalContinuationPerfect':False}
        if turn['state'] != 'COMPLETED':
            rows.append({**base,'status':'NOT_VERIFIABLE','code':'TURN_NOT_COMPLETED'});continue
        try:
            require(doc['interactionTurnId'] == turn['turn_id'] and turn['narration_id'] == plan['narrationId'], 'FOREIGN_TURN_SCOPE')
            require(doc['capturedProductHash'] == plan['productSnapshotHash'], 'FOREIGN_TURN_CAPTURED_VERSION')
            require(a.sha(turn['question'].encode()) == turn['question_hash'] == doc['questionHash'], 'TURN_QUESTION_HASH_MISMATCH')
            ac = by_segment[answer['segmentId']]
            a.full_sink_receipts(ac,plan['requiredSinks'])
            require(ac['identity_json']['lane'] == 'AUDIENCE_ANSWER', 'NOT_ANSWER_MEDIA')
            ae = by_attempt[ac['attempt_id']]
            a.contract.validate_identity(ae['identity'])
            require(ae['identity']['interactionTurnId'] == turn['turn_id'] and ae['identity']['sessionId'] == observer['sessionId'], 'ANSWER_INDEX_TURN_MISMATCH')
            require(ac['identity_json']=={k:ae['identity'][k] for k in a.BUSINESS_FIELDS},'ANSWER_INDEX_BUSINESS_IDENTITY_MISMATCH')
            position = commits.index(ac)
            completed_before.update(c['segment_id'] for c in commits[:position] if c['identity_json']['lane']=='NARRATION' and c['play_state']=='COMPLETED')
            for s in plan['segments']:
                if s['status'] != 'SATISFIED_BY_ANSWER':continue
                lexical = bool(s['factIds']) and set(s['factIds']).issubset(doc.get('mappedNarrationFactIds') or []) and s['text'] in doc['answerText']
                if lexical or turn['turn_id'] in canonical.get(s['segmentId'],[]):covered.add(s['segmentId'])
            expected = next((s for s in plan['segments'] if s['segmentId'] not in completed_before|covered),None)
            following = commits[position+1:]
            nc = next((c for c in following if c['identity_json']['lane']=='NARRATION'),None)
            base['answerSegmentId']=ac['segment_id']
            base['expectedNextSegmentId']=expected['segmentId'] if expected else None
            base['expectedNextBeatId']=expected['beatId'] if expected else None
            base['selectedToChromeEstimate']=protected(lambda:selected_av_estimate(turn,ae,chrome_av.get(ae['ordinal']),chrome))
            if nc is None:
                rows.append({**base,'status':'FAIL' if observer.get('status')=='FAIL' else 'CENSORED','code':'ANSWER_RESUME_NOT_OBSERVED'});continue
            a.full_sink_receipts(nc,plan['requiredSinks'])
            ne = by_attempt[nc['attempt_id']]
            a.contract.validate_identity(ne['identity'])
            require(nc['identity_json']=={k:ne['identity'][k] for k in a.BUSINESS_FIELDS},'RESUME_INDEX_BUSINESS_IDENTITY_MISMATCH')
            require(expected and nc['segment_id']==expected['segmentId'] and ne['identity']['beatId']==expected['beatId'], 'RESUMED_WRONG_SEGMENT_OR_BEAT')
            base.update(nextSegmentId=nc['segment_id'],nextBeatId=ne['identity']['beatId'])
            between = commits[position+1:commits.index(nc)]
            other_answers = [c['segment_id'] for c in between if c['identity_json']['lane']=='AUDIENCE_ANSWER']
            base['interveningAnswerSegments']=other_answers
            answer_row,next_row = chrome_av.get(ae['ordinal']),chrome_av.get(ne['ordinal'])
            if answer_row and next_row and answer_row['status']==next_row['status']=='MATCHED':
                original = number(ac['descriptor_json']['originalSampleCount'])
                gap = (number(next_row['referenceStartSeconds'])-number(answer_row['referenceStartSeconds'])-original/16000)*1000
                base['answerEndToResumeAudio']={'status':'CONDITIONAL_SOURCE_DURATION_ESTIMATE','valueMs':gap,
                    'clockDomain':'same Chrome recording PTS','assumptions':['source nominal playback rate1','prefix match plus original source duration; actual final speech waveform not separately matched']}
            else:base['answerEndToResumeAudio']={'status':'NOT_VERIFIABLE','code':'NONMATCHED_OR_MISSING_RECORDING_ROWS'}
            rows.append({**base,'status':'CONDITIONAL_BATCHED_ANSWERS' if other_answers else 'PASS_METADATA_FULL_REQUIRED_SINKS'})
        except Exception as exc:
            rows.append({**base,'status':'FAIL','code':getattr(exc,'code','TURN_MEDIA_BINDING_UNPROVEN')})
    estimates = [r['selectedToChromeEstimate']['selectedToBothCorrelatedAVMs'] for r in rows
                 if r.get('selectedToChromeEstimate',{}).get('status')=='CONDITIONAL_CLOCK_ESTIMATE']
    injected = Counter(e['question'] for e in observer.get('events',[]) if e['kind']=='COMMENT_INJECTED')
    selected = Counter(t['question'] for t in turns)
    return {'status':'COMPONENT_METADATA_ONLY','rows':rows,'statusCounts':dict(Counter(r['status'] for r in rows)),
            'injectedQuestionCounts':dict(injected),'selectedSQLTurnQuestionCounts':dict(selected),
            'explicitRejectedTurnCount':sum(t['state']=='REJECTED' for t in turns),
            'unattributedInjectedQuestionCounts':dict(injected-selected),
            'unselectedDisposition':'NOT_VERIFIABLE; unselected is not automatically rejected; injection accepted is not scheduler selected',
            'conditionalAllSelectedToChromeBothAVMs':quantiles(estimates),'busyCommentSLA':'NOT_VERIFIABLE',
            'selectionAssociationScope':'actual SQL question hash/turn source IDs; repeated injected text is counted, not falsely mapped to an individual event'}


def resource_samples(monitor, processes, worker_epoch):
    roles = {processes[key]:key for key in ('goPID','runtimePID','rtmpReceiverPID')}
    require(len(roles)==3, 'PROCESS_PIDS_NOT_DISTINCT')
    summaries = {role:{'pid':pid,'samples':0,'maxCPUPercent':None,'maxRSSBytes':None} for pid,role in roles.items()}
    gpu_fields = ('gpuAllocatedBytes','gpuReservedBytes','gpuDeviceMemoryUsedBytes','gpuUtilizationPercent','gpuTemperatureC')
    gpu_values={key:[] for key in gpu_fields};queue_values={'audioSamples':[],'videoFrames':[]}
    foreign=errors=0;previous=-1
    for row in monitor:
        elapsed=number(row['monitorElapsedSeconds']);require(elapsed>=previous,'MONITOR_CLOCK_REGRESSION');previous=elapsed
        if row.get('gpuObservationError'):errors+=1
        gpu=row.get('gpu')
        if gpu:
            if gpu.get('mode')!='gpu' or gpu.get('workerEpoch')!=worker_epoch:foreign+=1
            else:
                for key in gpu_fields:
                    if gpu.get(key) is not None:gpu_values[key].append(number(gpu[key]))
                for key in queue_values:
                    if gpu.get('queueDepth',{}).get(key) is not None:queue_values[key].append(number(gpu['queueDepth'][key]))
        local=row.get('localProcesses')
        if local:
            require(local['columns']==['pid','cpuPercent','rssKiB','state'],'MONITOR_COLUMNS_OR_UNITS_UNKNOWN')
            seen=set()
            for values in local['rows']:
                require(len(values)==4,'MONITOR_PROCESS_SHAPE_INVALID');pid=int(values[0])
                require(pid not in seen,'DUPLICATE_PROCESS_SAMPLE');seen.add(pid)
                require(pid in roles,'FOREIGN_PROCESS_PID')
                cpu=number(float(values[1]));rss=number(int(values[2]))*1024
                stats=summaries[roles[pid]];stats['samples']+=1
                stats['maxCPUPercent']=max(stats['maxCPUPercent'] or 0,cpu)
                stats['maxRSSBytes']=max(stats['maxRSSBytes'] or 0,rss)
    return {'status':'SAMPLED_COMPONENT_MAXIMA' if monitor else 'NOT_VERIFIABLE','sampleCount':len(monitor),
            'localProcesses':summaries,'processScope':'Go/Runtime/RTMP receiver only; not whole host, Chrome, PostgreSQL or publisher FFmpeg',
            'sampledGPUMaxima':{k:max(v) if v else None for k,v in gpu_values.items()},
            'sampledGPUQueueMaxima':{k:max(v) if v else None for k,v in queue_values.items()},
            'foreignWorkerOrNonGPUSamplesExcluded':foreign,'gpuObservationErrors':errors,
            'clockDomain':'monitor local Python monotonic, independent origin; not aligned to comment timestamps',
            'limit':'sampled maxima, not continuous peaks; PID starttime/reuse not verified; monitor origin is unaligned and may include pre/post-run or provider-probe samples'}


def descriptor_resources(sql):
    fields=('gpu_baseline_allocated_bytes','gpu_incremental_allocated_peak_bytes','gpu_incremental_reserved_peak_bytes',
            'worker_rgb_peak_bytes','worker_attempt_peak_bytes')
    values={k:[] for k in fields};missing=0
    for commit in sql.get('commits',[]):
        d=commit.get('descriptor_json',{}).get('stagingDescriptor')
        if not d or d.get('provenance',{}).get('source')!='GPU_INFERENCE':missing+=1;continue
        for field in fields:
            if d['resources'].get(field) is not None:values[field].append(number(d['resources'][field]))
    return {'scope':'Worker original per-attempt descriptor resource claims; separate from device/process monitor, not independent hardware attestation',
            'maxima':{k:max(v) if v else None for k,v in values.items()},'missingOrNonGPUDescriptors':missing}


def av_components(audit):
    result=[]
    for record in (audit or {}).get('recordedAV',[]):
        rows=record['rows'];unique(rows,'ordinal')
        offsets=[]
        for row in rows:
            if row['status']=='MATCHED':
                score=number(row['correlation']);require(.65<=score<=1.000001,'INVALID_WAVEFORM_CORRELATION')
                offsets.append(abs((number(row['referenceStartSeconds'])-number(row['videoFirstSeconds']))*1000))
        result.append({'recording':record['recording'],'clockDomain':'this recording PTS only',
            'statusCounts':dict(Counter(r['status'] for r in rows)),'rows':rows,
            'speechPrefixVsObservationBandAbsoluteMs':quantiles(offsets),
            'scope':'speech-prefix / post-GPU observation band onset; not phoneme lip sync, full-segment drift or audible proof'})
    return {'status':'RECORDED_COMPONENT_ROWS_ONLY' if result else 'NOT_VERIFIABLE','recordings':result}


def build_metrics(sql,observer,chrome,index,audit,monitor,processes):
    original=(audit or {}).get('automatedEvidenceStatus','NOT_VERIFIABLE')
    sql_cleanup={'sessions':[r['status'] for r in sql.get('sessions',[])],
                 'runs':[r['status'] for r in sql.get('runs',[])],
                 'bindingReleased':[r['released'] for r in sql.get('bindingRelease',[])],
                 'failureCleanupObservation':sql.get('failureCleanupObservation')}
    return {'scope':'POST_RUN_COMPONENT_ANALYSIS_ONLY_NOT_REPLACEMENT_ACCEPTANCE_GATE',
            'originalObserverStatus':observer.get('status'),'originalObserverFailure':observer.get('reason') if observer.get('status')=='FAIL' else None,
            'originalAuditStatus':original,'originalAuditChecks':(audit or {}).get('checks',[]),
            'originalTailScope':(audit or {}).get('tailScope','NOT_VERIFIABLE'),
            'originalUncompletedTail':(audit or {}).get('uncompletedTail'),
            'sqlUncompletedAttempts':[{'attemptId':r['attempt_id'],'state':r['status']} for r in sql.get('attempts',[]) if r['status']!='COMPLETED'],
            'sqlUncompletedCommits':[{'attemptId':r['attempt_id'],'playState':r['play_state']} for r in sql.get('commits',[]) if r['play_state']!='COMPLETED'],
            'artifactSource':processes.get('source'),
            'sessionId':observer.get('sessionId'),'humanNaturalness':'NOT_TESTED','audienceAudible':False,
            'continuousHour':protected(lambda:hour_observation(observer,chrome,sql)),
            'questionsAndResume':protected(lambda:transitions(sql,observer,index,audit,chrome)),
            'resources':protected(lambda:resource_samples(monitor,processes,observer['capturedProviders']['workerEpoch'])),
            'descriptorResources':protected(lambda:descriptor_resources(sql)),
            'recordedAV':protected(lambda:av_components(audit)),
            'cleanupMetadata':sql_cleanup,'busyCommentSLA':'NOT_VERIFIABLE',
            'staleFrameDrops':{'status':'NOT_VERIFIABLE','reason':'ManagementStatus/recordedAV exposes no complete stale-drop counter; missing counters never imply zero'},
            'interruptDecisionToLastNarrationSample':'NOT_VERIFIABLE: no independently mapped decision and last sample clock',
            'overallAcceptance':'UNCHANGED_ORIGINAL_GATE; never inferred from component metrics'}


def read_closed(path,jsonl=False):
    path=Path(path)
    require(path.suffix.lower() in ('.json','.jsonl'),'EXPECTED_JSON_METADATA_NOT_RAW_RECORDING')
    before=path.stat();require(before.st_size<=512*1024*1024,'JSON_METADATA_LIMIT')
    data=path.read_bytes();after=path.stat()
    require((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'ARTIFACT_CHANGED_DURING_READ')
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'DUPLICATE_JSON_KEY');result[key]=value
        return result
    def invalid(_):raise MetricsError('NONFINITE_JSON')
    load=lambda text:json.loads(text,object_pairs_hook=pairs,parse_constant=invalid)
    value=[load(line) for line in data.splitlines() if line.strip()] if jsonl else load(data)
    return value,{'path':str(path.resolve()),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('sql','observer','source-index','monitor','processes','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--chrome',type=Path);parser.add_argument('--audit',type=Path)
    parser.add_argument('--closed-artifact',action='store_true',required=True,help='operator confirms the run is stopped and JSON artifacts sealed; never point at a live run')
    args=parser.parse_args();values={};manifest=[]
    for name in ('sql','observer','source_index','monitor','processes','chrome','audit'):
        path=getattr(args,name)
        if path is None:values[name]=None;continue
        values[name],meta=read_closed(path,jsonl=name=='monitor');manifest.append(meta)
    result=build_metrics(values['sql'],values['observer'],values['chrome'],values['source_index'],values['audit'],values['monitor'],values['processes'])
    result['inputManifest']=manifest
    result['rawRecordingPolicy']='not opened, hashed or decoded by this tool; keep external recordings and their existing manifests outside Git'
    result['toolSHA256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'scope':'COMPONENT_REPORT_ONLY','originalObserverStatus':result['originalObserverStatus'],
                     'continuousHour':result['continuousHour'].get('continuousHour',False)}))
    return 0  # Successful analysis is never an acceptance PASS exit code.


if __name__=='__main__':raise SystemExit(main())
