# Session Integration Hooks 0.4.0

Baseline: e70274b8781a6c4076e3b35609108f46bac9f768. Frozen Control/Runtime 1.1, Provider 0.3.0 and Worker 1.1 remain unchanged.

## Ownership and capture

Authenticate the product HttpOnly cookie against the existing config_auth_sessions table. A second cookie name/path covers product routes; both cookies refer to ONE hashed server session. Scope comes only from that table. An operator-configured login adapter issues/revokes existing sessions; this MVP has one operator login, not SaaS registration.

resource_owners maps existing resource IDs to tenant AND user. No automatic claim of historical rows. References and collections must respect ownership. session_provider_bindings stores server-owned Session scope, immutable binding ID, room snapshot, capture/expiry timestamps and safe summary. Capture at business Session creation using Service.Capture, the same operation behind POST /internal/v0.3/provider-bindings. No binding fields enter v1.1 DTOs.

## Go hooks (Agent A owns integration)

Service has optional SessionIntegration: Prepare(ctx, sessionId, *CreateRuntimeSessionRequest) and Release(ctx, sessionId). Prepare replaces room context with the capture-time snapshot and verifies the lease. The public request retains its exact frozen shape. Terminal event handling releases after commit; a periodic reconciliation handles expired/abandoned rows. Hooks never implement a second provider catalog.

## Runtime hooks (handoff to Agent B)

SessionManager.create_session(request, *, factories=None, max_queue=None) admits per-Session factories. Existing callers retain behavior. Agent B should use SessionManager.speak and existing Utterance/PlatformContext; do not replace SessionManager or edit provider integration. All v0.4 integration lives in app/session_binding.py. Its subclass owns resolution, per-Session bundle, readiness checks, strict lease watchdog, status and terminal cleanup. No new media algorithm or Worker protocol.

## Additive internal interface 0.4.0

Backend GET /internal/v0.4/sessions/{sessionId}/binding: CONFIG_WORKER_TOKEN_FILE service role only; no browser identity input. Looks up scope from Session mapping then calls existing Resolve. Returns {integrationVersion:"0.4.0",scope,binding,credentials,capturedAt}. Private network/TLS; no-store; never log payloads. Backend DELETE same path releases via stored scope; idempotent. No caller-selected scope or profile enumeration.

Runtime GET /internal/v0.4/sessions/{sessionId}/providers: RUNTIME_CONTROL_TOKEN_FILE service role only; returns safe {integrationVersion,sessionId,bindingId,capturedAt,expiresAt,profiles:[{profileId,kind,provider,version,updatedAt}],mode,errorCode,workerEpoch}. Modes REAL / DEGRADED / UNAVAILABLE; mock sessions cannot be REAL. Backend owner-checked GET /api/v0.4/sessions/{sessionId}/providers projects this summary and explicitly indicates Runtime unavailability. Config state remains separate.

## Lifecycle

Incomplete bindings, unverified LLM, unsupported TTS parameters, unauthorized worker refs, non-ready/mismatched/simulation GPU fail closed. No global key or startup Lightweight fallback for selected SoulX. After successful SoulX preparation, existing degradation/recovery and generation fencing remain. Instantiate once per Session, ignore later profile edits. v0.3 lease has no renewal: stop BEFORE expiry; reject commands at expiry. Release on Stop, preparation/start failure, terminal event, Runtime shutdown and reconciliation. Persist only encrypted snapshots; plaintext only in trusted Runtime memory.

## Integration gate

SESSION_BINDINGS_ENABLED is explicit opt-in for Backend and Runtime. Accepted legacy development defaults do not change. Production refuses startup without identity/config/control-token integration. Real GPU/product acceptance is required before changing a deployed default. Agent B branch/code is neither merged nor imported here.

## Private probe extension

POST /internal/v0.4/provider-probes/tts on Runtime uses the distinct Runtime control token, forbids unknown fields, and accepts only {voiceId:"xiao_ya",modelRef:"xiaoya-default",speed:1}. It synthesizes a fixed phrase; returns {provider:"xiaoya",real:true,sampleRate,samples} only after nonzero PCM. This is a health probe, not a second profile or voice protocol. Public and private0.4 machine contracts are separate files in this directory; the frozen0.3 binding schema is referenced unchanged.

Bound LLM failure propagation adds only an opt-in provider property to the Session preparation hook. Legacy callers retain behavior; the bound manager tracks terminal cleanup tasks and awaits them before publisher shutdown.

## Accepted output integration follow-up

`runtime/app/bound_media.py` is the business-only adapter around the validated consumption wrapper. It admits headless SoulX publishing with RTMP pipe-delivery credits and preserves WebRTC credits, per-generation cancellation and pinned Worker links. `rtmp_media.py` exposes a private watermark after completed pipe writes without changing its encoder command or clocks. With no preview subscriber, drain waits for publishing; an absent preview cannot mask a real publisher failure. The same captured Session binding survives explicit Lightweight degradation and a bounded Worker reconnect, with promotion at a future speech boundary. Short real headless/dual RTMP and same-Session Worker recovery evidence is recorded in AGENT-A-ACCEPTANCE.md;24h lease real-time acceptance is deferred, with enforcement retained.
