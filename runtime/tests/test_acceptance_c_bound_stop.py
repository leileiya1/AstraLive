"""Actual BoundSessionManager/Session/TCP control; bindings and Worker are CPU
fixtures, and the fence callback is a control-only stub. No media/GPU claim.
"""
import asyncio
import copy
from types import SimpleNamespace
import unittest
from app.soulx_staging import Stage
from app.session import RuntimeFailure
from gpu_worker.tests.test_staging_contract import begin
import test_staging_binding_lifecycle as lifecycle_fixture
from test_staging_tcp import SoftwareWorkerWire

class DeferredReleaseWire(SoftwareWorkerWire):
    def __init__(self):
        super().__init__();self.release_seen=asyncio.Event();self.release_gate=asyncio.Event();self.release_sender=None
    async def send(self,writer,header,payload=b''):
        if header['type']=='StageReleased':
            async def later():
                self.release_seen.set();await self.release_gate.wait()
                await super(DeferredReleaseWire,self).send(writer,header,payload)
            self.release_sender=asyncio.create_task(later());return
        await super().send(writer,header,payload)

class AcceptanceBoundStopTests(unittest.IsolatedAsyncioTestCase):
    async def setup_control(self,wire):
        manager,binding,publisher,request,wire=await lifecycle_fixture.BoundStagingLifecycleTests.setup_manager(self,wire)
        await manager.create_session(request)
        for _ in range(100):
            if manager.get_session('s').state=='READY':break
            await asyncio.sleep(.01)
        await manager.start_session('s','start')
        session=manager.get_session('s');fences=[]
        # Strict cleanup is enabled while publication itself remains an explicit
        # control fixture; no synthetic callback is called real media proof.
        session.continuity=SimpleNamespace(fence=fences.append)
        request=begin();request['session_id']='s';request['worker_epoch']='software-epoch'
        request['identity'].update(sessionId='s',workerEpoch='software-epoch',workerRef=session.avatar_engine.link.worker_ref,workerGenerationId=8)
        ready=asyncio.get_running_loop().create_future();ready.set_result(None)
        stage=Stage(copy.deepcopy(request['identity']),request,produced=ready)
        wire.begin=request;session.avatar_engine.link.active=stage
        return manager,binding,publisher,session,stage,fences

    async def test_repeated_cancelled_stop_keeps_binding_until_exact_cleanup_ack(self):
        wire=SoftwareWorkerWire(block_cancel=True)
        manager,binding,publisher,session,stage,fences=await self.setup_control(wire)
        callers=[]
        try:
            first=asyncio.create_task(manager.stop_session('s','stop1'));callers.append(first)
            await asyncio.wait_for(wire.cancel_seen.wait(),2)
            first.cancel();await asyncio.gather(first,return_exceptions=True)
            original=stage.release_task
            second=asyncio.create_task(manager.stop_session('s','stop2'));callers.append(second)
            await asyncio.sleep(.01);second.cancel();await asyncio.gather(second,return_exceptions=True)
            self.assertIs(stage.release_task,original);self.assertFalse(original.cancelled())
            self.assertIn('s',manager.sessions);self.assertIn('s',manager.bound)
            self.assertEqual(binding.released,[]);self.assertIsNone(stage.released)
            final=asyncio.create_task(manager.stop_session('s','stop3'));callers.append(final)
            wire.cancel_gate.set();await asyncio.wait_for(final,2)
            self.assertEqual(session.state,'ENDED');self.assertEqual(binding.released,['s'])
            self.assertNotIn('s',manager.sessions);self.assertNotIn('s',manager.bound)
            self.assertEqual(wire.events.count('StageCancel'),1);self.assertEqual(wire.events.count('StageRelease'),1)
            self.assertEqual(stage.release_parameters,(False,'FORCE'))
            self.assertIsNone(session.avatar_engine.link.failed);self.assertIsNone(session.avatar_engine.link.writer)
            self.assertTrue(fences);self.assertIsNone(wire.error)
        finally:
            wire.cancel_gate.set()
            for task in callers:
                if not task.done():task.cancel()
            await asyncio.gather(*callers,return_exceptions=True)

    async def test_session_original_time_budgets_keep_binding_pending_until_explicit_cleanup(self):
        wire=DeferredReleaseWire()
        manager,binding,publisher,session,stage,fences=await self.setup_control(wire)
        try:
            with self.assertRaises(RuntimeFailure):await manager.stop_session('s','budget-stop')
            self.assertTrue(wire.release_seen.is_set())
            self.assertEqual(session.state,'STOPPING');self.assertIn('s',manager.sessions)
            self.assertIn('s',manager.bound);self.assertEqual(binding.released,[])
            self.assertIsNone(stage.released);self.assertFalse(stage.release_task.done())
            # A late physical proof alone must not emit Session ENDED or release
            # the binding after the original control budgets failed.
            wire.release_gate.set();await asyncio.wait_for(asyncio.shield(stage.release_task),2)
            self.assertEqual(session.state,'STOPPING');self.assertEqual(binding.released,[])
            self.assertEqual(wire.events.count('StageRelease'),1)
            await manager.stop_session('s','explicit-cleanup')
            self.assertEqual(session.state,'ENDED');self.assertEqual(binding.released,['s'])
            self.assertNotIn('s',manager.sessions);self.assertIsNone(session.avatar_engine.link.writer)
            self.assertIsNone(wire.error)
        finally:
            wire.release_gate.set()
            if wire.release_sender:await asyncio.gather(wire.release_sender,return_exceptions=True)
