# GPU Worker Status Contract 1.0

Additive read-only status endpoint; does not amend frozen user profile inputs or Control/Runtime v1.1. Internal inference protocol 1.1 is specified in GPU-WORKER-PRODUCTION-DESIGN.md.

`GET /api/v0.3/config/profiles/{profileId}/worker-status` uses the existing response envelope, HttpOnly Secure configuration cookie, tenant AND user profile ownership and an operator-owned physical-worker ACL. Browser-supplied tenant/user IDs are never used. Missing identity401; cross-scope Profile or known physical-worker ACL violation404; unregistered ref409 PROVIDER_TEST_UNAVAILABLE; unavailable/invalid probe502 PROVIDER_TEST_FAILED. No-store, existing requestId/timestamp fields. It does not mutate verification/default/Profile health.

`data` fields:

| Field | Meaning |
| --- | --- |
| statusVersion | `1.0` |
| workerRef | logical reference only |
| ready / health | warmup-and-health ready boolean; live status UP/DOWN |
| modelRevision | pinned model source revision |
| avatarCacheStatus | cacheId, avatarRef, status, metadataRestored, preprocessingRebuilt |
| gpuAllocatedBytes / gpuReservedBytes | process PyTorch allocator bytes; null for simulation |
| gpuUtilizationPercent / gpuTemperatureC / gpuDeviceMemoryUsedBytes | sampled single GPU device; null if unavailable |
| trueGeneratedFPS / modelComputeFPS | new model output rolling10s / synchronized inference computation rate; no held or cached frames |
| generatedFrames / publishedFrames | separate cumulative counters |
| queueDepth | audioSamples, videoFrames; bounded by32000/24 |
| lastError | null or static allowlisted code; arbitrary upstream exception text replaced by WORKER_ERROR |
| workerEpoch | process incarnation identifier |
| generationCancelStatus | generationId nullable, status NONE/PUBLICATION_FENCED; not CUDA hard preemption |
| diskFreeBytes / diskTotalBytes | worker persistent state volume |
| activeGenerationId | nullable worker job ID, distinct from business Session generation |
| mode | gpu/simulation; simulation is not GPU evidence |

No network address, SSH key/command, management/inference token, LLM/TTS key, merchant credential or raw upstream message is returned. Probe timeout2s, max64KiB, loopback-only operator port, no HTTP redirect/proxy. Unknown source fields are projected away. Startup status may have an empty cache identity until preparation completes. An unavailable Worker returns a static502 error, never fabricated ready=true or staleUP.

Operator registry permissions are local access controls for existing identities, not a second account store. Runtime factory consumption also requires the trusted binding scope to appear in its operator registry. Existing Session binding capture/resolve remains a separate integration gate documented in the frozen User Configuration Contract.
