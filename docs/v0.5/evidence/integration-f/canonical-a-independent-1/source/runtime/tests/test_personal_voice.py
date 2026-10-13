from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import unittest
import wave

import numpy as np

from app.cosyvoice_tts import CosyVoiceTTSProvider
from app.personal_processor import ProcessorFault
from app.personal_voice import PersonalVoiceRenderer
from app.providers import AudioChunk


NOW = datetime.now(timezone.utc)
TIME = NOW.isoformat()
FUTURE = (NOW + timedelta(minutes=5)).isoformat()


def voice_claim():
    return {"job": {"jobId": "job_a", "kind": "PREVIEW_VOICE", "action": "PREPARE", "state": "RUNNING",
                    "attempt": 1, "profileVersion": 1, "errorCode": "NONE", "outputAssetIds": [], "createdAt": TIME, "expiresAt": FUTURE},
            "scope": {"tenantId": "tenant_a", "userId": "user_a"}, "claimToken": "c" * 40,
            "leaseExpiresAt": FUTURE, "inputAssets": [], "previewText": "语音配置测试。",
            "voice": {"voiceProfileId": "voice_a", "name": "本人", "version": 1, "state": "PREPARING",
                      "enabled": True, "isDefault": False, "config": {"provider": "xiaoya", "voiceId": "xiao_ya", "modelRef": "xiaoya-default", "speed": 1, "volume": 1},
                      "capabilities": {"referenceAudio": False, "incrementalPCM": True, "speed": False, "volume": False},
                      "errorCode": "NONE", "createdAt": TIME, "updatedAt": TIME}}


class FakeProvider:
    async def synthesize_stream(self, text, voice, ctx):
        samples = (np.sin(np.arange(24000) * 2 * np.pi * 220 / 24000) * 10000).astype("<i2")
        yield AudioChunk(ctx.generation_id, 0, samples.tobytes(), 24000)


class PersonalVoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        os.chmod(self.root, 0o700)

    def tearDown(self):
        self.temp.cleanup()

    async def test_system_preview_from_exact_shared_voice_profile(self):
        data = await PersonalVoiceRenderer(self.root, system_factory=FakeProvider)(voice_claim(), {})
        with wave.open(BytesIO(data), "rb") as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (16000, 1, 2))
            self.assertEqual(wav.getnframes(), 16000)
            self.assertTrue(any(wav.readframes(16000)))

    async def test_missing_system_engine_never_synthesizes_placeholder(self):
        with self.assertRaisesRegex(ProcessorFault, "PROCESSOR_UNAVAILABLE"):
            await PersonalVoiceRenderer(self.root)(voice_claim(), {})

    async def test_versions_disabled_and_capabilities_cannot_be_ignored(self):
        renderer = PersonalVoiceRenderer(self.root, system_factory=FakeProvider)
        for field, value in (("enabled", False), ("version", 2), ("state", "DELETED")):
            claim = voice_claim()
            claim["voice"][field] = value
            with self.assertRaisesRegex(ProcessorFault, "CONFIG_VERSION_CONFLICT"):
                await renderer(claim, {})
        claim = voice_claim()
        claim["voice"]["capabilities"]["referenceAudio"] = True
        with self.assertRaisesRegex(ProcessorFault, "CAPABILITY_UNSUPPORTED"):
            await renderer(claim, {})

    async def test_unsupported_speed_and_nonfinite_volume_rejected_by_shared_schema(self):
        renderer = PersonalVoiceRenderer(self.root, system_factory=FakeProvider)
        for change in ({"speed": 1.5}, {"volume": float("nan")}):
            claim = voice_claim()
            claim["voice"]["config"].update(change)
            with self.assertRaisesRegex(ValueError, "INVALID_ARGUMENT"):
                await renderer(claim, {})

    async def test_cosyvoice_uses_only_claimed_reference_and_cleans_private_copy(self):
        output = BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(3 * 16000 * 2))
        reference = output.getvalue()
        claim = voice_claim()
        claim["voice"]["config"] = {"provider": "cosyvoice", "modelRef": "reviewed_model",
            "referenceAssetId": "original_audio", "referenceText": "参考文本。", "speed": 1, "volume": .8}
        claim["voice"]["capabilities"].update(referenceAudio=True, volume=True)
        claim["voice"]["normalizedAudioAssetId"] = "reference_audio"
        claim["inputAssets"] = [{"assetId": "reference_audio", "purpose": "NORMALIZED_AUDIO",
            "sourceAssetId": "original_audio", "sha256": hashlib.sha256(reference).hexdigest(),
            "byteLength": len(reference), "mediaType": "audio/wav", "preprocessingVersion": "reference-pcm16k-v1"}]
        paths = []
        class FakeEngine:
            sample_rate = 24000
            def inference_zero_shot(self, text, prompt, path, **options):
                self.options = options
                yield {"tts_speech": np.full((1, 24000), .2)}
        engine = FakeEngine()
        def factory(voice_id, path, text, volume):
            paths.append(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            return CosyVoiceTTSProvider(engine, threading.Lock(), voice_id, path, text, volume)
        async def quarantine(provider):
            self.fail("responsive fixture must not be quarantined")
        renderer = PersonalVoiceRenderer(self.root, cosyvoice_factories={"reviewed_model": factory}, quarantine_worker=quarantine)
        data = await renderer(claim, {"reference_audio": reference})
        with wave.open(BytesIO(data), "rb") as wav:
            self.assertEqual(wav.getnframes(), 16000)
        self.assertEqual(engine.options, {"stream": True, "speed": 1.0})
        self.assertFalse(paths[0].exists())
        self.assertEqual(list(self.root.iterdir()), [])
        claim["inputAssets"][0]["sourceAssetId"] = "other_owner_asset"
        with self.assertRaisesRegex(ProcessorFault, "OUTPUT_INVALID"):
            await renderer(claim, {"reference_audio": reference})


if __name__ == "__main__":
    unittest.main()
