"""CPU diagnostic fault injection; no GPU acceptance or altered budgets."""
import copy
import threading
import types
import unittest
from unittest.mock import Mock

from gpu_worker.staging_contract import ContractError
from gpu_worker.staging_service import StagingConnection, StagingDiagnosticFault, milliseconds


class DiagnosticTests(unittest.TestCase):
    def connection(self):
        events = []
        worker = types.SimpleNamespace(cfg=types.SimpleNamespace(staging_profile='staging-short-1',
            staging_short_gate_sha256=None, mode='simulation'),
            metrics=types.SimpleNamespace(epoch='diagnostic', event=lambda *a, **k: events.append((a, k))))
        conn = StagingConnection(worker, None, dict(session_id='diagnostic',
            requested_limits_revision='staging-short-1'))
        conn.stage = dict(identity={'workerGenerationId': 1}, state='STAGING', samples=640,
            frames={}, received=-1, pose=-1, slots=4, begin={},
            lease=types.SimpleNamespace(started=milliseconds(), deadline=milliseconds()+9000))
        conn.adapter = types.SimpleNamespace(cv=threading.Condition(), video=[], pending_samples=640,
            consume=Mock(side_effect=RuntimeError('secret-token private-path raw exception')))
        conn.resources = Mock(return_value=dict(worker_rgb_peak_bytes=0, worker_attempt_peak_bytes=1280,
            gpu_incremental_allocated_peak_bytes=None))
        conn.fence = Mock()
        conn.error = Mock()
        return conn, events

    def test_each_frozen_cap_reports_actual_snapshot_without_expansion(self):
        conn, events = self.connection()
        original_limits = copy.deepcopy(conn.limits)
        for field, cap, reason in (
            ('worker_rgb_peak_bytes', 'worker_rgb_bytes', 'WORKER_RGB_CAP'),
            ('worker_attempt_peak_bytes', 'worker_attempt_bytes', 'WORKER_HOST_CAP'),
            ('gpu_incremental_allocated_peak_bytes', 'gpu_incremental_allocated_bytes', 'GPU_ALLOCATED_CAP')):
            resources = dict(worker_rgb_peak_bytes=0, worker_attempt_peak_bytes=0,
                gpu_incremental_allocated_peak_bytes=None)
            resources[field] = conn.limits[cap]+1
            with self.assertRaises(StagingDiagnosticFault) as raised:
                conn.enforce_resources(resources)
            conn.failure_diagnostic('RESOURCE_CAP_CHECK', raised.exception)
            self.assertEqual(events[-1][1]['reason_code'], reason)
            self.assertEqual(events[-1][1]['resources'][field], original_limits[cap]+1)
            self.assertEqual(events[-1][1]['limits'], original_limits)
        self.assertEqual(conn.limits, original_limits)

    def test_native_failure_logs_phase_without_exception_text_then_fences(self):
        conn, events = self.connection()
        conn.sender()
        self.assertEqual(events[0][1]['reason_code'], 'NATIVE_CONSUME')
        self.assertEqual(events[0][1]['exception_type'], 'RuntimeError')
        self.assertNotIn('secret-token', repr(events))
        self.assertNotIn('private-path', repr(events))
        conn.fence.assert_called_once()
        conn.error.assert_called_once_with({}, 'STAGING_BUDGET_EXCEEDED')

    def test_produced_validation_logs_snapshot_and_keeps_existing_wire_error(self):
        conn, events = self.connection()
        conn.done = types.SimpleNamespace(wait=Mock(side_effect=[False, True]))
        conn.produced = Mock(side_effect=ContractError('sensitive invalid value'))
        conn.watcher()
        self.assertEqual(events[0][1]['phase'], 'PRODUCED_DESCRIPTOR_VALIDATION')
        self.assertEqual(events[0][1]['resources']['worker_attempt_peak_bytes'], 1280)
        self.assertNotIn('sensitive', repr(events))
        conn.fence.assert_called_once()

    def test_observation_failure_does_not_mask_original_fence_or_log_text(self):
        conn, events = self.connection()
        conn.resources.side_effect = ValueError('another secret')
        conn.sender()
        self.assertEqual(events[0][1]['resource_observation_error_type'], 'ValueError')
        self.assertIsNone(events[0][1]['resources'])
        self.assertNotIn('secret', repr(events))
        conn.fence.assert_called_once()


if __name__ == '__main__':
    unittest.main()
