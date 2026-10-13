"""Actual unchanged B StagingConnection TCP/control loop with fake Ready/model.

FAKE READY CONTROL-PLANE ONLY: no GPU/provider/media acceptance. No native
model is loaded; native operations are forbidden. Production C still rejects
real Ready.simulation=True, as existing wire regression verifies.
"""
import asyncio
import collections
import copy
import importlib.util
from pathlib import Path
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from app.soulx_staging import StagingClient, Stage, StagingFailure
from app.staging_settings import StagingSettings
from gpu_worker import staging_contract as c
from gpu_worker.tests.test_staging_contract import begin
from gpu_worker.validated.wire import receive


class IdleAdapter:
    AUDIO_BOUND=32000
    def __init__(self):
        self.cv=threading.Condition();self.pending_samples=0;self.video=collections.deque()
        self.committed=[b"unchanged-software-pose"]*9;self.error=None;self.closed=False;self.native_calls=0
    def close(self):self.closed=True
    def __getattr__(self,name):
        raise AssertionError("native operation forbidden in control-only fixture: "+name)


class ActualBControlSocket:
    def __init__(self,fault=None):
        self.fault=fault;self.adapter=IdleAdapter();self.health=[];self.error=None;self.connection=None
        self.listener=socket.socket();self.listener.bind(("127.0.0.1",0));self.listener.listen(1)
        self.port=self.listener.getsockname()[1]
        cfg=SimpleNamespace(staging_profile="staging-short-1",staging_short_gate_sha256=None,mode="simulation",worker_ref="control-fixture")
        ready=dict(cache_id="software-cache",input_asset_sha256="a"*64,model_revision="software-model",model_load_count=1,av_version="control-only",torch_version="not-loaded",weights_manifest_sha256="b"*64,simulation=False)
        self.worker=SimpleNamespace(cfg=cfg,ready=ready,metrics=SimpleNamespace(epoch="control-epoch"),highest_generation=-1,stop=threading.Event(),staging_unknown=False,active=None,adapter=None,model=SimpleNamespace(adapter=lambda:self.adapter))
        self.thread=threading.Thread(target=self.run,name="actual-B-control-fixture",daemon=True);self.thread.start()
    def run(self):
        from gpu_worker.staging_service import StagingConnection
        try:
            with self.listener.accept()[0] as conn:
                auth,payload=receive(conn);c.validate_message(auth,payload)
                assert auth["token"]=="software-control-role"*2
                self.connection=StagingConnection(self.worker,conn,auth)
                dispatch=self.connection.dispatch
                def observed(header,payload):
                    assert header["type"]=="StageHealth","no native or lease operation admitted"
                    self.health.append((header["nonce"],time.monotonic()))
                    if self.fault=="drop":return
                    if self.fault in {"nonce","epoch"}:
                        response=copy.deepcopy(header);response["type"]="StageHealthAck"
                        response.update(self.connection.counters())
                        response["nonce" if self.fault=="nonce" else "worker_epoch"]="wrong-observation"
                        self.connection.reply(response);return
                    return dispatch(header,payload)
                self.connection.dispatch=observed
                self.connection.run()  # Actual B run retains sock.settimeout(5).
        except Exception as exc:self.error=exc
        finally:self.listener.close()
    async def close(self):
        await asyncio.to_thread(self.thread.join,3)
        if self.thread.is_alive():raise AssertionError("owned B socket threads did not close")


@unittest.skipUnless(importlib.util.find_spec("av") and importlib.util.find_spec("numpy"),"actual B control socket dependencies missing; NOT TESTED")
class HeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def connected(self,fault=None):
        server=ActualBControlSocket(fault)
        self.addAsyncCleanup(server.close)
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        token=Path(directory.name)/"token";token.write_text("software-control-role"*2);token.chmod(0o600)
        client=StagingClient({"port":server.port,"assetSHA256":"a"*64,"tokenFile":str(token)},"control-session","control-fixture",StagingSettings(True,"staging-short-1"))
        self.addAsyncCleanup(client.close)
        await client.connect()
        return client,server

    async def test_actual_B_socket_idle_over_five_seconds_stays_ready_without_jobs(self):
        client,server=await self.connected()
        pose=copy.deepcopy(server.adapter.committed);watermark=server.worker.highest_generation
        await asyncio.sleep(6.2)
        self.assertIsNone(client.failed);self.assertTrue(server.thread.is_alive())
        self.assertGreaterEqual(len(server.health),5)
        self.assertEqual(len({nonce for nonce,_ in server.health}),len(server.health))
        self.assertIsNone(server.connection.stage);self.assertIsNone(client.active)
        self.assertEqual(server.worker.highest_generation,watermark)
        self.assertEqual(server.adapter.committed,pose);self.assertFalse(server.adapter.video)
        self.assertEqual(server.adapter.native_calls,0)
        await client.close();await server.close()
        self.assertIsNone(client.heartbeat);self.assertIsNone(client.rx);self.assertIsNone(client.writer)
        self.assertTrue(server.adapter.closed);self.assertIsNone(server.error)

    async def test_actual_B_idle_timeout_reproduced_without_control_heartbeat(self):
        client,server=await self.connected()
        client.heartbeat.cancel();await asyncio.gather(client.heartbeat,return_exceptions=True);client.heartbeat=None
        fences=[];client.on_failure=fences.append
        await asyncio.sleep(5.4)
        self.assertIsNotNone(client.failed)
        self.assertEqual(fences,["STAGING_CONNECTION_UNKNOWN"])
        self.assertFalse(server.health);self.assertIsNone(server.connection.stage)
        self.assertEqual(server.adapter.native_calls,0)

    async def test_health_wrong_nonce_epoch_and_missing_ack_immediately_fence(self):
        for fault in ("nonce","epoch","drop"):
            with self.subTest(fault=fault):
                client,server=await self.connected(fault)
                fences=[];client.on_failure=lambda reason:fences.append((reason,time.monotonic()))
                deadline=time.monotonic()+4
                while client.failed is None and time.monotonic()<deadline:await asyncio.sleep(.02)
                self.assertIsNotNone(client.failed)
                self.assertEqual(fences[0][0],"STAGING_CONNECTION_UNKNOWN")
                self.assertLess(fences[0][1]-server.health[0][1],2.5)
                self.assertIsNone(client.active);self.assertIsNone(server.connection.stage)
                self.assertEqual(server.adapter.native_calls,0)
                await client.close();await server.close();self.assertIsNone(server.error)

    def test_actual_B_health_counters_do_not_extend_expired_or_fenced_stage_lease(self):
        from gpu_worker.staging_service import StagingConnection
        for state in ("STAGING","FENCED","UNKNOWN"):
            worker=SimpleNamespace(cfg=SimpleNamespace(staging_profile="staging-short-1",staging_short_gate_sha256=None,mode="simulation"),metrics=SimpleNamespace(epoch="control-epoch"))
            connection=StagingConnection(worker,None,{"session_id":"control-session","requested_limits_revision":"staging-short-1"})
            connection.adapter=IdleAdapter();lease=c.LeaseBudget(begin(),0);lease.fence()
            connection.stage={"state":state,"lease":lease,"frames":{},"received":-1};snapshot=copy.deepcopy(vars(lease))
            replies=[];connection.reply=lambda response:replies.append(response)
            connection.dispatch({"type":"StageHealth","contract_revision":c.REVISION,"session_id":"control-session","worker_epoch":"control-epoch","nonce":"observed"},b"")
            self.assertEqual(vars(lease),snapshot);self.assertEqual(connection.stage["state"],state)
            self.assertEqual(replies[0]["type"],"StageHealthAck")
            self.assertEqual(connection.adapter.native_calls,0)

    async def test_connection_failure_fences_active_publication_and_pending_waiters_once(self):
        client=StagingClient({},"s","w",StagingSettings(True,"staging-short-1"))
        produced=asyncio.get_running_loop().create_future();pending=asyncio.get_running_loop().create_future()
        stage=Stage({}, {}, produced=produced,deadline=time.monotonic()+5)
        client.active=stage;client.pending[("StageCommitAck",None)]=pending
        deadline=stage.deadline;fences=[];client.on_failure=fences.append
        client.fail_connection(TimeoutError())
        client.fail_connection(ConnectionError())
        self.assertEqual(fences,["STAGING_CONNECTION_UNKNOWN"])
        self.assertTrue(stage.fenced);self.assertIs(stage.failed,client.failed)
        self.assertEqual(stage.deadline,deadline);self.assertIsNone(stage.pose);self.assertFalse(stage.reusable)
        for future in (produced,pending):
            with self.assertRaises(StagingFailure):await future
