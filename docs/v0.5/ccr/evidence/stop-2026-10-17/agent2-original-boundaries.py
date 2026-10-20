"""Agent2 independent Receiver review, synthetic fixtures, outside worktrees."""
import sys,copy,unittest
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,'/tmp/astralive-agent2-pr9-final.QQ1UiS')
import tests.test_receiver_contracts as fixture
rx=fixture.rx
class FinalReceiverReview(unittest.TestCase):
    def setUp(self):
        self.x=fixture.ReceiverContractTests();self.x.setUp()
    def commitq(self,q,**updates):
        x=self.x
        v=rx.wire(x.c,references=copy.deepcopy(q['references']),consumeRequestId=q['consumeRequestId'],consumeTicket=q['consumeTicket'],runtimePrincipalId=x.r.peer.principalId,runtimeIncarnation=x.r.peer.incarnation,channelBinding=x.r.peer.channelBinding,expectedRegistrationRevision=1)
        v.update(updates);return v
    def start(self):
        x=self.x;q,_=x.ready();a=x.consume(q);x.r.accept_ack(q,a)
        return q,a,a['consumption']['binding']['executionId']
    def test_01_unregistered_prepare_is_atomic_denial(self):
        x=self.x
        with self.assertRaises(ValueError):x.prepare()
        self.assertEqual((len(x.j.units),len(x.b.children),len(x.b.latches)),(0,0,0))
    def test_02_registration_cas_failure_can_retry_original_receipt(self):
        x=self.x;original=x.b.register;saved=[]
        def bad(control,q):
            saved.append(copy.deepcopy(q));q=copy.deepcopy(q);q['expectedRunRevision']+=1
            return original(control,q)
        x.b.register=bad
        with self.assertRaisesRegex(ValueError,'STATE_CONFLICT'):x.p.bootstrap()
        self.assertIsNone(x.b.registration);self.assertIsNone(x.j.registration_id)
        result=original(x.p.control,saved[0]);self.assertEqual(result['registration']['state'],'ACTIVE')
        self.assertEqual(original(x.p.control,saved[0])['registration'],result['registration'])
    def test_03_bad_ticket_has_no_partial_consume(self):
        x=self.x;q,_=x.ready();before=copy.deepcopy(x.j.grant_states)
        bad=self.commitq(q,consumeTicket='A'*43)
        with self.assertRaisesRegex(ValueError,'GRANT_TICKET_INVALID'):x.b.commit(x.g.peer,bad)
        self.assertFalse(x.b.latches);self.assertFalse(x.b.consume_keys);self.assertEqual(x.j.grant_states,before)
        self.assertTrue(x.b.commit(x.g.peer,self.commitq(q))['consumeAuthorized'])
    def test_04_bad_consume_cas_does_not_reserve_nonce(self):
        x=self.x;q,_=x.ready()
        with self.assertRaisesRegex(ValueError,'STATE_CONFLICT'):x.b.commit(x.g.peer,self.commitq(q,expectedRegistrationRevision=2))
        self.assertFalse(x.b.latches);self.assertFalse(x.b.consume_keys)
        self.assertTrue(x.b.commit(x.g.peer,self.commitq(q))['consumeAuthorized'])
    def test_05_thirty_two_identical_commits_have_one_true(self):
        x=self.x;q,_=x.ready();base=self.commitq(q)
        def invoke(i):
            v=copy.deepcopy(base);v['requestId']='retry_'+str(i);return x.b.commit(x.g.peer,v)
        with ThreadPoolExecutor(max_workers=8) as p:results=list(p.map(invoke,range(32)))
        self.assertEqual(sum(v['consumeAuthorized'] for v in results),1)
        self.assertTrue(all(v['consumption'] is None and v['consumeTiming'] is None for v in results if not v['consumeAuthorized']))
        self.assertEqual((len(x.b.latches),len(x.b.consume_keys)),(1,1))
    def test_06_nonce_cannot_be_reassigned_to_unit2(self):
        x=self.x;q,a,e=self.start();x.r.push_media(e,q['references']['permitId']);x.drain();x.prepare(1)
        q2,_=x.permit_and_start(1)
        with self.assertRaisesRegex(ValueError,'CONSUMPTION_CONFLICT'):x.b.commit(x.g.peer,self.commitq(q2,consumeRequestId=q['consumeRequestId']))
        self.assertEqual(len(x.b.latches),1)
        a2=x.consume(q2);self.assertTrue(x.r.accept_ack(q2,a2));self.assertEqual(len(x.b.latches),2)
    def test_07_old_epoch_generation_install_or_revoke_cannot_consume(self):
        for event in ('epoch','generation','install','revoke'):
            with self.subTest(event=event):
                self.setUp();x=self.x;q,_=x.ready()
                if event=='epoch':x.j.epoch+=1
                elif event=='generation':x.j.generation_id+=1
                elif event=='install':x.p.supervisor.install(x.p.control,x.b.context,x.r.peer,x.g.peer)
                else:x.b.revoke(x.p.control,rx.wire(x.c,bootstrapId=x.b.registration['binding']['bootstrapId'],expectedRegistrationRevision=1,reason='AUTHORITY_LOST'))
                with self.assertRaises(ValueError):x.consume(q)
                self.assertFalse(x.b.latches)
    def test_08_ticket_not_available_in_authority_or_journal_retry(self):
        x=self.x;q,_=x.ready();snapshot=x.b.snapshot(x.g.peer,rx.wire(x.c,references=q['references']))
        self.assertNotIn(q['consumeTicket'],repr(snapshot));self.assertNotIn(q['consumeTicket'],repr(x.j.ticket_verifiers))
        v=copy.deepcopy(x.c.load('examples/comment-start.json')['request']);v.update(expectedInboxRevision=x.j.inbox_revision,expectedAnswerRevision=x.j.answer_revision)
        retry=x.b.grant(x.r.peer,v);self.assertFalse(retry['startAuthorized']);self.assertIsNone(retry['consumeTicket']);self.assertIsNone(retry['consumeTiming'])
    def test_09_late_backend_positive_cannot_arm_guardian(self):
        x=self.x;q,_=x.ready();original=x.b.commit
        def late(peer,v):
            out=original(peer,v);x.j.now+=1.;return out
        x.b.commit=late
        with self.assertRaisesRegex(ValueError,'GRANT_EXPIRED'):x.consume(q)
        self.assertEqual(len(x.b.latches),1);self.assertFalse(x.g.local);self.assertEqual(x.r.tts_starts,0)
    def test_10_fsync_loss_does_not_regrant_consumed_latch(self):
        for phase in ('before_fsync','after_commit'):
            with self.subTest(phase=phase):
                self.setUp();x=self.x;q,_=x.ready()
                def crash():raise rx.Denied('CONSUMPTION_UNKNOWN')
                setattr(x.g,phase,crash)
                with self.assertRaises(ValueError):x.consume(q)
                setattr(x.g,phase,None)
                self.assertEqual(len(x.b.latches),1)
                retry=x.consume(q);self.assertFalse(retry['consumeAuthorized']);self.assertIsNone(retry['consumption']);self.assertEqual(x.r.tts_starts,0)
    def test_11_stop_between_authority_query_and_backend_commit(self):
        x=self.x;q,_=x.ready();x.b.snapshot(x.g.peer,rx.wire(x.c,references=q['references']))
        x.b.stop(x.p.control)
        with self.assertRaises(ValueError):x.b.commit(x.g.peer,self.commitq(q))
        self.assertFalse(x.b.latches);self.assertFalse(x.b.consume_keys)
    def test_12_five_second_renewal_stays_one_execution(self):
        x=self.x;q,a,e=self.start();initial=x.j.now;binding=copy.deepcopy(a['consumption']['binding'])
        for offset in (.5,1.,1.5,2.,2.5,3.,3.5,4.,4.5,5.):
            x.j.now=initial+offset;permit=x.b.acquire(x.r.peer,x.artifacts[0]['artifactId'],refresh=True)
            renewed=x.r.renew(e,permit['permitId']);self.assertNotIn('consumeAuthorized',renewed)
            x.r.push_media(e,permit['permitId'])
        x.drain();self.assertEqual((x.r.tts_starts,len(x.b.latches),x.j.command_start_count),(1,1,1))
        self.assertEqual(a['consumption']['binding'],binding)
    def test_13_local_stop_tombstone_prevents_new_consume(self):
        x=self.x;q,_=x.ready()
        out=x.g.stop(x.p.control,rx.wire(x.c,runId=x.j.command['runId']))
        self.assertEqual(out['state'],'CLOSED_FENCED');self.assertEqual(x.b.registration['state'],'ACTIVE')
        with self.assertRaises(ValueError):
            ack=x.consume(q);x.r.accept_ack(q,ack)
        self.assertFalse(x.b.latches);self.assertEqual(x.r.tts_starts,0)
    def test_14_stop_during_media_proof_fetch_prevents_handoff(self):
        x=self.x;q,a,e=self.start();original=x.b.snapshot;fired=[]
        def stop_after_read(peer,v):
            out=original(peer,v)
            if not fired:fired.append(True);x.p.stop()
            return out
        x.b.snapshot=stop_after_read
        with self.assertRaises(ValueError):x.r.push_media(e,q['references']['permitId'])
        self.assertEqual(x.g.media_count,0);self.assertEqual(x.g.barrier_state,'FENCED')
    def test_15_stop_during_last_consume_proof_fetch_prevents_positive_ack(self):
        x=self.x;q,_=x.ready();original=x.b.snapshot;calls=[]
        def stop_after_last_read(peer,v):
            out=original(peer,v);calls.append(True)
            if len(calls)==3:x.p.stop()
            return out
        x.b.snapshot=stop_after_last_read
        with self.assertRaises(ValueError):x.consume(q)
        self.assertEqual(len(x.b.latches),1);self.assertEqual(x.r.tts_starts,0)
if __name__=='__main__':unittest.main(verbosity=2)
