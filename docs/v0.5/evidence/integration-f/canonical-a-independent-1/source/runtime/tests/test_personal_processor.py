import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

import httpx

from app.personal_contract import PersonalContract
from app.personal_processor import PersonalMediaProcessor, PersonalProcessorClient, ProcessorFault


SCOPE = {"tenantId": "tenant_a", "userId": "user_a"}
NOW = datetime.now(timezone.utc)
CREATED = NOW.isoformat()
FUTURE = (NOW + timedelta(minutes=5)).isoformat()
DATA = b"test-input-is-not-real-user-media"


def claim_fixture(kind="VALIDATE_PHOTO"):
    purpose = "VOICE_REFERENCE" if kind == "VALIDATE_AUDIO" else "AVATAR_PHOTO"
    claim = {
        "job": {"jobId": "job_a", "kind": kind, "action": "VALIDATE", "state": "RUNNING", "attempt": 1,
                "errorCode": "NONE", "outputAssetIds": [], "createdAt": CREATED, "expiresAt": FUTURE},
        "scope": SCOPE, "claimToken": "c" * 40, "leaseExpiresAt": FUTURE,
        "inputAssets": [{"assetId": "asset_a", "purpose": purpose, "sha256": hashlib.sha256(DATA).hexdigest(),
                         "byteLength": len(DATA), "mediaType": "image/png" if kind != "VALIDATE_AUDIO" else "audio/wav",
                         "preprocessingVersion": ""}],
    }
    if kind == "VALIDATE_AUDIO":
        claim["referenceText"] = "参考文本。"
    return claim


def avatar_fixture():
    return {"avatarProfileId": "avatar_a", "name": "本人", "version": 1, "state": "PREPARING",
            "enabled": True, "isDefault": False, "config": {"provider": "soulx_lite", "photoAssetId": "photo_a",
            "workerProfileId": "worker_a", "modelRef": "soulx-flashhead-lite", "preprocessingVersion": "photo-face512-v1"},
            "normalizedPhotoAssetId": "asset_a", "errorCode": "NONE", "createdAt": CREATED, "updatedAt": CREATED}


class PersonalProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.claim = claim_fixture()
        self.requests = []
        self.results = []
        self.bad_digest = False
        self.heartbeat_denied = False
        async def handler(request):
            body = json.loads(request.content) if request.headers.get("Content-Type", "").startswith("application/json") else None
            self.requests.append((request.url.path, request.method, dict(request.headers), body))
            if request.url.path.endswith("/claim"):
                return self.ok(self.claim)
            if request.url.path.endswith("/heartbeat"):
                return httpx.Response(410) if self.heartbeat_denied else self.ok(self.claim)
            if "/inputs/" in request.url.path:
                return httpx.Response(200, content=DATA, headers={"X-Asset-SHA256": "0" * 64 if self.bad_digest else self.claim["inputAssets"][0]["sha256"]})
            if request.url.path.endswith("/outputs"):
                return self.ok({"uploadId": "output_upload", "assetId": "output_asset", "expiresAt": FUTURE}, 201)
            if "/personal-output-uploads/" in request.url.path:
                return httpx.Response(204)
            if request.url.path.endswith("/result"):
                self.results.append(body)
                job = {**self.claim["job"], "state": body["state"]}
                return self.ok(job)
            return httpx.Response(404)
        self.http = httpx.AsyncClient(base_url="https://backend.test", transport=httpx.MockTransport(handler), trust_env=False)
        self.client = PersonalProcessorClient(self.http, lambda: "processor-token")

    async def asyncTearDown(self):
        await self.http.aclose()

    @staticmethod
    def ok(data, status=200):
        return httpx.Response(status, json={"code": "OK", "data": data})

    async def test_consumes_shared_schema_and_posts_exact_normalized_result(self):
        async def validator(kind, data, text):
            self.assertEqual((kind, data, text), ("VALIDATE_PHOTO", DATA, ""))
            return b"fixture-output-for-protocol-only"
        processor = PersonalMediaProcessor(self.client, isolated_validator=validator)
        result = await processor.run("job_a", SCOPE, "processor_a")
        self.assertEqual(result["state"], "SUCCEEDED")
        body = self.results[0]
        PersonalContract().validate("SuccessResult", body)
        self.assertEqual(body["result"], {"kind": "VALIDATE_PHOTO", "outputAssetId": "output_asset", "preprocessingVersion": "photo-face512-v1"})
        output_request = next(r for r in self.requests if r[0].endswith("/outputs"))
        self.assertEqual(output_request[2]["x-job-claim"], self.claim["claimToken"])
        self.assertTrue(all("authorization" in r[2] for r in self.requests))

    async def test_audio_uses_private_upload_reference_text(self):
        self.claim = claim_fixture("VALIDATE_AUDIO")
        async def validator(kind, data, text):
            self.assertEqual(text, "参考文本。")
            return b"fixture-not-a-real-voice"
        result = await PersonalMediaProcessor(self.client, isolated_validator=validator).run("job_a", SCOPE, "processor_a")
        self.assertEqual(result["state"], "SUCCEEDED")
        self.assertEqual(self.results[0]["result"]["preprocessingVersion"], "reference-pcm16k-v1")

    async def test_missing_executor_cannot_report_success(self):
        result = await PersonalMediaProcessor(self.client).run("job_a", SCOPE, "processor_a")
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(self.results[0]["errorCode"], "PROCESSOR_UNAVAILABLE")
        self.assertFalse(any(r[0].endswith("/outputs") for r in self.requests))

    async def test_cross_scope_or_unknown_fields_rejected_before_input_read(self):
        for change in ("scope", "unknown"):
            self.requests.clear()
            self.claim = claim_fixture()
            if change == "scope":
                self.claim["scope"] = {"tenantId": "tenant_a", "userId": "user_b"}
            else:
                self.claim["gpuSshPassword"] = "not-permitted"
            with self.assertRaises(ProcessorFault):
                await PersonalMediaProcessor(self.client).run("job_a", SCOPE, "processor_a")
            self.assertEqual(len(self.requests), 1)

    async def test_path_injection_rejected_without_request(self):
        async with httpx.AsyncClient(base_url="https://backend.test") as unsafe:
            with self.assertRaisesRegex(ValueError, "PROCESSOR_TRANSPORT_UNSAFE"):
                PersonalProcessorClient(unsafe, lambda: "processor-token")
        with self.assertRaisesRegex(ValueError, "INVALID_ARGUMENT"):
            await self.client.claim("../other_job", SCOPE, "processor_a")
        self.assertEqual(self.requests, [])

    async def test_expired_claim_cannot_read_assets(self):
        self.claim["leaseExpiresAt"] = (NOW - timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ProcessorFault, "JOB_CLAIM_EXPIRED"):
            await PersonalMediaProcessor(self.client).run("job_a", SCOPE, "processor_a")
        self.assertEqual(len(self.requests), 1)

    async def test_digest_mismatch_prevents_output_publication(self):
        self.bad_digest = True
        async def validator(*args):
            self.fail("invalid digest must fence the decoder")
        result = await PersonalMediaProcessor(self.client, isolated_validator=validator).run("job_a", SCOPE, "processor_a")
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(self.results[0]["errorCode"], "OUTPUT_INVALID")
        self.assertFalse(any(r[0].endswith("/outputs") for r in self.requests))

    async def test_native_private_error_is_static_failure(self):
        async def validator(*args):
            raise RuntimeError("private path transcript and credentials")
        await PersonalMediaProcessor(self.client, isolated_validator=validator).run("job_a", SCOPE, "processor_a")
        self.assertEqual(self.results[0]["errorCode"], "PROVIDER_TEST_FAILED")
        self.assertNotIn("private path", json.dumps(self.results))

    async def test_heartbeat_failure_cancels_work_and_never_commits(self):
        self.heartbeat_denied = True
        cancelled = asyncio.Event()
        async def validator(*args):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()
        processor = PersonalMediaProcessor(self.client, isolated_validator=validator, heartbeat_interval=.01)
        with self.assertRaisesRegex(ProcessorFault, "JOB_CLAIM_EXPIRED"):
            await processor.run("job_a", SCOPE, "processor_a")
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.results, [])

    async def test_simulated_avatar_readiness_is_never_accepted(self):
        self.claim["job"].update(kind="PREPARE_AVATAR", action="PREPARE", profileVersion=1)
        self.claim["avatar"] = avatar_fixture()
        self.claim["inputAssets"][0].update(purpose="NORMALIZED_PHOTO", preprocessingVersion="photo-face512-v1")
        async def avatar(claim, inputs):
            return {"mode": "SIMULATION", "checkedAt": CREATED, "modelRevision": "pinned_revision",
                    "preprocessingVersion": "soulx-lite-512-seed42-v1", "inputSHA256": "0" * 64,
                    "cacheId": "cache_a", "workerProfileVersion": 1, "warmupFrames": 3, "encoderReady": True}
        result = await PersonalMediaProcessor(self.client, real_avatar_executor=avatar).run("job_a", SCOPE, "processor_a")
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(self.results[0]["errorCode"], "WORKER_NOT_READY")


if __name__ == "__main__":
    unittest.main()
