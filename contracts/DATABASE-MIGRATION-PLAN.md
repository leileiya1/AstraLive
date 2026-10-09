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
