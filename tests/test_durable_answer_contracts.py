"""CCR candidate contracts and synthetic oracle, not production SQL acceptance."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from jsonschema import ValidationError

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'contracts/v0.5/durable-live-2/examples/python/reference.py'
spec=importlib.util.spec_from_file_location('answer_oracle',P)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
c=r.c
receiver_spec=importlib.util.spec_from_file_location('receiver_mock',P.parent/'receiver.py')
receiver=importlib.util.module_from_spec(receiver_spec);receiver_spec.loader.exec_module(receiver)

class AnswerContractTests(unittest.TestCase):
    def setUp(self):
        objects={x['name']:x['value'] for x in c.load('examples/objects.json')}
        self.command=objects['CommentCommand']
        self.artifacts=[objects['AnswerUnit1'],objects['AnswerUnit2']]
        self.j=r.JournalOracle(self.command,self.artifacts)
        self.participants=receiver.Participants(self.j,c)
        self.participants.bootstrap()
        self.rows={x['operationId']:x for x in c.load('examples/protocol.json')}
        self.prepare=copy.deepcopy(self.rows['JournalPrepareAnswer']['request'])
        self.start=copy.deepcopy(c.load('examples/comment-start.json')['request'])

    def prepare_and_start(self):
        self.j.prepare(self.prepare)
        return self.j.start(self.start)

    def prepare_second(self):
        q=copy.deepcopy(self.prepare)
        q.update(artifact=self.artifacts[1],idempotencyKey='prepare:answer_demo:2',expectedInboxRevision=self.j.inbox_revision,expectedAnswerRevision=self.j.answer_revision)
        return self.j.prepare(q)

    def drain(self,index=0):
        q=copy.deepcopy(self.rows['JournalConfirmAnswerSegment']['request'])
        a=self.artifacts[index]
        q.update(artifactId=a['artifactId'],artifactHash=a['artifactHash'],idempotencyKey='drain:'+a['artifactId'],expectedAnswerRevision=self.j.answer_revision)
        if index:
            for proof in q['evidence']['sinkProofs']:
                proof.update(firstAudioSample=84000*index,finalAudioSampleExclusive=84000*(index+1),audioConsumedThroughExclusive=84000*(index+1),finalVideoFrame=87*(index+1),videoConsumedThroughFrame=87*(index+1))
        return self.j.drain(q)

    def test_schema_examples_states_protected_files_and_pending_ack(self):
        result=c.check_all()
        self.assertEqual(result['operations'],25)
        self.assertEqual(result['definitions'],132)

    def test_same_prepare_receipt_never_authorizes_start_or_changes_revision(self):
        first=self.j.prepare(self.prepare)
        self.assertEqual(self.j.prepare(self.prepare),first)
        self.assertEqual((len(self.j.units),self.j.inbox_revision,self.j.answer_revision),(1,2,1))
        self.assertNotIn('grant',first);self.assertNotIn('startAuthorized',first)
        self.assertEqual(self.j.command_start_count,0)
        stored=self.j.units[0]['artifact']
        for key in ('answerText','answerTextHash','productSnapshotVersion','factDependencies','artifactHash'):
            self.assertEqual(stored[key],self.prepare['artifact'][key])

    def test_prepare_after_start_returns_original_receipt_without_authority(self):
        receipt=self.j.prepare(self.prepare)
        self.j.start(self.start)
        revision=self.j.answer_revision
        q=copy.deepcopy(self.prepare);q['idempotencyKey']='alias_same_immutable_artifact'
        self.assertEqual(self.j.prepare(q),receipt)
        self.assertEqual(self.j.answer_revision,revision)
        self.assertEqual(self.j.command_start_count,1)

    def test_closed_prepare_response_cannot_smuggle_grant_or_sql(self):
        response=copy.deepcopy(self.rows['JournalPrepareAnswer']['response'])
        response['startAuthorized']=True
        with self.assertRaises(ValidationError):c.validate('JournalPrepareAnswerResponse',response)
        request=copy.deepcopy(self.prepare);request['sql']='arbitrary SQL is forbidden'
        with self.assertRaises(ValidationError):c.validate('JournalPrepareAnswerRequest',request)
        self.assertEqual(self.rows['JournalPrepareAnswer']['response']['inboxRevision'],2)
        self.assertEqual(self.start['expectedInboxRevision'],2)

    def test_concurrent_duplicate_prepare_and_start_one_grant(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts=list(pool.map(lambda _:self.j.prepare(self.prepare),range(8)))
            starts=list(pool.map(lambda _:self.j.start(self.start),range(8)))
        self.assertTrue(all(x==receipts[0] for x in receipts))
        self.assertEqual(sum(x['startAuthorized'] for x in starts),1)
        self.assertEqual(self.j.command_start_count,1)

    def test_body_or_fact_metadata_conflicts_roll_back(self):
        self.j.prepare(self.prepare)
        snapshot=copy.deepcopy(self.j.units)
        for field in ('answerText','productSnapshotVersion','factDependencies'):
            q=copy.deepcopy(self.prepare);a=q['artifact']
            if field=='answerText':a[field]='另一段正文。';a['answerTextHash']=c.text_hash(a[field])
            elif field=='productSnapshotVersion':a[field]='f'*64
            else:a[field][0]['expiresAt']='2026-10-16T00:00:01Z'
            a['artifactHash']=c.artifact_hash(a)
            with self.assertRaises((ValueError,r.Rejected)):
                self.j.prepare(q)
            self.assertEqual(self.j.units,snapshot)

    def test_question_hash_cannot_stand_in_for_answer_hash(self):
        q=copy.deepcopy(self.prepare)
        q['artifact']['answerTextHash']=self.command['payload']['textHash']
        q['artifact']['artifactHash']=c.artifact_hash(q['artifact'])
        with self.assertRaises(ValueError):self.j.prepare(q)
        self.assertEqual(self.j.units,[])

    def test_same_grant_cannot_begin_tts_twice(self):
        grant=self.prepare_and_start()['answerGrant']
        artifact_id=self.artifacts[0]['artifactId']
        self.j.begin_tts(artifact_id,grant)
        with self.assertRaisesRegex(r.Rejected,'RECOVERY_UNKNOWN'):self.j.begin_tts(artifact_id,grant)

    def test_lost_start_ack_and_retries_never_repeat_execution(self):
        self.j.prepare(self.prepare)
        self.j.start(self.start)  # deliberately discard grant response
        for _ in range(3):
            reply=self.j.start(self.start)
            self.assertFalse(reply['startAuthorized']);self.assertIsNone(reply['answerGrant'])
        self.assertEqual(self.j.command_start_count,1)
        self.assertEqual(len(self.j.units),1)

    def test_stop_epoch_binding_owner_producer_and_revision_rejected_before_duplicate(self):
        for mode in ('stop','epoch','binding','owner','producer','revision','role'):
            with self.subTest(mode=mode):
                self.setUp();self.j.prepare(self.prepare)
                q=copy.deepcopy(self.prepare)
                if mode=='stop':self.j.stopped=True
                if mode=='epoch':self.j.epoch=2
                if mode=='binding':self.j.binding_until=self.j.now
                if mode=='owner':q['ownerId']='other_owner'
                if mode=='producer':q['producerIncarnation']='other_process'
                if mode=='revision':q['contractRevision']='durable-live-1'
                if mode=='role':self.j.role='CONTROL'
                with self.assertRaises((r.Rejected,ValidationError)):self.j.prepare(q)
                self.assertEqual(len(self.j.units),1)

    def test_expired_or_changed_facts_block_start_and_further_handoffs(self):
        self.j.prepare(self.prepare)
        self.j.fact_verified=self.j.now-3
        with self.assertRaisesRegex(r.Rejected,'FACT_EXPIRED'):self.j.start(self.start)
        self.j.fact_verified=self.j.now
        grant=self.j.start(self.start)['answerGrant']
        self.assertEqual(self.j.handoff(self.artifacts[0]['artifactId'],grant),self.artifacts[0]['answerText'])
        self.j.fact_verified=self.j.now-3
        with self.assertRaisesRegex(r.Rejected,'FACT_EXPIRED'):self.j.handoff(self.artifacts[0]['artifactId'],grant)
        self.j.fact_verified=self.j.now
        self.j.facts['PRODUCT_DETAILS']=('changed_version','f'*64)
        with self.assertRaisesRegex(r.Rejected,'PLAN_CHANGED'):self.j.handoff(self.artifacts[0]['artifactId'],grant)

    def test_expired_permit_never_allows_late_start(self):
        self.j.prepare(self.prepare);self.j.permit_until=self.j.now
        with self.assertRaisesRegex(r.Rejected,'LEASE_LOST'):self.j.start(self.start)
        self.assertEqual(self.j.state,'ACCEPTED')

    def test_continuation_is_one_shot_same_command_and_waits_for_drain(self):
        self.prepare_and_start();self.prepare_second()
        q=copy.deepcopy(self.rows['JournalStartAnswerSegment']['request'])
        q['expectedAnswerRevision']=self.j.answer_revision
        with self.assertRaisesRegex(r.Rejected,'ANSWER_GAP'):self.j.start_segment(q)
        self.drain();q['expectedAnswerRevision']=self.j.answer_revision
        self.assertTrue(self.j.start_segment(q)['segmentStartAuthorized'])
        duplicate=self.j.start_segment(q)
        self.assertFalse(duplicate['segmentStartAuthorized']);self.assertIsNone(duplicate['grant'])
        self.assertEqual(self.j.command_start_count,1)
        self.assertEqual({u['artifact']['commandId'] for u in self.j.units},{self.command['commandId']})

    def test_third_undrained_unit_and_semantic_fragments_rejected(self):
        self.prepare_and_start();self.prepare_second()
        q=copy.deepcopy(self.prepare);a=q['artifact']
        a.update(sequence=3,artifactId='unit_3',previousArtifactHash=self.artifacts[1]['artifactHash'])
        a['artifactHash']=c.artifact_hash(a)
        q.update(idempotencyKey='prepare:3',expectedInboxRevision=3,expectedAnswerRevision=3)
        with self.assertRaisesRegex(r.Rejected,'ANSWER_WINDOW_FULL'):self.j.prepare(q)
        for text in ('如果你想购买XL，','价格是129.90','x'*241+'。'):
            a=copy.deepcopy(self.artifacts[0]);a['answerText']=text;a['answerTextHash']=c.text_hash(text);a['artifactHash']=c.artifact_hash(a)
            with self.assertRaises((ValueError,ValidationError)):c.validate_artifact(a)

    def test_sequence_gaps_and_hash_chain_rejected(self):
        self.prepare_and_start()
        q=copy.deepcopy(self.prepare);a=copy.deepcopy(self.artifacts[1]);a['previousArtifactHash']='f'*64;a['artifactHash']=c.artifact_hash(a)
        q.update(artifact=a,idempotencyKey='prepare:2',expectedInboxRevision=3,expectedAnswerRevision=2)
        with self.assertRaisesRegex(r.Rejected,'ANSWER_GAP'):self.j.prepare(q)

    def test_seal_and_all_units_drain_required_for_global_completion(self):
        self.prepare_and_start();self.prepare_second();self.drain()
        with self.assertRaises(r.Rejected):self.j.complete()
        q=copy.deepcopy(self.rows['JournalStartAnswerSegment']['request']);q['expectedAnswerRevision']=self.j.answer_revision
        self.j.start_segment(q);self.drain(1)
        with self.assertRaises(r.Rejected):self.j.complete()
        seal=copy.deepcopy(self.rows['JournalSealAnswer']['request']);seal['expectedAnswerRevision']=self.j.answer_revision
        self.assertEqual(self.j.seal(seal),self.j.seal(seal))
        self.j.complete();self.assertEqual(self.j.state,'TERMINAL')

    def test_mixed_version_wire_rejected_in_both_directions(self):
        v1=c.common.load('examples/protocol.json')
        for row in v1:
            name=row['operationId']+'Request'
            with self.assertRaises(ValidationError):c.validate(name,row['request'])
        v2=c.load('examples/comment-start.json')['request']
        with self.assertRaises(ValidationError):c.common.validate('#/$defs/JournalStartRequest',v2)

    def test_first_safe_unit_can_start_before_llm_eof(self):
        async def scenario():
            eof_allowed=asyncio.Event();first_tts=asyncio.Event()
            async def provider():
                yield self.artifacts[0]['answerText']
                await eof_allowed.wait()
                yield self.artifacts[1]['answerText']
            async def streaming_consumer():
                async for text in provider():
                    if not first_tts.is_set():
                        self.assertEqual(text,self.prepare['artifact']['answerText'])
                        self.j.prepare(self.prepare)
                        grant=self.j.start(self.start)['answerGrant']
                        self.j.begin_tts(self.artifacts[0]['artifactId'],grant)
                        first_tts.set()  # synthetic TTS eligibility, not actual audio
            task=asyncio.create_task(streaming_consumer())
            await asyncio.wait_for(first_tts.wait(),1)
            self.assertFalse(eof_allowed.is_set());self.assertFalse(task.done())
            eof_allowed.set();await task
        asyncio.run(scenario())

    def test_go_python_canonical_vectors_are_identical(self):
        vectors=ROOT/'contracts/v0.5/durable-live-2/examples/hash-vectors.json'
        go=subprocess.check_output(['go','run',str(ROOT/'contracts/v0.5/durable-live-2/examples/go/canonical.go'),str(vectors)],cwd=ROOT,text=True)
        py=subprocess.check_output([sys.executable,str(ROOT/'contracts/v0.5/durable-live-2/examples/python/canonical.py'),str(vectors)],cwd=ROOT,text=True)
        self.assertEqual(json.loads(go),json.loads(py))

if __name__=='__main__':unittest.main()
