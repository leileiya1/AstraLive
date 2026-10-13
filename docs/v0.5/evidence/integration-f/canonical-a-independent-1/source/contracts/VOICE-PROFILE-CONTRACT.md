# VoiceProfile Contract v0.3.1

Status: FROZEN 2026-10-09. Machine contract: `personal-assets/schema.json`; ownership/storage/jobs: ASSET-STORAGE-CONTRACT; atomic session snapshot: AVATAR-PROFILE-CONTRACT. VoiceProfile is distinct from generic TTS Profile and legacy voiceId. No voice-cloning engine or formal TTS default is changed by this contract.

## Entity and provider-specific parameters

VoiceProfile `{voiceProfileId,name,version,state,enabled,isDefault,config,normalizedAudioAssetId?,capabilities,errorCode,createdAt,updatedAt}`. Config is a closed discriminated union:

| provider | Required config | Capability |
| --- | --- | --- |
| xiaoya | provider, voiceId=`xiao_ya`, modelRef=`xiaoya-default`, speed=1, volume=1 | preset, incrementalPCM=true, referenceAudio=false, speed=false, volume=false |
| cosyvoice | provider, operator-registered modelRef, referenceAssetId, referenceText, speed=1, volume 0..2 | referenceAudio=true, incrementalPCM=true, speed=false, volume=true |

Other providers need a versioned capability/config schema before admission; never forward an unvalidated free-form parameter bag or assume OpenAI compatibility. Current optional local CosyVoice engine is an adapter boundary, not proof that weights/license/deployment/quality have been approved. Model registry must record reviewed model/dependency/data license readiness and already-installed weights before enabling its capability. Disabled/uninstalled providers return PROCESSOR_UNAVAILABLE; never download weights or rent GPU in response to a profile write.

referenceAssetId is the owner's READY VOICE_REFERENCE source, whose READY normalized derivative is mono16k PCM16 WAV, duration3..30s. referenceText is trimmed 1..1000 Unicode code points, no NUL; encrypted at rest using the external keyring, only owner/config backend and assigned processor can read it, no transcript logs or browser persistence. The public owner-authorized VoiceProfile may return referenceText because it is editable user text, never an API key. The profile stores immutable normalizedAudioAssetId/digest after successful preparation. Changing reference text makes a new profile version, even if audio bytes are identical. Portrait and voice assets may come from separate owner uploads; no inferred person/identity match is asserted.

The accepted old generic TTS config stores speed 0.5..2; current XiaoYa and optional CosyVoice streaming adapters do not expose speed control. That legacy metadata is not evidence of applied speed. New VoiceProfile rejects any non-1 speed (422 CAPABILITY_UNSUPPORTED); xiaoya also rejects non-1 volume, cosyvoice supports volume0..2. Do not silently ignore unsupported parameters or change existing v0.3.0 schema to pretend support.

## Public API and states

Under `/api/v0.3/config/voice-profiles`:

| Method/path | Input | Success |
| --- | --- | --- |
| GET collection / GET `/{voiceProfileId}` | cookie | array / VoiceProfile |
| POST collection | `{name,config}` + Idempotency-Key | 201 CREATED VoiceProfile |
| PUT `/{voiceProfileId}` | `{expectedVersion,name,config}` | new CREATED revision; enabled=true |
| POST `/{voiceProfileId}/prepare` | `{expectedVersion}` + Idempotency-Key | 202 Job |
| POST `/{voiceProfileId}/preview` | `{expectedVersion,text}` + Idempotency-Key | 202 PREVIEW_VOICE Job |
| POST `/{voiceProfileId}/default` | `{expectedVersion}` | READY enabled VoiceProfile; NEXT_SESSION |
| POST `/{voiceProfileId}/disable` | `{expectedVersion}` | DISABLED, clears default |
| DELETE `/{voiceProfileId}` | `{expectedVersion}` | 204 tombstone; pinned old revisions survive lease |

Shared states CREATED -> VALIDATING -> PREPARING -> READY/FAILED, any live state -> DISABLED/DELETED. PREPARE for voice is a PREVIEW_VOICE job with private fixed diagnostic text “语音配置测试。” and purpose VOICE_PREVIEW; its verified generated PCM output is the readiness check, not a storage-only validation. It is marked internally as the preparation action so completion can update current-version readiness. Failed prepare is FAILED; failure of a later ordinary preview records its Job error and does not erase an otherwise READY revision. Preview user text is trimmed1..200 code points, no NUL; no arbitrary SSML, URLs or file paths. Require a READY revision for ordinary preview. No no-op “test success” for XiaoYa before an actual synthesis adapter completes.

Profile preparation has the same missing-processor, idempotency, cancellation and CAS rules as Avatar. Any successful voice prepare/preview must yield a verified READY VOICE_PREVIEW WAV, mono16kPCM16, finite nonempty samples, <=30s/20MiB, complete generation with no sequence gap. A JobKind alone does not let the worker claim configuration readiness; Backend derives preparation vs ordinary preview from the immutable job record. Wrong kind, missing output, invalid PCM, unsupported capability, runtime 401/cloud error or interrupted stream fails the job. Public error is static PROVIDER_TEST_FAILED when no more specific safe code applies; private redacted diagnostics may correlate by request/job ID. Never report a placeholder silence/demo file as real synthesis.

Output preview does not certify subjective similarity, licensing, long-running stability or quality. New default selection cannot silently replace the formal runtime XiaoYa default; Session consumption is gated by the separate personal-binding integration. “Current default” describes the next personal-binding capture, not the voice of an already-playing Session. Internal PCM streaming contract remains owned by Runtime/Voice Agent; this contract supplies immutable profile/reference descriptors and capabilities, not changes to accepted speech/session events.
