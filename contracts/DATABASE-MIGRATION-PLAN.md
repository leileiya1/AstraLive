# Database Migration Plan v0.3.0

Status: FROZEN 2026-10-09. Add migration 000003 only; no changes to accepted Session/resource tables or earlier migrations. PostgreSQL and pgx remain the persistence stack.

- `config_principals`: composite PK tenant_id/user_id. Reserved adapter identity namespace until existing login service supplies external mapping.
- `config_auth_sessions`: opaque session token hash, composite FK principal, expiry, deletion revokes.
- `user_settings`: composite PK principal, versioned policy JSON; only schema-validated safe values.
- `config_profiles`: physical shared lifecycle table with PK tenant/user/id; checked kind, provider, safe config JSON, monotonically increasing version, enabled/default, verification/error, health/timestamp. Partial unique index `(tenant_id,user_id,kind) WHERE is_default AND enabled`.
- `llm_profiles`, `tts_profiles`, `avatar_profiles`, `gpu_worker_profiles`, `live_platform_profiles`: filtered SQL views over the physical table, preserving common version/lifecycle transactions. These are logical entities, not independent schemas with divergent behavior.
- `provider_credentials`: composite FK profile ON DELETE CASCADE; AES-256-GCM ciphertext including nonce, key_id. No plaintext, key suffix or key hash for display.
- `provider_bindings`: scoped immutable JSON snapshot containing safe config + encrypted credential copies, expires_at; detached from mutable profiles so deletion doesn't mutate an active binding.

All repositories must filter by tenant_id AND user_id, including joins/update/delete/test/default/binding/health. PostgreSQL constraints enforce matching ownership; application authentication is mandatory. This release uses application scope enforcement plus composite FKs, not DB RLS: DB admin/service account remains privileged. Test same-tenant cross-user and cross-tenant isolation explicitly.

Writes/default changes serialize per principal by locking principal row. Profile mutations compare expectedVersion under lock. Credential write and profile version reset are one transaction. Tests record results with version CAS. Capturing bindings locks same principal and reads all default profiles/credentials atomically. Secret rotation and disabling affect only new bindings. Expired auth sessions/bindings need periodic deletion; lazy expiry prevents access even before cleanup.

Deploy backup DB, apply normal embedded migration runner, configure keyring + trusted identity origin adapter. Templates contain no secrets. Existing production Provider defaults and env values are NOT imported or overwritten. Rollback disables configuration routes first; drop new views/tables in reverse dependency order only after no consumers/bindings remain. Never roll back the accepted core schema. Verify migration idempotency and real PostgreSQL integration before claiming migration acceptance.

## Additive personal media migration v0.3.1 — frozen design, not yet applied

Do not edit migration 000003 or replace its `avatar_profiles` view. The next executable migration belongs with personal-media repository implementation and must use the existing embedded Go migration runner. Proposed physical tables/constraints below are required by AVATAR/VOICE/ASSET-STORAGE contracts; no earlier Session table is altered.

| Table | Keys and required columns / constraints |
| --- | --- |
| `personal_assets` | PK(tenant_id,user_id,id), FK principal; purpose/state checked enums, version>0, declared/actual byte_length>=0, sha256 lowercase64, sniffed media_type, preprocessing_version, source_asset_id composite self-FK, consent_policy/accepted_at, created_at/deleted_at |
| `personal_asset_objects` | PK/FK scoped asset; private storage_key UNIQUE, encrypted object descriptor/key_id (external key itself absent), storage state; immutable object per asset |
| `personal_asset_uploads` | scoped PK upload ID, scoped asset FK, expires_at, declared_length/hash, status, reservation_bytes; private audio transcript key_id/ciphertext; no client paths/names |
| `personal_avatar_profiles` | scoped PK id; current_version>0, enabled/default/state, name; FK principal; partial unique default per owner where enabled/default |
| `personal_avatar_profile_revisions` | PK(owner,id,version), scoped profile FK; immutable validated config without paths, scoped source/normalized photo FKs, worker_profile_id + frozen worker version/model revision/preprocessing/digest, append-only readiness proof by attempt; worker kind checked transactionally against config_profiles |
| `voice_profiles` | scoped PK id; current_version>0, enabled/default/state, name; FK principal; partial unique default per owner where enabled/default |
| `voice_profile_revisions` | PK(owner,id,version), scoped profile FK; provider-specific safe config, transcript key_id/ciphertext separately, scoped source/normalized audio FKs, capability/model revision snapshot; no plaintext transcript in config JSON |
| `personal_processing_jobs` | scoped PK id; kind/action/state checked, target entity+version, encrypted private immutable input snapshot (including transcripts/preview text), deadline, attempt>=0, worker assignment, hashed claim token/lease expiry; scoped asset/revision joins; terminal outcome static error only |
| `personal_job_assets` | PK(owner,job_id,asset_id,role), composite FKs both sides; INPUT/OUTPUT and attempt; no output promotion across attempt |
| `personal_session_bindings` | scoped PK id; session_id logical reference (no Session schema change), contract_version, immutable Avatar/Voice revision FKs plus private captured readiness/config/capability snapshots and detached Provider snapshot ref, created/expires/released; session+idempotency ownership verified |
| `personal_binding_assets` | scoped binding/asset FKs, captured sha256/purpose/preprocessing identity; immutable allowlist and retention lease |
| `personal_idempotency` | unique(owner,operation,resource,key), request digest, result reference, expires_at; body mismatch 409; no raw credentials/transcripts in cache |
| `personal_storage_usage` | scoped principal PK; reserved/retained bytes and counts >=0, transactionally locked for quotas; reconciliation verifies against object/upload rows |

All asset/profile/revision/job/binding relations enforce tenant AND user with composite FKs; external login identity must map to config_principals. JSON cannot substitute for ownership FKs. Provider type/kind, profile-state transitions and cross-field proof validation occur in the same transaction as repository writes. Encrypt private processing/transcript snapshots using external AEAD keyring with owner+record+version as authenticated context. Bindings reference immutable revisions and encrypted Provider copies, never mutable profile rows for resolution. RLS is not assumed; service authentication and owner-filtered SQL remain mandatory.

Serialize profile/default/capture/delete/quotas using the same principal lock as v0.3.0. Capture inserts Provider snapshot and personal binding plus asset allowlist atomically. Renew/release change only lease state, including dependent Provider expiry. Lock ordering: principal -> profile/revision -> job/binding -> asset/upload/usage; reconciliation uses the same order. Stale attempt/version cannot publish a derivative or readiness. Object writes happen before READY transaction; failed commit leaves quarantined bytes for reconciler. Blob deletion is retried after DELETING commits, then DELETED commits only when active bytes are gone; no cascade erases lease protection.

Historical tombstones remain 30 days; expired leases/uploads/idempotency are GC'd after authorization has already stopped at expiry. Old unleased profile revisions can be pruned after bindings/jobs release; retained history metadata cannot authorize media. Back up migration + object manifest together, verify hashes and deletion retention on restore. Rollback must first disable new routes/stop jobs/release leases, never drop generic configuration tables or accepted Session data. Acceptance requires a real PostgreSQL apply/rollback test and concurrent-owner/CAS/atomic-capture tests when executable migration is added; this documentation is not a claimed migration PASS.
