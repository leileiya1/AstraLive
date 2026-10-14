"""CPU fault classification only; no provider/GPU or physical receipts."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.narration import NarrationCommands
from app.session import RuntimeFailure

class PreparationDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self,where,exc):
        records=[];fences=[];guards=[]
        def guard(command):
            guards.append(command)
            if where=='initial_guard' or where=='final_guard' and len(guards)==2:raise exc
        async def product(product):
            if where=='tool_refresh':raise exc
            return {'private':'PRIVATE_TOOL_FACT'}
        async def choose(*args):
            if where=='bridge_llm':raise exc
            return 1
        async def record(op,command,proof):
            records.append(op)
            if op=='RESUME_PREPARED' and where=='journal_record':raise exc
        session=SimpleNamespace(tool_client=SimpleNamespace(get_product=product),llm=object())
        executor=SimpleNamespace(session=session,guard=guard,timeline=SimpleNamespace(journal=SimpleNamespace(record=record)),fence=fences.append)
        adapter=NarrationCommands(None,None,None)
        command={'commandId':'prepare-cmd','commandType':'PREPARE_RESUME_BRIDGE','payload':{'context':{'productId':'private-product','goal':'PRIVATE_PLAN'},'choices':['','PRIVATE_CHOICE']}}
        with patch('app.narration.bridge_choice',choose),self.assertLogs('app',level='WARNING') as logs:
            with self.assertRaises(type(exc)):await adapter._prepare(executor,command)
        raw=logs.output[0].split('narration_preparation_failed ',1)[1]
        self.assertNotIn('PRIVATE',raw);row=json.loads(raw)
        self.assertEqual(row['phase'],where);self.assertIn(where,row['phaseDurationsMs']);self.assertGreaterEqual(row['elapsedMs'],0)
        self.assertEqual(records[-1],'UNKNOWN');self.assertEqual(fences,['PREPARATION_UNKNOWN'])
        return row

    async def test_bridge_provider_failure_stays_unknown_and_has_phase(self):
        row=await self.scenario('bridge_llm',RuntimeFailure('LLM_FAILED','PRIVATE_PROVIDER_ERROR',502))
        self.assertEqual(row['code'],'LLM_FAILED');self.assertEqual(row['errorType'],'RuntimeFailure')
        self.assertIn('tool_refresh',row['phaseDurationsMs'])

    async def test_tool_unknown_exception_redacted(self):
        row=await self.scenario('tool_refresh',RuntimeError('PRIVATE_TOOL_ERROR'))
        self.assertEqual(row['code'],'OTHER')

    async def test_journal_unknown_exception_redacted(self):
        row=await self.scenario('journal_record',RuntimeError('PRIVATE_ACK_ERROR'))
        self.assertEqual(row['code'],'OTHER')

    async def test_guard_failure_and_timeout_classified_without_retry(self):
        row=await self.scenario('final_guard',ValueError('RUN_SEALED: PRIVATE_EXTRA'))
        self.assertEqual(row['code'],'RUN_SEALED')
        row=await self.scenario('bridge_llm',TimeoutError('PRIVATE_TIMEOUT'))
        self.assertEqual(row['errorType'],'TimeoutError')
