"""Synthetic oracle input tests only; no PostgreSQL, GPU or live Golden claim."""
import copy
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1]/'canonical_coverage_audit.py'
spec = importlib.util.spec_from_file_location('canonical_oracle', path)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def fixture(template='price-subject-1'):
    snapshot = {'productId':'product', 'name':'说明书', 'description':'纯文本<&>\u2028',
                'price':'99.00', 'currency':'CNY', 'stock':'20', 'sizes':'电子版'}
    version = audit.product_snapshot_hash(snapshot)
    text = audit.TEMPLATES[template].replace('{{price}}', snapshot['price'])
    target = {'segmentId':'target', 'textHash':audit.text_hash(text), 'factId':'price', 'templateRevision':template}
    policy = {'policyRevision':'canonical-cny-price-1', 'sessionId':'session', 'narrationId':'narration',
              'runEpoch':1, 'productId':'product', 'productSnapshotHash':version, 'factVersion':version, 'targets':[target]}
    segment = {'segmentId':'target', 'beatId':'beat', 'segmentOrdinal':1, 'text':text,
               'textHash':target['textHash'], 'factIds':['price'], 'lane':'NARRATION', 'status':'PENDING'}
    plan = {'sessionId':'session', 'narrationId':'narration', 'productId':'product',
            'productSnapshotHash':version, 'factVersion':version, 'requiredSinks':['preview','rtmp'],
            'segments':[segment], '_cnyPriceCoveragePolicy':policy}
    current = copy.deepcopy(plan)
    current.pop('_cnyPriceCoveragePolicy')
    current['segments'][0]['status'] = 'SATISFIED_BY_ANSWER'
    narration = {'session_id':'session', 'narration_id':'narration', 'run_epoch':1, 'tenant_id':'tenant',
                 'user_id':'owner', 'plan_json':plan, 'document_json':{'plan':current}}
    answer_text = '这款目前价格是人民币99.00元。'
    answer_hash = audit.text_hash(answer_text)
    identity = {'sessionId':'session', 'runEpoch':1, 'timelineEpoch':2, 'generationId':3,
                'segmentId':'answer', 'utteranceId':'utterance', 'lane':'AUDIENCE_ANSWER',
                'workerEpoch':'synthetic-only', 'workerGenerationId':7}
    sinks = [{'sinkId':sink, 'media':media, 'identity':copy.deepcopy(identity), 'startSample':0,
              'endSample':16000, 'finalMarker':True, 'evidenceType':'sink_consumed',
              'evidenceRef':'synthetic-only'} for sink in plan['requiredSinks'] for media in ('audio','video')]
    commit = {'command_id':'commit', 'session_id':'session', 'run_epoch':1, 'tenant_id':'tenant', 'user_id':'owner',
              'attempt_id':'attempt', 'segment_id':'answer', 'identity_json':identity, 'start_sample':0,
              'end_sample':16000, 'sample_rate':16000, 'required_sinks':plan['requiredSinks'],
              'sink_receipts':sinks, 'play_state':'COMPLETED', 'installed_at':'synthetic', 'completed_at':'synthetic',
              'completion_hash':'sha256:'+'3'*64, 'descriptor_json':{'textHash':answer_hash, 'factIds':['price'],
              'factVersion':version, 'requiredSinks':plan['requiredSinks'], 'sampleCount':16000, 'finalMarker':True}}
    checkpoint = {'identity':{k:identity[k] for k in audit.IDENTITY_KEYS}, 'attemptId':'attempt',
                  'startPosition':{'sessionId':'session', 'runEpoch':1, 'timelineEpoch':2, 'sampleIndex':0,
                                   'sampleRate':16000, 'ptsUs':0},
                  'finalPosition':{'sessionId':'session', 'runEpoch':1, 'timelineEpoch':2, 'sampleIndex':16000,
                                   'sampleRate':16000, 'ptsUs':1000000},
                  'requiredSinks':plan['requiredSinks'], 'sinks':[{'sinkId':sink,'audioStart':0,'audioEnd':16000,
                  'videoStart':0,'videoEnd':16000} for sink in plan['requiredSinks']],
                  'finalMarker':True, 'evidenceRef':'commit:SEGMENT_COMPLETED', 'factVersion':version,
                  'textHash':answer_hash, 'audienceAudible':False}
    decision = {'policy':copy.deepcopy(policy), 'interactionTurnId':'turn', 'phase':'FULFILLED',
                'answerPreparedCommandId':'prepare', 'answerPreparedObservationHash':'sha256:'+'1'*64,
                'answerSegmentId':'answer', 'answerTextHash':answer_hash, 'mappedFactIds':['price'],
                'completionCommandId':'commit', 'completionProofHash':commit['completion_hash'],
                'completedCheckpoint':checkpoint, 'appliedTargetSegmentIds':['target']}
    turn = {'turn_id':'turn', 'session_id':'session', 'narration_id':'narration', 'tenant_id':'tenant', 'user_id':'owner',
            'state':'COMPLETED', 'document_json':{'interactionTurnId':'turn', 'state':'COMPLETED',
            'capturedProductHash':version, 'mappedNarrationFactIds':['price'], 'answerFactIds':['price'],
            'answerText':answer_text, 'answer':{'segmentId':'answer', 'text':answer_text, 'textHash':answer_hash,
            'factIds':['price'], 'lane':'AUDIENCE_ANSWER', 'status':'COMPLETED'}, '_cnyPriceCoverageDecision':decision}}
    command = {'commandId':'prepare', 'sessionId':'session', 'runEpoch':1, 'traceId':'trace',
               'commandType':'START_AUDIENCE_ANSWER', 'narrationId':'narration', 'tenantId':'tenant', 'userId':'owner',
               'interactionTurnId':'turn', 'answerText':answer_text, 'factIds':['price'], 'productSnapshotHash':version}
    observations, receipts = [], []
    for cmd, operation, state, seq, marker in (('prepare','ANSWER_PREPARED','ready',1,'1'),
                                               ('commit','COMMIT_INSTALLED','committed',3,'2'),
                                               ('commit','SEGMENT_COMPLETED','completed',5,'3')):
        ack = {'durable':True, 'state':state, 'receiptSeq':seq, 'observationHash':'sha256:'+marker*64,
               'producerIncarnation':'synthetic-runtime-incarnation'}
        obs = {'command_id':cmd, 'operation':operation, 'observation_hash':ack['observationHash'],
               'response_json':ack, 'session_id':'session', 'run_epoch':1, 'tenant_id':'tenant', 'user_id':'owner'}
        if operation == 'ANSWER_PREPARED':
            obs['preparedProof'] = {'text':answer_text, 'factIds':['price'], 'productSnapshotHash':version}
        observations.append(obs)
        receipts.append({'command_id':cmd, 'evidence_type':'timeline_journal', 'evidence_ref':operation,
                         'session_id':'session', 'run_epoch':1, 'tenant_id':'tenant', 'user_id':'owner',
                         'receipt_seq':seq, 'producer_incarnation':ack['producerIncarnation'],
                         'observation_hash':ack['observationHash'], 'state':state})
    return [narration, [turn], [commit], observations, receipts, [command]], snapshot


class CanonicalEvidenceRejectionTests(unittest.TestCase):
    def call(self, args, snapshot):
        return audit.validated_cny_price_coverage(*args, product_snapshot=snapshot)

    def rejected(self, args, snapshot, code=None):
        with self.assertRaises(audit.CoverageAuditError) as caught:
            self.call(args,snapshot)
        if code:
            self.assertEqual(caught.exception.code,code)

    def test_both_finite_templates_accept_only_full_recorded_proof(self):
        for template in ('price-subject-1','price-answer-wording-1'):
            with self.subTest(template=template):
                args,snapshot=fixture(template)
                self.assertEqual(self.call(args,snapshot), {'target':['turn']})

    def test_old_plan_without_private_policy_cannot_be_upgraded(self):
        args,snapshot=fixture()
        args[0]['plan_json'].pop('_cnyPriceCoveragePolicy')
        args[1][0]['document_json'].pop('_cnyPriceCoverageDecision')
        self.assertEqual(self.call(args,snapshot),{})

    def test_private_decision_without_recorded_policy_is_rejected(self):
        args,snapshot=fixture();args[0]['plan_json'].pop('_cnyPriceCoveragePolicy')
        self.rejected(args,snapshot,'CANONICAL_ORPHAN_DECISION_WITHOUT_POLICY')

    def test_custom_claim_cannot_be_authorized_by_resigning_its_text_hash(self):
        for claim in ('本商品优惠标价是人民币99.00元。','本商品当前标价是人民币99.00元。购买后保证有效。',' 本商品当前标价是人民币99.00元。'):
            with self.subTest(claim=claim):
                args,snapshot=fixture()
                for s in (args[0]['plan_json']['segments'][0], args[0]['document_json']['plan']['segments'][0]):
                    s['text']=claim;s['textHash']=audit.text_hash(claim)
                args[0]['plan_json']['_cnyPriceCoveragePolicy']['targets'][0]['textHash']=audit.text_hash(claim)
                self.rejected(args,snapshot,'CANONICAL_NONEXACT_TARGET_CLAIM')

    def test_extra_answer_claim_is_rejected_even_with_resigned_text(self):
        args,snapshot=fixture();turn=args[1][0]['document_json']
        turn['answerText']=turn['answer']['text']+'这款保证有效。'
        turn['answer']['text']=turn['answerText']
        turn['answer']['textHash']=audit.text_hash(turn['answerText'])
        turn['_cnyPriceCoverageDecision']['answerTextHash']=turn['answer']['textHash']
        self.rejected(args,snapshot,'CANONICAL_NONEXACT_OR_UNCOMPLETED_ANSWER')

    def test_non_cny_snapshot_cannot_grant_price_coverage(self):
        args,snapshot=fixture();snapshot['currency']='USD'
        self.rejected(args,snapshot,'CANONICAL_CAPTURED_PRODUCT_MISMATCH')

    def test_changed_final_product_value_does_not_prove_captured_version(self):
        args,snapshot=fixture();snapshot['price']='100.00'
        self.rejected(args,snapshot,'CANONICAL_CAPTURED_PRODUCT_MISMATCH')

    def test_nonfinite_price_is_not_a_canonical_price(self):
        args,snapshot=fixture();snapshot['price']='NaN'
        self.rejected(args,snapshot,'CANONICAL_NONFINITE_PRICE')

    def test_target_or_answer_cannot_include_another_fact(self):
        for where in ('target','answer','mapping'):
            args,snapshot=fixture()
            if where=='target':args[0]['plan_json']['segments'][0]['factIds'].append('stock')
            elif where=='answer':args[1][0]['document_json']['answerFactIds'].append('stock')
            else:args[1][0]['document_json']['mappedNarrationFactIds'].append('stock')
            with self.subTest(where=where):self.rejected(args,snapshot)

    def test_unfulfilled_decision_or_turn_does_not_grant_coverage(self):
        for phase in ('PREPARED','UNKNOWN'):
            args,snapshot=fixture();args[1][0]['document_json']['_cnyPriceCoverageDecision']['phase']=phase
            with self.subTest(phase=phase):self.rejected(args,snapshot,'CANONICAL_UNFULFILLED_OR_FOREIGN_DECISION')
        args,snapshot=fixture();args[1][0]['state']='UNKNOWN'
        self.rejected(args,snapshot,'CANONICAL_FOREIGN_OR_UNFINISHED_TURN')

    def test_unknown_or_partial_playback_cannot_be_completed_by_labels(self):
        args,snapshot=fixture();args[2][0]['play_state']='UNKNOWN'
        self.rejected(args,snapshot,'CANONICAL_UNCOMPLETED_ANSWER')
        args,snapshot=fixture();args[2][0]['sink_receipts'][0]['endSample']-=1
        self.rejected(args,snapshot,'CANONICAL_PARTIAL_OR_UNPROVEN_SINK')

    def test_missing_and_duplicate_sink_receipts_do_not_replace_required_video(self):
        args,snapshot=fixture();args[2][0]['sink_receipts'].pop()
        self.rejected(args,snapshot,'CANONICAL_MISSING_OR_FOREIGN_SINK')
        args,snapshot=fixture();args[2][0]['sink_receipts'].append(copy.deepcopy(args[2][0]['sink_receipts'][0]))
        self.rejected(args,snapshot,'CANONICAL_DUPLICATE_SINK_RECEIPT')

    def test_prepared_command_must_be_the_recorded_original(self):
        args,snapshot=fixture();args[1][0]['document_json']['_cnyPriceCoverageDecision']['answerPreparedCommandId']='invented'
        self.rejected(args,snapshot)
        args,snapshot=fixture();args[5][0]['interactionTurnId']='foreign'
        self.rejected(args,snapshot,'CANONICAL_PREPARED_COMMAND_MISMATCH')

    def test_prepared_text_or_snapshot_cannot_be_rebound(self):
        for key,value in (('text','不同价格'),('productSnapshotHash','sha256:'+'0'*64),('factIds',['stock'])):
            args,snapshot=fixture();args[3][0]['preparedProof'][key]=value
            with self.subTest(key=key):self.rejected(args,snapshot,'CANONICAL_PREPARED_PROOF_MISMATCH')

    def test_private_forged_hash_is_not_a_sql_observation(self):
        args,snapshot=fixture();args[1][0]['document_json']['_cnyPriceCoverageDecision']['answerPreparedObservationHash']='sha256:'+'f'*64
        self.rejected(args,snapshot,'CANONICAL_PREPARED_PROOF_MISMATCH')

    def test_hash_match_without_actual_matching_receipt_is_not_proof(self):
        args,snapshot=fixture();args[4][0]['observation_hash']='sha256:'+'f'*64
        self.rejected(args,snapshot,'CANONICAL_RECEIPT_ACK_MISMATCH')
        args,snapshot=fixture();args[4].pop(0)
        self.rejected(args,snapshot,'CANONICAL_MISSING_OR_DUPLICATE_JOURNAL_RECEIPT')

    def test_foreign_owner_and_run_are_rejected_at_each_evidence_layer(self):
        for index,owner_key in ((1,'user_id'),(2,'tenant_id'),(3,'user_id'),(4,'tenant_id'),(5,'userId')):
            args,snapshot=fixture();args[index][0][owner_key]='foreign'
            with self.subTest(index=index):self.rejected(args,snapshot,'CANONICAL_FOREIGN_SCOPE')
        args,snapshot=fixture();args[5][0]['runEpoch']=2
        self.rejected(args,snapshot,'CANONICAL_FOREIGN_SCOPE')

    def test_false_integer_cannot_impersonate_run_or_receipt_sequence(self):
        args,snapshot=fixture();args[2][0]['identity_json']['generationId']=True
        self.rejected(args,snapshot,'CANONICAL_INVALID_INTEGER')
        args,snapshot=fixture();args[4][0]['receipt_seq']=True
        self.rejected(args,snapshot,'CANONICAL_INVALID_INTEGER')

    def test_actual_receipt_producer_and_sequence_must_match_ack(self):
        for key,value in (('producer_incarnation','foreign-runtime'),('receipt_seq',100)):
            args,snapshot=fixture();args[4][0][key]=value
            with self.subTest(key=key):self.rejected(args,snapshot,'CANONICAL_RECEIPT_ACK_MISMATCH')

    def test_completion_cannot_use_another_producer_or_nonadvancing_seq(self):
        for field,value in (('producerIncarnation','other-runtime'),('receiptSeq',3)):
            args,snapshot=fixture();args[3][2]['response_json'][field]=value
            with self.subTest(field=field):self.rejected(args,snapshot,'CANONICAL_COMPLETION_PROOF_MISMATCH')

    def test_private_completion_hash_must_equal_actual_completion_and_sql(self):
        args,snapshot=fixture();args[1][0]['document_json']['_cnyPriceCoverageDecision']['completionProofHash']='sha256:'+'f'*64
        self.rejected(args,snapshot,'CANONICAL_COMPLETION_PROOF_MISMATCH')

    def test_checkpoint_must_bind_exact_identity_attempt_positions_and_full_sinks(self):
        for field in ('identity','attemptId','finalPosition','sinks'):
            args,snapshot=fixture();p=args[1][0]['document_json']['_cnyPriceCoverageDecision']['completedCheckpoint']
            if field=='identity':p[field]['timelineEpoch']=1
            elif field=='attemptId':p[field]='foreign-attempt'
            elif field=='finalPosition':p[field]['ptsUs']+=1
            else:p[field][0]['audioEnd']-=1
            with self.subTest(field=field):self.rejected(args,snapshot)

    def test_duplicate_targets_or_applied_ids_are_not_multiple_coverage(self):
        args,snapshot=fixture();policy=args[0]['plan_json']['_cnyPriceCoveragePolicy'];policy['targets']*=2
        self.rejected(args,snapshot,'CANONICAL_DUPLICATE_OR_MISSING_TARGET')
        args,snapshot=fixture();args[1][0]['document_json']['_cnyPriceCoverageDecision']['appliedTargetSegmentIds']*=2
        self.rejected(args,snapshot,'CANONICAL_DUPLICATE_OR_FOREIGN_APPLIED_TARGET')

    def test_foreign_applied_target_and_extra_private_claim_are_rejected(self):
        args,snapshot=fixture();args[1][0]['document_json']['_cnyPriceCoverageDecision']['appliedTargetSegmentIds']=['other']
        self.rejected(args,snapshot,'CANONICAL_DUPLICATE_OR_FOREIGN_APPLIED_TARGET')
        args,snapshot=fixture();args[1][0]['document_json']['_cnyPriceCoverageDecision']['extraClaim']='free shipping'
        self.rejected(args,snapshot,'CANONICAL_UNFULFILLED_OR_FOREIGN_DECISION')

    def test_satisfied_status_without_fulfilled_mapping_does_not_prove_coverage(self):
        args,snapshot=fixture();args[1]=[]
        self.rejected(args,snapshot,'CANONICAL_SATISFIED_TARGET_WITHOUT_PROOF')

    def test_empty_applied_targets_proves_no_coverage(self):
        args,snapshot=fixture();args[1][0]['document_json']['_cnyPriceCoverageDecision'].pop('appliedTargetSegmentIds')
        args[0]['document_json']['plan']['segments'][0]['status']='PENDING'
        self.assertEqual(self.call(args,snapshot),{})

    def test_target_already_committed_cannot_also_be_satisfied_by_answer(self):
        args,snapshot=fixture();extra=copy.deepcopy(args[2][0]);extra.update(command_id='other',segment_id='target')
        args[2].append(extra)
        self.rejected(args,snapshot,'CANONICAL_TARGET_ALREADY_COMMITTED')

    def test_missing_safe_projection_is_uncertainty_not_inferred_pass(self):
        args,snapshot=fixture();args[3][0].pop('preparedProof')
        self.rejected(args,snapshot,'CANONICAL_MALFORMED_OR_MISSING_EVIDENCE')

    def test_two_distinct_complete_turns_cannot_both_map_the_same_target(self):
        args,snapshot=fixture();second,_=fixture()
        turn=second[1][0];turn['turn_id']='turn-2'
        doc=turn['document_json'];doc['interactionTurnId']='turn-2'
        doc['answer']['segmentId']='answer-2'
        d=doc['_cnyPriceCoverageDecision']
        d.update(interactionTurnId='turn-2',answerPreparedCommandId='prepare-2',
                 answerSegmentId='answer-2',completionCommandId='commit-2')
        d['completedCheckpoint'].update(attemptId='attempt-2',evidenceRef='commit-2:SEGMENT_COMPLETED')
        d['completedCheckpoint']['identity'].update(segmentId='answer-2',utteranceId='utterance-2')
        commit=second[2][0];commit.update(command_id='commit-2',segment_id='answer-2',attempt_id='attempt-2')
        commit['identity_json'].update(segmentId='answer-2',utteranceId='utterance-2')
        for sink in commit['sink_receipts']:sink['identity']=copy.deepcopy(commit['identity_json'])
        second[5][0].update(commandId='prepare-2',interactionTurnId='turn-2')
        for rows in (second[3],second[4]):
            for row in rows:row['command_id']+='-2'
        for index in range(1,6):args[index].extend(second[index])
        self.rejected(args,snapshot,'CANONICAL_DUPLICATE_TARGET_MAPPING')

    def test_hash_domain_preserves_unicode_html_and_sorted_keys(self):
        # Independently specified Go durability.Canonical byte representation.
        args,snapshot=fixture()
        expected='{"currency":"CNY","description":"纯文本<&>\u2028","name":"说明书","price":"99.00","productId":"product","sizes":"电子版","stock":"20"}'
        import hashlib
        want='sha256:'+hashlib.sha256(expected.encode('utf-8')).hexdigest()
        self.assertEqual(audit.product_snapshot_hash(snapshot),want)
        self.assertEqual(audit.product_snapshot_hash(dict(reversed(list(snapshot.items())))),want)

    def test_snapshot_cannot_add_fact_labels_or_replace_decimal_strings_with_numbers(self):
        args,snapshot=fixture();snapshot['claims']='guaranteed'
        self.rejected(args,snapshot,'CANONICAL_INVALID_PRODUCT_SNAPSHOT')
        args,snapshot=fixture();snapshot['price']=99.0
        self.rejected(args,snapshot,'CANONICAL_INVALID_PRODUCT_SNAPSHOT')


if __name__=='__main__':unittest.main()
