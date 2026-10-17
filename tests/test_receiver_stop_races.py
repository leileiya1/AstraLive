"""Independent Stop-boundary regressions; fixtures only, no production IO."""
import unittest
from tests import test_receiver_contracts as fixtures

rx = fixtures.rx

class ReceiverStopRaceTests(unittest.TestCase):
    def setUp(self):
        self.x = fixtures.ReceiverContractTests()
        self.x.setUp()

    def start(self):
        x = self.x
        q, _ = x.ready()
        ack = x.consume(q)
        x.r.accept_ack(q, ack)
        return q, ack['consumption']['binding']['executionId']

    def test_a_guardian_stop_without_backend_stop_rejects_consume(self):
        x = self.x
        q, _ = x.ready()
        stopped = x.g.stop(x.p.control, rx.wire(x.c, runId=x.j.command['runId']))
        self.assertEqual(stopped['state'], 'CLOSED_FENCED')
        self.assertEqual(x.b.registration['state'], 'ACTIVE')
        with self.assertRaises(ValueError):
            ack = x.consume(q)
            x.r.accept_ack(q, ack)
        self.assertFalse(x.b.latches)
        self.assertEqual(x.r.tts_starts, 0)
        self.assertEqual(x.g.media_count, 0)
        self.assertEqual(x.g.barrier_state, 'FENCED')

    def test_b_stop_after_authority_read_before_media_handoff(self):
        x = self.x
        q, execution = self.start()
        original = x.b.snapshot
        fired = []
        def stop_after_read(peer, request):
            out = original(peer, request)
            if not fired:
                fired.append(True)
                x.p.stop()
            return out
        x.b.snapshot = stop_after_read
        with self.assertRaises(ValueError):
            x.r.push_media(execution, q['references']['permitId'])
        self.assertEqual(x.g.media_count, 0)
        self.assertEqual(x.r.tts_starts, 1)  # already started before injected Stop
        self.assertEqual(x.g.barrier_state, 'FENCED')

    def test_c_stop_at_last_consume_query_suppresses_true_ack(self):
        x = self.x
        q, _ = x.ready()
        original = x.b.snapshot
        calls = []
        def stop_at_last_read(peer, request):
            out = original(peer, request)
            calls.append(True)
            if len(calls) == 3:
                x.p.stop()
            return out
        x.b.snapshot = stop_at_last_read
        with self.assertRaises(ValueError):
            x.consume(q)
        self.assertEqual(len(x.b.latches), 1)
        self.assertEqual(x.r.tts_starts, 0)
        self.assertEqual(x.g.media_count, 0)
        self.assertEqual(x.g.barrier_state, 'FENCED')

if __name__ == '__main__':
    unittest.main()
