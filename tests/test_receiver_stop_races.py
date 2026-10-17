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


class ReceiverStopInterleavingTests(unittest.TestCase):
    # Share fixture helpers without rediscovering ABC or the original99 tests.
    setUp = ReceiverStopRaceTests.setUp
    start = ReceiverStopRaceTests.start

    def local_stop(self):
        x = self.x
        return x.g.stop(x.p.control, rx.wire(x.c, runId=x.j.command['runId']))

    def assert_no_new_output(self, starts, media):
        self.assertEqual(self.x.r.tts_starts, starts)
        self.assertEqual(self.x.g.media_count, media)

    def unknown_latch(self):
        x = self.x
        self.assertEqual(len(x.b.latches), 1)
        grant = next(iter(x.b.latches))
        self.assertEqual(x.g.local_audit[grant]['state'], 'UNKNOWN')
        self.assertFalse(x.g.local)
        self.assertEqual(x.g.barrier_state, 'FENCED')
        self.assert_no_new_output(0, 0)
        # Backend may still know CONSUMED while Guardian knows only UNKNOWN.
        q = rx.wire(x.c, bootstrapId=x.b.registration['binding']['bootstrapId'], grantId=grant)
        self.assertEqual(x.g.query_consumption(x.r.peer, q)['summary']['state'], 'UNKNOWN')
        for _ in range(3):
            with self.assertRaises(ValueError):
                x.consume(self.request)
        self.assertEqual(len(x.b.latches), 1)

    def test_stop_after_first_query_prevents_backend_commit(self):
        x = self.x
        q, _ = x.ready()
        original = x.b.snapshot
        def stopped(peer, request):
            out = original(peer, request)
            self.local_stop()
            return out
        x.b.snapshot = stopped
        with self.assertRaises(ValueError):
            x.consume(q)
        self.assertEqual(x.b.registration['state'], 'ACTIVE')
        self.assertFalse(x.b.latches)
        self.assert_no_new_output(0, 0)

    def test_stop_during_commit_preserves_consumed_latch_unknown(self):
        x = self.x
        self.request, _ = x.ready()
        original = x.b.commit
        def stopped(peer, request):
            out = original(peer, request)
            self.local_stop()
            return out
        x.b.commit = stopped
        with self.assertRaises(ValueError):
            x.consume(self.request)
        self.unknown_latch()

    def test_stop_before_fsync_cannot_rearm(self):
        x = self.x
        self.request, _ = x.ready()
        x.g.before_fsync = self.local_stop
        with self.assertRaises(ValueError):
            x.consume(self.request)
        self.unknown_latch()

    def test_stop_after_fsync_cannot_rearm(self):
        x = self.x
        self.request, _ = x.ready()
        x.g.after_commit = self.local_stop
        with self.assertRaises(ValueError):
            x.consume(self.request)
        self.unknown_latch()

    def test_stop_immediately_before_positive_ack_suppresses_ack(self):
        x = self.x
        self.request, _ = x.ready()
        x.g.before_consume_ack = self.local_stop
        with self.assertRaises(ValueError):
            x.consume(self.request)
        self.unknown_latch()
        self.assertFalse(any(e['kind'] == 'CONSUME_ACK' for e in x.g.linearized))

    def test_stop_immediately_before_media_handoff(self):
        x = self.x
        q, execution = self.start()
        x.g.before_handoff = self.local_stop
        with self.assertRaises(ValueError):
            x.r.push_media(execution, q['references']['permitId'])
        self.assert_no_new_output(1, 0)
        self.assertFalse(any(e['kind'] == 'MEDIA' for e in x.g.linearized))

    def test_stop_during_renew_query(self):
        x = self.x
        q, execution = self.start()
        original = x.b.snapshot
        def stopped(peer, request):
            out = original(peer, request)
            self.local_stop()
            return out
        x.b.snapshot = stopped
        with self.assertRaises(ValueError):
            x.r.renew(execution, q['references']['permitId'])
        self.assert_no_new_output(1, 0)

    def test_stop_at_final_renew_commit(self):
        x = self.x
        q, execution = self.start()
        x.g.before_renew_commit = self.local_stop
        with self.assertRaises(ValueError):
            x.r.renew(execution, q['references']['permitId'])
        self.assert_no_new_output(1, 0)

    def finish_ready(self):
        x = self.x
        q, execution = self.start()
        x.r.push_media(execution, q['references']['permitId'])
        evidence = x.rows['JournalConfirmAnswerSegment']['request']['evidence']
        x.g.observer_fixture = lambda binding: evidence
        return q, execution, x.r.execution_request(execution)

    def test_stop_during_finish_authority_query(self):
        x = self.x
        _, execution, request = self.finish_ready()
        original = x.b.snapshot
        def stopped(peer, q):
            out = original(peer, q)
            self.local_stop()
            return out
        x.b.snapshot = stopped
        with self.assertRaises(ValueError):
            x.g.finish_unit(x.r.peer, request)
        self.assertNotIn(execution, x.g.finished_units)
        self.assertEqual(x.g.barrier_state, 'FENCED')
        self.assert_no_new_output(1, 1)

    def test_stop_during_finish_observer(self):
        x = self.x
        _, execution, request = self.finish_ready()
        observer = x.g.observer_fixture
        def stopped(binding):
            evidence = observer(binding)
            self.local_stop()
            return evidence
        x.g.observer_fixture = stopped
        with self.assertRaises(ValueError):
            x.g.finish_unit(x.r.peer, request)
        self.assertNotIn(execution, x.g.finished_units)
        self.assertEqual(x.g.barrier_state, 'FENCED')
        self.assert_no_new_output(1, 1)

    def test_stop_at_final_finish_commit(self):
        x = self.x
        _, execution, request = self.finish_ready()
        x.g.before_finish_commit = self.local_stop
        with self.assertRaises(ValueError):
            x.g.finish_unit(x.r.peer, request)
        self.assertNotIn(execution, x.g.finished_units)
        self.assertEqual(x.g.barrier_state, 'FENCED')
        self.assert_no_new_output(1, 1)

    def test_finish_during_media_rpc_invalidates_barrier_without_run_stop(self):
        x = self.x
        q, execution, _ = self.finish_ready()
        original = x.b.snapshot
        fired = []
        def finish_after_read(peer, request):
            out = original(peer, request)
            if not fired:
                fired.append(True)
                x.drain()
            return out
        x.b.snapshot = finish_after_read
        with self.assertRaises(ValueError):
            x.r.push_media(execution, q['references']['permitId'])
        self.assertEqual(x.g.barrier_state, 'STAGED_CLOSED')
        self.assertNotIn(x.j.command['runId'], x.g.stops)
        self.assert_no_new_output(1, 1)

    def test_fenced_closing_unknown_admission_never_queries_authority(self):
        for state in ('FENCED', 'CLOSING', 'UNKNOWN'):
            with self.subTest(state=state):
                self.setUp()
                x = self.x
                q, _ = x.ready()
                x.g.barrier_state = state
                def forbidden(*args):
                    self.fail('must reject locally before Authority RPC')
                x.b.snapshot = forbidden
                with self.assertRaises(ValueError):
                    x.consume(q)
                self.assertFalse(x.b.latches)
                self.assert_no_new_output(0, 0)

    def test_all_execution_paths_deny_after_local_stop(self):
        x = self.x
        q, execution = self.start()
        self.local_stop()
        for action in (lambda: x.consume(q), lambda: x.r.renew(execution, q['references']['permitId']),
                       lambda: x.r.push_media(execution, q['references']['permitId']),
                       lambda: x.g.finish_unit(x.r.peer, x.r.execution_request(execution))):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(x.b.registration['state'], 'ACTIVE')
        self.assert_no_new_output(1, 0)

    def test_stage_cannot_reopen_stopped_or_fenced_existing_context(self):
        for mode in ('stop', 'fenced', 'unknown'):
            with self.subTest(mode=mode):
                self.setUp()
                x = self.x
                x.ready()
                if mode == 'stop':
                    self.local_stop()
                else:
                    x.g.barrier_state = mode.upper()
                with self.assertRaises(ValueError):
                    x.g.stage(x.p.control, x.p.transcript[0]['request'])
                self.assertFalse(x.b.latches)
                self.assert_no_new_output(0, 0)

    def test_restart_during_final_consume_proof_rejects_old_identity(self):
        for process in ('runtime', 'guardian'):
            with self.subTest(process=process):
                self.setUp()
                x = self.x
                q, _ = x.ready()
                x.g.before_consume_ack = x.r.restart if process == 'runtime' else x.g.restart
                with self.assertRaises(ValueError):
                    x.consume(q)
                with self.assertRaises(ValueError):
                    x.consume(q)
                self.assertEqual(len(x.b.latches), 1)
                self.assert_no_new_output(0, 0)

    def test_restart_during_media_proof_rejects_old_identity(self):
        for process in ('runtime', 'guardian'):
            with self.subTest(process=process):
                self.setUp()
                x = self.x
                q, execution = self.start()
                x.g.before_handoff = x.r.restart if process == 'runtime' else x.g.restart
                with self.assertRaises(ValueError):
                    x.r.push_media(execution, q['references']['permitId'])
                self.assert_no_new_output(1, 0)

    def test_finish_expired_during_observer_cannot_close_unit(self):
        x = self.x
        _, execution, q = self.finish_ready()
        observer = x.g.observer_fixture
        def late(binding):
            evidence = observer(binding)
            x.j.now += 1.1
            return evidence
        x.g.observer_fixture = late
        with self.assertRaisesRegex(ValueError, 'LEASE_LOST'):
            x.g.finish_unit(x.r.peer, q)
        self.assertNotIn(execution, x.g.finished_units)
        self.assert_no_new_output(1, 1)

    def test_wrong_authenticated_channel_rejected_by_every_execution_path(self):
        x = self.x
        q, execution, finish = self.finish_ready()
        other = x.r.peer._replace(channelBinding=x.c.digest('other_live_connection'))
        for action in (lambda: x.g.renew(other, x.r.execution_request(execution, q['references']['permitId'])),
                       lambda: x.g.media(other, x.r.execution_request(execution, q['references']['permitId'], True)),
                       lambda: x.g.finish_unit(other, finish)):
            with self.assertRaisesRegex(ValueError, 'FORBIDDEN'):
                action()
        self.assert_no_new_output(1, 1)

    def test_normal_finish_is_not_stop_and_unit2_remains_legal(self):
        x = self.x
        q, execution = self.start()
        x.r.push_media(execution, q['references']['permitId'])
        registration = x.b.registration.copy()
        revision = x.g.barrier
        x.drain()
        self.assertGreater(x.g.barrier, revision)
        self.assertEqual(x.g.barrier_state, 'STAGED_CLOSED')
        self.assertFalse(x.g.stops)
        x.prepare(1)
        q2, _ = x.permit_and_start(1)
        ack = x.consume(q2)
        self.assertTrue(x.r.accept_ack(q2, ack))
        self.assertEqual(x.b.registration, registration)
        self.assertEqual(x.j.command_start_count, 1)
        self.assertEqual(x.r.tts_starts, 2)
        self.assertEqual(x.g.media_count, 1)

    def test_unrelated_run_stop_does_not_close_current_registration(self):
        x = self.x
        q, _ = x.ready()
        x.g.stop(x.p.control, rx.wire(x.c, runId='different_run'))
        ack = x.consume(q)
        self.assertTrue(x.r.accept_ack(q, ack))
        self.assertEqual(x.r.tts_starts, 1)

    def blocked_operation_stop(self, operation, install_pause, expected_latches, starts, media):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        entered, release = Event(), Event()
        def pause():
            entered.set()
            self.assertTrue(release.wait(3), 'test did not release external operation')
        install_pause(pause)
        with ThreadPoolExecutor(2) as pool:
            work = pool.submit(operation)
            try:
                self.assertTrue(entered.wait(2), 'external operation never reached')
                # If the operation holds the Guardian lock across RPC/callback,
                # this timeout fails instead of hanging the test indefinitely.
                stop = pool.submit(self.local_stop)
                self.assertEqual(stop.result(timeout=1)['state'], 'CLOSED_FENCED')
            finally:
                release.set()
            with self.assertRaises(ValueError):
                work.result(timeout=2)
        self.assertEqual(len(self.x.b.latches), expected_latches)
        self.assertEqual(self.x.g.barrier_state, 'FENCED')
        self.assert_no_new_output(starts, media)

    def test_stop_does_not_wait_for_consume_authority_rpc(self):
        x = self.x
        q, _ = x.ready()
        original = x.b.snapshot
        def install(pause):
            def blocked(peer, request):
                out = original(peer, request)
                pause()
                return out
            x.b.snapshot = blocked
        self.blocked_operation_stop(lambda: x.consume(q), install, 0, 0, 0)

    def test_stop_does_not_wait_for_media_authority_rpc(self):
        x = self.x
        q, execution = self.start()
        original = x.b.snapshot
        def install(pause):
            def blocked(peer, request):
                out = original(peer, request)
                pause()
                return out
            x.b.snapshot = blocked
        self.blocked_operation_stop(lambda: x.r.push_media(execution, q['references']['permitId']), install, 1, 1, 0)

    def test_stop_does_not_wait_for_deny_replay_fsync(self):
        x = self.x
        q, _ = x.ready()
        def install(pause):
            x.g.before_fsync = pause
        self.blocked_operation_stop(lambda: x.consume(q), install, 1, 0, 0)

    def test_stop_does_not_wait_for_drain_observer(self):
        x = self.x
        _, _, request = self.finish_ready()
        observer = x.g.observer_fixture
        def install(pause):
            def blocked(binding):
                out = observer(binding)
                pause()
                return out
            x.g.observer_fixture = blocked
        self.blocked_operation_stop(lambda: x.g.finish_unit(x.r.peer, request), install, 1, 1, 1)

    def test_concurrent_stop_media_commits_have_one_linearizable_order(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        for _ in range(24):
            self.setUp()
            x = self.x
            q, execution = self.start()
            barrier = Barrier(2)
            def media():
                barrier.wait()
                try:
                    return x.r.push_media(execution, q['references']['permitId'])['accepted']
                except ValueError:
                    return False
            def stop():
                barrier.wait()
                return self.local_stop()
            with ThreadPoolExecutor(2) as pool:
                a, b = pool.submit(media), pool.submit(stop)
                accepted, stopped = a.result(timeout=2), b.result(timeout=2)
            kinds = [e['kind'] for e in x.g.linearized]
            self.assertEqual(kinds.count('STOP'), 1)
            self.assertEqual(kinds.count('MEDIA'), int(accepted))
            if accepted:
                self.assertLess(kinds.index('MEDIA'), kinds.index('STOP'))
            with self.assertRaises(ValueError):
                x.r.push_media(execution, q['references']['permitId'])
            self.assertEqual(x.g.media_count, int(accepted))
            self.assertEqual(x.r.tts_starts, 1)

    def test_concurrent_stop_consume_never_rearms_after_local_close(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        for _ in range(16):
            self.setUp()
            x = self.x
            q, _ = x.ready()
            barrier = Barrier(2)
            def consume():
                barrier.wait()
                try:
                    return x.consume(q)
                except ValueError:
                    return None
            def stop():
                barrier.wait()
                return self.local_stop()
            with ThreadPoolExecutor(2) as pool:
                a, b = pool.submit(consume), pool.submit(stop)
                ack, stopped = a.result(timeout=2), b.result(timeout=2)
            kinds = [e['kind'] for e in x.g.linearized]
            if ack and ack['consumeAuthorized']:
                self.assertLess(kinds.index('CONSUME_ACK'), kinds.index('STOP'))
                with self.assertRaises(ValueError):
                    x.r.accept_ack(q, ack)
            self.assertEqual(x.b.registration['state'], 'ACTIVE')
            self.assertEqual(x.g.barrier_state, 'FENCED')
            with self.assertRaises(ValueError):
                x.consume(q)
            self.assert_no_new_output(0, 0)

    def test_media_that_wins_before_stop_is_ordered_and_cannot_repeat(self):
        x = self.x
        q, execution = self.start()
        self.assertTrue(x.r.push_media(execution, q['references']['permitId'])['accepted'])
        self.local_stop()
        kinds = [e['kind'] for e in x.g.linearized]
        self.assertLess(kinds.index('MEDIA'), kinds.index('STOP'))
        with self.assertRaises(ValueError):
            x.r.push_media(execution, q['references']['permitId'])
        self.assert_no_new_output(1, 1)

    def test_stop_after_last_proof_without_backend_stop_still_cancels_ack(self):
        x = self.x
        self.request, _ = x.ready()
        original = x.b.snapshot
        calls = []
        def stop_at_third_read(peer, request):
            out = original(peer, request)
            calls.append(True)
            if len(calls) == 3:
                self.local_stop()
            return out
        x.b.snapshot = stop_at_third_read
        with self.assertRaises(ValueError):
            x.consume(self.request)
        self.assertEqual(x.b.registration['state'], 'ACTIVE')
        self.unknown_latch()



    def test_thirty_two_identical_consume_requests_have_one_positive_ack(self):
        from concurrent.futures import ThreadPoolExecutor
        x = self.x
        q, _ = x.ready()
        with ThreadPoolExecutor(8) as pool:
            acks = list(pool.map(lambda _: x.g.consume(x.r.peer, q), range(32)))
        winners = [a for a in acks if a['consumeAuthorized']]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(x.b.latches), 1)
        self.assertTrue(all(a['consumption'] is None for a in acks if not a['consumeAuthorized']))
        self.assertTrue(x.r.accept_ack(q, winners[0]))
        self.assert_no_new_output(1, 0)

    def test_thirty_two_identical_media_ordinals_have_one_handoff(self):
        from concurrent.futures import ThreadPoolExecutor
        x = self.x
        q, execution = self.start()
        request = x.r.execution_request(execution, q['references']['permitId'], True)
        def send(_):
            try:
                return x.g.media(x.r.peer, request)['accepted']
            except ValueError as e:
                self.assertEqual(str(e), 'BOUNDARY_CONFLICT')
                return False
        with ThreadPoolExecutor(8) as pool:
            self.assertEqual(sum(pool.map(send, range(32))), 1)
        self.assert_no_new_output(1, 1)

    def test_closed_and_unknown_execution_states_deny_every_output_path(self):
        for state in ('FENCED', 'CLOSING', 'UNKNOWN'):
            with self.subTest(state=state):
                self.setUp()
                x = self.x
                q, execution = self.start()
                x.g.barrier_state = state
                for action in (lambda: x.r.renew(execution, q['references']['permitId']),
                               lambda: x.r.push_media(execution, q['references']['permitId']),
                               lambda: x.g.finish_unit(x.r.peer, x.r.execution_request(execution))):
                    with self.assertRaises(ValueError):
                        action()
                self.assert_no_new_output(1, 0)

    def test_proof_expiry_at_final_handoff_rejects_media(self):
        x = self.x
        q, execution = self.start()
        def expire():
            x.j.now += 1.1
        x.g.before_handoff = expire
        with self.assertRaisesRegex(ValueError, 'LEASE_LOST'):
            x.r.push_media(execution, q['references']['permitId'])
        self.assert_no_new_output(1, 0)

    def race_stop_with_ongoing_commit(self, kind):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        for _ in range(12):
            self.setUp()
            x = self.x
            if kind == 'FINISH':
                q, execution, request = self.finish_ready()
                action = lambda: x.g.finish_unit(x.r.peer, request)
                baseline_media = 1
            else:
                q, execution = self.start()
                action = lambda: x.r.renew(execution, q['references']['permitId'])
                baseline_media = 0
            barrier = Barrier(2)
            def perform():
                barrier.wait()
                try:
                    action()
                    return True
                except ValueError:
                    return False
            def stop():
                barrier.wait()
                return self.local_stop()
            with ThreadPoolExecutor(2) as pool:
                a, b = pool.submit(perform), pool.submit(stop)
                accepted, stopped = a.result(timeout=2), b.result(timeout=2)
            kinds = [e['kind'] for e in x.g.linearized]
            # start() already installed Runtime's initial RENEW before the race.
            race_events = kinds[kinds.index('CONSUME_ACK') + 2:]
            if kind == 'FINISH':
                race_events = race_events[race_events.index('MEDIA') + 1:]
            self.assertEqual(race_events.count(kind), int(accepted))
            if accepted:
                self.assertLess(race_events.index(kind), race_events.index('STOP'))
            self.assertFalse(any(k in ('RENEW', 'FINISH', 'MEDIA', 'CONSUME_ACK')
                                 for k in race_events[race_events.index('STOP') + 1:]))
            self.assertEqual(x.g.barrier_state, 'FENCED')
            self.assert_no_new_output(1, baseline_media)

    def test_concurrent_stop_renew_has_no_commit_after_stop(self):
        self.race_stop_with_ongoing_commit('RENEW')

    def test_concurrent_stop_finish_has_no_reopen_after_stop(self):
        self.race_stop_with_ongoing_commit('FINISH')

if __name__ == '__main__':
    unittest.main()
