"""Opt-in v0.3.1 processor protocol, consuming immutable Agent 1 JobClaims.

No Backend handlers, profile store or default selection are created here. Operators
must inject resource-isolated validation and authorized REAL inference executors.
Absent executors fail closed. No polling, automatic compute retry or GPU startup.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json

import httpx

from .personal_assets import AssetValidationError
from .personal_contract import PersonalContract


class ProcessorFault(RuntimeError):
    pass


class PersonalProcessorClient:
    def __init__(self, http: httpx.AsyncClient, token_provider, contract=None):
        if http.base_url.scheme != "https":
            raise ValueError("PROCESSOR_TLS_REQUIRED")
        if http.trust_env:
            raise ValueError("PROCESSOR_TRANSPORT_UNSAFE")
        self.http, self.token_provider = http, token_provider
        self.contract = contract or PersonalContract()

    def _headers(self, claim=None):
        token = self.token_provider()
        if not token or any(c in token for c in "\r\n"):
            raise ProcessorFault("PROCESSOR_UNAVAILABLE")
        headers = {"Authorization": "Bearer " + token}
        if claim is not None:
            headers["X-Job-Claim"] = claim["claimToken"]
        return headers

    async def _json(self, path, body, schema, claim=None):
        try:
            data = bytearray()
            async with self.http.stream("POST", path, json=body, headers=self._headers(claim),
                                        follow_redirects=False, timeout=10) as response:
                if response.status_code not in {200, 201}:
                    raise ProcessorFault("JOB_CLAIM_EXPIRED" if response.status_code in {401, 403, 404, 409, 410} else "PROCESSOR_UNAVAILABLE")
                async for part in response.aiter_bytes():
                    if len(data) + len(part) > 65536:
                        raise ProcessorFault("OUTPUT_INVALID")
                    data.extend(part)
            envelope = json.loads(data)
            if envelope.get("code") != "OK":
                raise ProcessorFault("OUTPUT_INVALID")
            return self.contract.validate(schema, envelope["data"])
        except ProcessorFault:
            raise
        except Exception:
            raise ProcessorFault("OUTPUT_INVALID") from None

    async def claim(self, job_id, scope, worker_ref):
        self.contract.validate("Scope", scope)
        self.contract.validate_property("Job", "jobId", job_id)
        body = self.contract.validate("ClaimInput", {"scope": scope, "workerRef": worker_ref})
        claim = await self._json(f"/internal/v0.3/personal-jobs/{job_id}/claim", body, "JobClaim")
        if claim["scope"] != scope or claim["job"]["jobId"] != job_id:
            raise ProcessorFault("JOB_CLAIM_EXPIRED")
        return claim

    async def heartbeat(self, claim):
        body = {"claimToken": claim["claimToken"], "attempt": claim["job"]["attempt"]}
        updated = await self._json(f"/internal/v0.3/personal-jobs/{claim['job']['jobId']}/heartbeat", body, "JobClaim")
        # Lease extension must never alter immutable inputs, scope or attempt.
        for key in ("scope", "claimToken", "inputAssets", "avatar", "voice", "previewText", "referenceText"):
            if updated.get(key) != claim.get(key):
                raise ProcessorFault("JOB_CLAIM_EXPIRED")
        if updated["job"] != claim["job"]:
            raise ProcessorFault("JOB_CLAIM_EXPIRED")
        return updated

    async def read_input(self, claim, descriptor):
        self.contract.validate("AssetDescriptor", descriptor)
        if descriptor not in claim["inputAssets"]:
            raise ProcessorFault("OUTPUT_INVALID")
        path = f"/internal/v0.3/personal-jobs/{claim['job']['jobId']}/inputs/{descriptor['assetId']}/content"
        data = bytearray()
        try:
            async with self.http.stream("GET", path, headers=self._headers(claim),
                                        follow_redirects=False, timeout=10) as response:
                if response.status_code != 200:
                    raise ProcessorFault("JOB_CLAIM_EXPIRED")
                if response.headers.get("X-Asset-SHA256") != descriptor["sha256"]:
                    raise ProcessorFault("OUTPUT_INVALID")
                async for part in response.aiter_bytes():
                    if len(data) + len(part) > descriptor["byteLength"]:
                        raise ProcessorFault("OUTPUT_INVALID")
                    data.extend(part)
        except ProcessorFault:
            raise
        except Exception:
            raise ProcessorFault("PROCESSOR_UNAVAILABLE") from None
        if len(data) != descriptor["byteLength"] or hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
            raise ProcessorFault("OUTPUT_INVALID")
        return bytes(data)

    async def write_output(self, claim, data, purpose, media_type):
        body = {"claimToken": claim["claimToken"], "attempt": claim["job"]["attempt"],
                "purpose": purpose, "byteLength": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mediaType": media_type}
        self.contract.validate("OutputUploadInput", body)
        ticket = await self._json(f"/internal/v0.3/personal-jobs/{claim['job']['jobId']}/outputs", body, "OutputTicket", claim)
        try:
            response = await self.http.put(f"/internal/v0.3/personal-output-uploads/{ticket['uploadId']}/content",
                content=data, headers={**self._headers(claim), "Content-Type": "application/octet-stream"},
                follow_redirects=False, timeout=10)
            if response.status_code != 204:
                raise ProcessorFault("OUTPUT_INVALID")
        except ProcessorFault:
            raise
        except Exception:
            raise ProcessorFault("PROCESSOR_UNAVAILABLE") from None
        return ticket["assetId"]

    async def result(self, claim, body):
        self.contract.validate("JobResultInput", body)
        if body["claimToken"] != claim["claimToken"] or body["attempt"] != claim["job"]["attempt"]:
            raise ProcessorFault("JOB_CLAIM_EXPIRED")
        return await self._json(f"/internal/v0.3/personal-jobs/{claim['job']['jobId']}/result", body, "Job")


class PersonalMediaProcessor:
    def __init__(self, client: PersonalProcessorClient, isolated_validator=None,
                 real_voice_renderer=None, real_avatar_executor=None, heartbeat_interval=15):
        if not 0 < heartbeat_interval <= 20:
            raise ValueError("INVALID_ARGUMENT")
        self.client = client
        self.heartbeat_interval = heartbeat_interval
        self.validator = isolated_validator
        self.voice_renderer = real_voice_renderer
        self.avatar_executor = real_avatar_executor

    async def _execute(self, claim):
        kind = claim["job"]["kind"]
        if (kind in {"VALIDATE_PHOTO", "VALIDATE_AUDIO"} and self.validator is None
                or kind == "PREVIEW_VOICE" and self.voice_renderer is None):
            raise ProcessorFault("PROCESSOR_UNAVAILABLE")
        if kind in {"PREPARE_AVATAR", "PREVIEW_AVATAR"} and self.avatar_executor is None:
            raise ProcessorFault("WORKER_NOT_READY")
        inputs = {asset["assetId"]: await self.client.read_input(claim, asset) for asset in claim["inputAssets"]}
        if kind in {"VALIDATE_PHOTO", "VALIDATE_AUDIO"}:
            if self.validator is None:
                raise ProcessorFault("PROCESSOR_UNAVAILABLE")
            purpose = "AVATAR_PHOTO" if kind == "VALIDATE_PHOTO" else "VOICE_REFERENCE"
            sources = [asset for asset in claim["inputAssets"] if asset["purpose"] == purpose]
            if len(sources) != 1 or len(inputs) != 1:
                raise ProcessorFault("OUTPUT_INVALID")
            data = await self.validator(kind, inputs[sources[0]["assetId"]], claim.get("referenceText", ""))
            output_purpose, media, preprocessing = (
                ("NORMALIZED_PHOTO", "image/png", "photo-face512-v1") if kind == "VALIDATE_PHOTO" else
                ("NORMALIZED_AUDIO", "audio/wav", "reference-pcm16k-v1"))
            output_id = await self.client.write_output(claim, data, output_purpose, media)
            return {"kind": kind, "outputAssetId": output_id, "preprocessingVersion": preprocessing}
        if kind == "PREVIEW_VOICE":
            if self.voice_renderer is None or "voice" not in claim:
                raise ProcessorFault("PROCESSOR_UNAVAILABLE")
            data = await self.voice_renderer(claim, inputs)
            output_id = await self.client.write_output(claim, data, "VOICE_PREVIEW", "audio/wav")
            return {"kind": kind, "outputAssetId": output_id}
        if kind in {"PREPARE_AVATAR", "PREVIEW_AVATAR"}:
            if self.avatar_executor is None or "avatar" not in claim:
                raise ProcessorFault("WORKER_NOT_READY")
            photos = [asset for asset in claim["inputAssets"]
                      if asset["purpose"] == "NORMALIZED_PHOTO"
                      and asset["assetId"] == claim["avatar"].get("normalizedPhotoAssetId")
                      and asset["preprocessingVersion"] == "photo-face512-v1"]
            if len(photos) != 1:
                raise ProcessorFault("OUTPUT_INVALID")
            result = await self.avatar_executor(claim, inputs)
            if kind == "PREPARE_AVATAR":
                self.client.contract.validate("Readiness", result)
                if result["mode"] != "REAL" or not result["encoderReady"]:
                    raise ProcessorFault("WORKER_NOT_READY")
                if (result["inputSHA256"] != photos[0]["sha256"]
                        or result["preprocessingVersion"] != "soulx-lite-512-seed42-v1"):
                    raise ProcessorFault("OUTPUT_INVALID")
                return {"kind": kind, "readiness": result}
            output_id = await self.client.write_output(claim, result, "AVATAR_PREVIEW", "video/mp4")
            return {"kind": kind, "outputAssetId": output_id}
        raise ProcessorFault("INVALID_ARGUMENT")

    async def run(self, job_id, scope, worker_ref):
        claim = await self.client.claim(job_id, scope, worker_ref)
        if (claim["job"]["state"] != "RUNNING" or claim["job"]["attempt"] < 1
                or datetime.fromisoformat(claim["leaseExpiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)
                or datetime.fromisoformat(claim["job"]["expiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)):
            raise ProcessorFault("JOB_CLAIM_EXPIRED")
        actions = {"VALIDATE_PHOTO": {"VALIDATE"}, "VALIDATE_AUDIO": {"VALIDATE"},
                   "PREPARE_AVATAR": {"PREPARE"}, "PREVIEW_AVATAR": {"PREVIEW"},
                   "PREVIEW_VOICE": {"PREPARE", "PREVIEW"}}
        assets = claim["inputAssets"]
        if (claim["job"]["action"] not in actions[claim["job"]["kind"]]
                or len(assets) > 4 or len({a["assetId"] for a in assets}) != len(assets)):
            raise ProcessorFault("OUTPUT_INVALID")
        deadline = 120 if claim["job"]["kind"] == "PREPARE_AVATAR" else 60

        async def execute():
            async with asyncio.timeout(deadline):
                return await self._execute(claim)

        async def heartbeat():
            while True:
                await asyncio.sleep(self.heartbeat_interval)
                await self.client.heartbeat(claim)

        work = asyncio.create_task(execute())
        pulse = asyncio.create_task(heartbeat())
        try:
            done, _ = await asyncio.wait({work, pulse}, return_when=asyncio.FIRST_COMPLETED)
            if pulse in done:
                await pulse  # Lease/auth failure fences output; do not send success.
                raise ProcessorFault("JOB_CLAIM_EXPIRED")
            result = await work
            body = {"claimToken": claim["claimToken"], "attempt": claim["job"]["attempt"],
                    "state": "SUCCEEDED", "result": result}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            allowed = self.client.contract.document["components"]["schemas"]["ErrorCode"]["enum"]
            code = str(exc) if isinstance(exc, (ProcessorFault, AssetValidationError)) and str(exc) in allowed else "PROVIDER_TEST_FAILED"
            if isinstance(exc, TimeoutError):
                code = "JOB_TIMEOUT"
            # Expired/cancelled claims cannot publish any result.
            if code == "JOB_CLAIM_EXPIRED":
                raise ProcessorFault(code) from None
            body = {"claimToken": claim["claimToken"], "attempt": claim["job"]["attempt"], "state": "FAILED", "errorCode": code}
        finally:
            work.cancel()
            pulse.cancel()
            await asyncio.gather(work, pulse, return_exceptions=True)
        return await self.client.result(claim, body)
