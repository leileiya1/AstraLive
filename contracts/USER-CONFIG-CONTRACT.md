# User Configuration Contract v0.3.0

Status: FROZEN 2026-10-09. Additive configuration API only. Existing `CONTRACTS.md`, Control/Runtime v1.1, Session FSM and production defaults remain unchanged. Machine schema: `user-config/schema.json`; consumer types generated from schema. Breaking revisions require a new contract version.

## Identity and API

The inspected repository has no public user login or tenant identity implementation; its INTERNAL_API_TOKEN authenticates Runtime tools only. Do not pretend Git authentication is application authentication. Configuration uses server-side opaque sessions, stored as SHA-256 token hashes. A trusted existing login service/operator provisions them through the separate identity adapter. This module does not implement passwords or a second OIDC system. Until a login service is connected, the settings page correctly reports 401.

All `/api/v0.3/config/**` require a valid HttpOnly Secure SameSite=Strict cookie `astralive_config_session`, resolved to `{tenantId,userId}` by the Backend. Client supplied identity is never accepted. Scope is BOTH tenant AND user, including same-tenant users. HTTPS same-origin hosting is required. Mutations require Origin equal to configured public origin; no permissive CORS. Responses use the existing OK/error envelope, Cache-Control: no-store. IDs are strings, timestamps UTC RFC3339, versions positive integers.

| Method/path under `/api/v0.3/config` | Meaning |
| --- | --- |
| GET `/me` | authenticated identity and configuration contract version |
| GET `/profiles` | caller-owned profiles, safe metadata only; empty means unconfigured |
| POST `/profiles` | create profile; optional write-only `secret` |
| PUT `/profiles/{profileId}` | replace safe config with `expectedVersion`; credential unchanged |
| PUT `/profiles/{profileId}/credential` | `{expectedVersion,secret}`; encrypt replacement and invalidate verification |
| DELETE `/profiles/{profileId}/credential` | `{expectedVersion}`; remove credential, invalidate verification/default |
| POST `/profiles/{profileId}/test` | `{expectedVersion}`; backend-only real adapter test; persist version-bound outcome |
| POST `/profiles/{profileId}/default` | `{expectedVersion}`; one enabled default per scope/kind; LLM requires verified current version |
| POST `/profiles/{profileId}/disable` | `{expectedVersion}`; disable and clear default |
| DELETE `/profiles/{profileId}` | `{expectedVersion}`; remove profile/credential, pinned bindings unaffected |
| GET/PUT `/settings` | versioned base policy: `maxQueue` 1..100, `failurePolicy` STOP only; effect NEXT_SESSION |

Profile shape: `{profileId,kind,name,provider,config,version,enabled,isDefault,credentialConfigured,verification,errorCode,health,updatedAt}`. Kinds LLM/TTS/AVATAR/GPU_WORKER/LIVE_PLATFORM. verification UNTESTED/VERIFIED/FAILED; health UNKNOWN/UP/DOWN with stale worker health resolved to UNKNOWN. isDefault means selected for a FUTURE configuration binding, not proven active in the existing Runtime. LLM health reflects the most recent connection test, not a live Runtime probe. No fabricated availability. `credentialConfigured` is boolean only: no masked key, suffix or plaintext.

Profile input `{kind,name,provider,config,secret?}`. Update `{expectedVersion,name,config}` cannot change kind/provider; create a new profile instead. Provider config schemas reject unknown fields, credential-like content in metadata, arbitrary parameter bags, user-supplied tenant/user IDs, URLs containing credentials, query strings or fragments. Secret 1..4096 UTF-8 bytes. Race updates return 409 CONFIG_VERSION_CONFLICT. Cross-scope ID always 404 RESOURCE_NOT_FOUND. Test failures return 502 PROVIDER_AUTH_FAILED (upstream 401/403), PROVIDER_RATE_LIMITED, PROVIDER_TEST_FAILED; never HTTP 200 with a failed test. Unsupported probe returns 409 PROVIDER_TEST_UNAVAILABLE; configuration can still be saved, never silently verified.

## Effect boundary

Every Provider payload/credential/disable write increments profile version and resets verification and health; config/credential replacement clears default. Selecting defaults changes selection flags only, without changing the Provider payload version. Explicit default selection follows successful verification for LLM. Binding capture is atomic and immutable; existing bindings retain old encrypted credential versions until release/expiry. Verification updates use compare-and-set; a test of version N cannot mark N+1 verified. No hot mutation of existing Runtime Providers. Existing Session paths do not call this module yet; provider-binding integration is the other Agents' explicit integration gate. UI must disclose this boundary.
