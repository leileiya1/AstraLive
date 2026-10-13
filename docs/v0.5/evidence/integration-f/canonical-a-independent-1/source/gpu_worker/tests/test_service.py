import asyncio
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from PIL import Image
from gpu_worker.client import WorkerLink
from gpu_worker.config import Config
from gpu_worker.probe import probe
from gpu_worker.validated.wire import send, receive


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        image = self.root / 'avatar.png'
        Image.new('RGB', (512, 512), '#888888').save(image)
        token, management = self.root/'inference-token', self.root/'management-token'
        token.write_text('i'*64)
        management.write_text('m'*64)
        token.chmod(0o600)
        management.chmod(0o600)
        cfg = dict(worker_ref='test-worker', avatar_ref='portrait', asset_path=str(image), asset_sha256=hashlib.sha256(image.read_bytes()).hexdigest(), lab_root=str(self.root), state_dir=str(self.root/'state'), token_file=str(token), manifest_sha256='a'*64, python=sys.executable, management_token_file=str(management), port=free_port(), management_port=free_port(), mode='simulation', minimum_free_disk_bytes=1, startup_timeout_s=30, stop_timeout_s=5, retries=1, retry_initial_s=.1)
        self.path = self.root/'config.json'
        self.path.write_text(json.dumps(cfg))
        self.cfg = Config.load(self.path)
        self.proc = subprocess.Popen([sys.executable, '-m', 'gpu_worker.supervisor', '--config', str(self.path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.endpoint = dict(port=cfg['port'], tokenFile=str(token), avatarRef='portrait', assetSHA256=cfg['asset_sha256'], allowSimulation=True)
        self.links=[]
        await self.wait_ready()

    async def wait_ready(self, old_epoch=None):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if self.proc.poll() is not None:
                self.fail('supervisor exited: '+(self.root/'state/supervisor.log').read_text())
            try:
                result=await asyncio.to_thread(probe,self.cfg)
                if result['ready'] and result['workerEpoch']!=old_epoch:return result
            except Exception:pass
            await asyncio.sleep(.05)
        self.fail('READY timeout')

    async def asyncTearDown(self):
        for link in self.links:await link.close()
        self.proc.terminate()
        try:await asyncio.to_thread(self.proc.wait,10)
        except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
        self.temp.cleanup()

    async def link(self, session='session-a'):
        link=WorkerLink(self.endpoint,session)
        self.links.append(link)
        await link.connect()
        return link

    async def render(self, link, gid, samples=15360, origin=16000):
        await link.begin(gid,origin)
        producer=asyncio.create_task(link.send_audio(gid,0,origin,bytes(samples*2),True))
        packets=[]
        for seq in range((samples*25+15999)//16000):
            p=await asyncio.wait_for(link.receive(gid),5)
            self.assertEqual(p['pts_us'],origin*1000000//16000+seq*40000)
            self.assertEqual(p['generation_id'],gid)
            await link.consumed(p)
            packets.append(p)
        await producer
        await asyncio.wait_for(link.complete(gid),5)
        await link.cancel(gid)
        return packets

    async def test_ready_pcm_force_cache_and_resource_snapshot(self):
        link=await self.link()
        self.assertEqual(link.ready['model_load_count'],1)
        first_cache=link.ready['cache_id']
        packets=await self.render(link,1)
        self.assertEqual(len(packets),24)
        await link.begin(2,31360)
        await link.send_audio(2,0,31360,bytes(30720),False)
        await link.cancel(2)
        await self.render(link,3,640,31360)
        status=await asyncio.to_thread(probe,self.cfg,'/v1/status')
        self.assertEqual(status['avatarCacheStatus']['cacheId'],first_cache)
        self.assertEqual(status['generationCancelStatus']['status'],'PUBLICATION_FENCED')
        self.assertIsNone(status['gpuAllocatedBytes'])
        self.assertGreater(status['trueGeneratedFPS'],0)
        self.assertLessEqual(status['queueDepth']['audioSamples'],32000)
        self.assertLessEqual(status['queueDepth']['videoFrames'],24)

    async def test_auth_epoch_session_and_payload_limits(self):
        def rejected(header,payload=b''):
            with socket.create_connection(('127.0.0.1',self.cfg.port),timeout=2) as s:
                send(s,header,payload)
                with self.assertRaises((EOFError,ConnectionResetError)):receive(s)
        await asyncio.to_thread(rejected,dict(type='Auth',protocol_version=1,internal_version='1.1',session_id='session-a',token='wrong'))
        link=await self.link()
        # Send a forged cross-session control. Server closes only the lease, not service.
        await link._write(dict(type='Health',nonce=1))
        async with link.lock:
            header=dict(type='CancelGeneration',generation_id=1,session_id='session-b',worker_epoch=link.epoch)
            from gpu_worker.validated.wire import MAX_PAYLOAD
            self.assertEqual(MAX_PAYLOAD,2097152)
            import struct
            h=json.dumps(header).encode()
            link.writer.write(struct.pack('!II',len(h),0)+h)
            await link.writer.drain()
        for _ in range(100):
            if link.error:break
            await asyncio.sleep(.01)
        self.assertIsNotNone(link.error)
        self.assertTrue((await self.wait_ready())['ready'])

    async def test_crash_restart_new_epoch_cache_recovery_and_future_jobs(self):
        link=await self.link()
        await self.render(link,1,640)
        old=link.epoch
        state=json.loads((self.root/'state/supervisor.json').read_text())
        os.kill(state['childPid'],signal.SIGKILL)
        status=await self.wait_ready(old)
        self.assertTrue(status['avatarCacheStatus']['metadataRestored'])
        self.assertTrue(status['avatarCacheStatus']['preprocessingRebuilt'])
        for _ in range(100):
            if link.error:break
            await asyncio.sleep(.01)
        self.assertIsNotNone(link.error)
        fresh=await link.reconnect()
        self.links.append(fresh)
        self.assertNotEqual(fresh.epoch,old)
        await self.render(fresh,2,640)

    async def test_business_session_crash_keeps_live_and_lightweight_audio(self):
        from types import SimpleNamespace
        from runtime.app.config import Settings
        from runtime.app.events import MemoryEventPublisher
        from runtime.app.models import CreateSession, Utterance
        from runtime.app.providers import AudioChunk, MockLLMProvider, MockMediaOutput
        from runtime.app.session import SessionManager
        from gpu_worker.runtime_adapter import RemoteAvatarEngine, ConsumptionMediaOutput
        class PCMSource:
            async def synthesize_stream(self,text,voice,ctx):
                for i in range(75):
                    await asyncio.sleep(.005)
                    yield AudioChunk(ctx.generation_id,i,bytes(640),16000,1)
        class FakeConsumptionSink(MockMediaOutput):
            def __init__(self):
                super().__init__()
                self.audio_total=0;self.video_total=0
                self.track=lambda:SimpleNamespace(enqueued=0,consumed=0,generation_id=1,last_recv_monotonic=0)
                self.peer=SimpleNamespace(connection=SimpleNamespace(connectionState='connected'),audio=self.track(),video=self.track())
                self.peers=[self.peer]
            async def push_audio(self,chunk):
                await super().push_audio(chunk)
                self.audio_total+=len(chunk.pcm)//2
                self.peer.audio.enqueued+=1;self.peer.audio.consumed+=1;self.peer.audio.last_recv_monotonic=time.monotonic()
            async def push_video(self,frame):
                await super().push_video(frame)
                self.video_total+=1
                self.peer.video.enqueued+=1;self.peer.video.consumed+=1;self.peer.video.last_recv_monotonic=time.monotonic()
            async def interrupt(self,generation):
                await super().interrupt(generation)
                self.peer.audio.generation_id=self.peer.video.generation_id=generation
        avatar=RemoteAvatarEngine(self.endpoint,'business-session',self.cfg)
        sink=FakeConsumptionSink()
        events=MemoryEventPublisher()
        manager=SessionManager(Settings(),events,MockLLMProvider,PCMSource,lambda:avatar,lambda:ConsumptionMediaOutput(sink,avatar))
        request=CreateSession.model_validate({'commandId':'cmd-create','traceId':'trace','sessionId':'business-session','avatar':{'avatarId':'a','engine':'MOCK'},'voice':{'voiceId':'v','provider':'MOCK'},'config':{'fps':25,'preview':{'type':'WEBRTC'}},'context':{'roomId':'r','systemPrompt':'test'}})
        try:
            await manager.create_session(request)
            session=manager.get_session('business-session')
            for _ in range(100):
                if session.state=='READY':break
                await asyncio.sleep(.02)
            self.assertEqual(session.state,'READY')
            await manager.start_session('business-session','trace')
            # Separate service process crashes; no Runtime/Backend Session control call.
            state=json.loads((self.root/'state/supervisor.json').read_text())
            os.kill(state['childPid'],signal.SIGKILL)
            for _ in range(100):
                if avatar.link.error:break
                await asyncio.sleep(.01)
            item=Utterance.model_validate({'commandId':'cmd-talk','traceId':'trace','utteranceId':'u','text':'hello','priority':40,'interruptPolicy':'NONE','source':'OPERATOR','voice':{'voiceId':'v'}})
            await manager.speak('business-session',item)
            for _ in range(400):
                if any(e['eventType']=='UTTERANCE_COMPLETED' and e.get('utteranceId')=='u' for e in events.events):break
                await asyncio.sleep(.02)
            self.assertEqual(session.state,'LIVE')
            self.assertTrue(any(e['eventType']=='UTTERANCE_COMPLETED' and e.get('utteranceId')=='u' for e in events.events))
            self.assertTrue(any(f.rgb for f in sink.video_frames))
            self.assertTrue(avatar.degraded)
            self.assertGreaterEqual(sink.audio_total,75*320)
            self.assertFalse(any(e['eventType']=='RUNTIME_FAILED' for e in events.events))
            await manager.stop_session('business-session','trace')
            self.assertEqual(session.state,'ENDED')
            self.assertNotIn('business-session',manager.sessions)
        finally:
            await manager.close()

    async def test_withheld_video_credit_keeps_health_responsive_and_force_recovers(self):
        link=await self.link()
        await link.begin(1,0)
        await link.send_audio(1,0,0,bytes(61440),False)
        # Decode four in-flight frames but deliberately withhold all consumption credit.
        for _ in range(4):await asyncio.wait_for(link.receive(1),5)
        await asyncio.sleep(.6)
        status=await asyncio.to_thread(probe,self.cfg,'/v1/status')
        self.assertTrue(status['ready'])
        self.assertLessEqual(status['queueDepth']['videoFrames'],24)
        self.assertLessEqual(status['queueDepth']['audioSamples'],32000)
        self.assertIsNotNone(link.last_health)
        await asyncio.wait_for(link.cancel(1),2)
        await self.render(link,2,640)

    async def test_management_auth_and_graceful_control_stop(self):
        def unauth():
            with self.assertRaises(HTTPError) as error:urlopen(f'http://127.0.0.1:{self.cfg.management_port}/v1/status',timeout=2)
            self.assertEqual(error.exception.code,401)
        await asyncio.to_thread(unauth)
        link=await self.link()
        await link.begin(1,0)
        from gpu_worker.cli import stop
        await asyncio.to_thread(stop,self.cfg)
        await asyncio.to_thread(self.proc.wait,10)
        self.assertEqual(self.proc.returncode,0)
        self.assertFalse((self.root/'state/control.sock').exists())


if __name__=='__main__':unittest.main()
