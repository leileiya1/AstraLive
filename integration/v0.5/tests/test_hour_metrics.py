"""Synthetic metadata/oracle rejection tests, never hour/GPU/audience evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

path=Path(__file__).resolve().parents[1]/'hour_metrics.py'
spec=importlib.util.spec_from_file_location('hour_component_metrics',path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fixture():
    a=m.oracle()
    sid='sessionId_1';nid='narrationId_1';required=['preview','rtmp']
    plan={'sessionId':sid,'narrationId':nid,'productSnapshotHash':'captured',
          'requiredSinks':required,'segments':[{'segmentId':'before','beatId':'beat1','status':'COMPLETED','factIds':['name'],'text':'name'},
                                            {'segmentId':'next','beatId':'beat2','status':'COMPLETED','factIds':['stock'],'text':'stock'}]}
    commits=[];index=[]
    for ordinal,(segment,lane,beat) in enumerate((('before','NARRATION','beat1'),('answer','AUDIENCE_ANSWER','beat2'),('next','NARRATION','beat2')),1):
        ident={k:k+'_1' for k in a.contract.IDENTITY_FIELDS}
        ident.update(sessionId=sid,narrationId=nid,runEpoch=1,timelineEpoch=1,generationId=ordinal,
            workerGenerationId=ordinal,segmentId=segment,attemptId='attempt'+str(ordinal),stageId='stage'+str(ordinal),
            lane=lane,beatId=beat,interactionTurnId='turn' if lane=='AUDIENCE_ANSWER' else None)
        business={k:ident[k] for k in a.BUSINESS_FIELDS}
        start,end=(ordinal-1)*16000,ordinal*16000
        receipts=[{'sinkId':sink,'media':media,'identity':copy.deepcopy(business),'startSample':start,'endSample':end,
                   'finalMarker':True,'evidenceType':'sink_consumed','evidenceRef':'software-only'}
                  for sink in required for media in ('audio','video')]
        commits.append({'command_id':ident['commandId']+str(ordinal),'attempt_id':ident['attemptId'],'segment_id':segment,
            'session_id':sid,'run_epoch':1,'identity_json':business,'play_state':'COMPLETED','start_sample':start,'end_sample':end,
            'required_sinks':required,'sink_receipts':receipts,'installed_at':'synthetic','completed_at':'synthetic',
            'completion_hash':'sha256:'+'1'*64,'descriptor_json':{'originalSampleCount':16000}})
        index.append({'ordinal':ordinal,'identity':ident})
    question='有货吗？'
    turn={'turn_id':'turn','session_id':sid,'narration_id':nid,'state':'COMPLETED','question':question,
          'question_hash':a.sha(question.encode()),'document_json':{'interactionTurnId':'turn','state':'COMPLETED',
          'capturedProductHash':'captured','questionHash':a.sha(question.encode()),'answer':{'segmentId':'answer'},
          'answerText':'answer','mappedNarrationFactIds':[],'selectedAt':'2025-01-01T00:00:01.500Z'}}
    sql={'sessions':[{'id':sid,'status':'ENDED'}],'runs':[{'session_id':sid,'status':'SEALED'}],
         'narrations':[{'session_id':sid,'narration_id':nid,'plan_json':{},'document_json':{'plan':plan}}],
         'turns':[turn],'commits':commits,'bindingRelease':[{'released':True}]}
    checkpoints=[{'targetSeconds':t,'elapsedSeconds':t+.1,'browser':{'at':t*1000,'peerCreations':1,
                 'connectionState':'connected','iceConnectionState':'completed','recordingFailed':False}} for t in m.CHECKPOINTS]
    observer={'sessionId':sid,'status':'OBSERVED_PENDING_INDEPENDENT_SQL_AV_QUALITY_AUDIT','normalStop':True,
        'continuousDurationSeconds':3600.5,'requestedSeconds':3600,'browserStopRequestedAt':3601000,
        'checkpoints':checkpoints,'events':[{'kind':'COMMENT_INJECTED','question':question,'browserAt':1}],
        'capturedProviders':{'workerEpoch':'workerEpoch_1'}}
    video=[{'barcode':{'ordinal':i,'frameSequence':0,'layoutRevision':m.LAYOUT},'presentationTime':t,'at':t+1}
           for i,t in ((2,2000),(3,4000))]
    chrome={'clockDomain':'chrome_performance_ms','timeOrigin':1735689600000,'recordingStartedAt':0,'startedAt':0,
            'peerCreations':1,'connectionEvents':[{'at':0,'state':'connected','iceState':'completed'}],
            'recordedBytes':100,'recordingChunks':1,'recordingFailed':False,'video':video}
    avrows=[{'ordinal':i,'status':'MATCHED','correlation':.9,'firstObservedSequence':0,'lastObservedSequence':24,
             'expectedLastSequence':24,'referenceStartSeconds':t+.04,'videoFirstSeconds':t} for i,t in ((2,2),(3,4))]
    audit={'automatedEvidenceStatus':'CONDITIONAL','tailScope':'NOT_FORMAL_CENSORED_TAIL',
           'uncompletedTail':[{'attemptId':'tail','state':'UNKNOWN'}],
           'checks':[{'status':'CONDITIONAL','code':'PRESERVED_ORIGINAL'}],
           'recordedAV':[{'recording':'chrome','rows':avrows}]}
    processes={'goPID':1,'runtimePID':2,'rtmpReceiverPID':3}
    monitor=[{'monitorElapsedSeconds':0,'gpu':{'mode':'gpu','workerEpoch':'workerEpoch_1','gpuAllocatedBytes':10,
              'gpuDeviceMemoryUsedBytes':20,'queueDepth':{'audioSamples':640,'videoFrames':1}},
              'localProcesses':{'columns':['pid','cpuPercent','rssKiB','state'],
                                'rows':[['1','125.5','100','S'],['2','50','200','S'],['3','3','300','S']]}}]
    return sql,observer,chrome,index,audit,monitor,processes


class HourMetricsRejectionTests(unittest.TestCase):
    def test_failed_23_minute_run_cannot_be_upgraded_by_requested_hour(self):
        args=list(fixture());args[1].update(status='FAIL',reason='provider failure',failureElapsedSeconds=1391.268)
        args[1].pop('continuousDurationSeconds');args[1]['checkpoints']=args[1]['checkpoints'][:3];args[2]=None
        result=m.build_metrics(*args)
        self.assertFalse(result['continuousHour']['continuousHour'])
        self.assertEqual(result['continuousHour']['actualObservedSeconds'],1391.268)
        self.assertEqual(result['continuousHour']['status'],'FAIL')
        self.assertEqual(result['originalObserverStatus'],'FAIL')

    def test_reconnection_or_short_recording_span_rejects_hour(self):
        sql,o,c,*_=fixture()
        c['connectionEvents'].append({'at':1800000,'state':'disconnected','iceState':'disconnected'})
        self.assertFalse(m.hour_observation(o,c,sql)['continuousHour'])
        sql,o,c,*_=fixture();c['recordingStartedAt']=3000000
        self.assertFalse(m.hour_observation(o,c,sql)['continuousHour'])

    def test_three_checkpoints_cannot_imply_all_six(self):
        sql,o,c,*_=fixture();o['checkpoints']=o['checkpoints'][:3]
        self.assertIn('SIX_ORDERED_CHECKPOINTS_MISSING',m.hour_observation(o,c,sql)['reasons'])

    def test_running_observer_or_missing_normal_stop_is_not_closed_hour(self):
        sql,o,c,*_=fixture();o['status']='RUNNING'
        self.assertFalse(m.hour_observation(o,c,sql)['continuousHour'])
        sql,o,c,*_=fixture();o.pop('normalStop')
        self.assertFalse(m.hour_observation(o,c,sql)['continuousHour'])

    def test_boolean_peer_count_is_not_one_proven_peer(self):
        sql,o,c,*_=fixture();c['peerCreations']=True
        self.assertFalse(m.hour_observation(o,c,sql)['continuousHour'])

    def test_post_stop_closed_event_is_not_false_midrun_reconnect(self):
        sql,o,c,*_=fixture();c['connectionEvents'].append({'at':3602000,'state':'closed','iceState':'closed'})
        self.assertTrue(m.hour_observation(o,c,sql)['continuousHour'])

    def test_original_failed_gate_and_unknown_tail_are_preserved(self):
        args=list(fixture());args[4]['automatedEvidenceStatus']='FAIL'
        result=m.build_metrics(*args)
        self.assertEqual(result['originalAuditStatus'],'FAIL')
        self.assertEqual(result['originalUncompletedTail'],args[4]['uncompletedTail'])
        self.assertEqual(result['overallAcceptance'],'UNCHANGED_ORIGINAL_GATE; never inferred from component metrics')

    def test_selection_uses_actual_sql_selected_at_and_never_injection_time(self):
        args=list(fixture());result=m.build_metrics(*args)
        estimate=result['questionsAndResume']['rows'][0]['selectedToChromeEstimate']
        self.assertEqual(estimate['status'],'CONDITIONAL_CLOCK_ESTIMATE')
        self.assertAlmostEqual(estimate['selectedToBothCorrelatedAVMs'],540,places=2)
        args[1]['events'][0]['browserAt']=999999
        self.assertEqual(m.build_metrics(*args)['questionsAndResume']['rows'][0]['selectedToChromeEstimate'],estimate)
        args[0]['turns'][0]['document_json'].pop('selectedAt')
        self.assertEqual(m.build_metrics(*args)['questionsAndResume']['rows'][0]['selectedToChromeEstimate']['status'],'NOT_VERIFIABLE')

    def test_recorder_start_is_not_recording_pts_zero_anchor(self):
        args=list(fixture());first=m.build_metrics(*args)['questionsAndResume']['rows'][0]['selectedToChromeEstimate']
        args[2]['recordingStartedAt']=1234567
        second=m.build_metrics(*args)['questionsAndResume']['rows'][0]['selectedToChromeEstimate']
        self.assertEqual(first,second)

    def test_duplicate_barcode_or_censored_recording_keeps_latency_unknown(self):
        args=list(fixture());args[2]['video'].append(copy.deepcopy(args[2]['video'][0]))
        self.assertEqual(m.build_metrics(*args)['questionsAndResume']['rows'][0]['selectedToChromeEstimate']['code'],'MISSING_OR_AMBIGUOUS_RENDER_MARKER')
        args=list(fixture());args[4]['recordedAV'][0]['rows'][0]['status']='CENSORED'
        result=m.build_metrics(*args)
        self.assertEqual(result['questionsAndResume']['rows'][0]['selectedToChromeEstimate']['status'],'NOT_VERIFIABLE')
        self.assertEqual(result['recordedAV']['recordings'][0]['statusCounts']['CENSORED'],1)

    def test_negative_mapping_is_not_clamped_into_fast_latency(self):
        args=list(fixture());args[0]['turns'][0]['document_json']['selectedAt']='2025-01-01T00:10:00Z'
        result=m.build_metrics(*args)
        self.assertEqual(result['questionsAndResume']['rows'][0]['selectedToChromeEstimate']['code'],'NEGATIVE_CLOCK_MAPPED_LATENCY')
        self.assertEqual(result['busyCommentSLA'],'NOT_VERIFIABLE')

    def test_wrong_next_beat_or_partial_sink_is_not_resume_success(self):
        args=list(fixture());args[3][2]['identity']['beatId']='wrong'
        self.assertEqual(m.build_metrics(*args)['questionsAndResume']['rows'][0]['status'],'FAIL')
        args=list(fixture());args[0]['commits'][2]['sink_receipts'].pop()
        self.assertEqual(m.build_metrics(*args)['questionsAndResume']['rows'][0]['status'],'FAIL')

    def test_missing_resume_is_failure_in_failed_run_and_censored_on_planned_stop(self):
        args=list(fixture());args[0]['commits'].pop()
        args[1]['status']='FAIL'
        self.assertEqual(m.build_metrics(*args)['questionsAndResume']['rows'][0]['status'],'FAIL')
        args[1]['status']='OBSERVED_PENDING_INDEPENDENT_SQL_AV_QUALITY_AUDIT'
        self.assertEqual(m.build_metrics(*args)['questionsAndResume']['rows'][0]['status'],'CENSORED')

    def test_unselected_injection_is_not_implicitly_rejected(self):
        args=list(fixture());args[1]['events'].append({'kind':'COMMENT_INJECTED','question':'unmatched'})
        result=m.build_metrics(*args)['questionsAndResume']
        self.assertEqual(result['explicitRejectedTurnCount'],0)
        self.assertEqual(result['unattributedInjectedQuestionCounts'],{'unmatched':1})

    def test_cpu_rss_is_component_sampled_and_cpu_can_exceed_one_core(self):
        *_,monitor,p=fixture();r=m.resource_samples(monitor,p,'workerEpoch_1')
        self.assertEqual(r['localProcesses']['goPID']['maxCPUPercent'],125.5)
        self.assertEqual(r['localProcesses']['runtimePID']['maxRSSBytes'],200*1024)
        self.assertIn('not whole host',r['processScope'])

    def test_foreign_worker_or_cpu_mode_does_not_prove_gpu_peak(self):
        *_,monitor,p=fixture();monitor[0]['gpu']['workerEpoch']='foreign'
        r=m.resource_samples(monitor,p,'workerEpoch_1')
        self.assertIsNone(r['sampledGPUMaxima']['gpuAllocatedBytes'])
        self.assertEqual(r['foreignWorkerOrNonGPUSamplesExcluded'],1)

    def test_unknown_units_and_nonfinite_sampling_are_not_silently_converted(self):
        *_,monitor,p=fixture();monitor[0]['localProcesses']['columns'][2]='rssBytes'
        with self.assertRaises(m.MetricsError):m.resource_samples(monitor,p,'workerEpoch_1')
        *_,monitor,p=fixture();monitor[0]['localProcesses']['rows'][0][1]='NaN'
        with self.assertRaises(m.MetricsError):m.resource_samples(monitor,p,'workerEpoch_1')

    def test_recorded_prefix_offsets_are_not_reported_as_phoneme_sync(self):
        *_,audit,monitor,p=fixture();r=m.av_components(audit)
        self.assertIn('not phoneme lip sync',r['recordings'][0]['scope'])
        self.assertAlmostEqual(r['recordings'][0]['speechPrefixVsObservationBandAbsoluteMs']['max'],40,places=6)

    def test_invalid_old_normalized_score_above_one_is_rejected(self):
        *_,audit,monitor,p=fixture();audit['recordedAV'][0]['rows'][0]['correlation']=88.29
        with self.assertRaises(m.MetricsError):m.av_components(audit)

    def test_missing_stale_counters_are_not_zero(self):
        self.assertEqual(m.build_metrics(*fixture())['staleFrameDrops']['status'],'NOT_VERIFIABLE')

    def test_json_duplicate_keys_and_nan_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data.json'
            for data in ('{"state":1,"state":2}','{"value":NaN}'):
                p.write_text(data)
                with self.assertRaises(m.MetricsError):m.read_closed(p)


if __name__=='__main__':unittest.main()
