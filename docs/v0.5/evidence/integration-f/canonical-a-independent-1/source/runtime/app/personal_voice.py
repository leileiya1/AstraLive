"""Render Agent 1 VoiceProfiles using operator-injected, installed local engines."""
from io import BytesIO
import os
from pathlib import Path
import tempfile
import wave

from .models import VoiceConfig
from .personal_contract import PersonalContract
from .personal_processor import ProcessorFault
from .providers import GenerationContext
from .voice_stream import StreamingVoiceAdapter


class PersonalVoiceRenderer:
    """Factory registry contains reviewed installed models only, never user code.

    cosyvoice factories accept (voice_id, reference_path, reference_text, volume)
    and return CosyVoiceTTSProvider sharing their loaded model's lock. A factory
    must not download/train. The service owns auditing/registration and GPU cost.
    """
    def __init__(self, private_temp_root: Path, system_factory=None, cosyvoice_factories=None,
                 quarantine_worker=None, contract=None):
        path = Path(private_temp_root)
        if (not path.is_absolute() or path.resolve() != path or not path.is_dir()
                or path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid()):
            raise ValueError("PRIVATE_TEMP_ROOT_REQUIRED")
        self.root, self.system_factory = path, system_factory
        self.factories = dict(cosyvoice_factories or {})
        if self.factories and quarantine_worker is None:
            raise ValueError("VOICE_QUARANTINE_HANDLER_REQUIRED")
        self.quarantine_worker = quarantine_worker
        self.contract = contract or PersonalContract()
        self.retained = []  # Only when supervisor could not prove native shutdown.

    async def __call__(self, claim, inputs):
        import asyncio
        self.contract.validate("JobClaim", claim)
        if claim["job"]["kind"] != "PREVIEW_VOICE" or "voice" not in claim:
            raise ProcessorFault("OUTPUT_INVALID")
        profile = claim["voice"]
        config = profile["config"]
        expected = {"referenceAudio": config["provider"] == "cosyvoice", "incrementalPCM": True,
                    "speed": False, "volume": config["provider"] == "cosyvoice"}
        if profile["capabilities"] != expected:
            raise ProcessorFault("CAPABILITY_UNSUPPORTED")
        if (not profile["enabled"] or profile["version"] != claim["job"].get("profileVersion")
                or profile["state"] in {"FAILED", "DISABLED", "DELETED"}):
            raise ProcessorFault("CONFIG_VERSION_CONFLICT")
        if claim["job"]["action"] == "PREVIEW" and profile["state"] != "READY":
            raise ProcessorFault("ASSET_NOT_READY")
        text = claim.get("previewText", "")
        if not text or text != text.strip() or "\x00" in text or len(text) > 200:
            raise ProcessorFault("INVALID_ARGUMENT")
        if claim["job"]["action"] == "PREPARE" and text != "语音配置测试。":
            raise ProcessorFault("INVALID_ARGUMENT")
        temp = None
        provider = None
        try:
            if config["provider"] == "xiaoya":
                if self.system_factory is None:
                    raise ProcessorFault("PROCESSOR_UNAVAILABLE")
                provider = self.system_factory()
            else:
                factory = self.factories.get(config["modelRef"])
                if factory is None:
                    raise ProcessorFault("PROCESSOR_UNAVAILABLE")
                assets = [a for a in claim["inputAssets"] if a["purpose"] == "NORMALIZED_AUDIO"
                          and a.get("sourceAssetId") == config["referenceAssetId"]
                          and a["preprocessingVersion"] == "reference-pcm16k-v1"]
                if len(assets) != 1 or assets[0]["assetId"] not in inputs:
                    raise ProcessorFault("OUTPUT_INVALID")
                if profile.get("normalizedAudioAssetId", assets[0]["assetId"]) != assets[0]["assetId"]:
                    raise ProcessorFault("OUTPUT_INVALID")
                if config["referenceText"] != config["referenceText"].strip() or "\x00" in config["referenceText"]:
                    raise ProcessorFault("INVALID_ARGUMENT")
                normalized = inputs[assets[0]["assetId"]]
                import hashlib
                if len(normalized) != assets[0]["byteLength"] or hashlib.sha256(normalized).hexdigest() != assets[0]["sha256"]:
                    raise ProcessorFault("OUTPUT_INVALID")
                temp = tempfile.TemporaryDirectory(prefix="voice-", dir=self.root)
                reference = Path(temp.name) / "reference.wav"
                fd = os.open(reference, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as file:
                    file.write(normalized)
                provider = factory(profile["voiceProfileId"], reference, config["referenceText"], config["volume"])
            ctx = GenerationContext(claim["job"]["attempt"], claim["job"]["jobId"],
                                    claim["job"]["jobId"], claim["job"]["jobId"])
            stream = StreamingVoiceAdapter(provider, profile["voiceProfileId"]).synthesize_stream(
                text, VoiceConfig(voiceId=profile["voiceProfileId"]), ctx)
            pcm = bytearray()
            try:
                # Job deadline is 60s; leave time for output verification/commit.
                async with asyncio.timeout(50):
                    async for chunk in stream:
                        if len(pcm) + len(chunk.pcm) > 30 * 16000 * 2:
                            raise ProcessorFault("OUTPUT_INVALID")
                        pcm.extend(chunk.pcm)
            finally:
                await stream.aclose()
            output = BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(pcm)
            return output.getvalue()
        finally:
            if provider is not None and getattr(provider, "poisoned", False):
                # Supervisor must stop/recycle the owning model process before
                # confirming cleanup. Retain the private reference until then.
                try:
                    stopped = await self.quarantine_worker(provider)
                except BaseException:
                    if temp is not None:
                        self.retained.append(temp)
                    raise
                if stopped is not True:
                    if temp is not None:
                        self.retained.append(temp)
                    raise ProcessorFault("PROCESSOR_UNAVAILABLE")
            if temp is not None:
                temp.cleanup()
