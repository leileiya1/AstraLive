# Provider Contract v0.3.0

Status: FROZEN 2026-10-09. Existing Runtime LLMProvider/TTSProvider/AvatarEngine/MediaOutput Protocols and neural networks are unchanged.

## Capability registry

| kind/provider | safe config | credential | connection test |
| --- | --- | --- | --- |
| LLM / deepseek | model (nonempty), maxTokens 1..8192, temperature optional 0..2 | API Key required | Go POST fixed https://api.deepseek.com/chat/completions; nonempty assistant reply required |
| LLM / openai-compatible | same plus endpoint (HTTPS origin or /v1 only) | API Key required | same chat-completions subset; no claim of all parameter compatibility |
| TTS / xiaoya | voiceId `xiao_ya`, speed 0.5..2, modelRef `xiaoya-default` | none | NOT IMPLEMENTED: needs Avatar/Voice Agent's actual synthesis probe; metadata is not a test |
| AVATAR / mock, lightweight, soulx | avatarRef (logical ID), workerProfileId optional | none | NOT IMPLEMENTED: preparation/render health owned by Avatar/Worker Agents |
| GPU_WORKER / soulx | workerRef (logical ID) | none | health report only; never rents/starts GPU |
| LIVE_PLATFORM / generic | platform (logical label) | stream key or credentials required | DISALLOWED: storage only, no platform connection |

XiaoYa currently uses local sherpa-onnx VITS, not a remote TTS API. Credentials/speed are not retrofitted into accepted TTS or clone engines. Provider-specific capabilities are validated independently. Future TTS adapters require an explicit schema + actual probe, not arbitrary compatibility assumptions.

## Shared internal binding interface

Dedicated `CONFIG_WORKER_TOKEN` Bearer authentication, never the browser cookie or Runtime Tool token. Trusted Control orchestrator supplies server-owned identity; no browser access. TLS/private service network required; responses Cache-Control:no-store and must not enter logs/traces.

- POST `/internal/v0.3/provider-bindings`: `{tenantId,userId}`; returns immutable `{bindingId,contractVersion:"0.3.0",profiles:[safe profile snapshots],settings,expiresAt}`. Atomically captures enabled defaults and their encrypted credentials. Not an existing Session mutation; orchestrator records bindingId in its private Session ownership mapping. Expires after 24 hours.
- POST `/internal/v0.3/provider-bindings/{bindingId}/resolve`: `{tenantId,userId}`; returns snapshot + server-only `credentials:{profileId: plaintext}` for the authenticated trusted consumer. Plaintext may exist transiently in worker memory only. Never relay this response to a public API/browser. Exact tenant/user match is mandatory. Current profile edits/deletes cannot change snapshot. Consumers must instantiate one Provider bundle per binding and retain it throughout Session lifetime. Consumers must reject a missing required Provider/default and must never fall back to experimental/global credentials. An empty binding represents unconfigured state, not a runnable Session. After 24h a new Session must obtain a new binding; renew-before-expiry protocol is not defined, so do not run v0.3 Sessions longer than the lease.
- DELETE `/internal/v0.3/provider-bindings/{bindingId}`: `{tenantId,userId}`; release encrypted snapshot on normal Stop/failure/cleanup.
- POST `/internal/v0.3/worker-health`: `{tenantId,userId,profileId,expectedVersion,health:"UP"|"DOWN"}`; writes only matching GPU_WORKER profile/version; Backend timestamps receipt; health TTL 60 seconds; absence/staleness UNKNOWN. No control command or allocation.

Auth adapter uses separate `CONFIG_IDENTITY_TOKEN`: POST `/internal/v0.3/config-sessions` `{tenantId,userId}` returns a 12h opaque token to trusted login adapter ONLY. Adapter must set `astralive_config_session` Secure/HttpOnly/SameSite=Strict/Path=/api/v0.3/config, never expose it to JS; provisioned identity must come from authenticated login claims. DELETE same path with `{token}` revokes. Do not expose internal routes through public ingress. Integration/operator tool can provision test identities; ordinary user must not SSH/edit .env.

References verified during design: [DeepSeek chat completion](https://api-docs.deepseek.com/api/create-chat-completion/), [DeepSeek errors](https://api-docs.deepseek.com/quick_start/error_codes/). 401 from provider is not caller login 401: Backend returns 502 PROVIDER_AUTH_FAILED and persisted FAILED status. No raw provider response/error text is reflected.
