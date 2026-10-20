"""Cross-participant contract mocks; NOT SQL/process/media acceptance."""
import base64
import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
import tests.test_durable_answer_contracts as original

rx=original.receiver

class ReceiverContractTests(unittest.TestCase):
    def setUp(self):
        objects={x['name']:x['value'] for x in original.c.load('examples/objects.json')}
        self.c=original.c;self.j=original.r.JournalOracle(objects['CommentCommand'],[objects['AnswerUnit1'],objects['AnswerUnit2']])
        self.p=rx.Participants(self.j,self.c);self.b=self.p.backend;self.g=self.p.guardian;self.r=self.p.runtime
        self.rows={x['operationId']:x for x in self.c.load('examples/protocol.json')};self.artifacts=[objects['AnswerUnit1'],objects['AnswerUnit2']];self.events=[]
    def call(self,from_actor,to_actor,op,request,fn):
        out=fn(request);self.c.validate(op+'Request',request);self.c.validate(op+'Response',out)
        self.events.append(dict(fromActor=from_actor,toActor=to_actor,operationId=op,request=copy.deepcopy(request),response=copy.deepcopy(out)));return out
    def bootstrap(self):
        self.assertIsNone(self.j.generation_id);self.assertIsNone(self.j.guardian_incarnation)
        registration=self.p.bootstrap();self.events.extend(self.p.transcript);return registration
    def prepare(self,index=0):
        q=copy.deepcopy(self.rows['JournalPrepareAnswer']['request']);q.update(artifact=copy.deepcopy(self.artifacts[index]),idempotencyKey='unit:'+str(index),expectedInboxRevision=self.j.inbox_revision,expectedAnswerRevision=self.j.answer_revision)
        out=self.b.prepare(self.r.peer,q);self.r.artifacts[q['artifact']['artifactId']]=copy.deepcopy(q['artifact'])
        self.events.append(dict(fromActor='RUNTIME',toActor='BACKEND',operationId='JournalPrepareAnswer',request=q,response=out));return out
    def permit_and_start(self,index=0):
        a=self.artifacts[index];permit=self.b.acquire(self.r.peer,a['artifactId'])
        template=copy.deepcopy(self.rows['AcquireOutputPermit']);template['request'].update(answerArtifactId=a['artifactId'],guardianId=self.b.registration['binding']['guardianId'])
        template['response'].update(permitId=permit['permitId'],issuedAt=permit['issuedAt'],expiresAt=permit['expiresAt'],answerArtifactId=a['artifactId'],factObservationId=permit['factObservationId'],factValidUntil=self.j.observations[permit['factObservationId']]['validUntil'])
        self.events.append(dict(fromActor='RUNTIME',toActor='BACKEND',**template))
        sent=self.r.clock(),self.r.suspend_clock()
        if not index:
            q=copy.deepcopy(self.c.load('examples/comment-start.json')['request']);q.update(permitId=permit['permitId'],expectedInboxRevision=self.j.inbox_revision,expectedAnswerRevision=self.j.answer_revision);out=self.b.grant(self.r.peer,q);grant=out['answerGrant'];op='JournalStart'
        else:
            q=copy.deepcopy(self.rows['JournalStartAnswerSegment']['request']);q.update(permitId=permit['permitId'],expectedAnswerRevision=self.j.answer_revision);out=self.b.grant(self.r.peer,q,True);grant=out['grant'];op='JournalStartAnswerSegment'
        self.r.remember_start(grant,out,sent)
        self.events.append(dict(fromActor='RUNTIME',toActor='BACKEND',operationId=op,request=q,response=out))
        refs=dict(bootstrapId=self.b.registration['binding']['bootstrapId'],artifactId=a['artifactId'],artifactHash=a['artifactHash'],grantId=grant['grantId'],permitId=permit['permitId'])
        return self.r.request(self.b.registration,refs),grant
    def ready(self):self.bootstrap();self.prepare();return self.permit_and_start()
    def consume(self,q):return self.call('RUNTIME','GUARDIAN','ReceiverConsume',q,lambda request:self.g.consume(self.r.peer,request))
    def drain(self,index=0):
        # Synthetic registered observer fixture, not a claim about PCM/RTMP.
        q=copy.deepcopy(self.rows['JournalConfirmAnswerSegment']['request']);a=self.artifacts[index]
        q.update(artifactId=a['artifactId'],artifactHash=a['artifactHash'],idempotencyKey='drain:'+a['artifactId'],expectedAnswerRevision=self.j.answer_revision)
        for proof in q['evidence']['sinkProofs']:
            proof.update(firstAudioSample=84000*index,finalAudioSampleExclusive=84000*(index+1),audioConsumedThroughExclusive=84000*(index+1),finalVideoFrame=87*(index+1),videoConsumedThroughFrame=87*(index+1))
        record=next(rec for rec in self.r.executions.values() if rec['binding']['artifactId']==a['artifactId'])
        finish=self.r.execution_request(record['binding']['executionId'])
        self.g.observer_fixture=lambda binding:copy.deepcopy(q['evidence'])  # trusted test Observer, not request JSON
        self.call('RUNTIME','GUARDIAN','ReceiverFinishUnit',finish,lambda request:self.g.finish_unit(self.r.peer,request))
        out=self.j.drain(q);self.events.append(dict(fromActor='RUNTIME',toActor='BACKEND',operationId='JournalConfirmAnswerSegment',request=q,response=out));return out
    def test_normal_bootstrap_prepare_permit_start_consume_pcm_drain(self):
        q,grant=self.ready();ack=self.consume(q);self.assertTrue(self.r.accept_ack(q,ack))
        execution=ack['consumption']['binding']['executionId'];self.r.push_media(execution,q['references']['permitId']);self.drain()
        self.assertEqual(self.r.tts_starts,1);self.assertEqual(len(self.b.latches),1);self.assertEqual(self.j.command_start_count,1)
        self.assertEqual(self.j.units[0]['state'],'DRAINED');self.assertEqual(self.g.media_count,1)
    def test_unit2_same_attempt_generation_turn_new_unit_grant(self):
        q,_=self.ready();ack=self.consume(q);self.r.accept_ack(q,ack);self.r.push_media(ack['consumption']['binding']['executionId'],q['references']['permitId']);binding=copy.deepcopy(self.b.registration['binding']);self.drain();self.prepare(1)
        q2,grant=self.permit_and_start(1);ack2=self.consume(q2);self.r.accept_ack(q2,ack2);self.r.push_media(ack2['consumption']['binding']['executionId'],q2['references']['permitId']);self.drain(1)
        self.assertEqual(self.b.registration['binding'],binding);self.assertEqual(self.j.command_start_count,1);self.assertEqual(len(self.b.latches),2);self.assertEqual(self.r.tts_starts,2)
        self.assertNotEqual(ack['consumption']['binding']['executionId'],ack2['consumption']['binding']['executionId'])
    def test_prepare_permit_start_fail_before_bootstrap(self):
        with self.assertRaisesRegex(ValueError,'BOOTSTRAP_REQUIRED'):self.prepare()
        with self.assertRaisesRegex(ValueError,'BOOTSTRAP_REQUIRED'):self.b.acquire(self.r.peer,self.artifacts[0]['artifactId'])
        with self.assertRaisesRegex(ValueError,'BOOTSTRAP_REQUIRED'):self.j.prepare(self.rows['JournalPrepareAnswer']['request'])
    def test_runtime_cannot_register_or_call_guardian_authority(self):
        self.bootstrap();registration_request=self.p.transcript[1]['request']
        with self.assertRaisesRegex(ValueError,'FORBIDDEN'):self.b.register(self.r.peer,registration_request)
        with self.assertRaisesRegex(ValueError,'FORBIDDEN'):self.g.stage(self.r.peer,self.p.transcript[0]['request'])
        self.prepare();q,_=self.permit_and_start()
        query=rx.wire(self.c,references=q['references'])
        with self.assertRaisesRegex(ValueError,'FORBIDDEN'):self.b.snapshot(self.r.peer,query)
        with self.assertRaisesRegex(ValueError,'FORBIDDEN'):self.b.stop(self.g.peer)
        with self.assertRaisesRegex(ValueError,'FORBIDDEN'):self.g.stop(self.r.peer,rx.wire(self.c,runId=self.j.command['runId']))
    def test_forged_stage_receipt_signature_rejected(self):
        self.bootstrap();q=copy.deepcopy(self.p.transcript[1]['request']);self.b.registration=None
        q['receipt']['signature']=base64.b64encode(b'x'*64).decode()
        with self.assertRaisesRegex(ValueError,'FORBIDDEN'):self.b.register(self.p.control,q)
    def test_wrong_generation(self):
        q,_=self.ready();q['expectedGenerationId']+=1
        with self.assertRaisesRegex(ValueError,'GENERATION_MISMATCH'):self.consume(q)
        self.assertFalse(self.b.latches)
    def test_wrong_guardian_incarnation(self):
        q,_=self.ready();q['expectedGuardianIncarnation']='wrong_process'
        with self.assertRaisesRegex(ValueError,'GUARDIAN_INCARNATION_MISMATCH'):self.consume(q)
        self.assertFalse(self.b.latches)
    def test_two_runtimes_concurrent_consume_one_true(self):
        q,_=self.ready();barrier=Barrier(2)
        # Two live requesters sharing a producer credential still have separate
        # authenticated channels. This also covers duplicate client races.
        peer=self.r.peer._replace(channelBinding=self.c.digest('different_channel'))
        other=rx.RuntimeActor(self.c,self.p.supervisor,self.g,self.j.producer,lambda:self.j.now,peer=peer)
        other.artifacts=copy.deepcopy(self.r.artifacts);other.grants=copy.deepcopy(self.r.grants);other.tickets=copy.deepcopy(self.r.tickets);other.start_deadlines=copy.deepcopy(self.r.start_deadlines)
        q2=other.request(self.b.registration,q['references'])
        def go(actor,request):
            barrier.wait()
            try:ack=self.g.consume(actor.peer,request);return actor.accept_ack(request,ack)
            except rx.Denied as e:self.assertEqual(str(e),'CONSUMPTION_CONFLICT');return False
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(go,self.r,q);b=pool.submit(go,other,q2);winners=[a.result(),b.result()]
        self.assertEqual(sum(winners),1);self.assertEqual(len(self.b.latches),1);self.assertEqual(self.r.tts_starts+other.tts_starts,1)
    def test_direct_authority_commit_race_has_one_durable_winner(self):
        q,_=self.ready();barrier=Barrier(2)
        def go(nonce):
            request=rx.wire(self.c,references=q['references'],consumeRequestId=nonce,consumeTicket=q['consumeTicket'],runtimePrincipalId=self.r.peer.principalId,runtimeIncarnation=self.r.peer.incarnation,channelBinding=self.r.peer.channelBinding,expectedRegistrationRevision=1)
            barrier.wait()
            try:return self.b.commit(self.g.peer,request)['consumeAuthorized']
            except rx.Denied as e:self.assertEqual(str(e),'CONSUMPTION_CONFLICT');return False
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(go,'nonce1');b=pool.submit(go,'nonce2');self.assertEqual(sum([a.result(),b.result()]),1)
        self.assertEqual(len(self.b.latches),1)
    def test_consume_ack_loss_query_retry_never_restart(self):
        q,_=self.ready();ack=self.consume(q);self.r.lose_ack(q)
        retry=self.consume(q);self.assertFalse(retry['consumeAuthorized']);self.assertIsNone(retry['consumption'])
        with self.assertRaisesRegex(ValueError,'CONSUMPTION_UNKNOWN'):self.r.accept_ack(q,ack)
        self.assertEqual(self.r.tts_starts,0);self.assertEqual(len(self.b.latches),1)
    def test_stop_after_commit_before_ack(self):
        q,_=self.ready();self.g.after_commit=self.p.stop
        with self.assertRaisesRegex(ValueError,'CONSUMPTION_UNKNOWN'):self.consume(q)
        self.assertEqual(len(self.b.latches),1);self.assertEqual(self.r.tts_starts,0);self.assertEqual(self.b.registration['state'],'REVOKED')
    def test_stop_consume_concurrent_never_output_after_stop(self):
        for _ in range(8):
            self.setUp();q,_=self.ready();barrier=Barrier(2)
            def consume():
                barrier.wait()
                try:return self.g.consume(self.r.peer,q)
                except ValueError:return None
            def stop():barrier.wait();self.p.stop()
            with ThreadPoolExecutor(2) as pool:
                a=pool.submit(consume);b=pool.submit(stop);ack=a.result();b.result()
            if ack and ack['consumeAuthorized']:
                with self.assertRaises(ValueError):self.r.accept_ack(q,ack)
            self.assertEqual(self.r.tts_starts,0)
    def test_guardian_restart_cannot_reconsume(self):
        q,_=self.ready();ack=self.consume(q);self.g.restart()
        with self.assertRaises(ValueError):self.consume(q)
        with self.assertRaises(ValueError):self.r.accept_ack(q,ack)
        self.assertEqual(len(self.b.latches),1)
    def test_runtime_restart_cannot_reconsume(self):
        q,_=self.ready();ack=self.consume(q);self.r.restart()
        with self.assertRaises(ValueError):self.consume(q)
        with self.assertRaises(ValueError):self.r.accept_ack(q,ack)
        self.assertEqual(self.r.tts_starts,0)
    def test_consumed_grant_proof_renewal_never_tts_again(self):
        q,grant=self.ready();ack=self.consume(q);self.r.accept_ack(q,ack);execution=ack['consumption']['binding']['executionId'];initial=self.j.now
        for offset in (.5,1.,1.5,2.,2.5,3.,3.5,4.,4.5,5.):
            self.j.now=initial+offset;permit=self.b.acquire(self.r.peer,self.artifacts[0]['artifactId'],refresh=offset in (1.5,3.,4.5))
            reply=self.r.renew(execution,permit['permitId']);self.c.validate('ReceiverRenewResponse',reply)
            self.assertNotIn('consumeAuthorized',reply);self.r.push_media(execution,permit['permitId'])
        self.drain();self.assertEqual(self.r.tts_starts,1);self.assertEqual(self.j.command_start_count,1);self.assertEqual(len(self.b.latches),1)
    def test_late_ack_is_not_execution_authority(self):
        q,_=self.ready();ack=self.consume(q);self.j.now+=.9
        with self.assertRaisesRegex(ValueError,'GRANT_EXPIRED'):self.r.accept_ack(q,ack)
        self.assertEqual(self.r.tts_starts,0)
    def test_old_epoch_and_expired_binding_block_consume(self):
        for mode in ('epoch','binding'):
            self.setUp();q,_=self.ready()
            if mode=='epoch':self.j.epoch+=1
            else:self.j.binding_until=self.j.now
            with self.assertRaises(ValueError):self.consume(q)
            self.assertFalse(self.b.latches)
    def test_closed_schemas_reject_runtime_self_registration_fields(self):
        q,_=self.ready();q['generationId']=q['expectedGenerationId']
        from jsonschema import ValidationError
        with self.assertRaises(ValidationError):self.consume(q)

    def test_registration_retries_and_cas_cannot_rebind_generation(self):
        reg=self.bootstrap();q=copy.deepcopy(self.p.transcript[1]['request'])
        self.assertEqual(self.b.register(self.p.control,q)['registration'],reg)
        q['binding']['generationId']+=1
        with self.assertRaises(ValueError):self.b.register(self.p.control,q)
        self.assertEqual(self.b.registration,reg)
    def test_replaced_physical_install_revokes_prior_bootstrap(self):
        q,_=self.ready()
        self.p.supervisor.install(self.p.control,self.b.context,self.r.peer,self.g.peer)
        with self.assertRaisesRegex(ValueError,'REGISTRATION_REVOKED'):self.consume(q)
    def test_query_consumption_is_metadata_only_after_ack_loss_or_restart(self):
        q,_=self.ready();ack=self.consume(q);self.r.lose_ack(q)
        query=rx.wire(self.c,bootstrapId=q['references']['bootstrapId'],grantId=q['references']['grantId'])
        before=self.g.query_consumption(self.r.peer,query);self.c.validate('ReceiverQueryConsumptionResponse',before)
        self.assertEqual(set(before['summary']),{'state','receiptId'});self.assertNotIn('consumeAuthorized',before)
        self.g.restart();after=self.g.query_consumption(self.r.peer,query)
        self.assertEqual(after['summary']['state'],'UNKNOWN');self.assertNotIn('consumption',after)
    def test_backend_commit_ack_loss_has_no_guardian_latch_or_tts(self):
        q,_=self.ready()
        commit=rx.wire(self.c,references=q['references'],consumeRequestId=q['consumeRequestId'],consumeTicket=q['consumeTicket'],runtimePrincipalId=self.r.peer.principalId,runtimeIncarnation=self.r.peer.incarnation,channelBinding=self.r.peer.channelBinding,expectedRegistrationRevision=1)
        self.b.commit(self.g.peer,commit)  # Backend committed, receiver never got ACK.
        retry=self.consume(q);self.assertFalse(retry['consumeAuthorized']);self.assertFalse(self.g.local)
        self.assertFalse(self.r.accept_ack(q,retry));self.assertEqual(self.r.tts_starts,0)
    def test_response_cannot_cache_authorization_on_false(self):
        from jsonschema import ValidationError
        q,_=self.ready();ack=self.consume(q);ack['consumeAuthorized']=False
        with self.assertRaises(ValidationError):self.c.validate('ReceiverConsumeResponse',ack)

    def test_lost_start_ack_cannot_recover_ticket_from_authority(self):
        q,_=self.ready();self.r.tickets.clear();self.r.grants.clear()
        snapshot=self.b.snapshot(self.g.peer,rx.wire(self.c,references=q['references']))['snapshot']
        self.assertNotIn('consumeTicket',snapshot);self.assertNotIn('consumeTicket',snapshot['grant'])
        q['consumeTicket']='A'*43
        with self.assertRaisesRegex(ValueError,'GRANT_TICKET_INVALID'):self.consume(q)
        self.assertFalse(self.b.latches);self.assertEqual(self.r.tts_starts,0)
    def test_lost_continuation_ack_cannot_recover_ticket(self):
        q,_=self.ready();ack=self.consume(q);self.r.accept_ack(q,ack);self.r.push_media(ack['consumption']['binding']['executionId'],q['references']['permitId']);self.drain();self.prepare(1)
        q2,_=self.permit_and_start(1);self.r.tickets.clear();q2['consumeTicket']='A'*43
        with self.assertRaisesRegex(ValueError,'GRANT_TICKET_INVALID'):self.consume(q2)
        self.assertEqual(len(self.b.latches),1);self.assertEqual(self.r.tts_starts,1)
    def test_different_runtime_principal_race_never_steals_grant(self):
        q,_=self.ready();other=rx.RuntimeActor(self.c,self.p.supervisor,self.g,self.j.producer,lambda:self.j.now)
        barrier=Barrier(2)
        def go(peer):
            barrier.wait()
            try:return self.g.consume(peer,copy.deepcopy(q))['consumeAuthorized']
            except rx.Denied as e:self.assertEqual(str(e),'FORBIDDEN');return False
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(go,self.r.peer);b=pool.submit(go,other.peer);self.assertEqual([a.result(),b.result()],[True,False])
        self.assertEqual(len(self.b.latches),1)
    def test_same_first_ack_cannot_start_tts_twice(self):
        q,_=self.ready();ack=self.consume(q);self.assertTrue(self.r.accept_ack(q,ack))
        with self.assertRaisesRegex(ValueError,'CONSUMPTION_UNKNOWN'):self.r.accept_ack(q,ack)
        self.assertEqual(self.r.tts_starts,1)
    def test_unit2_rejects_late_unit1_media_renew_and_drain(self):
        q,_=self.ready();ack=self.consume(q);self.r.accept_ack(q,ack);execution=ack['consumption']['binding']['executionId'];self.r.push_media(execution,q['references']['permitId']);self.drain();self.prepare(1)
        q2,_=self.permit_and_start(1);ack2=self.consume(q2);self.r.accept_ack(q2,ack2)
        for action in (lambda:self.r.push_media(execution,q['references']['permitId']),lambda:self.r.renew(execution,q['references']['permitId']),lambda:self.g.finish_unit(self.r.peer,self.r.execution_request(execution))):
            with self.assertRaisesRegex(ValueError,'STALE_EXECUTION'):action()
        self.assertEqual(self.b.registration['binding']['generationId'],ack2['consumption']['binding']['generationId'])
    def test_stop_between_stage_and_register_defeats_old_receipt(self):
        original=self.b.register
        def stop_before_register(control,request):self.b.stop(self.p.control);return original(control,request)
        self.b.register=stop_before_register
        with self.assertRaisesRegex(ValueError,'RUN_STOPPED'):self.p.bootstrap()
        self.assertIsNone(self.b.registration);self.assertIsNone(self.j.registration_id)
    def test_plaintext_ticket_absent_from_durable_authority_and_receipts(self):
        q,_=self.ready();ticket=q['consumeTicket'];self.consume(q)
        snapshot=self.b.snapshot(self.g.peer,rx.wire(self.c,references=q['references']))
        for value in (self.b.registration,self.b.latches,self.b.consume_keys,self.j.ticket_verifiers,self.j.grants,snapshot,self.g.local):
            self.assertNotIn(ticket,repr(value))
    def test_local_clock_offsets_do_not_use_remote_absolute_timestamps(self):
        self.r.clock=lambda:self.j.now+10000;self.r.suspend_clock=self.r.clock;self.g.clock=lambda:self.j.now-20000;self.g.suspend_clock=self.g.clock
        q,_=self.ready();ack=self.consume(q);self.assertTrue(self.r.accept_ack(q,ack));self.assertEqual(self.r.tts_starts,1)
    def test_suspend_during_proof_rpc_cannot_reanchor_full_ttl(self):
        q,_=self.ready();ack=self.consume(q);self.r.accept_ack(q,ack);execution=ack['consumption']['binding']['executionId']
        original=self.b.snapshot
        def suspend(peer,request):
            out=original(peer,request);self.g.suspend_clock=lambda:self.g.clock()+2;return out
        self.b.snapshot=suspend
        with self.assertRaisesRegex(ValueError,'LEASE_LOST'):self.r.renew(execution,q['references']['permitId'])
    def test_backend_ack_loss_and_local_fsync_crashes_never_rearm(self):
        for phase in ('backend_ack','before_fsync','after_fsync'):
            self.setUp();q,_=self.ready()
            def crash():raise rx.Denied('CONSUMPTION_UNKNOWN')
            if phase=='backend_ack':
                original=self.b.commit
                def lost(peer,request):original(peer,request);crash()
                self.b.commit=lost
            elif phase=='before_fsync':self.g.before_fsync=crash
            else:self.g.after_commit=crash
            with self.assertRaisesRegex(ValueError,'CONSUMPTION_UNKNOWN'):self.consume(q)
            self.assertEqual(len(self.b.latches),1);self.assertEqual(self.r.tts_starts,0)
            if phase=='backend_ack':self.b.commit=original
            self.g.before_fsync=None;self.g.after_commit=None
            retry=self.consume(q);self.assertFalse(retry['consumeAuthorized']);self.assertIsNone(retry['consumption'])
    def test_consume_nonce_or_channel_reassignment_conflicts(self):
        q,_=self.ready();self.consume(q)
        for field,value in (('consumeRequestId','other_nonce'),('channelBinding',self.c.digest('other_channel'))):
            request=rx.wire(self.c,references=q['references'],consumeTicket=q['consumeTicket'],consumeRequestId=q['consumeRequestId'],runtimePrincipalId=self.r.peer.principalId,runtimeIncarnation=self.r.peer.incarnation,channelBinding=self.r.peer.channelBinding,expectedRegistrationRevision=1)
            request[field]=value
            with self.assertRaisesRegex(ValueError,'CONSUMPTION_CONFLICT'):self.b.commit(self.g.peer,request)
    def test_physical_install_reader_is_controlled_and_precedes_registration(self):
        self.bootstrap();binding=self.b.registration['binding'];request=rx.wire(self.c,physicalInstallProofRef=binding['physicalInstallProofRef'],expectedBindingHash=self.c.digest(binding))
        with self.assertRaisesRegex(ValueError,'FORBIDDEN'):self.p.supervisor.read_installation(self.r.peer,request)
        result=self.p.supervisor.read_installation(self.g.peer,request);self.c.validate('ReadReceiverPhysicalInstallationResponse',result)
        self.assertEqual(result['installation']['state'],'CLOSED_INSTALLED')

    def test_late_unit1_media_rejected_even_before_unit2_or_business_confirm(self):
        q,_=self.ready();ack=self.consume(q);self.r.accept_ack(q,ack);execution=ack['consumption']['binding']['executionId'];self.r.push_media(execution,q['references']['permitId'])
        evidence=copy.deepcopy(self.rows['JournalConfirmAnswerSegment']['request']['evidence'])
        self.g.observer_fixture=lambda binding:evidence
        self.g.finish_unit(self.r.peer,self.r.execution_request(execution))
        self.assertEqual(self.j.units[0]['state'],'STARTED')
        with self.assertRaisesRegex(ValueError,'STALE_EXECUTION'):self.r.push_media(execution,q['references']['permitId'])
    def test_proof_exchange_delay_after_ack_does_not_extend_start_deadline(self):
        q,_=self.ready();ack=self.consume(q);original=self.g.renew
        def delayed(peer,request):out=original(peer,request);self.j.now+=1;return out
        self.g.renew=delayed
        with self.assertRaises(ValueError):self.r.accept_ack(q,ack)
        self.assertEqual(self.r.tts_starts,0)
    def test_runtime_cannot_forge_a_control_role_in_authenticated_context(self):
        self.bootstrap();fake=self.r.peer._replace(role='CONTROL_REGISTRAR')
        with self.assertRaisesRegex(ValueError,'FORBIDDEN'):self.b.register(fake,self.p.transcript[1]['request'])

if __name__=='__main__':unittest.main()
