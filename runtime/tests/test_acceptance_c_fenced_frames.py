"""Actual loopback bounded frame/control ordering; software peer/provenance only,
not decoded native video, real Worker authentication, GPU or sink acceptance.
"""
import asyncio
import copy
import struct
import unittest
from app.soulx_staging import StagingClient,Stage,StagingFailure
from app.staging_settings import StagingSettings
from gpu_worker import staging_contract as c
from gpu_worker.tests.test_staging_contract import begin,produced,message
from test_staging_pose_stop import read,send

async def send_frame(writer,header,payload):
    c.validate_message(header,payload);raw=c.canonical_bytes(header)
    writer.write(struct.pack('!II',len(raw),len(payload))+raw+payload);await writer.drain()

def setup_stage():
    request=begin();end=produced();d=end['descriptor']
    for key in ('pcm_sha256','source_format','request_fingerprint'):d[key]=copy.deepcopy(request[key])
    data=b'opaque-cpu-h264-packet'
    frame=message('StageVideo');frame.update(frame_sequence=0,pts_us=0,sample_start=0,sample_end=640,
        payload_sha256=c.bytes_digest(data),native_rgb_sha256='sha256:'+'a'*64,provenance=copy.deepcopy(d['provenance']))
    d.update(video_bytes=len(data),video_stream_sha256=c.bytes_digest(struct.pack('!Q',len(data))+data))
    end['descriptor_sha256']=c.descriptor_hash(d)
    client=StagingClient({},request['session_id'],request['identity']['workerRef'],StagingSettings(True,'staging-short-1'))
    client.epoch=request['worker_epoch']
    client.ready={'selected_limits':copy.deepcopy(d['limits']),**{k:d['provenance'][k] for k in ('weights_manifest_sha256','input_asset_sha256','cache_id')},'model_revision':d['provenance']['model_source_revision']}
    stage=Stage(copy.deepcopy(request['identity']),request,produced=asyncio.get_running_loop().create_future());client.active=stage
    return client,stage,frame,data,end

class FencedFrameTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_fence_before_cancel_stores_before_ack_but_never_ready(self):
        client,stage,frame,data,end=setup_stage();renew_done=asyncio.Event();stored=asyncio.Event();closed=asyncio.Event();wire=[];errors=[]
        # Controlled captured renewal still finishing: Stop publication fence is
        # immediate, while StageCancel has not yet reached its write boundary.
        stage.renew_task=asyncio.create_task(renew_done.wait())
        def failed(reason):stored.set();renew_done.set()
        client.on_failure=failed
        async def peer(reader,writer):
            try:
                while not stage.fenced:await asyncio.sleep(.001)
                await send_frame(writer,frame,data)
                ack=await read(reader);wire.append(ack['type'])
                self.assertEqual(ack['type'],'StageReceived')
                self.assertEqual(stage.frames[0][1],data) # immutable bytes before actual ACK
                self.assertEqual(ack['payload_sha256'],c.bytes_digest(data))
                await send(writer,{**ack,'type':'StageReceivedAck'})
                await send(writer,end)
                while stage.descriptor is None and client.failed is None:await asyncio.sleep(.001)
                self.assertFalse(stage.produced.done());self.assertIsNone(stage.commit);self.assertIsNone(stage.pose)
                stored.set();renew_done.set()
                cancel=await read(reader);wire.append(cancel['type'])
                fenced=message('StageFenced');fenced.update(control_id=cancel['control_id'],latest_consumed_sequence=-1)
                await send(writer,fenced)
                release=await read(reader);wire.append(release['type'])
                answer=message('StageReleased');answer.update(control_id=release['control_id'],latest_consumed_sequence=-1,
                    native_safe_boundary=True,retained_artifact_bytes=0,terminal_disposition='PROVEN_CANCELLED',reusable=True)
                await send(writer,answer);await reader.read()
            except BaseException as exc:errors.append(type(exc).__name__);stored.set();renew_done.set()
            finally:writer.close();await writer.wait_closed();closed.set()
        server=await asyncio.start_server(peer,'127.0.0.1',0)
        client.reader,client.writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1]);client.rx=asyncio.create_task(client.receive_loop())
        cleanup=asyncio.create_task(client.release(stage))
        try:
            await asyncio.wait_for(stored.wait(),2)
            answer=await asyncio.wait_for(cleanup,2)
            self.assertEqual(answer['terminal_disposition'],'PROVEN_CANCELLED');self.assertIsNone(client.failed)
            self.assertEqual(wire,['StageReceived','StageCancel','StageRelease'])
            self.assertFalse(stage.produced.done());self.assertIsNone(stage.commit);self.assertIsNone(stage.pose)
        finally:
            renew_done.set()
            if not cleanup.done():cleanup.cancel()
            await asyncio.gather(cleanup,return_exceptions=True);await client.close();server.close();await server.wait_closed();await asyncio.wait_for(closed.wait(),2)
        self.assertEqual(errors,[])

    async def drain_scenario(self,kind):
        client,stage,frame,data,_=setup_stage();closed=asyncio.Event();wire=[];errors=[]
        cleanup=None
        crossing=kind=='write_lock_crossing'
        failure=kind in ('after_fenced','gap','foreign','bad_hash','provenance','budget')
        if crossing:await client.write_lock.acquire()
        if kind=='budget':client.ready['selected_limits']['runtime_artifact_bytes']=len(data)-1
        async def peer(reader,writer):
            try:
                if crossing:
                    while not stage.fenced:await asyncio.sleep(0)
                    # Cancel was queued first on the held writer lock. RX then
                    # stores actual immutable bytes but waits behind Cancel.
                    await send_frame(writer,frame,data)
                    while not stage.frames:await asyncio.sleep(0)
                    self.assertEqual(stage.frames[0][1],data)
                    client.write_lock.release()
                cancel=await read(reader);wire.append(cancel['type']);self.assertEqual(cancel['type'],'StageCancel')
                self.assertTrue(stage.cancel_written)
                if not crossing:
                    outgoing=copy.deepcopy(frame)
                    if kind=='gap':outgoing.update(frame_sequence=1,pts_us=40000,sample_start=640,sample_end=1280)
                    if kind=='foreign':outgoing['identity']['stageId']='another-stage'
                    if kind=='provenance':outgoing['provenance']['cache_id']='sha256:'+'b'*64
                    if kind=='bad_hash':
                        # Intentionally malformed payload: bypass test sender's
                        # own validator to exercise actual production _read.
                        raw=c.canonical_bytes(outgoing);writer.write(struct.pack('!II',len(raw),len(data))+raw+b'X'*len(data));await writer.drain()
                    elif kind!='after_fenced':
                        await send_frame(writer,outgoing,data)
                        if not failure:await send_frame(writer,outgoing,data) # exact duplicate: no credit
                if failure and kind!='after_fenced':
                    await reader.read();return
                if not crossing and kind!='after_fenced':
                    while not stage.drain_headers and client.failed is None:await asyncio.sleep(0)
                    self.assertEqual(stage.frames,[]);self.assertEqual(len(stage.drain_headers),1)
                    self.assertEqual(stage.encoded_bytes,len(data));self.assertFalse(stage.produced.done())
                fenced=message('StageFenced');fenced.update(control_id=cancel['control_id'],latest_consumed_sequence=-1)
                if kind=='after_fenced':
                    # Same batch: RX must mark the matched Fenced before the
                    # cleanup waiter gets scheduled, then reject the next frame.
                    a=c.canonical_bytes(fenced);b=c.canonical_bytes(frame)
                    writer.write(struct.pack('!II',len(a),0)+a+struct.pack('!II',len(b),len(data))+b+data);await writer.drain()
                    await reader.read();return
                await send(writer,fenced)
                release=await read(reader);wire.append(release['type']);self.assertEqual(release['type'],'StageRelease')
                answer=message('StageReleased');answer.update(control_id=release['control_id'],latest_consumed_sequence=-1,
                    native_safe_boundary=True,retained_artifact_bytes=0,terminal_disposition='PROVEN_CANCELLED',reusable=True)
                await send(writer,answer);await reader.read()
            except BaseException as exc:errors.append(type(exc).__name__)
            finally:writer.close();await writer.wait_closed();closed.set()
        server=await asyncio.start_server(peer,'127.0.0.1',0)
        client.reader,client.writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1]);client.rx=asyncio.create_task(client.receive_loop())
        cleanup=asyncio.create_task(client.release(stage))
        try:
            if failure:
                with self.assertRaises(StagingFailure):await asyncio.wait_for(cleanup,2)
                self.assertIsNotNone(client.failed);self.assertIsNone(stage.released);self.assertFalse(stage.reusable)
                self.assertTrue(stage.produced.done())
                self.assertIsInstance(stage.produced.exception(),StagingFailure) # rejected, never READY
                self.assertIsNone(stage.commit);self.assertIsNone(stage.pose)
            else:
                reply=await asyncio.wait_for(cleanup,2);self.assertEqual(reply['terminal_disposition'],'PROVEN_CANCELLED')
                self.assertIsNone(client.failed);self.assertTrue(stage.worker_fenced)
                self.assertEqual(wire,['StageCancel','StageRelease']) # no post-Cancel credit
                self.assertFalse(stage.produced.done());self.assertIsNone(stage.commit);self.assertIsNone(stage.pose)
        finally:
            if crossing and client.write_lock.locked():client.write_lock.release()
            if not cleanup.done():cleanup.cancel()
            await asyncio.gather(cleanup,return_exceptions=True);await client.close();server.close();await server.wait_closed();await asyncio.wait_for(closed.wait(),2)
        self.assertEqual(errors,[])

    async def test_after_cancel_valid_frame_and_duplicate_drain_without_credit(self):await self.drain_scenario('drain')
    async def test_cancel_write_lock_precedes_waiting_storage_ack(self):await self.drain_scenario('write_lock_crossing')
    async def test_worker_fenced_marks_inside_rx_before_next_buffered_frame(self):await self.drain_scenario('after_fenced')
    async def test_cancel_drain_rejects_gap(self):await self.drain_scenario('gap')
    async def test_cancel_drain_rejects_foreign_identity(self):await self.drain_scenario('foreign')
    async def test_cancel_drain_rejects_payload_hash_mismatch(self):await self.drain_scenario('bad_hash')
    async def test_cancel_drain_rejects_provenance_mismatch(self):await self.drain_scenario('provenance')
    async def test_cancel_drain_preserves_encoded_artifact_budget(self):await self.drain_scenario('budget')
