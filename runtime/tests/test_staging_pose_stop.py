"""Actual loopback TCP cancellation/cleanup; software peer, not native/GPU."""
import asyncio
import copy
import struct
import time
import unittest
from app.soulx_staging import StagingAvatarEngine,StagingClient,Stage,StagingFailure
from app.staging_settings import StagingSettings
from gpu_worker import staging_contract as c
from gpu_worker.tests.test_staging_contract import begin,commit,pose,produced,message

async def read(reader):
    n,p=struct.unpack('!II',await reader.readexactly(8));header=c.decode_header(await reader.readexactly(n))
    data=await reader.readexactly(p);c.validate_message(header,data);return header
async def send(writer,header):
    c.validate_message(header);data=c.canonical_bytes(header)
    writer.write(struct.pack('!II',len(data),0)+data);await writer.drain()

class PoseStopTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self,kind):
        queued=asyncio.Event();allow=asyncio.Event();closed=asyncio.Event();wire=[];errors=[]
        cm=commit();p=pose();p['pose_proof']['commit_proof_fingerprint']=cm['commit_proof_fingerprint']
        p['pose_proof_fingerprint']=c.pose_fingerprint(p['identity'],p['pose_proof'])
        future=asyncio.get_running_loop().create_future();future.set_result(None)
        stage=Stage(cm['identity'],begin(),produced=future,commit=cm,descriptor=produced(),deadline=time.monotonic()+9)
        async def peer(reader,writer):
            try:
                packet=await read(reader);wire.append(packet['type']);queued.set();await allow.wait()
                ack=message('StagePoseConsumedAck');ack.update(pose_ack_id=packet['pose_proof']['pose_ack_id'],
                    pose_proof_fingerprint=packet['pose_proof_fingerprint'],latest_consumed_sequence=0,pose_history_sha256='sha256:'+'a'*64)
                if kind=='foreign':ack['identity']['stageId']='foreign-stage'
                if kind=='unknown':ack['pose_ack_id']='unsolicited'
                if kind=='wrong_proof':ack['pose_proof_fingerprint']='sha256:'+'b'*64
                await send(writer,ack)
                if kind=='matching':
                    cancel=await read(reader);wire.append(cancel['type']);self.assertEqual(cancel['type'],'StageCancel')
                    fenced=message('StageFenced');fenced.update(control_id=cancel['control_id'],publication_fenced=True,latest_consumed_sequence=0,pose_history_sha256='sha256:'+'a'*64)
                    await send(writer,fenced)
                    release=await read(reader);wire.append(release['type']);self.assertEqual(release['latest_consumed_sequence'],0)
                    self.assertEqual(release['pose_proof_fingerprint'],packet['pose_proof_fingerprint'])
                    reply=message('StageReleased');reply.update(control_id=release['control_id'],native_safe_boundary=True,
                        retained_artifact_bytes=0,latest_consumed_sequence=0,pose_history_sha256='sha256:'+'a'*64,
                        terminal_disposition='UNKNOWN',reusable=False)
                    await send(writer,reply)
                await reader.read()
            except BaseException as exc:errors.append(type(exc).__name__)
            finally:writer.close();await writer.wait_closed();closed.set()
        server=await asyncio.start_server(peer,'127.0.0.1',0)
        client=StagingClient({},cm['session_id'],'workerRef_1',StagingSettings(True,'staging-short-1'));client.epoch=cm['worker_epoch'];client.active=stage
        client.reader,client.writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1])
        client.rx=asyncio.create_task(client.receive_loop())
        avatar=StagingAvatarEngine.__new__(StagingAvatarEngine);avatar.link=client;avatar.running=True;avatar.speaking=True
        pending=asyncio.create_task(client.pose(stage,p['pose_proof'],lambda:None));cleanup=None
        try:
            await asyncio.wait_for(queued.wait(),2)
            # Actual cancellation propagation point: caller awaited a pose ACK.
            pending.cancel();await asyncio.gather(pending,return_exceptions=True)
            cleanup=asyncio.create_task(avatar.interrupt(2));await asyncio.sleep(.02)
            self.assertTrue(stage.fenced);self.assertFalse(cleanup.done())
            self.assertIsNone(stage.pose);self.assertEqual(wire,['StagePoseConsumed'])
            allow.set()
            if kind=='matching':
                await asyncio.wait_for(cleanup,2);await avatar.stop()
                self.assertEqual(wire,['StagePoseConsumed','StageCancel','StageRelease'])
                self.assertEqual(stage.pose['pose_proof']['latest_consumed_sequence'],0)
                self.assertEqual(stage.released['terminal_disposition'],'UNKNOWN');self.assertFalse(stage.reusable)
                self.assertIsNone(client.failed);self.assertFalse(avatar.running)
                self.assertIsNone(client.rx);self.assertIsNone(client.writer)
            else:
                with self.assertRaises(StagingFailure):await asyncio.wait_for(cleanup,2)
                self.assertIsNone(stage.released);self.assertFalse(stage.reusable)
                if kind!='wrong_proof':self.assertEqual(client.failed.code,'STAGING_IDENTITY_MISMATCH' if kind=='foreign' else 'STAGING_CONFLICT')
                self.assertEqual(wire,['StagePoseConsumed'])
        finally:
            allow.set()
            for task in (pending,cleanup):
                if task and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
            await client.close();server.close();await server.wait_closed();await asyncio.wait_for(closed.wait(),2)
        self.assertEqual(errors,[])

    async def test_cancelled_pose_drains_actual_ack_before_interrupt_then_stop(self):await self.scenario('matching')
    async def test_cancelled_pose_foreign_ack_still_fences(self):await self.scenario('foreign')
    async def test_cancelled_pose_unknown_ack_still_fences(self):await self.scenario('unknown')
    async def test_cancelled_pose_wrong_proof_cannot_claim_cleanup(self):await self.scenario('wrong_proof')

    async def test_cancelled_pose_missing_ack_keeps_original_five_second_deadline(self):
        queued=asyncio.Event();done=asyncio.Event();wire=[]
        async def peer(reader,writer):
            try:
                wire.append((await read(reader))['type']);queued.set();await reader.read()
            finally:writer.close();await writer.wait_closed();done.set()
        cm=commit();p=pose();p['pose_proof']['commit_proof_fingerprint']=cm['commit_proof_fingerprint']
        future=asyncio.get_running_loop().create_future();future.set_result(None)
        stage=Stage(cm['identity'],begin(),produced=future,commit=cm,descriptor=produced(),deadline=time.monotonic()+9)
        server=await asyncio.start_server(peer,'127.0.0.1',0)
        client=StagingClient({},cm['session_id'],'workerRef_1',StagingSettings(True,'staging-short-1'));client.epoch=cm['worker_epoch'];client.active=stage
        client.reader,client.writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1]);client.rx=asyncio.create_task(client.receive_loop())
        began=time.monotonic();pending=asyncio.create_task(client.pose(stage,p['pose_proof'],lambda:None))
        try:
            await asyncio.wait_for(queued.wait(),2);pending.cancel();await asyncio.gather(pending,return_exceptions=True)
            with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(client.release(stage),6)
            self.assertGreaterEqual(time.monotonic()-began,4.8);self.assertLess(time.monotonic()-began,6)
            self.assertIsNone(stage.pose);self.assertIsNone(stage.released);self.assertFalse(stage.reusable)
            self.assertTrue(stage.fenced);self.assertEqual(wire,['StagePoseConsumed'])
            self.assertEqual(client.pending,{})
        finally:await client.close();server.close();await server.wait_closed();await asyncio.wait_for(done.wait(),2)
