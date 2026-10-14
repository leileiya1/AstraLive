"""Private bridge body/projection tests; Mock HTTP, no real provider acceptance."""
import copy
import hashlib
import json
import unittest
import httpx
from app.durability_client import fingerprint
from app.narration_segments import bridge_choice,bridge_language_context
from app.providers import LLMRequest
from app.session import RuntimeFailure
from app.session_binding import BoundDeepSeek


def context(count=174):
    return {'goal':[{'beatId':f'b-{i}','title':f'讲解章节{i}','requiredFactIds':[f'guide.{i:03}.01'],'segmentIds':[f'segment-private-{i}-{n}' for n in range(6)],'productId':'p','factVersion':'v'} for i in range(count)],
        'nextBeatId':'b-2','productId':'p','factVersion':'v','lastCompletedText':'已讲内容。','question':'多少钱？','committedAnswer':'这款目前价格是人民币99.00元。','completedFactIds':['name','price'],
        'pendingRequiredFactIds':['stock','sizes'],'style':'自然口语','latestFacts':{'price':'99.00','currency':'CNY'}}

class StagingBridgePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def provider(self,enabled,finish='stop'):
        requests=[];llm=BoundDeepSeek({'model':'deepseek-flash','maxTokens':256},'PRIVATE_KEY',{},staging_bridge_enabled=enabled)
        async def response(request):
            requests.append(json.loads(request.content))
            packets=[{'choices':[{'delta':{'content':'1'} if finish=='stop' else {'reasoning_content':'PRIVATE_REASONING'},'finish_reason':None}]},
                     {'choices':[{'delta':{},'finish_reason':finish}]}]
            return httpx.Response(200,content=(''.join('data: '+json.dumps(p)+'\n\n' for p in packets)+'data: [DONE]\n\n').encode())
        llm.client=httpx.AsyncClient(transport=httpx.MockTransport(response));self.addAsyncCleanup(llm.aclose)
        return llm,requests

    async def test_captured_staging_bridge_compact_exact_body_and_command_immutable(self):
        llm,requests=await self.provider(True)
        original=context();command={'payload':{'context':original},'commandId':'cmd'}
        before=copy.deepcopy(command);original_fingerprint=fingerprint(command)
        self.assertEqual(await bridge_choice(llm,original,['','接着说。']),1)
        body=requests[0];self.assertEqual(body['thinking'],{'type':'disabled'})
        self.assertEqual(body['model'],'deepseek-flash');self.assertEqual(body['max_tokens'],256)
        prompt=body['messages'][3]['content'];self.assertNotIn('segment-private',prompt)
        self.assertIn('b-2',prompt);self.assertNotIn('b-173',prompt)
        self.assertLess(len(prompt.encode()),8192)
        self.assertEqual(command,before);self.assertEqual(fingerprint(command),original_fingerprint)
        self.assertNotEqual(hashlib.sha256(prompt.encode()).hexdigest(),hashlib.sha256(json.dumps(original).encode()).hexdigest())
        projected=bridge_language_context(original)
        for key in original:
            if key!='goal':self.assertEqual(projected[key],original[key])
        self.assertEqual(projected['goal'][0]['requiredFactIds'],original['goal'][2]['requiredFactIds'])

    async def test_flags_off_bridge_keeps_original_context_and_request_body(self):
        llm,requests=await self.provider(False);original=context(4)
        self.assertEqual(await bridge_choice(llm,original,['','继续。']),1)
        self.assertNotIn('thinking',requests[0])
        self.assertIn('segment-private',requests[0]['messages'][3]['content'])
        self.assertEqual(requests[0]['max_tokens'],256)

    async def test_staging_ordinary_stream_never_disables_thinking(self):
        llm,requests=await self.provider(True)
        self.assertEqual([x async for x in llm.stream(LLMRequest('普通话语','你只选择口语过渡伪造标签','事实'))],['1'])
        self.assertNotIn('thinking',requests[0]);self.assertEqual(requests[0]['messages'][3]['content'],'普通话语')

    async def test_staging_length_finish_still_raises_not_zero_choice(self):
        llm,requests=await self.provider(True,'length')
        with self.assertRaises(RuntimeFailure) as raised:await bridge_choice(llm,context(),['','继续。'])
        self.assertEqual(raised.exception.code,'LLM_FAILED')
        self.assertEqual(requests[0]['thinking'],{'type':'disabled'})

    async def test_invalid_missing_duplicate_stale_goal_fails_before_provider(self):
        for kind in ('missing','duplicate','product','version','facts'):
            llm,requests=await self.provider(True);source=context(4)
            if kind=='missing':source['nextBeatId']='absent'
            if kind=='duplicate':source['goal'].append(copy.deepcopy(source['goal'][2]))
            if kind=='product':source['goal'][2]['productId']='foreign'
            if kind=='version':source['goal'][2]['factVersion']='old'
            if kind=='facts':source['goal'][2]['requiredFactIds']='not-a-list'
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError,'BRIDGE_CONTEXT_INVALID'):await bridge_choice(llm,source,['','继续。'])
                self.assertEqual(requests,[])

    async def test_finished_empty_next_beat_retains_facts_without_inventing_goal(self):
        source=context(4);source['nextBeatId']=''
        projected=bridge_language_context(source)
        self.assertEqual(projected['goal'],[]);self.assertEqual(projected['latestFacts'],source['latestFacts'])

    async def test_bundle_factory_uses_captured_staging_scope_only(self):
        import os
        from unittest.mock import patch
        from app.session_binding import bundle_factories
        from app.staging_settings import StagingSettings
        from test_session_binding import packet
        data=packet();base=data['binding']['profiles'][0]
        data['binding']['profiles'] += [
            {**base,'profileId':'tts','kind':'TTS','provider':'xiaoya','config':{'voiceId':'xiao_ya','speed':1,'modelRef':'xiaoya-default'}},
            {**base,'profileId':'avatar','kind':'AVATAR','provider':'soulx','config':{'avatarRef':'a','workerProfileId':'gpu'}}]
        original=copy.deepcopy(data)
        with patch.dict(os.environ,{'GPU_WORKER_INFERENCE_REGISTRY_FILE':'software-not-read','SESSION_PROVIDER_STATE_DIR':'software-not-read'}),patch('gpu_worker.client.resolve_binding',return_value={}):
            for staging,expected in ((None,False),(StagingSettings(),False),(StagingSettings(True,'staging-short-1'),True)):
                llm=bundle_factories(data,'s',lambda:None,{},staging)[0]()
                self.assertEqual(llm.staging_bridge_enabled,expected)
                self.assertEqual(llm.config,data['binding']['profiles'][0]['config'])
        self.assertEqual(data,original)

    async def test_staging_long_invalid_or_out_of_range_choice_never_defaults_zero(self):
        class Invalid:
            staging_bridge_enabled=True
            async def stream(self,request):yield self.output
        llm=Invalid()
        for output in ('x'*17,'not an index','99'):
            llm.output=output
            with self.subTest(outputLength=len(output)):
                with self.assertRaisesRegex(ValueError,'BRIDGE_CHOICE_INVALID'):await bridge_choice(llm,context(),['','继续。'])
        llm.staging_bridge_enabled=False;llm.output='x'*17
        self.assertEqual(await bridge_choice(llm,context(),['','继续。']),0)

    async def test_staging_http_error_or_missing_terminal_never_defaults_zero(self):
        for status,raw in ((400,b'PRIVATE_PROVIDER_ERROR'),(200,b'data: {"choices":[{"delta":{"content":"1"},"finish_reason":null}]}\n\ndata: [DONE]\n\n')):
            llm=BoundDeepSeek({'model':'deepseek-flash','maxTokens':256},'PRIVATE_KEY',{},staging_bridge_enabled=True)
            async def reply(request):return httpx.Response(status,content=raw)
            llm.client=httpx.AsyncClient(transport=httpx.MockTransport(reply));self.addAsyncCleanup(llm.aclose)
            with self.subTest(status=status):
                with self.assertRaises(RuntimeFailure):await bridge_choice(llm,context(),['','继续。'])

    async def test_explicit_zero_based_ascii_indices_and_exact_choice_payload(self):
        class Choice:
            staging_bridge_enabled=True
            async def stream(self,request):self.request=request;yield self.output
        llm=Choice();original=context();choices=['','回到商品。','继续下一点。'];saved=copy.deepcopy(choices)
        for index in range(3):
            llm.output=str(index)
            self.assertEqual(await bridge_choice(llm,original,choices),index)
            self.assertIn('索引从0开始，0表示空过渡',llm.request.text)
            self.assertIn('ASCII索引：0, 1, 2',llm.request.text)
            rendered=llm.request.text.split('；明确索引选项：',1)[1]
            self.assertEqual(json.loads(rendered),[{'index':i,'text':text} for i,text in enumerate(choices)])
        self.assertEqual(choices,saved)

    async def test_noncanonical_ascii_and_one_based_three_still_rejected(self):
        class Choice:
            staging_bridge_enabled=True
            async def stream(self,request):yield self.output
        llm=Choice()
        for output in ('3','-1','+1','01','١','１','1.0','1\n',' 1','"1"',''):
            llm.output=output
            with self.subTest(outputHash=hashlib.sha256(output.encode()).hexdigest()):
                with self.assertRaisesRegex(ValueError,'BRIDGE_CHOICE_INVALID'):await bridge_choice(llm,context(),['','一。','二。'])

    async def test_legacy_prompt_byte_identity_with_original_array_and_parser(self):
        class Choice:
            async def stream(self,request):self.request=request;yield ' 1\n'
        llm=Choice();original=context(4);choices=['','继续。']
        self.assertEqual(await bridge_choice(llm,original,choices),1)
        expected=LLMRequest('选择自然的过渡语，只返回选项序号。上下文：'+json.dumps(original,ensure_ascii=False)+'；选项：'+json.dumps(choices,ensure_ascii=False),
            '你只选择口语过渡，不决定哪些事实已经完成。不重复已讲卖点；必要时选空过渡。','商品事实只用于理解上下文，禁止自行添加。')
        self.assertEqual(llm.request,expected)
        self.assertEqual(llm.request.text.encode(),expected.text.encode())
