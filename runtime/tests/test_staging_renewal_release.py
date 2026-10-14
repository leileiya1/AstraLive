"""Real loopback TCP software peer; control-only, no native/GPU acceptance."""
import asyncio
import copy
import struct
import time
import unittest
from types import SimpleNamespace

from app.soulx_staging import Stage, StagingClient, StagingFailure
from app.staging_settings import StagingSettings
from gpu_worker import staging_contract as c
from gpu_worker.tests.test_staging_contract import begin, commit, pose, produced, renewal, message

async def read(reader):
    n,p=struct.unpack('!II',await reader.readexactly(8))
    header=c.decode_header(await reader.readexactly(n));payload=await reader.readexactly(p)
    c.validate_message(header,payload);return header

async def send(writer,header):
    c.validate_message(header);data=c.canonical_bytes(header)
    writer.write(struct.pack('!II',len(data),0)+data);await writer.drain()

class RenewalReleaseTests(unittest.IsolatedAsyncioTestCase):
    def client_stage(self):
        packet=renewal();client=StagingClient({},packet['session_id'],'workerRef_1',StagingSettings(True,'staging-short-1'))
        client.epoch=packet['worker_epoch']
        cm=commit();p=pose();p['pose_proof']['commit_proof_fingerprint']=cm['commit_proof_fingerprint']
        p['pose_proof_fingerprint']=c.pose_fingerprint(p['identity'],p['pose_proof'])
        future=asyncio.get_running_loop().create_future();future.set_result(None)
        stage=Stage(cm['identity'],begin(),produced=future,commit=cm,pose=p,descriptor=produced(),deadline=time.monotonic()+9)
        client.active=stage;return client,stage,packet

    async def loopback(self,kind):
        client,stage,packet=self.client_stage()
        queued=asyncio.Event();allow_ack=asyncio.Event();wire=[];peer_errors=[]
        ack=c.LeaseBudget(begin(),0).renew(packet,100)
        async def peer(reader,writer):
            try:
                wire.append((await read(reader))['type']);queued.set()
                await allow_ack.wait();response=copy.deepcopy(ack)
                if kind=='foreign_identity':response['identity']['stageId']='foreign-stage'
                if kind=='unsolicited_sequence':response['renewal_sequence']=2
                await send(writer,response)
                if kind=='matching':
                    request=await read(reader);wire.append(request['type'])
                    release=message('StageReleased');release.update(control_id=request['control_id'],latest_consumed_sequence=0,
                        terminal_disposition='PROVEN_COMPLETE',reusable=True,native_safe_boundary=True,retained_artifact_bytes=0)
                    await send(writer,release)
                await reader.read()
            except BaseException as exc:peer_errors.append(type(exc).__name__)
            finally:writer.close();await writer.wait_closed()
        server=await asyncio.start_server(peer,'127.0.0.1',0)
        client.reader,client.writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1])
        client.rx=asyncio.create_task(client.receive_loop())
        stage.renew_task=asyncio.create_task(client.exchange(packet,'StageRenewAck'))
        release=None
        try:
            await asyncio.wait_for(queued.wait(),2)
            release=asyncio.create_task(client.release(stage,complete=True))
            await asyncio.sleep(.02)
            self.assertTrue(stage.renew_stop.is_set());self.assertFalse(stage.renew_task.cancelled())
            self.assertFalse(release.done());self.assertEqual(wire,['StageRenew'])
            allow_ack.set()
            if kind=='matching':
                result=await asyncio.wait_for(release,2)
                self.assertTrue(result['reusable']);self.assertIsNone(client.failed)
                self.assertEqual(wire,['StageRenew','StageRelease']);self.assertFalse(stage.renew_task.cancelled())
            else:
                with self.assertRaises(StagingFailure):await asyncio.wait_for(release,2)
                self.assertEqual(client.failed.code,'STAGING_IDENTITY_MISMATCH' if kind=='foreign_identity' else 'STAGING_CONFLICT')
                self.assertTrue(stage.fenced);self.assertIsNone(stage.released)
        finally:
            allow_ack.set()
            if release and not release.done():release.cancel();await asyncio.gather(release,return_exceptions=True)
            await client.close();server.close();await server.wait_closed()
        self.assertEqual(peer_errors,[])

    async def test_pending_renewal_drains_before_release(self):await self.loopback('matching')
    async def test_foreign_identity_still_fences(self):await self.loopback('foreign_identity')
    async def test_unsolicited_sequence_still_fences(self):await self.loopback('unsolicited_sequence')

    async def test_stop_during_real_grant_await_never_sends_renew_after_release(self):
        client,stage,packet=self.client_stage();started=asyncio.Event();finish=asyncio.Event();wire=[]
        async def request(*args):
            started.set();await finish.wait()
            return {'status':'ACTIVE','leaseToken':7,'barrierSeq':0,'remainingMs':9000,'sessionId':client.sid,'runEpoch':1}
        async def exchange(header,response,**kwargs):
            wire.append(header['type'])
            self.assertEqual(header['type'],'StageRelease')
            return {'latest_consumed_sequence':0,'terminal_disposition':'PROVEN_COMPLETE','reusable':True}
        client.exchange=exchange
        stage.renew_task=asyncio.create_task(client.renew(stage,{'runEpoch':1,'commandSeq':1},SimpleNamespace(leaseToken=7),SimpleNamespace(request=request),lambda:None))
        await asyncio.wait_for(started.wait(),2)
        release=asyncio.create_task(client.release(stage,complete=True))
        await asyncio.sleep(.02);self.assertFalse(release.done());self.assertTrue(stage.renew_stop.is_set())
        finish.set();await asyncio.wait_for(release,2)
        self.assertEqual(wire,['StageRelease']);self.assertIsNone(stage.failed);self.assertFalse(stage.renew_task.cancelled())

    async def test_release_stops_sleep_without_new_grant(self):
        client,stage,packet=self.client_stage()
        async def request(*args):self.fail('new grant after stop')
        async def exchange(header,response,**kwargs):return {'latest_consumed_sequence':0,'terminal_disposition':'PROVEN_COMPLETE','reusable':True}
        client.exchange=exchange
        stage.renew_task=asyncio.create_task(client.renew(stage,{'runEpoch':1},None,SimpleNamespace(request=request),lambda:None))
        await asyncio.sleep(0)
        await asyncio.wait_for(client.release(stage,complete=True),.5)
        self.assertFalse(stage.renew_task.cancelled());self.assertIsNone(stage.failed)

    async def test_drained_renewal_ack_does_not_extend_stopped_stage_deadline(self):
        client,stage,packet=self.client_stage();sent=asyncio.Event();reply_allowed=asyncio.Event()
        original_deadline=stage.deadline;wire=[]
        async def fields(*args):return {k:packet[k] for k in ('a_grant','a_rtt_ms','grant_age_ms','worker_rtt_ms','safety_ms','lease_ms')}
        async def exchange(header,response,**kwargs):
            wire.append(header['type'])
            if header['type']=='StageRenew':
                sent.set();await reply_allowed.wait()
                return {'renewal_fingerprint':header['renewal_fingerprint'],'renewal_sequence':header['renewal_sequence'],'lease_remaining_ms':10000}
            return {'latest_consumed_sequence':0,'terminal_disposition':'PROVEN_COMPLETE','reusable':True}
        client.lease_fields=fields;client.exchange=exchange
        stage.renew_task=asyncio.create_task(client.renew(stage,{},None,None,lambda:None))
        await asyncio.wait_for(sent.wait(),2)
        release=asyncio.create_task(client.release(stage,complete=True))
        await asyncio.sleep(.02);reply_allowed.set();await asyncio.wait_for(release,2)
        self.assertEqual(stage.deadline,original_deadline);self.assertEqual(wire,['StageRenew','StageRelease'])

    async def test_missing_renewal_ack_keeps_unknown_and_no_successful_release(self):
        client,stage,packet=self.client_stage();sent=asyncio.Event();wire=[]
        async def fields(*args):return {k:packet[k] for k in ('a_grant','a_rtt_ms','grant_age_ms','worker_rtt_ms','safety_ms','lease_ms')}
        async def exchange(header,response,**kwargs):
            wire.append(header['type']);sent.set();await asyncio.sleep(.03);raise asyncio.TimeoutError()
        client.lease_fields=fields;client.exchange=exchange
        stage.renew_task=asyncio.create_task(client.renew(stage,{},None,None,lambda:None))
        await asyncio.wait_for(sent.wait(),2)
        with self.assertRaises(asyncio.TimeoutError):await client.release(stage,complete=True)
        self.assertTrue(stage.fenced);self.assertIsInstance(stage.failed,asyncio.TimeoutError)
        self.assertIsNone(stage.released);self.assertFalse(stage.reusable);self.assertEqual(wire,['StageRenew'])
