"""Mock-only integration/lifecycle tests; never real GPU/DeepSeek evidence."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
from app.config import Settings
from app.events import MemoryEventPublisher
from app.models import CreateSession
from app.providers import MockLLMProvider, MockTTSProvider, MockAvatarEngine, MockMediaOutput, LLMRequest, AudioChunk
from app.session import RuntimeFailure
from app.session_binding import BindingClient, BoundSessionManager, BoundDeepSeek, FixedDeepSeekTransport

CREATE={"commandId":"cmd_1","traceId":"trace_1","sessionId":"session_1","avatar":{"avatarId":"avatar_1","engine":"MOCK"},"voice":{"voiceId":"voice_1","provider":"MOCK"},"config":{"fps":25,"preview":{"type":"WEBRTC"}},"context":{"roomId":"room_1","systemPrompt":"fixed"}}

def packet(ttl=3600):
    now=datetime.now(timezone.utc)
    profile={"profileId":"llm","kind":"LLM","provider":"deepseek","version":1,"updatedAt":now.isoformat(),"enabled":True,"isDefault":True,"verification":"VERIFIED","config":{"model":"deepseek-flash","maxTokens":128}}
    worker={**profile,"profileId":"gpu","kind":"GPU_WORKER","provider":"soulx","config":{"workerRef":"physical-1"}}
    return {"integrationVersion":"0.4.0","scope":{"tenantId":"tenant","userId":"user"},"capturedAt":now.isoformat(),"credentials":{"llm":"old-synthetic-secret"},"binding":{"bindingId":"binding-1","contractVersion":"0.3.0","expiresAt":(now+timedelta(seconds=ttl)).isoformat(),"profiles":[profile,worker],"settings":{"policy":{"maxQueue":7,"failurePolicy":"STOP"}}}}

class Client:
    def __init__(self,data=None):self.data=data or packet();self.released=[];self.fail_release=False
    async def resolve(self,sid):return copy.deepcopy(self.data)
    async def release(self,sid):
        if self.fail_release:raise RuntimeError('service down')
        self.released.append(sid)

class TaggedLLM(MockLLMProvider):
    def __init__(self,key):self.api_key=key

class BindingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client=Client();self.publisher=MemoryEventPublisher()
        def builder(data,*args):
            key=data['credentials']['llm']
            return lambda:TaggedLLM(key),MockTTSProvider,MockAvatarEngine,MockMediaOutput
        self.manager=BoundSessionManager(Settings(),self.publisher,MockLLMProvider,MockTTSProvider,MockAvatarEngine,MockMediaOutput,binding_client=self.client,bundle_builder=builder)
    async def asyncTearDown(self):await self.manager.close()
    async def create(self):
        await self.manager.create_session(CreateSession(**CREATE))
        for _ in range(20):
            if self.manager.get_session('session_1').state=='READY':return
            await asyncio.sleep(.01)
    async def test_snapshot_key_is_used_without_global_key_or_hot_change(self):
        with patch.dict(os.environ,{'LLM_API_KEY':'forbidden-global-key'}):await self.create()
        session=self.manager.get_session('session_1');self.assertEqual(session.llm.api_key,'old-synthetic-secret');self.assertEqual(session.max_queue,7)
        self.client.data['credentials']['llm']='new-synthetic-secret';self.client.data['binding']['profiles'][0]['version']=2
        self.assertEqual(session.llm.api_key,'old-synthetic-secret')
        self.assertEqual(self.manager.provider_status('session_1')['profiles'][0]['version'],1)
        self.assertNotIn('synthetic-secret',json.dumps(self.manager.provider_status('session_1')))
        self.assertEqual(self.manager.provider_status('session_1')['mode'],'UNAVAILABLE') # Mock must not claim REAL.
        await self.manager.stop_session('session_1','trace_1');self.assertEqual(session.llm.api_key,'');self.assertEqual(self.client.released,['session_1'])
        self.assertFalse(self.manager.bound);self.assertFalse(self.manager.leases);self.assertFalse(self.manager.monitors)
    async def test_expired_lease_rejected_and_released(self):
        self.client.data=packet(20)
        with self.assertRaisesRegex(RuntimeFailure,'lease'):await self.create()
        self.assertEqual(self.client.released,['session_1']);self.assertFalse(self.manager.sessions)
    async def test_lease_watchdog_stops_ready_session_before_expiry(self):
        await self.create();await self.manager._lease('session_1',0)
        self.assertFalse(self.manager.sessions);self.assertEqual(self.client.released,['session_1'])
        self.assertIn('SESSION_FAILED',[e['eventType'] for e in self.publisher.events])
    async def test_one_physical_worker_cannot_be_double_assigned(self):
        await self.create();second={**CREATE,'sessionId':'session_2'}
        with self.assertRaisesRegex(RuntimeFailure,'already assigned'):await self.manager.create_session(CreateSession(**second))
        self.assertIn('session_1',self.manager.sessions);self.assertNotIn('session_2',self.manager.sessions)
    async def test_no_bundle_fallback_when_builder_fails(self):
        def fail(*args):raise RuntimeFailure('WORKER_NOT_READY','worker unavailable',503)
        self.manager.bundle_builder=fail
        with self.assertRaises(RuntimeFailure):await self.create()
        self.assertFalse(self.manager.sessions);self.assertEqual(self.client.released,['session_1'])
    async def test_prepare_failure_cleans_provider_and_binding(self):
        class FailedAvatar(MockAvatarEngine):
            async def prepare(self,config):raise RuntimeFailure('WORKER_NOT_READY','worker unavailable',503)
        self.manager.bundle_builder=lambda *args:(MockLLMProvider,MockTTSProvider,FailedAvatar,MockMediaOutput)
        await self.manager.create_session(CreateSession(**CREATE))
        for _ in range(30):
            if not self.manager.sessions:break
            await asyncio.sleep(.01)
        self.assertFalse(self.manager.sessions);self.assertFalse(self.manager.bound);self.assertEqual(self.client.released,['session_1'])
        self.assertEqual(next(e for e in self.publisher.events if e['eventType']=='SESSION_FAILED')['payload']['code'],'WORKER_NOT_READY')
    async def test_release_is_retryable_when_backend_down(self):
        await self.create();self.client.fail_release=True;await self.manager.stop_session('session_1','trace_1')
        self.assertIn('session_1',self.manager.release_pending);self.client.fail_release=False;await self.manager._release('session_1');self.assertFalse(self.manager.release_pending)
    async def test_commands_reject_lease_boundary(self):
        await self.create();self.manager.bound['session_1']['deadline']=asyncio.get_running_loop().time()+30
        with self.assertRaises(RuntimeFailure):await self.manager.start_session('session_1','trace_1')
    async def test_bound_auth_failure_stops_and_releases_without_mock_fallback(self):
        await self.create();await self.manager.start_session('session_1','trace_1')
        self.manager.bound['session_1']['errors']['errorCode']='PROVIDER_AUTH_FAILED'
        for _ in range(120):
            if self.client.released:break
            await asyncio.sleep(.01)
        self.assertFalse(self.manager.sessions)
        self.assertEqual(self.client.released,['session_1'])
        self.assertEqual(next(e for e in self.publisher.events if e['eventType']=='SESSION_FAILED')['payload']['code'],'PROVIDER_AUTH_FAILED')
    async def test_duplicate_does_not_release_current_binding(self):
        await self.create()
        with self.assertRaises(RuntimeFailure):await self.manager.create_session(CreateSession(**CREATE))
        self.assertFalse(self.client.released)
    async def test_worker_degradation_and_recovery_emit_lifecycle_without_hot_switch(self):
        await self.create()
        session=self.manager.get_session('session_1')
        session.avatar_engine.link=type('Link',(),{'ready':{'simulation':False},'epoch':'epoch-test'})()
        await self.manager.start_session('session_1','trace_1')
        session.avatar_engine.degraded=True
        for _ in range(120):
            if any(e['eventType']=='SESSION_DEGRADED' for e in self.publisher.events):break
            await asyncio.sleep(.01)
        self.assertEqual(self.manager.provider_status('session_1')['mode'],'DEGRADED')
        self.assertEqual(session.state,'LIVE')
        session.avatar_engine.degraded=False
        for _ in range(120):
            recovered=[e for e in self.publisher.events if e['eventType']=='SESSION_STARTED' and e.get('payload',{}).get('code')=='WORKER_RECOVERED']
            if recovered:break
            await asyncio.sleep(.01)
        self.assertTrue(recovered)
        self.assertEqual(session.llm.api_key,'old-synthetic-secret')
        self.assertFalse(self.client.released)

class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_service_request_and_no_user_supplied_scope(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'token';p.write_text('w'*40);p.chmod(0o600)
            seen=[]
            async def handler(request):
                seen.append(request)
                return httpx.Response(200,json={'code':'OK','data':packet()})
            client=BindingClient('http://127.0.0.1:1234',str(p),httpx.MockTransport(handler));await client.resolve('session_1')
            self.assertEqual(seen[0].headers['Authorization'],'Bearer '+'w'*40);self.assertEqual(seen[0].content,b'')
    async def test_upstream_auth_failure_is_static_and_visible(self):
        async def handler(request):return httpx.Response(401,json={'error':'echoed-synthetic-secret'})
        errors={};llm=BoundDeepSeek({'model':'deepseek-flash','maxTokens':32},'synthetic-secret',errors)
        transport=lambda *args:FixedDeepSeekTransport(transport=httpx.MockTransport(handler))
        with patch('app.session_binding.FixedDeepSeekTransport',transport):
            with self.assertRaises(RuntimeFailure) as raised:
                async for _ in llm.stream(LLMRequest('hello','system','facts')):pass
        self.assertEqual(errors['errorCode'],'PROVIDER_AUTH_FAILED');self.assertNotIn('synthetic-secret',str(raised.exception))

class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_tts_probe_validates_real_result_and_rejects_empty_output(self):
        from app.main import create_app
        class FakeTTS:
            empty=False
            def __init__(self,*args):pass
            async def synthesize_stream(self,text,voice,ctx):
                if not self.empty:yield AudioChunk(ctx.generation_id,0,b'\x01\x00'*4000,22050)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name,char in [('control','c'),('binding','b')]:
                (root/name).write_text(char*40);(root/name).chmod(0o600)
            env={'SESSION_BINDINGS_ENABLED':'true','CONFIG_BACKEND_URL':'http://127.0.0.1:1234','RUNTIME_CONTROL_TOKEN_FILE':str(root/'control'),'CONFIG_WORKER_TOKEN_FILE':str(root/'binding'),'TTS_MODEL_DIR':'synthetic-model-path'}
            with patch.dict(os.environ,env),patch('app.main.BoundXiaoYa',FakeTTS):
                app=create_app(Settings(),MemoryEventPublisher())
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://runtime') as client:
                    body={'voiceId':'xiao_ya','speed':1,'modelRef':'xiaoya-default'};path='/internal/v0.4/provider-probes/tts'
                    self.assertEqual((await client.post(path,json=body)).status_code,401)
                    headers={'Authorization':'Bearer '+'c'*40}
                    result=await client.post(path,json=body,headers=headers);self.assertEqual(result.status_code,200);self.assertEqual(result.json()['samples'],4000)
                    self.assertEqual((await client.post(path,json={**body,'speed':1.5},headers=headers)).status_code,422)
                    FakeTTS.empty=True;self.assertEqual((await client.post(path,json=body,headers=headers)).status_code,502)
                await app.state.manager.close()
