"""Production bound manager/factory/Session + actual TCP lifecycle.

Binding, LLM/TTS/media and Worker GPU provenance are explicit CPU test doubles.
No real provider inference, Chrome, RTMP or durable SQL acceptance is claimed.
"""
import asyncio
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import Settings
from app.events import MemoryEventPublisher
from app.models import CreateSession, SessionConfig
from app.providers import MockLLMProvider, MockTTSProvider, MockAvatarEngine, MockMediaOutput
from app.session_binding import BoundSessionManager
from app.soulx_staging import StagingAvatarEngine, StagingFailure
from app.staging_settings import StagingSettings
from test_session_binding import CREATE, Client, TaggedLLM, packet
from test_staging_tcp import SoftwareWorkerWire


class BoundStagingLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def setup_manager(self, wire=None):
        wire=wire or SoftwareWorkerWire()
        server=await asyncio.start_server(wire.handler,"127.0.0.1",0)
        self.addAsyncCleanup(server.wait_closed);self.addCleanup(server.close)
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        token=Path(directory.name)/"token";token.write_text("software-role-only-token"*2);token.chmod(0o600)
        endpoint={"port":server.sockets[0].getsockname()[1],"assetSHA256":"a"*64,"tokenFile":str(token)}
        data=packet();base=data["binding"]["profiles"][0]
        data["binding"]["profiles"] += [
            {**base,"profileId":"tts","kind":"TTS","provider":"xiaoya","config":{"voiceId":"xiao_ya","speed":1,"modelRef":"xiaoya-default"}},
            {**base,"profileId":"avatar","kind":"AVATAR","provider":"soulx","config":{"avatarRef":"software-avatar","workerProfileId":"gpu"}}]
        client=Client(data);publisher=MemoryEventPublisher()
        staging=StagingSettings(True,"staging-short-1")
        publisher.run_commands={("s","BEGIN_RUN"):{"payload":{"featureFlags":staging.capture()}}}
        manager=BoundSessionManager(Settings(),publisher,MockLLMProvider,MockTTSProvider,MockAvatarEngine,MockMediaOutput,binding_client=client)
        manager.staging_settings=staging
        for context in [patch.dict(os.environ,{"GPU_WORKER_INFERENCE_REGISTRY_FILE":"software-registry-not-read","SESSION_PROVIDER_STATE_DIR":directory.name,"TTS_MODEL_DIR":"software-not-read"}),
            patch("gpu_worker.client.resolve_binding",return_value=endpoint),
            patch("app.session_binding.BoundDeepSeek",lambda config,key,errors,**kwargs:TaggedLLM(key)),
            patch("app.session_binding.BoundXiaoYa",lambda model:MockTTSProvider())]:
            context.start();self.addCleanup(context.stop)
        self.addAsyncCleanup(manager.close)
        request=CreateSession(**(copy.deepcopy(CREATE)|{"sessionId":"s","avatar":{"avatarId":"business-avatar","engine":"SOULX"}}))
        return manager,client,publisher,request,wire

    async def test_real_bound_factory_configure_prepare_start_interrupt_stop(self):
        manager,client,publisher,request,wire=await self.setup_manager()
        await manager.create_session(request)
        session=manager.get_session("s")
        self.assertIsInstance(session.avatar_engine,StagingAvatarEngine)
        avatar=session.avatar_engine
        self.assertIsNot(avatar.config,request.config)
        request.config.fps=30
        self.assertEqual(avatar.config.fps,25)
        for _ in range(100):
            if session.state!="PREPARING":break
            await asyncio.sleep(.01)
        self.assertEqual(session.state,"READY")
        self.assertEqual(manager.provider_status("s")["workerEpoch"],"software-epoch")
        await manager.start_session("s","trace-start")
        self.assertTrue(avatar.running)
        await manager.interrupt("s","trace-interrupt")
        self.assertEqual(avatar.generation_id,session.generation_id)
        await manager.stop_session("s","trace-stop")
        self.assertFalse(avatar.running);self.assertIsNone(avatar.link.writer);self.assertIsNone(avatar.link.rx)
        self.assertFalse(manager.sessions);self.assertFalse(manager.bound)
        self.assertEqual(client.released,["s"])
        self.assertFalse(wire.events)  # No StageBegin/idle/legacy inference.
        self.assertIsNone(wire.error)
        await avatar.stop()  # Physical close is idempotent.

    async def test_unsupported_session_clock_rejected_before_worker_connection(self):
        manager,client,publisher,request,wire=await self.setup_manager()
        request.config.fps=30
        with self.assertRaisesRegex(StagingFailure,"STAGING_UNSUPPORTED"):
            await manager.create_session(request)
        self.assertFalse(manager.sessions);self.assertFalse(manager.bound)
        self.assertIsNone(wire.socket);self.assertEqual(client.released,["s"])

    async def test_actual_wire_simulation_negotiation_rejected_and_binding_cleaned(self):
        manager,client,publisher,request,wire=await self.setup_manager(SoftwareWorkerWire(simulation=True))
        await manager.create_session(request)
        for _ in range(100):
            if client.released:break
            await asyncio.sleep(.01)
        self.assertEqual(client.released,["s"])
        self.assertFalse(manager.sessions);self.assertFalse(manager.bound)
        self.assertIn("SESSION_FAILED",[event["eventType"] for event in publisher.events])
        self.assertFalse(wire.events)

    async def test_start_without_config_and_verified_connection_rejects(self):
        avatar=StagingAvatarEngine({"port":1},"s","w",StagingSettings(True,"staging-short-1"))
        with self.assertRaises(StagingFailure):await avatar.start()
        with self.assertRaises(StagingFailure):await avatar.prepare(None)
        avatar.configure_session(SessionConfig(fps=25,preview={"type":"WEBRTC"}))
        with self.assertRaises(StagingFailure):await avatar.start()
        self.assertFalse(avatar.running)
