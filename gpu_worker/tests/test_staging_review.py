"""Regression for independent review: UNKNOWN is process-incarnation sticky."""
import types
import unittest

from gpu_worker.staging_contract import ContractError, REVISION
from gpu_worker.staging_service import StagingConnection


class BrokenSocket:
    def sendall(self, _):
        raise OSError('owned diagnostic disconnect')
    def shutdown(self, _):
        pass


class StickyUnknownTests(unittest.TestCase):
    def connection(self):
        worker = types.SimpleNamespace(cfg=types.SimpleNamespace(staging_profile='staging-short-1',
            staging_short_gate_sha256=None,mode='simulation'), metrics=types.SimpleNamespace(epoch='old-incarnation'),
            staging_unknown=True)
        connection = StagingConnection(worker,BrokenSocket(),{'session_id':'new-unstarted-session',
            'requested_limits_revision':'staging-short-1'})
        return worker, connection

    def health(self, sequence=0):
        return {'type':'StageHealthAck','contract_revision':REVISION,'session_id':'new-unstarted-session',
            'worker_epoch':'old-incarnation','nonce':'nonce-'+str(sequence),'audio_credit_samples':32000,
            'native_queue_frames':0,'network_inflight_frames':0}

    def test_unstarted_connection_writer_failure_keeps_prior_unknown(self):
        worker, connection = self.connection()
        connection.reply(self.health())
        connection.writer()
        self.assertTrue(connection.done.is_set())
        self.assertIsNone(connection.stage)
        self.assertTrue(worker.staging_unknown,'writer must not clear an older incarnation UNKNOWN')

    def test_unstarted_connection_queue_overflow_keeps_prior_unknown(self):
        worker, connection = self.connection()
        for sequence in range(64):
            connection.reply(self.health(sequence))
        with self.assertRaises(ContractError):
            connection.reply(self.health(65))
        self.assertTrue(worker.staging_unknown,'capacity failure must not clear an older UNKNOWN')


if __name__=='__main__':
    unittest.main()
