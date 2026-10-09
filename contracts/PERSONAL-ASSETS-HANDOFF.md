# Personal Avatar / Voice / AssetStorage shared handoff v0.3.1

Status: FROZEN 2026-10-09. This is the missing Agent 1 contract handoff, committed in the main repository. No alternate branch/file is required.

## Authoritative locations

| Boundary | Human contract | Machine / Go / TypeScript |
| --- | --- | --- |
| AvatarProfile / readiness / session effect | AVATAR-PROFILE-CONTRACT.md | personal-assets/schema.json: AvatarProfile, AvatarConfig, Readiness, PersonalBinding |
| VoiceProfile / provider capabilities | VOICE-PROFILE-CONTRACT.md | personal-assets/schema.json: VoiceProfile, VoiceConfig, VoiceCapabilities |
| AssetStorage / upload / validation / preview | ASSET-STORAGE-CONTRACT.md | personal-assets/schema.json: Asset, UploadTicket, JobClaim, JobResultInput |
| Backend internal adapter interfaces | backend/internal/personalconfig/contracts.go | AssetStorage, ProfileService, PersonalBindingStore, ProcessorProtocol, JobService |
| Frontend consumer types | frontend/src/api/personal-assets-generated.ts | generated from the SAME OpenAPI file |
| Migration, privacy | DATABASE-MIGRATION-PLAN.md; SECURITY-BOUNDARY.md | v0.3.1 appendices |

Repository-relative backend/frontend paths above are from repository root; Markdown contracts are in `contracts/`. Human rules define cross-field/state/ownership constraints that OpenAPI 3.0 cannot fully express. Unknown public fields remain forbidden. Examples and negative schema fixtures are exercised by `backend/internal/personalconfig/contract_test.go`.

## Agent implementation responsibilities

Backend/config owner implements scoped storage/profile/job repositories and the newly frozen HTTP routes, identity/CSRF enforcement, quotas/leases, immutable revisions, atomic Provider/media snapshot and result validation. Avatar/Voice Agent consumes profile + asset descriptors and supplies installed real photo/audio validation and voice synthesis adapters; no access to users' LLM keys. SoulX Worker Agent consumes only assigned immutable input assets/model registry and returns versioned REAL readiness/proof and encoded preview; local input/model/cache paths never leave the Worker. Frontend uses cookie-authenticated Backend, closed generated DTOs, asynchronous jobs and real capability flags; never calls Workers directly or shows QUEUED/SIMULATION as success.

The newly frozen public endpoint group is `/api/v0.3/config/{asset-uploads,assets,avatar-profiles,voice-profiles,personal-jobs,personal-capabilities}`. Existing `/profiles` is v0.3.0 generic Provider configuration and must not be reinterpreted as the new personal entities. All internal routes and complete input/output types are enumerated in the machine specification. No edits to accepted Session logic, SoulX neural network, voice clone engine or formal defaults are included in this handoff.

## Implementation coverage (2026-10-09)

| Item | Evidence / state |
| --- | --- |
| Frozen human contracts, OpenAPI, Go DTO/interface package, generated TS types | supplied in this handoff; schema/DTO positive and negative tests |
| Existing v0.3.0 encrypted generic Provider/configuration center | implemented separately; see backend/USER-CONFIG-IMPLEMENTATION-REPORT.md |
| New AssetStorage upload/preview/profile/job HTTP handlers and DB repositories | NOT IMPLEMENTED by this contract patch; OpenAPI x-implementation-status=CONTRACT_ONLY |
| v0.3.1 physical media migration | fully specified migration plan; executable migration to accompany repository implementation, not yet applied |
| Optional Runtime/Worker files from other agents | adapter work is not HTTP/profile/storage readiness; this patch neither edits nor stages them |
| New personal profile Session consumption | gated on atomic binding adapter + regression; no claim that accepted Sessions already use new entities |
| Real DeepSeek acceptance with a newly supplied user key | still pending; synthetic provider tests are not this acceptance |

`personal-capabilities` must only report true after its corresponding handler, repository, storage and real registered processor are ready. If the new route group is absent, Frontend presents “personal assets unavailable” and does not invent mock upload/previews. Contract types are not a license to advertise unavailable features. Config v0.3.0 `/me` keeps its 0.3.0 response; personal capability version is 0.3.1. This version is additive, not a silent replacement of old payloads.

## Required integration acceptance

1. Two real authenticated users, including same tenant: upload/read/preview/delete/profile/default/job/internal lease access cannot cross users. Anonymous API is 401; forged scope is rejected. Processor bearer without job/binding assignment cannot read bytes; browser cookie cannot call internal routes.
2. Stream valid photo/audio; wrong SHA/size/MIME, archive, SVG, animated image, multi-stream audio, oversized decompression and missing face inspector reject with static errors. Refresh retains metadata, not credentials/media/transcripts in browser storage.
3. Prepare real Worker and real voice adapter; prove normalized digests, REAL warmup/encoder, actual nonempty PCM/encoded preview and terminal Job. SIMULATION, unavailable adapter, timeout, malformed output and upstream 401 never return successful readiness.
4. Concurrent config/credential/media-default update vs capture produces a coherent generation; existing Session retains its original Avatar/Voice/Provider/asset digests. Stale job result cannot mark newer version READY. Rotation and renew cannot change a playing session's Provider.
5. Cancel/release/expire; old attempt cannot commit/read; leased media cannot be deleted; unreferenced deletion removes bytes and quota reservations. Preview does not auto-start a paid GPU.
6. Generate specs/types, validate all OpenAPI requests/examples, run Backend/Frontend and accepted Runtime regression. Separately report schema/unit checks versus PostgreSQL/HTTP/browser/GPU evidence.

## Reproducible contract checks

```sh
python3 contracts/personal-assets/generate_schema.py
(cd frontend && bun run generate:personal-api)
(cd backend && go test ./internal/personalconfig ./internal/userconfig)
```

Breaking fields/enums, thresholds or capability semantics require a new contract revision and coordinated consumer migration. Additive provider schemas must be reviewed as a new capability; no open-ended config object is allowed.

## Verification recorded for this handoff

2026-10-09 local checkout: `go test ./...` PASS; `go test -race ./internal/personalconfig` PASS (final run 2.045s); `go vet ./internal/personalconfig` PASS. Frontend `bun run build` PASS (includes generated personal types and TypeScript checking); `bun run test` 34/34 PASS. Runtime `PYTHONPATH=runtime runtime/.venv/bin/python -m unittest discover -s runtime/tests -p 'test_*.py'` ran113 tests in5.436s, OK,11 opt-in tests skipped. This Runtime run also picked up the other agents' current optional adapters; their files are not part of this contract commit. SHA256 checks against the pre-change frozen baseline for CONTRACTS.md/control-api.openapi.yaml/runtime-api.openapi.yaml all match. These are local contract/unit/regression results, not live PostgreSQL/new-upload/browser/GPU/provider acceptance.
