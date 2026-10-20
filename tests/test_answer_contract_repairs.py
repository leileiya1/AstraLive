"""PR9 owner-review regressions. Synthetic contract oracle, not SQL/media tests."""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import tests.test_durable_answer_contracts as original

r=original.r
c=original.c

class AnswerRepairTests(unittest.TestCase):
    def setUp(self):
        self.case=original.AnswerContractTests();self.case.setUp()
        self.j=self.case.j

    def drain_request(self,index=0):
        q=copy.deepcopy(self.case.rows['JournalConfirmAnswerSegment']['request'])
        a=self.case.artifacts[index]
        q.update(artifactId=a['artifactId'],artifactHash=a['artifactHash'],idempotencyKey='drain:'+a['artifactId'],expectedAnswerRevision=self.j.answer_revision)
        if index:
            for p in q['evidence']['sinkProofs']:
                p.update(firstAudioSample=84000*index,finalAudioSampleExclusive=84000*(index+1),audioConsumedThroughExclusive=84000*(index+1),finalVideoFrame=87*(index+1),videoConsumedThroughFrame=87*(index+1))
        return q

    def test_delayed_unit2_after_trusted_drain(self):
        self.case.prepare_and_start();self.case.drain()
        result=self.case.prepare_second()
        self.assertTrue(result['prepared'])
        self.assertEqual(self.j.command_start_count,1)

    def test_prepare_alias_key_cannot_be_reassigned(self):
        self.case.prepare_and_start()
        q=copy.deepcopy(self.case.prepare);q['idempotencyKey']='alias_key'
        self.j.prepare(q)
        q.update(artifact=copy.deepcopy(self.case.artifacts[1]),expectedInboxRevision=self.j.inbox_revision,expectedAnswerRevision=self.j.answer_revision)
        with self.assertRaisesRegex(r.Rejected,'ANSWER_CONFLICT'):self.j.prepare(q)

    def test_drain_receipt_cannot_cross_artifacts(self):
        self.case.prepare_and_start();self.case.prepare_second()
        q=self.drain_request();self.j.drain(q)
        q.update(artifactId=self.case.artifacts[1]['artifactId'],artifactHash=self.case.artifacts[1]['artifactHash'],expectedAnswerRevision=self.j.answer_revision)
        with self.assertRaisesRegex(r.Rejected,'ANSWER_CONFLICT'):self.j.drain(q)
        self.assertEqual(self.j.units[1]['state'],'PREPARED')

    def test_grant_models_consume_deadline_instead_of_opaque_string(self):
        grant=self.case.prepare_and_start()['answerGrant']
        self.assertIsInstance(grant,dict)
        c.validate('AnswerGrant',grant)

    def test_prepare_before_drain_preserves_single_start_and_turn(self):
        command=copy.deepcopy(self.j.command)
        self.case.prepare_and_start();self.case.prepare_second();self.case.drain()
        self.assertEqual(self.j.units[0]['state'],'DRAINED')
        self.assertEqual(self.j.units[1]['state'],'PREPARED')
        self.assertEqual(self.j.command,command)
        self.assertEqual(self.j.command_start_count,1)
        q=copy.deepcopy(self.case.rows['JournalStartAnswerSegment']['request'])
        q['expectedAnswerRevision']=self.j.answer_revision
        self.assertTrue(self.j.start_segment(q)['segmentStartAuthorized'])
        self.assertEqual(self.j.command_start_count,1)

    def test_drain_before_prepare_continuation_uses_trusted_boundary(self):
        self.case.prepare_and_start();self.case.drain();self.case.prepare_second()
        q=copy.deepcopy(self.case.rows['JournalStartAnswerSegment']['request'])
        q['expectedAnswerRevision']=self.j.answer_revision
        self.assertTrue(self.j.start_segment(q)['segmentStartAuthorized'])
        self.assertEqual(self.j.command_start_count,1)

    def test_forged_drained_projection_cannot_grant_prepared_unit2(self):
        self.case.prepare_and_start();self.case.prepare_second()
        self.j.units[0]['state']='DRAINED'
        q=copy.deepcopy(self.case.rows['JournalStartAnswerSegment']['request'])
        q['expectedAnswerRevision']=self.j.answer_revision
        with self.assertRaisesRegex(r.Rejected,'EVIDENCE_CONFLICT'):self.j.start_segment(q)
        self.assertEqual(self.j.units[1]['state'],'PREPARED')
        self.assertEqual(len(self.j.grants),1)

    def test_untrusted_or_ineligible_predecessor_never_allows_prepare(self):
        for state in ('PREPARED','UNKNOWN','INTERRUPTED','DRAINED'):
            with self.subTest(state=state):
                self.setUp();self.case.prepare_and_start()
                self.j.units[0]['state']=state  # DRAINED without a trusted proof is forged
                with self.assertRaises(r.Rejected):self.case.prepare_second()
                self.assertEqual(len(self.j.units),1)

    def test_prepare_drain_concurrent_cas_loser_rereads(self):
        for _ in range(8):
            self.setUp();self.case.prepare_and_start()
            prepare=copy.deepcopy(self.case.prepare)
            prepare.update(artifact=copy.deepcopy(self.case.artifacts[1]),idempotencyKey='prepare:unit2',expectedInboxRevision=self.j.inbox_revision,expectedAnswerRevision=self.j.answer_revision)
            drain=self.drain_request();barrier=Barrier(2)
            def invoke(name,q):
                barrier.wait()
                try:return name,True,(self.j.prepare(q) if name=='prepare' else self.j.drain(q))
                except r.Rejected as e:return name,False,str(e)
            with ThreadPoolExecutor(max_workers=2) as pool:
                a=pool.submit(invoke,'prepare',prepare);b=pool.submit(invoke,'drain',drain)
                results=[a.result(),b.result()]
            self.assertEqual(sum(x[1] for x in results),1)
            loser=next(x for x in results if not x[1]);self.assertEqual(loser[2],'STATE_CONFLICT')
            q=prepare if loser[0]=='prepare' else drain
            q['expectedAnswerRevision']=self.j.answer_revision
            (self.j.prepare if loser[0]=='prepare' else self.j.drain)(q)
            self.assertEqual([u['state'] for u in self.j.units],['DRAINED','PREPARED'])
            self.assertEqual(self.j.command_start_count,1)

    def test_prepare_alias_remains_bound_after_drain(self):
        self.case.prepare_and_start()
        q=copy.deepcopy(self.case.prepare);q['idempotencyKey']='alias'
        receipt=self.j.prepare(q);self.case.drain()
        q.update(expectedAnswerRevision=999,requestId='retry_correlation')
        self.assertEqual(self.j.prepare(q),receipt)
        q.update(artifact=copy.deepcopy(self.case.artifacts[1]),expectedInboxRevision=self.j.inbox_revision,expectedAnswerRevision=self.j.answer_revision)
        with self.assertRaisesRegex(r.Rejected,'ANSWER_CONFLICT'):self.j.prepare(q)
        self.assertEqual(self.j.prepare_receipts['alias'][0]['artifactId'],'answer_unit_1')

    def test_concurrent_prepare_alias_can_bind_only_one_artifact(self):
        self.case.prepare_and_start();barrier=Barrier(2)
        q1=copy.deepcopy(self.case.prepare);q1['idempotencyKey']='shared_alias'
        q2=copy.deepcopy(q1);q2.update(artifact=copy.deepcopy(self.case.artifacts[1]),expectedInboxRevision=self.j.inbox_revision,expectedAnswerRevision=self.j.answer_revision)
        def call(q):
            barrier.wait()
            try:self.j.prepare(q);return True
            except r.Rejected as e:self.assertEqual(str(e),'ANSWER_CONFLICT');return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(call,[q1,q2]))
        self.assertEqual(sum(results),1)
        self.assertIn('shared_alias',self.j.prepare_receipts)

    def test_drain_duplicate_ignores_only_correlation_and_expected_revision(self):
        self.case.prepare_and_start();q=self.drain_request()
        receipt=self.j.drain(q)
        retry=copy.deepcopy(q);retry.update(requestId='retry_request',expectedAnswerRevision=999)
        self.assertEqual(self.j.drain(retry),receipt)
        self.assertEqual(receipt['artifactId'],q['artifactId'])
        self.assertEqual(receipt['drainIdentityHash'],c.digest(r.drain_identity(q)))

    def test_drain_key_hash_answer_and_evidence_changes_conflict(self):
        self.case.prepare_and_start();q=self.drain_request();self.j.drain(q)
        for kind in ('artifactHash','answerId','evidence'):
            with self.subTest(kind=kind):
                retry=copy.deepcopy(q)
                if kind=='artifactHash':retry[kind]='f'*64
                elif kind=='answerId':retry[kind]='different_answer'
                else:retry['evidence']['evidenceRef']='different_proof'
                with self.assertRaisesRegex(r.Rejected,'ANSWER_CONFLICT'):self.j.drain(retry)

    def test_consumed_grant_survives_five_seconds_with_new_permits_and_facts(self):
        grant=self.case.prepare_and_start()['answerGrant'];artifact='answer_unit_1'
        self.j.now+=.1;self.j.begin_tts(artifact,grant)
        original_grant=copy.deepcopy(grant);initial_observations=copy.deepcopy(self.j.observations)
        initial=self.j.now-.1;permit_ids=set()
        for offset in (.5,1.,1.5,2.,2.5,3.,3.5,4.,4.5,5.):
            self.j.now=initial+offset
            if offset in (1.5,3.,4.5):self.j.refresh_facts(artifact,grant=grant)
            permit=self.j.renew_permit(artifact,grant=grant);permit_ids.add(permit['permitId'])
            self.assertEqual(self.j.handoff(artifact,grant),self.case.artifacts[0]['answerText'])
        self.assertGreater(len(permit_ids),1)
        self.assertEqual(grant,original_grant)
        for key,value in initial_observations.items():self.assertEqual(self.j.observations[key],value)
        self.assertEqual(self.j.grant_states[grant['grantId']],'CONSUMED')
        self.assertEqual(self.j.command_start_count,1)
        with self.assertRaisesRegex(r.Rejected,'RECOVERY_UNKNOWN'):self.j.begin_tts(artifact,grant)
        self.case.drain();self.assertEqual(self.j.units[0]['state'],'DRAINED')

    def test_renewed_proofs_never_resurrect_unconsumed_expired_grant(self):
        grant=self.case.prepare_and_start()['answerGrant'];self.j.now+=.9
        self.j.refresh_facts('answer_unit_1',grant=grant)
        self.j.renew_permit('answer_unit_1',grant=grant)
        with self.assertRaisesRegex(r.Rejected,'GRANT_EXPIRED'):self.j.begin_tts('answer_unit_1',grant)
        self.assertNotIn('answer_unit_1',self.j.tts_started)
        self.assertEqual(self.j.units[0]['state'],'UNKNOWN')
        self.assertFalse(self.j.start(self.case.start)['startAuthorized'])

    def test_late_global_start_ack_cannot_start(self):
        self.test_renewed_proofs_never_resurrect_unconsumed_expired_grant()

    def test_continuation_ack_loss_never_mints_second_grant(self):
        self.case.prepare_and_start();self.case.drain();self.case.prepare_second()
        q=copy.deepcopy(self.case.rows['JournalStartAnswerSegment']['request']);q['expectedAnswerRevision']=self.j.answer_revision
        self.j.start_segment(q)  # lost HTTP/ACK, grant not available to the executor
        self.j.mark_unknown('answer_unit_2')
        retry=self.j.start_segment(q)
        self.assertFalse(retry['segmentStartAuthorized']);self.assertIsNone(retry['grant'])
        self.assertEqual(self.j.command_start_count,1)
        self.assertEqual(len(self.j.grants),2)

    def test_wrong_artifact_attempt_generation_and_producer_renewal_rejected(self):
        grant=self.case.prepare_and_start()['answerGrant'];self.j.begin_tts('answer_unit_1',grant);self.case.prepare_second()
        calls=[lambda:self.j.renew_permit('answer_unit_2',grant=grant),
               lambda:self.j.refresh_facts('answer_unit_2',grant=grant),
               lambda:self.j.renew_permit('answer_unit_1',grant=grant,attempt_id='wrong_attempt'),
               lambda:self.j.renew_permit('answer_unit_1',grant=grant,generation_id=8),
               lambda:self.j.refresh_facts('answer_unit_1',grant=grant,producer='restarted_process')]
        for call in calls:
            with self.assertRaises(r.Rejected):call()
        self.j.generation_id=8
        with self.assertRaises(r.Rejected):self.j.handoff('answer_unit_1',grant)

    def test_bootstrap_generation_cannot_be_rebound_before_consumption(self):
        grant=self.case.prepare_and_start()['answerGrant'];self.j.generation_id=8
        self.j.refresh_facts('answer_unit_1',grant=grant)
        self.j.renew_permit('answer_unit_1',grant=grant)
        with self.assertRaisesRegex(r.Rejected,'EVIDENCE_CONFLICT'):self.j.begin_tts('answer_unit_1',grant)

    def test_stop_old_epoch_and_binding_expiry_outrank_renewal(self):
        for change in ('stop','epoch','binding'):
            with self.subTest(change=change):
                self.setUp();grant=self.case.prepare_and_start()['answerGrant'];self.j.begin_tts('answer_unit_1',grant)
                if change=='stop':self.j.stopped=True
                elif change=='epoch':self.j.epoch+=1
                else:self.j.binding_until=self.j.now
                for fn in (self.j.renew_permit,self.j.refresh_facts):
                    with self.assertRaises(r.Rejected):fn('answer_unit_1',grant=grant)
                with self.assertRaises(r.Rejected):self.j.handoff('answer_unit_1',grant)

    def test_expired_current_facts_block_output_until_authoritative_same_value_refresh(self):
        grant=self.case.prepare_and_start()['answerGrant'];self.j.begin_tts('answer_unit_1',grant);initial=self.j.now
        for offset in (.5,1.,1.5):
            self.j.now=initial+offset;self.j.renew_permit('answer_unit_1',grant=grant)
        self.j.now=initial+2.1
        with self.assertRaisesRegex(r.Rejected,'FACT_EXPIRED'):self.j.handoff('answer_unit_1',grant)
        self.j.refresh_facts('answer_unit_1',grant=grant);self.j.renew_permit('answer_unit_1',grant=grant)
        self.j.handoff('answer_unit_1',grant)
        self.j.facts['PRODUCT_DETAILS']=('changed','f'*64)
        with self.assertRaisesRegex(r.Rejected,'PLAN_CHANGED'):self.j.refresh_facts('answer_unit_1',grant=grant)

    def test_restart_and_unknown_cannot_restore_execution_from_proofs(self):
        for event in ('restart','unknown','guardian_restart'):
            with self.subTest(event=event):
                self.setUp();grant=self.case.prepare_and_start()['answerGrant'];self.j.begin_tts('answer_unit_1',grant)
                if event=='restart':self.j.runtime_restart()
                elif event=='unknown':self.j.mark_unknown('answer_unit_1')
                else:self.j.guardian_incarnation='new_guardian_process'
                for fn in (self.j.renew_permit,self.j.refresh_facts):
                    with self.assertRaises(r.Rejected):fn('answer_unit_1',grant=grant)
                with self.assertRaises(r.Rejected):self.j.handoff('answer_unit_1',grant)
                with self.assertRaises(r.Rejected):self.j.begin_tts('answer_unit_1',grant)
                self.assertEqual(self.j.command_start_count,1)

    def test_modified_grant_body_cannot_extend_consumption_deadline(self):
        grant=self.case.prepare_and_start()['answerGrant'];grant['expiresAt']='2026-10-16T00:00:10Z'
        with self.assertRaisesRegex(r.Rejected,'ANSWER_CONFLICT'):self.j.begin_tts('answer_unit_1',grant)

    def test_lost_receiver_consumption_ack_is_unknown_not_restartable(self):
        grant=self.case.prepare_and_start()['answerGrant']
        self.j._consume('answer_unit_1',grant)  # receiver latched; caller lost ACK
        self.j.mark_unknown('answer_unit_1')
        self.assertEqual(self.j.grant_states[grant['grantId']],'CONSUMED')
        self.assertNotIn('answer_unit_1',self.j.tts_started)
        with self.assertRaises(r.Rejected):self.j.begin_tts('answer_unit_1',grant)
        with self.assertRaises(r.Rejected):self.j.renew_permit('answer_unit_1',grant=grant)
        self.assertFalse(self.j.start(self.case.start)['startAuthorized'])

    def test_go_python_lifecycle_trace_agree_and_reject_wrong_binding(self):
        root=original.ROOT;trace_path=root/'contracts/v0.5/durable-live-2/examples/grant-renewal-trace.json'
        go=root/'contracts/v0.5/durable-live-2/examples/go/lifecycle.go'
        py=root/'contracts/v0.5/durable-live-2/examples/python/canonical.py'
        go_result=subprocess.check_output(['go','run',str(go),str(trace_path)],cwd=root,text=True)
        py_result=subprocess.check_output([sys.executable,str(py),'--lifecycle',str(trace_path)],cwd=root,text=True)
        self.assertEqual(json.loads(go_result),json.loads(py_result))
        self.assertEqual(json.loads(go_result)['lastOffsetMs'],5000)
        self.assertEqual(json.loads(go_result)['initialConsumeWindowMs'],800)
        for mutation in ('late_consumption','wrong_artifact','wrong_observation'):
            trace=json.loads(trace_path.read_text())
            if mutation=='late_consumption':trace['consumption']['consumedAt']='2026-10-16T00:00:01.000Z'
            elif mutation=='wrong_artifact':trace['permits'][-1]['artifactId']='other_artifact'
            else:trace['observations'][-1]['generationId']=8
            with self.assertRaises(ValueError):c.validate_lifecycle_trace(trace)
            with tempfile.TemporaryDirectory() as directory:
                bad=Path(directory)/'bad-trace.json';bad.write_text(json.dumps(trace))
                result=subprocess.run(['go','run',str(go),str(bad)],cwd=root,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)

if __name__=='__main__':unittest.main()
