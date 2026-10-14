"""Local admission fault/diagnostic tests; no PG, media or GPU acceptance."""
import asyncio
import json
import time
import unittest
from types import SimpleNamespace

from app.durability_client import fingerprint
from app.narration import NarrationCommands
from app.narration_segments import SegmentExecutor
from app.session import RuntimeFailure


class AdmissionJournal:
    def __init__(self,remaining=1000):self.operations=[];self.remaining=remaining
    async def accept(self,command):
        self.operations.append('accept');return {'execute':True,'run':{'leaseToken':7}}
    async def start(self,command,token):
        self.operations.append('start');return {'execute':True,'run':{'remainingMs':self.remaining}}


class AdmissionDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self,remaining=1000):
        session=SimpleNamespace(state='LIVE',current_task=None)
        executor=SegmentExecutor.__new__(SegmentExecutor)
        executor.session=session;executor.closed=False;executor.task=None
        executor.timeline=SimpleNamespace(run_epoch=1,epoch=1)
        executor.run_guard=lambda:None
        session.continuity=executor
        journal=AdmissionJournal(remaining)
        manager=SimpleNamespace(get_session=lambda sid:session)
        adapter=NarrationCommands(journal,None,manager)
        adapter.runs['s']={'epoch':1,'deadline':time.monotonic()+10,'sealed':False,'barrier_pending':False}
        command={'schemaVersion':'0.5','commandType':'COMMIT_SEGMENT','sessionId':'s','runEpoch':1,'timelineEpoch':1,'commandId':'new-command','payload':{'text':'PRIVATE_PROVIDER_TEXT','leaseToken':'PRIVATE_LEASE_TOKEN'}}
        command['requestFingerprint']=fingerprint(command)
        return adapter,executor,journal,command

    def row(self,logs):
        raw=logs.output[0].split('narration_admission_failed ',1)[1]
        self.assertNotIn('PRIVATE',raw)
        return json.loads(raw)

    async def test_completed_sql_before_local_task_returns_can_reject_next_begin(self):
        adapter,executor,journal,command=self.adapter()
        # Controlled receipt-return window: SQL completion already visible,
        # previous local task still waiting for its completion HTTP response.
        returned=asyncio.Event()
        prior=asyncio.create_task(returned.wait())
        executor.task=prior;executor.session.current_task=prior
        try:
            with self.assertLogs('app',level='WARNING') as logs:
                with self.assertRaisesRegex(ValueError,'BOUNDARY_CONFLICT'):
                    await adapter.execute(command)
            row=self.row(logs)
            self.assertEqual(row['phase'],'segment_begin')
            self.assertEqual(row['code'],'BOUNDARY_CONFLICT')
            self.assertEqual(row['boundaryHint'],'ACTIVE_SEGMENT')
            self.assertFalse(row['previousTaskDone'])
            self.assertEqual(journal.operations,['accept','start'])
            self.assertFalse(prior.cancelled())
            self.assertFalse(executor.closed)
        finally:
            returned.set();await prior

    async def test_expired_started_grant_keeps_original_error_and_no_retry(self):
        adapter,executor,journal,command=self.adapter(0)
        with self.assertLogs('app',level='WARNING') as logs:
            with self.assertRaises(RuntimeFailure) as raised:await adapter.execute(command)
        self.assertEqual(raised.exception.code,'LEASE_LOST')
        row=self.row(logs)
        self.assertEqual(row['phase'],'post_start_guard');self.assertEqual(row['code'],'LEASE_LOST')
        self.assertTrue(row['deadlineExpired'])
        self.assertEqual(journal.operations,['accept','start'])
        self.assertIsNone(executor.task)

    async def test_unknown_exception_text_and_code_never_leak(self):
        adapter,executor,journal,command=self.adapter()
        async def fail(*args):raise RuntimeFailure('PRIVATE_UNAPPROVED_CODE','PRIVATE_EXCEPTION_BODY',409)
        executor.begin=fail
        with self.assertLogs('app',level='WARNING') as logs:
            with self.assertRaises(RuntimeFailure):await adapter.execute(command)
        self.assertEqual(self.row(logs)['code'],'OTHER')
        self.assertEqual(journal.operations,['accept','start'])

    async def test_actual_guard_exact_reasons_and_safe_link_scope(self):
        for closed,state,epoch,expected in ((True,'LIVE',1,'RUN_SEALED'),(False,'DEGRADED',1,'RUN_SEALED'),(False,'LIVE',2,'STALE_TIMELINE_EPOCH')):
            with self.subTest(closed=closed,state=state,epoch=epoch):
                adapter,executor,journal,command=self.adapter()
                executor.closed=closed;executor.session.state=state;executor.timeline.epoch=epoch
                executor.session.avatar_engine=SimpleNamespace(link=SimpleNamespace(failed=SimpleNamespace(code='STAGING_CONFLICT')))
                with self.assertLogs('app',level='WARNING') as logs:
                    with self.assertRaisesRegex(ValueError,expected):await adapter.execute(command)
                row=self.row(logs)
                self.assertEqual(row['code'],expected);self.assertEqual(row['sessionState'],state)
                self.assertEqual(row['executorClosed'],closed);self.assertEqual(row['timelineEpoch'],epoch)
                self.assertEqual(row['stagingLinkFailureCode'],'STAGING_CONFLICT')
                self.assertIsNone(row['boundaryHint']);self.assertEqual(journal.operations,['accept','start'])

    async def test_static_prefix_never_discloses_remainder_or_foreign_link_code(self):
        adapter,executor,journal,command=self.adapter()
        executor.session.avatar_engine=SimpleNamespace(link=SimpleNamespace(failed=SimpleNamespace(code='PRIVATE_LINK_CODE')))
        async def fail(*args):raise ValueError('RUN_SEALED: PRIVATE_EXCEPTION_BODY')
        executor.begin=fail
        with self.assertLogs('app',level='WARNING') as logs:
            with self.assertRaises(ValueError):await adapter.execute(command)
        row=self.row(logs);self.assertEqual(row['code'],'RUN_SEALED')
        self.assertIsNone(row['stagingLinkFailureCode']);self.assertIsNone(row['boundaryHint'])
