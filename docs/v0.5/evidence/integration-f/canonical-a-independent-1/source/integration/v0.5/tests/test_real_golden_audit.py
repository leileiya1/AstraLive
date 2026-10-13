"""Oracle rejection tests only; fabricated inputs NEVER establish real GPU PASS."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import wave

SCRIPT = Path(__file__).resolve().parents[1]/'real_golden_audit.py'
spec = importlib.util.spec_from_file_location('real_golden_oracle',SCRIPT)
audit = importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
from gpu_worker.tests.test_staging_contract import produced


def claimed_reference():
    # Deliberately fabricated provenance to exercise rejection paths only.
    header = produced()
    d = header['descriptor']
    d['provenance']['source']='GPU_INFERENCE'
    d['provenance']['model_source_revision']=audit.NATIVE_MODEL_REVISION
    for key in d['resources']:
        if key.startswith('gpu_'):
            d['resources'][key]=0
    header['descriptor_sha256']=audit.contract.descriptor_hash(d)
    return {'stageDescriptor':header,'identity':copy.deepcopy(header['identity']),
        'scope':'TEST_ONLY_REAL_GPU_OUTPUT_INSTRUMENTATION','layoutRevision':audit.LAYOUT,
        'ordinal':1,'frames':[{'sequence':0,'ptsUs':0}],
        'speechPCMHash':d['pcm_sha256'],'readyContentHash':d['pcm_sha256'],
        'originalSamples':d['original_samples'],'padSamples':d['pad_samples']}


class OracleRejectionTests(unittest.TestCase):
    def assert_rejected(self, code, function):
        with self.assertRaises(audit.AuditFailure) as caught:
            function()
        self.assertEqual(caught.exception.code,code)
        return caught.exception

    def commit(self):
        identity={'sessionId':'s','generationId':1}
        return {'play_state':'COMPLETED','installed_at':'t','completed_at':'t',
            'start_sample':0,'end_sample':640,'identity_json':identity,
            'required_sinks':['chrome','rtmp'],'completion_hash':'sha256:'+'a'*64,
            'sink_receipts':[{'sinkId':sink,'media':media,'startSample':0,'endSample':640,
                'identity':copy.deepcopy(identity),'finalMarker':True,'evidenceType':'sink_consumed','evidenceRef':'receipt'}
                for sink in ('chrome','rtmp') for media in ('audio','video')]}

    def test_legacy_synthetic_sql_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'sql-proof.json').write_text(json.dumps({'document':{},'commits':[]}))
            self.assert_rejected('NOT_ACTUAL_GO_SQL_PROOF_ARRAYS',lambda:audit.Auditor(root,root/'fixture.json').load())

    def test_cpu_provenance_cannot_be_used_as_real_gpu(self):
        reference=claimed_reference()
        d=reference['stageDescriptor']['descriptor'];d['provenance']['source']='CPU_SIMULATION'
        for key in d['resources']:
            if key.startswith('gpu_'):d['resources'][key]=None
        reference['stageDescriptor']['descriptor_sha256']=audit.contract.descriptor_hash(d)
        self.assert_rejected('SYNTHETIC_GPU_PROVENANCE',lambda:audit.stage_descriptor(reference))

    def test_wrong_frozen_descriptor_hash_is_rejected(self):
        reference=claimed_reference();reference['stageDescriptor']['descriptor_sha256']='sha256:'+'f'*64
        with self.assertRaises(audit.contract.ContractError):audit.stage_descriptor(reference)

    def test_unknown_playback_is_not_completion(self):
        commit=self.commit();commit['play_state']='UNKNOWN'
        self.assert_rejected('UNPROVEN_PLAY_STATE',lambda:audit.full_sink_receipts(commit,['chrome','rtmp']))

    def test_missing_video_sink_cannot_pass_with_only_audio(self):
        commit=self.commit();commit['sink_receipts'].pop()
        self.assert_rejected('MISSING_OR_FOREIGN_REQUIRED_SINK_MEDIA',lambda:audit.full_sink_receipts(commit,['chrome','rtmp']))

    def test_partial_tail_is_not_full_contiguous_completion(self):
        commit=self.commit();commit['sink_receipts'][0]['endSample']=639
        self.assert_rejected('SINK_RECEIPT_GAP_OR_PARTIAL_TAIL',lambda:audit.full_sink_receipts(commit,['chrome','rtmp']))

    def test_duplicate_receipt_does_not_replace_missing_sink(self):
        commit=self.commit();commit['sink_receipts'].append(copy.deepcopy(commit['sink_receipts'][0]))
        self.assert_rejected('DUPLICATE_SINK_RECEIPT',lambda:audit.full_sink_receipts(commit,['chrome','rtmp']))

    def test_foreign_receipt_identity_is_rejected(self):
        commit=self.commit();commit['sink_receipts'][0]['identity']['generationId']=2
        self.assert_rejected('SINK_RECEIPT_FOREIGN_IDENTITY',lambda:audit.full_sink_receipts(commit,['chrome','rtmp']))

    def test_source_pcm_hash_must_match_actual_wav_bytes(self):
        reference=claimed_reference()
        with tempfile.TemporaryDirectory() as directory:
            wav=Path(directory)/'speech.wav'
            with wave.open(str(wav),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(bytes(1280))
            self.assert_rejected('ACTUAL_PCM_CONTENT_HASH_MISMATCH',lambda:audit.audit_media_bytes(reference,wav,Path(directory)/'native.h264'))

    def test_packet_boundaries_cannot_be_guessed_from_annex_b(self):
        reference=claimed_reference();d=reference['stageDescriptor']['descriptor']
        pcm=bytes(1280);d['pcm_sha256']=audit.sha(pcm);d['video_bytes']=3
        reference.update(speechPCMHash=audit.sha(pcm),readyContentHash=audit.sha(pcm))
        reference['stageDescriptor']['descriptor_sha256']=audit.contract.descriptor_hash(d)
        with tempfile.TemporaryDirectory() as directory:
            wav=Path(directory)/'speech.wav';video=Path(directory)/'native.h264';video.write_bytes(b'bad')
            with wave.open(str(wav),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(pcm)
            failure=self.assert_rejected('MISSING_ACTUAL_PACKET_BOUNDARIES',lambda:audit.audit_media_bytes(reference,wav,video))
            self.assertEqual(failure.status,'NOT_VERIFIABLE')

    def test_bad_encoded_packet_hash_is_rejected_before_decoder(self):
        reference=claimed_reference();d=reference['stageDescriptor']['descriptor'];pcm=bytes(1280)
        d['pcm_sha256']=audit.sha(pcm);d['video_bytes']=3
        reference.update(speechPCMHash=audit.sha(pcm),readyContentHash=audit.sha(pcm))
        reference['frames'][0].update(payloadBytes=3,payloadSHA256=audit.sha(b'wrong'))
        reference['stageDescriptor']['descriptor_sha256']=audit.contract.descriptor_hash(d)
        with tempfile.TemporaryDirectory() as directory:
            wav=Path(directory)/'speech.wav';video=Path(directory)/'native.h264';video.write_bytes(b'bad')
            with wave.open(str(wav),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(pcm)
            self.assert_rejected('ACTUAL_H264_PACKET_HASH_MISMATCH',lambda:audit.audit_media_bytes(reference,wav,video))

    def test_uncertainty_is_retained_without_logging_exception_values(self):
        auditor=audit.Auditor(Path('/unused'),Path('/unused'))
        def uncertain():raise audit.AuditFailure('AMBIGUOUS_REPEATED_REFERENCE','CONDITIONAL')
        self.assertFalse(auditor.check('uncertainty',uncertain))
        self.assertEqual(auditor.report['checks'][0]['status'],'CONDITIONAL')
        def secret_failure():raise ValueError('secret-token-value')
        auditor.check('bad shape',secret_failure)
        self.assertNotIn('secret-token-value',json.dumps(auditor.report))

    def test_reference_path_cannot_escape_artifact(self):
        self.assert_rejected('REFERENCE_ESCAPES_ARTIFACT',lambda:audit.contained(Path('/tmp/owned'),'../elsewhere'))

    def test_sql_trace_id_cannot_be_rebound_by_self_reported_gpu_identity(self):
        reference=claimed_reference();identity=reference['identity']
        attempt={column:identity[key] for key,column in audit.ATTEMPT_FIELDS.items()}
        commit={'identity_json':{key:identity[key] for key in audit.BUSINESS_FIELDS}}
        segment={'segment_id':identity['segmentId'],'narration_id':identity['narrationId']}
        command={key:identity[key] for key in audit.COMMAND_FIELDS}
        command.update(commandType='COMMIT_SEGMENT',traceId='different-trace')
        self.assert_rejected('SQL_COMMAND_TRACEID_MISMATCH',lambda:audit.bind_identity(reference,commit,attempt,segment,command))

    def test_completed_answer_does_not_make_wrong_resume_segment_correct(self):
        text='可信答复。';question='请回答。'
        answer={'segmentId':'a','lane':'AUDIENCE_ANSWER','status':'COMPLETED',
                'text':text,'textHash':audit.sha(text.encode()),'factIds':[]}
        turn={'interactionTurnId':'t','state':'COMPLETED','question':question,'questionHash':audit.sha(question.encode()),
            'sourceIds':['source'],'capturedProductHash':'product','answer':answer,'answerText':text,
            'answerFactIds':[],'mappedNarrationFactIds':[]}
        row={'turn_id':'t','state':'COMPLETED','question':question,'question_hash':turn['questionHash'],
             'source_ids':['source'],'document_json':turn}
        plan={'productSnapshotHash':'product','segments':[
            {'segmentId':'n0','beatId':'b0','status':'COMPLETED'},
            {'segmentId':'n1','beatId':'b1','status':'PENDING'}]}
        commits=[{'segment_id':sid,'attempt_id':sid,'start_sample':i*640,'end_sample':(i+1)*640,
            'identity_json':{'lane':'AUDIENCE_ANSWER' if sid=='a' else 'NARRATION'},
            'descriptor_json':{'textHash':answer['textHash']}}
            for i,sid in enumerate(('n0','a','wrong-next'))]
        references={'a':{'identity':{'interactionTurnId':'t','lane':'AUDIENCE_ANSWER','beatId':'b1'}}}
        self.assert_rejected('ANSWER_RESUMED_WRONG_NEXT_SEGMENT',lambda:audit.selected_turns([row],commits,references,plan,True))

    def test_selected_unfinished_turn_is_rejected_before_fact_coverage(self):
        row={'turn_id':'t','state':'ANSWERING','document_json':{
            'interactionTurnId':'t','state':'ANSWERING','answer':{'segmentId':'a'}}}
        self.assert_rejected('SELECTED_TURN_NOT_TERMINAL_COMPLETED',lambda:audit.selected_turns([row],[],{}, {'segments':[]},True))

    def test_repeated_waveform_remains_ambiguous(self):
        import numpy as np
        spec=importlib.util.spec_from_file_location('waveform_oracle',SCRIPT.with_name('observer_audit.py'))
        oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
        reference=np.random.default_rng(41).normal(0,.1,8000)
        observed=np.concatenate((np.zeros(8000),reference,np.zeros(8000),reference,np.zeros(8000)))
        result=oracle.match(reference,observed,1)
        self.assertEqual(result['status'],'AMBIGUOUS')


if __name__=='__main__':unittest.main()
