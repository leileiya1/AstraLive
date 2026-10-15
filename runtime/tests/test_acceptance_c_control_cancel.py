"""Real loopback control peer; no Worker native/GPU/auth/Provider acceptance."""
import asyncio
import copy
import json
import unittest
from app.soulx_staging import StagingClient,Stage,StagingFailure
from app.staging_settings import StagingSettings
from gpu_worker.tests.test_staging_contract import begin,message,commit,pose,produced
from test_staging_pose_stop import read,send

class AcceptanceControlCancelTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self,phase,*,armed=False,complete=False):
        pending=asyncio.Event();allow=asyncio.Event();reply_sent=asyncio.Event();peer_done=asyncio.Event();wire=[];errors=[]
        async def peer(reader,writer):
            try:
                cancel=await read(reader);wire.append(cancel['type'])
                if complete:
                    self.assertEqual(cancel['type'],'StageRelease')
                    self.assertEqual(cancel['reason'],'COMPLETE')
                    pending.set();await allow.wait()
                    released=message('StageReleased');released.update(control_id=cancel['control_id'],native_safe_boundary=True,
                        retained_artifact_bytes=0,latest_consumed_sequence=0,pose_history_sha256='sha256:'+'a'*64,terminal_disposition='PROVEN_COMPLETE',reusable=True)
                    await send(writer,released);reply_sent.set();await reader.read();return
                self.assertEqual(cancel['type'],'StageCancel');self.assertEqual(cancel['reason'],'STOP')
                if phase=='cancel':pending.set();await allow.wait()
                fenced=message('StageFenced');fenced.update(control_id=cancel['control_id'],publication_fenced=True,
                    latest_consumed_sequence=0 if armed else -1,pose_history_sha256='sha256:'+'a'*64)
                await send(writer,fenced)
                if phase=='cancel':reply_sent.set()
                release=await read(reader);wire.append(release['type'])
                while release['type']=='StageCancel':
                    self.assertEqual(release,cancel);await send(writer,fenced)
                    release=await read(reader);wire.append(release['type'])
                self.assertEqual(release['control_id'],cancel['control_id'])
                self.assertEqual(release['latest_consumed_sequence'],0 if armed else -1)
                if phase=='release':pending.set();await allow.wait()
                released=message('StageReleased');released.update(control_id=release['control_id'],native_safe_boundary=True,
                    retained_artifact_bytes=0,latest_consumed_sequence=0 if armed else -1,pose_history_sha256='sha256:'+'a'*64,
                    terminal_disposition='UNKNOWN' if armed else 'PROVEN_CANCELLED',reusable=not armed)
                await send(writer,released)
                if phase=="release":reply_sent.set()
                await reader.read()
            except BaseException as exc:errors.append(type(exc).__name__)
            finally:writer.close();await writer.wait_closed();peer_done.set()
        server=await asyncio.start_server(peer,'127.0.0.1',0)
        request=begin();client=StagingClient({},request['session_id'],'workerRef_1',StagingSettings(True,'staging-short-1'))
        client.epoch=request['worker_epoch'];done=asyncio.get_running_loop().create_future();done.set_result(None)
        stage=Stage(copy.deepcopy(request['identity']),request,produced=done);client.active=stage
        if armed:
            stage.commit=commit();stage.pose=pose();stage.descriptor=produced()
        client.reader,client.writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1])
        client.rx=asyncio.create_task(client.receive_loop());callers=[]
        try:
            first=asyncio.create_task(client.release(stage,complete=complete,reason='STOP'));callers.append(first)
            await asyncio.wait_for(pending.wait(),2)
            first.cancel();await asyncio.gather(first,return_exceptions=True)
            # Repeated caller cancellation cannot discard the same physical
            # control exchange, reset its deadline or issue another request.
            second=asyncio.create_task(client.release(stage,complete=armed and not complete,reason='FORCE'));callers.append(second)
            await asyncio.sleep(.01);second.cancel();await asyncio.gather(second,return_exceptions=True)
            allow.set();await asyncio.wait_for(reply_sent.wait(),2)
            await asyncio.sleep(.01)
            self.assertIsNone(client.failed)
            final=asyncio.create_task(client.release(stage,complete=armed and not complete,reason='FORCE'));callers.append(final)
            answer=await asyncio.wait_for(final,2)
            self.assertIsNone(client.failed)
            self.assertEqual(answer['terminal_disposition'],'PROVEN_COMPLETE' if complete else 'UNKNOWN' if armed else 'PROVEN_CANCELLED')
            self.assertEqual(answer['reusable'],complete or not armed)
            self.assertEqual(stage.release_parameters,(complete,'STOP'))
            self.assertTrue(answer['native_safe_boundary']);self.assertTrue(stage.released)
            self.assertEqual(wire,['StageRelease'] if complete else ['StageCancel','StageRelease'])
        finally:
            allow.set()
            for task in callers:
                if not task.done():task.cancel()
            await asyncio.gather(*callers,return_exceptions=True)
            await client.close();server.close();await server.wait_closed();await asyncio.wait_for(peer_done.wait(),2)
        self.assertEqual(errors,[])

    async def test_repeated_cancel_caller_preserves_inflight_fence_ack(self):await self.scenario('cancel')
    async def test_repeated_cancel_caller_preserves_inflight_release_ack(self):await self.scenario('release')

    async def test_cancel_then_complete_caller_does_not_upgrade_unknown(self):await self.scenario('release',armed=True)
    async def test_complete_then_stop_caller_preserves_original_proof_and_fences(self):await self.scenario('release',armed=True,complete=True)

    async def control_failure(self,phase,kind):
        queued=asyncio.Event();late=asyncio.Event();sent=asyncio.Event();done=asyncio.Event();wire=[];errors=[]
        async def peer(reader,writer):
            try:
                packet=await read(reader);wire.append(packet['type'])
                fenced=message('StageFenced');fenced.update(control_id=packet['control_id'],publication_fenced=True,
                    latest_consumed_sequence=-1,pose_history_sha256='sha256:'+'a'*64)
                if phase=='release':
                    await send(writer,fenced);packet=await read(reader);wire.append(packet['type'])
                    answer=message('StageReleased');answer.update(control_id=packet['control_id'],native_safe_boundary=True,
                        retained_artifact_bytes=0,latest_consumed_sequence=-1,pose_history_sha256='sha256:'+'a'*64,
                        terminal_disposition='PROVEN_CANCELLED',reusable=True)
                else:answer=fenced
                queued.set()
                if kind=='missing':await late.wait()
                if kind=='rx_close':return
                if kind=='foreign':answer['worker_epoch']='foreign-epoch';answer['identity']['workerEpoch']='foreign-epoch'
                if kind=='wrong_prefix':answer['latest_consumed_sequence']=0
                await send(writer,answer);sent.set();await reader.read()
            except BaseException as exc:errors.append(type(exc).__name__)
            finally:writer.close();await writer.wait_closed();done.set()
        server=await asyncio.start_server(peer,'127.0.0.1',0);request=begin()
        client=StagingClient({},request['session_id'],'workerRef_1',StagingSettings(True,'staging-short-1'));client.epoch=request['worker_epoch']
        produced_future=asyncio.get_running_loop().create_future();produced_future.set_result(None)
        stage=Stage(copy.deepcopy(request['identity']),request,produced=produced_future);client.active=stage
        client.reader,client.writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1]);client.rx=asyncio.create_task(client.receive_loop())
        first=asyncio.create_task(client.release(stage));callers=[first]
        try:
            await asyncio.wait_for(queued.wait(),2)
            if kind=='missing':
                began=asyncio.get_running_loop().time();original_task=stage.release_task
                first.cancel();await asyncio.gather(first,return_exceptions=True)
                again=asyncio.create_task(client.release(stage,reason='FORCE'));callers.append(again)
                await asyncio.sleep(.01);again.cancel();await asyncio.gather(again,return_exceptions=True)
                self.assertIs(stage.release_task,original_task)
                final=asyncio.create_task(client.release(stage));callers.append(final)
                budget=10 if phase=='cancel' else 15
                with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(final,budget+2)
                elapsed=asyncio.get_running_loop().time()-began
                self.assertGreaterEqual(elapsed,budget-.2);self.assertLess(elapsed,budget+1.5)
                # Exact ACK past the original deadline remains untrusted: no
                # receipt resurrection and no implicit retry/new generation.
                late.set();await asyncio.wait_for(sent.wait(),2)
                for _ in range(100):
                    if client.failed:break
                    await asyncio.sleep(.001)
                self.assertEqual(client.failed.code,'STAGING_CONFLICT')
            else:
                with self.assertRaises(StagingFailure):await asyncio.wait_for(first,2)
            self.assertIsNone(stage.released);self.assertFalse(stage.reusable);self.assertTrue(stage.fenced)
            self.assertEqual(wire,['StageCancel'] if phase=='cancel' else ['StageCancel','StageRelease'])
            with self.assertRaises(StagingFailure):await client.begin({},b'',0,{},None,None,lambda:None)
        finally:
            late.set()
            for task in callers:
                if not task.done():task.cancel()
            await asyncio.gather(*callers,return_exceptions=True)
            await client.close();server.close();await server.wait_closed();await asyncio.wait_for(done.wait(),2)
        self.assertEqual(errors,[])

    async def test_cancel_ack_missing_and_past_deadline_stays_unknown(self):await self.control_failure('cancel','missing')
    async def test_release_ack_missing_and_past_deadline_stays_unknown(self):await self.control_failure('release','missing')
    async def test_foreign_control_ack_never_claims_cleanup(self):await self.control_failure('cancel','foreign')
    async def test_wrong_fence_prefix_never_claims_cleanup(self):await self.control_failure('cancel','wrong_prefix')
    async def test_wrong_release_prefix_never_claims_cleanup(self):await self.control_failure('release','wrong_prefix')
    async def test_receive_failure_never_claims_cleanup(self):await self.control_failure('cancel','rx_close')
