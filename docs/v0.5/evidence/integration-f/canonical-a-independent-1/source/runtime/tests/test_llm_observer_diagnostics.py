"""Mock SSE/HTTP diagnosis and disclosure regressions, not real LLM evidence."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from app.providers import LLMRequest
from app.session import RuntimeFailure
from app.session_binding import BoundDeepSeek


class LLMSafeObserverTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self,events=None,status=200,enabled=True,raw=None):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        env={"ASTRALIVE_STAGING_OBSERVER_DIR":directory.name} if enabled else {}
        with patch.dict(os.environ,env,clear=True):
            errors={};llm=BoundDeepSeek({"model":"deepseek-flash","maxTokens":256},"never-log-private-key",errors)
        self.addAsyncCleanup(llm.aclose)
        response=raw if raw is not None else "".join("data: "+json.dumps(event)+"\n\n" for event in events)+"data: [DONE]\n\n"
        async def upstream(request):
            body=json.loads(request.content)
            self.assertEqual(body["max_tokens"],256)
            self.assertNotIn("thinking",body)
            self.assertEqual(body["messages"][3]["content"],"never-log-private-question")
            return httpx.Response(status,content=response.encode())
        llm.client=httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        spoken=[];failure=None
        try:
            async for token in llm.stream(LLMRequest("never-log-private-question","你只选择口语过渡测试","never-log-private-facts")):spoken.append(token)
        except RuntimeFailure as exc:failure=exc
        path=Path(directory.name)/"llm-calls.jsonl"
        row=json.loads(path.read_text()) if path.exists() else None
        if row:
            text=path.read_text()
            for secret in ("never-log-private-key","never-log-private-question","never-log-private-facts","never-log-private-reasoning","never-log-error-body"):
                self.assertNotIn(secret,text)
        return row,failure,spoken

    async def test_reasoning_only_length_finish_is_distinct_without_reasoning_disclosure(self):
        row,failure,spoken=await self.run_case([
            {"choices":[{"delta":{"reasoning_content":"never-log-private-reasoning"},"finish_reason":None}]},
            {"choices":[{"delta":{},"finish_reason":"length"}],"usage":{"prompt_tokens":32,"completion_tokens":256,"total_tokens":288,"completion_tokens_details":{"reasoning_tokens":256}}}])
        self.assertIsNotNone(failure);self.assertFalse(spoken)
        detail=row["streamDiagnostic"]
        self.assertEqual(detail["httpStatus"],200);self.assertEqual(detail["finishReason"],"length")
        self.assertEqual(detail["streamOutcome"],"FINISH_NOT_STOP");self.assertEqual(detail["errorType"],"RuntimeError")
        self.assertEqual(detail["reasoningDeltaCount"],1);self.assertEqual(detail["reasoningTokens"],256)
        self.assertEqual(detail["contentDeltaCount"],0);self.assertEqual(row["responseChars"],0)

    async def test_http_auth_status_distinct_and_error_body_never_persisted(self):
        row,failure,_=await self.run_case(status=401,raw='{"error":"never-log-error-body"}')
        self.assertEqual(failure.code,"PROVIDER_AUTH_FAILED")
        self.assertEqual(row["streamDiagnostic"],{"httpStatus":401,"errorType":"HTTPStatusError","streamOutcome":"HTTP_STATUS_ERROR"})

    async def test_unknown_finish_reason_and_stream_error_never_dump_upstream_strings(self):
        for packet in ({"choices":[{"delta":{},"finish_reason":"never-log-private-reasoning"}]}, {"error":{"message":"never-log-error-body"}}):
            with self.subTest(packetKind="finish" if "choices" in packet else "error"):
                row,failure,_=await self.run_case([packet])
                self.assertIsNotNone(failure)
                self.assertEqual(row["streamDiagnostic"]["errorType"],"RuntimeError")
                if "choices" in packet:self.assertEqual(row["streamDiagnostic"]["finishReason"],"OTHER")
                else:self.assertEqual(row["streamDiagnostic"]["streamOutcome"],"PROVIDER_STREAM_ERROR")

    async def test_malformed_json_records_static_exception_class_only(self):
        row,failure,_=await self.run_case(raw='data: {never-log-error-body\n\n')
        self.assertIsNotNone(failure)
        self.assertEqual(row["streamDiagnostic"]["errorType"],"JSONDecodeError")

    async def test_success_unchanged_and_default_off_creates_no_observer(self):
        events=[{"choices":[{"delta":{"content":"approved spoken fixture"},"finish_reason":None}]},{"choices":[{"delta":{},"finish_reason":"stop"}]}]
        for enabled in (True,False):
            row,failure,spoken=await self.run_case(events,enabled=enabled)
            self.assertIsNone(failure);self.assertEqual(spoken,["approved spoken fixture"])
            if enabled:
                self.assertEqual(row["streamDiagnostic"]["streamOutcome"],"COMPLETED")
                self.assertEqual(row["streamDiagnostic"]["finishReason"],"stop")
                self.assertTrue(row["streamDiagnostic"]["doneObserved"])
                self.assertEqual(row["streamDiagnostic"]["contentDeltaCount"],1)
            else:self.assertIsNone(row)
