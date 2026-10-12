"""Transient staging proof arithmetic with explicit journal/sink test doubles."""
import copy
import unittest

from app.media_timeline import MediaTimeline
from gpu_worker import staging_contract as c
from gpu_worker.tests.test_staging_contract import produced


class JournalDouble:
    async def record(self, operation, command, proof):
        return {'durable': True, 'state': 'committed', 'revision': 1, 'receiptSeq': 4,
            'observationHash': 'sha256:' + 'a' * 64, 'producerIncarnation': 'fixture-runtime', 'testDouble': True}


class StagingTimelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.produced = produced()
        d = self.produced['descriptor']
        d['provenance']['source'] = 'CPU_SIMULATION'
        for key in d['resources']:
            if key.startswith('gpu_'):
                d['resources'][key] = None
        self.produced['descriptor_sha256'] = c.descriptor_hash(d)
        self.full = self.produced['identity']
        self.timeline = MediaTimeline(self.full['sessionId'], 1, 48000, JournalDouble())
        command = {key:self.full[key] for key in ('commandId','sessionId','runEpoch','timelineEpoch','segmentId','lane')}
        command['commandType'] = 'COMMIT_SEGMENT'
        descriptor = {'sampleCount':1920, 'contentHash':d['pcm_sha256'], 'finalMarker':True,
            'utteranceId':self.full['utteranceId'], 'requiredSinks':['preview','rtmp'],
            'workerEpoch':self.full['workerEpoch'], 'workerGenerationId':self.full['workerGenerationId'],
            'stagingDescriptorHash':self.produced['descriptor_sha256']}
        result = await self.timeline.CommitSegment(command, self.full['attemptId'], 1,
            descriptor, self.timeline.position(0), 0)
        self.identity = result['identity']
        refs = self.timeline.installation_ack(self.identity)
        self.commit = {'descriptor_sha256':self.produced['descriptor_sha256'],
            'a_installed_ref':c.installed_reference(self.full, refs['a_ack']), 'b_installed_ref':refs['b_installed_ref'],
            'output':{'sampleRate':48000,'startSample':0,'endSample':1920,'sourceRate':16000,
                'sourceSamples':640,'ratioNumerator':3,'ratioDenominator':1},
            'required_sinks':[{'sinkId':sink,'incarnation':'fixture-runtime'} for sink in ('preview','rtmp')], 'optional_sinks':[]}

    async def test_all_required_minimum_never_rounds_partial_frame_up(self):
        for sink in ('preview','rtmp'):
            self.assertTrue(self.timeline.observe_sink_progress(self.identity,sink,'video',0,1920))
            self.assertTrue(self.timeline.observe_sink_progress(self.identity,sink,'audio',0,960 if sink=='rtmp' else 1920))
        proof = self.timeline.consumed_pose_proof(self.identity,self.produced,self.commit)
        self.assertEqual(proof['latest_consumed_sequence'],-1)
        self.assertEqual(proof['output_end_sample'],960)
        self.assertEqual(proof['source_end_sample'],0)
        self.assertTrue(self.timeline.observe_sink_progress(self.identity,'rtmp','audio',960,1920))
        final = self.timeline.consumed_pose_proof(self.identity,self.produced,self.commit)
        self.assertEqual(final['latest_consumed_sequence'],0)
        self.assertEqual(final['source_end_sample'],640)
        self.assertEqual(final['output_end_sample'],1920)
        self.assertTrue(all(r['incarnation']=='fixture-runtime' for r in final['required_sink_receipts']))

    async def test_gap_foreign_incarnation_and_uninstalled_metadata_reject(self):
        self.assertFalse(self.timeline.observe_sink_progress(self.identity,'rtmp','audio',960,1920))
        for sink in ('preview','rtmp'):
            for medium in ('audio','video'):
                self.timeline.observe_sink_progress(self.identity,sink,medium,0,1920)
        forged = copy.deepcopy(self.commit)
        forged['required_sinks'][1]['incarnation']='foreign'
        with self.assertRaises(ValueError):
            self.timeline.consumed_pose_proof(self.identity,self.produced,forged)
        del self.timeline.installed_acks[self.identity.segmentId]['observationHash']
        with self.assertRaises(ValueError):self.timeline.installation_ack(self.identity)

    async def test_fence_rejects_pose_and_keeps_original_commit_shape(self):
        from dataclasses import asdict
        shape = asdict(self.timeline.commits[self.identity.segmentId])
        self.assertNotIn('installed_ack',shape)
        self.assertNotIn('producerIncarnation',shape)
        self.timeline.fence_now('STOP')
        with self.assertRaises(ValueError):self.timeline.installation_ack(self.identity)


if __name__ == '__main__':
    unittest.main()
