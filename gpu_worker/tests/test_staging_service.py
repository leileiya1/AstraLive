"""Actual TCP/encoder/controller with CPU simulation; no GPU/playback claim."""
import asyncio
import copy
import hashlib
import os
import socket
import time
import unittest
from unittest.mock import patch

from gpu_worker import staging_contract as c
from gpu_worker.config import secret
from gpu_worker.tests.test_service import ServiceTests
from gpu_worker.tests.test_staging_contract import message
from gpu_worker.validated.wire import receive, send


class Client:
    def __init__(self, cfg):
        self.cfg = cfg
        self.socket = socket.create_connection(('127.0.0.1', cfg.port), timeout=3)
        self.socket.settimeout(3)
        auth = dict(type='Auth', protocol_version=1, internal_version='1.2', session_id='stage-test',
            token=secret(cfg.token_file), requested_capabilities=[c.CAPABILITY], requested_limits_revision='staging-short-1')
        send(self.socket, auth)
        self.ready, _ = receive(self.socket)
        c.validate_negotiation(auth, self.ready)
        self.gid = self.ready['highest_generation_id']
        self.identity = None
        self.produced = None

    def start(self, samples=640, lease=9000):
        self.gid += 1
        h = message('StageBegin')
        identity = h['identity']
        identity.update(sessionId='stage-test', workerRef=self.cfg.worker_ref,
            workerEpoch=self.ready['worker_epoch'], workerGenerationId=self.gid,
            stageId='stage-' + str(self.gid), segmentId='segment-' + str(self.gid))
        self.identity = identity
        self.pcm = bytes(samples * 2)
        h.update(session_id='stage-test', worker_epoch=self.ready['worker_epoch'], cache_id=self.ready['cache_id'],
            pcm_sha256=c.bytes_digest(self.pcm), original_samples=samples, pad_samples=0,
            source_samples=samples, lease_ms=lease, a_rtt_ms=1, grant_age_ms=0, worker_rtt_ms=1, safety_ms=100)
        h['a_grant'].update(sessionId='stage-test', runEpoch=1, remainingMs=10000)
        h['request_fingerprint'] = c.stage_begin_fingerprint(h)
        self.send(h)
        return self.expect('StageBegun')[0]

    def header(self, name):
        h = message(name)
        h.update(identity=copy.deepcopy(self.identity), session_id='stage-test', worker_epoch=self.ready['worker_epoch'])
        return h

    def send(self, header, payload=b''):
        c.validate_message(header, payload)
        send(self.socket, header, payload)

    def expect(self, name, allow_error=False):
        while True:
            h, payload = receive(self.socket)
            c.validate_message(h, payload)
            if h['type'] == name:
                return h, payload
            if h['type'] == 'StageError' and not allow_error:
                raise AssertionError(h)

    def audio(self):
        h = self.header('StageAudio')
        h.update(chunk_sequence=0, first_sample_index=0, sample_count=len(self.pcm)//2,
            final_chunk=True, chunk_sha256=c.bytes_digest(self.pcm))
        self.send(h, self.pcm)

    def receive_artifact(self):
        count = 0
        stream = hashlib.sha256()
        while True:
            h, payload = receive(self.socket)
            c.validate_message(h, payload)
            if h['type'] == 'StageVideo':
                self.assert_frame(h, count)
                import struct
                stream.update(struct.pack('!Q', len(payload)) + payload)
                ack = self.header('StageReceived')
                ack.update(frame_sequence=count, payload_sha256=h['payload_sha256'],
                    native_rgb_sha256=h['native_rgb_sha256'], storage_receipt_id='stored-' + str(count))
                self.send(ack)
                count += 1
            elif h['type'] == 'StageProduced':
                assert h['descriptor']['frame_count'] == count
                assert h['descriptor']['video_stream_sha256'] == 'sha256:' + stream.hexdigest()
                assert h['descriptor']['provenance']['source'] == 'CPU_SIMULATION'
                assert h['descriptor']['resources']['gpu_baseline_allocated_bytes'] is None
                self.produced = h
                return h
            elif h['type'] == 'StageError':
                raise AssertionError(h)

    @staticmethod
    def assert_frame(header, seq):
        assert header['frame_sequence'] == seq
        assert header['pts_us'] == seq * 40000
        assert seq or header['keyframe']

    def arm(self):
        h = self.header('StageCommit')
        proof = h['commit_proof']
        proof['descriptor_sha256'] = self.produced['descriptor_sha256']
        for k in ('sessionId','runEpoch','timelineEpoch','commandId','segmentId','attemptId','generationId'):
            proof['a_installed_ref'][k] = self.identity[k]
        proof['a_installed_ref'].update(producerIncarnation='runtime-test', receiptSeq=4, timelineRevision=1)
        proof['b_installed_ref'].update(revision=1, receipt_ref='real-test-double-install')
        proof['required_sinks'] = [dict(sinkId='preview', incarnation='runtime-test'), dict(sinkId='rtmp', incarnation='runtime-test')]
        proof['optional_sinks'] = []
        samples = len(self.pcm)//2
        proof['output'].update(sampleRate=48000, startSample=100, endSample=100+samples*3,
            sourceSamples=samples, ratioNumerator=3, ratioDenominator=1)
        h['commit_proof_fingerprint'] = c.commit_fingerprint(self.identity, proof)
        self.commit_header = h
        self.send(h)
        return self.expect('StageCommitAck')[0]

    def pose(self):
        h = self.header('StagePoseConsumed')
        proof = h['pose_proof']
        samples = len(self.pcm)//2
        proof.update(pose_ack_id='pose-' + str(self.gid), descriptor_sha256=self.produced['descriptor_sha256'],
            commit_proof_fingerprint=self.commit_header['commit_proof_fingerprint'],
            latest_consumed_sequence=samples//640-1, source_end_sample=samples,
            output_end_sample=100+samples*3)
        proof['required_sink_receipts'] = [dict(sinkId=sink, incarnation='runtime-test',
            evidenceRef='TEST_DOUBLE:' + sink, localRevision=1, startSample=100,
            audioEndSample=100+samples*3, videoEndSample=100+samples*3, evidenceType='sink_consumed') for sink in ('preview','rtmp')]
        h['pose_proof_fingerprint'] = c.pose_fingerprint(self.identity, proof)
        self.pose_header = h
        self.send(h)
        return self.expect('StagePoseConsumedAck')[0]

    def cancel(self):
        h = self.header('StageCancel')
        h.update(control_id='control-' + str(self.gid), reason='STOP')
        self.send(h)
        return self.expect('StageFenced')[0]

    def release(self, complete=False, armed=False, pose=False):
        h = self.header('StageRelease')
        h.update(control_id='control-' + str(self.gid), reason='COMPLETE' if complete else 'CANCELLED',
            descriptor_sha256=self.produced['descriptor_sha256'] if self.produced else None,
            commit_proof_fingerprint=self.commit_header['commit_proof_fingerprint'] if armed else None,
            pose_proof_fingerprint=self.pose_header['pose_proof_fingerprint'] if pose else None,
            latest_consumed_sequence=len(self.pcm)//1280-1 if pose else -1)
        self.send(h)
        return self.expect('StageReleased')[0]

    def close(self):
        self.socket.close()


class StagingServiceTests(ServiceTests):
    async def asyncSetUp(self):
        self.env_patch = patch.dict(os.environ, {'ASTRALIVE_WORKER_STAGING_ENABLED':'true'})
        self.env_patch.start()
        await super().asyncSetUp()
        self.stage_clients = []

    async def asyncTearDown(self):
        for client in self.stage_clients:
            client.close()
        try:
            await super().asyncTearDown()
        finally:
            self.env_patch.stop()

    async def client(self):
        result = await asyncio.to_thread(Client, self.cfg)
        self.stage_clients.append(result)
        return result

    async def test_produced_without_pose_then_cancel_next_is_clean(self):
        client = await self.client()
        def run():
            first = client.start(15360)
            client.audio()
            artifact = client.receive_artifact()
            self.assertEqual(artifact['descriptor']['frame_count'], 24)
            fenced = client.cancel()
            self.assertEqual(fenced['pose_history_sha256'], first['pose_history_sha256'])
            self.assertEqual(fenced['latest_consumed_sequence'], -1)
            released = client.release()
            self.assertTrue(released['reusable'])
            self.assertEqual(released['terminal_disposition'], 'PROVEN_CANCELLED')
            client.produced = None
            second = client.start()
            self.assertEqual(second['pose_history_sha256'], first['pose_history_sha256'])
            client.cancel()
            client.release()
        await asyncio.to_thread(run)

    async def test_all_required_pose_and_successful_release(self):
        client = await self.client()
        def run():
            first = client.start(6400)
            client.audio();client.receive_artifact();client.arm()
            applied = client.pose()
            self.assertNotEqual(applied['pose_history_sha256'], first['pose_history_sha256'])
            client.send(client.pose_header)
            duplicate = client.expect('StagePoseConsumedAck')[0]
            self.assertEqual(duplicate, applied)
            released = client.release(complete=True, armed=True, pose=True)
            self.assertEqual(released['terminal_disposition'], 'PROVEN_COMPLETE')
            self.assertTrue(released['reusable'])
        await asyncio.to_thread(run)

    async def test_postcommit_cancel_is_unknown_and_blocks_new_generation(self):
        client = await self.client()
        def run():
            client.start();client.audio();client.receive_artifact();client.arm();client.cancel()
            released = client.release(armed=True)
            self.assertEqual(released['terminal_disposition'], 'UNKNOWN')
            self.assertFalse(released['reusable'])
            client.gid += 1
            h = self.header_for_future(client)
            client.send(h)
            self.assertEqual(client.expect('StageError', allow_error=True)[0]['code'], 'STAGING_RETIRED')
        await asyncio.to_thread(run)

    @staticmethod
    def header_for_future(client):
        h = client.header('StageBegin')
        h['identity']['workerGenerationId'] = client.gid
        h['identity']['stageId'] += '-future'
        h.update(cache_id=client.ready['cache_id'], pcm_sha256=c.bytes_digest(client.pcm),
            original_samples=640,pad_samples=0,source_samples=640,lease_ms=9000,a_rtt_ms=1,grant_age_ms=0,worker_rtt_ms=1,safety_ms=100)
        h['a_grant'].update(sessionId='stage-test',runEpoch=1,remainingMs=10000)
        h['request_fingerprint'] = c.stage_begin_fingerprint(h)
        return h

    async def test_withheld_storage_credit_health_and_cancel_remain_responsive(self):
        client = await self.client()
        def run():
            client.start(15360);client.audio()
            received = 0
            while received < 4:
                h, _ = receive(client.socket)
                if h['type'] == 'StageVideo':received += 1
            health = dict(type='StageHealth',contract_revision=c.REVISION,session_id='stage-test',worker_epoch=client.ready['worker_epoch'],nonce='nonce')
            client.send(health)
            result = client.expect('StageHealthAck')[0]
            self.assertEqual(result['network_inflight_frames'],4)
            self.assertLessEqual(result['native_queue_frames'],24)
            client.cancel();client.release()
        await asyncio.to_thread(run)

    async def test_lease_expiry_refuses_renewal_and_cleanup_is_possible(self):
        client = await self.client()
        def run():
            client.start(lease=150)
            error = client.expect('StageError',allow_error=True)[0]
            self.assertEqual(error['code'],'STAGING_LEASE_EXPIRED')
            h = client.header('StageRenew')
            h.update(renewal_sequence=1,lease_ms=9000,a_rtt_ms=1,grant_age_ms=0,worker_rtt_ms=1,safety_ms=100)
            h['a_grant'].update(sessionId='stage-test',runEpoch=1,remainingMs=10000)
            h['renewal_fingerprint']=c.renewal_fingerprint(h)
            client.send(h)
            self.assertEqual(client.expect('StageError',allow_error=True)[0]['code'],'STAGING_RETIRED')
            client.cancel();client.release()
        await asyncio.to_thread(run)


if __name__ == '__main__':
    unittest.main()
